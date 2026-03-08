import { browser } from '$app/environment';
import { api, type TabSessionLifecycle, type TabSessionRoute, type TabSessionStateRequest, type TabSessionSubscription } from '$lib/api/client';
import { getBackendUrl } from '$lib/config';

const TAB_SESSION_ID_KEY = 'percus.realtime.tab_session_id';
const TAB_SESSION_REVISION_KEY = 'percus.realtime.tab_session_revision';

type RealtimeSourceMeta = {
  subscription_id?: string;
  kind?: TabSessionSubscription['kind'];
  params?: Record<string, unknown>;
  generation?: number;
} | null;

export type TabRealtimeEvent = {
  v: number;
  stream_seq: number;
  session_id: string;
  config_revision: number;
  emitted_at: string;
  source: RealtimeSourceMeta;
  op: 'snapshot' | 'append' | 'control' | 'error';
  source_version?: number | null;
  cursor?: string | null;
  payload: Record<string, unknown>;
};

type ContributorState = {
  id: string;
  subscriptions: TabSessionSubscription[];
  onEvent?: (event: TabRealtimeEvent) => void;
};

export type TabRealtimeContributor = {
  contributorId: string;
  subscriptions?: TabSessionSubscription[];
  onEvent?: (event: TabRealtimeEvent) => void;
};

export type TabRealtimeContributorHandle = {
  setSubscriptions: (subscriptions: TabSessionSubscription[]) => void;
  setEventHandler: (onEvent?: (event: TabRealtimeEvent) => void) => void;
  dispose: () => void;
};

const buildDefaultRoute = (): TabSessionRoute => ({
  id: 'unknown',
  url: '/',
  params: {}
});

const readStoredRevision = () => {
  if (!browser) return 0;
  const raw = sessionStorage.getItem(TAB_SESSION_REVISION_KEY) ?? '';
  const parsed = Number.parseInt(raw, 10);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
};

const writeStoredRevision = (revision: number) => {
  if (!browser) return;
  sessionStorage.setItem(TAB_SESSION_REVISION_KEY, String(revision));
};

const createTabSessionId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `tab-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};

const readTabSessionId = () => {
  if (!browser) return '';
  const existing = sessionStorage.getItem(TAB_SESSION_ID_KEY);
  if (existing) return existing;
  const nextId = createTabSessionId();
  sessionStorage.setItem(TAB_SESSION_ID_KEY, nextId);
  return nextId;
};

const writeTabSessionId = (tabSessionId: string) => {
  if (!browser) return;
  sessionStorage.setItem(TAB_SESSION_ID_KEY, tabSessionId);
};

const filterRouteParams = (params: Record<string, string | undefined>) => {
  const entries = Object.entries(params)
    .map(([key, value]) => [key.trim(), String(value ?? '').trim()] as const)
    .filter(([key, value]) => key && value);
  return Object.fromEntries(entries);
};

class TabRealtimeClient {
  private tabSessionId = readTabSessionId();
  private revision = readStoredRevision();
  private route: TabSessionRoute = buildDefaultRoute();
  private lifecycle: TabSessionLifecycle = {
    visibility: document.visibilityState === 'hidden' ? 'background' : 'foreground'
  };
  private contributors = new Map<string, ContributorState>();
  private subscriptionOwners = new Map<string, string>();
  private source: EventSource | null = null;
  private syncInFlight: Promise<void> | null = null;
  private syncQueued = false;
  private streamReconnectTimer: number | null = null;
  private disposed = false;
  private lastHandledStreamSeq = 0;

  constructor() {
    document.addEventListener('visibilitychange', this.handleVisibilityChange);
    window.addEventListener('online', this.handleOnline);
    window.addEventListener('pagehide', this.handlePageHide);
  }

  registerContributor(input: TabRealtimeContributor): TabRealtimeContributorHandle {
    const contributor: ContributorState = {
      id: input.contributorId,
      subscriptions: input.subscriptions ? [...input.subscriptions] : [],
      onEvent: input.onEvent
    };
    this.contributors.set(input.contributorId, contributor);
    this.scheduleSync();

    return {
      setSubscriptions: (subscriptions) => {
        const current = this.contributors.get(input.contributorId);
        if (!current) return;
        current.subscriptions = [...subscriptions];
        this.scheduleSync();
      },
      setEventHandler: (onEvent) => {
        const current = this.contributors.get(input.contributorId);
        if (!current) return;
        current.onEvent = onEvent;
      },
      dispose: () => {
        if (!this.contributors.delete(input.contributorId)) return;
        this.scheduleSync();
      }
    };
  }

  setRoute(input: { id?: string; url?: string; params?: Record<string, string | undefined> }) {
    const nextRoute: TabSessionRoute = {
      id: String(input.id ?? this.route.id ?? 'unknown').trim() || 'unknown',
      url: String(input.url ?? this.route.url ?? '/').trim() || '/',
      params: filterRouteParams(input.params ?? {})
    };
    if (JSON.stringify(nextRoute) === JSON.stringify(this.route)) {
      return;
    }
    this.route = nextRoute;
    this.scheduleSync();
  }

  async close(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    window.removeEventListener('online', this.handleOnline);
    window.removeEventListener('pagehide', this.handlePageHide);
    this.closeStream();
    if (this.streamReconnectTimer !== null) {
      window.clearTimeout(this.streamReconnectTimer);
      this.streamReconnectTimer = null;
    }
    try {
      await api.realtime.deleteTabSession(this.tabSessionId);
    } catch {
      // Ignore close-time failures. The backend TTL will eventually clean up.
    }
  }

  private readonly handleVisibilityChange = () => {
    this.lifecycle = {
      visibility: document.visibilityState === 'hidden' ? 'background' : 'foreground'
    };
    this.scheduleSync();
  };

  private readonly handleOnline = () => {
    this.scheduleSync();
    this.ensureStream();
  };

  private readonly handlePageHide = () => {
    this.lifecycle = {
      visibility: 'closing',
      reason: 'pagehide'
    };
    void this.flushClosingState();
  };

  private async flushClosingState() {
    this.closeStream();
    const state = this.buildState(this.revision + 1);
    const baseUrl = getBackendUrl();
    const stateUrl = new URL(
      `/api/realtime/tab-sessions/${encodeURIComponent(this.tabSessionId)}/state`,
      baseUrl
    );
    const sessionUrl = new URL(
      `/api/realtime/tab-sessions/${encodeURIComponent(this.tabSessionId)}`,
      baseUrl
    );

    try {
      await fetch(stateUrl.toString(), {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state),
        keepalive: true
      });
    } catch {
      // Ignore; we still try to delete the session.
    }

    try {
      await fetch(sessionUrl.toString(), {
        method: 'DELETE',
        credentials: 'include',
        keepalive: true
      });
    } catch {
      // Ignore close-time failures.
    }
  }

  private buildState(nextRevision: number): TabSessionStateRequest {
    const subscriptions: TabSessionSubscription[] = [];
    const seen = new Set<string>();
    this.subscriptionOwners.clear();

    for (const contributor of this.contributors.values()) {
      for (const subscription of contributor.subscriptions) {
        if (seen.has(subscription.subscription_id)) {
          throw new Error(`Duplicate realtime subscription_id: ${subscription.subscription_id}`);
        }
        seen.add(subscription.subscription_id);
        this.subscriptionOwners.set(subscription.subscription_id, contributor.id);
        subscriptions.push(subscription);
      }
    }

    return {
      revision: nextRevision,
      lifecycle: this.lifecycle,
      route: this.route,
      subscriptions
    };
  }

  private scheduleSync() {
    if (this.disposed) return;
    if (this.syncInFlight) {
      this.syncQueued = true;
      return;
    }
    this.syncInFlight = this.syncState()
      .catch((error) => {
        console.error('tab realtime sync failed', error);
      })
      .finally(() => {
        this.syncInFlight = null;
        if (this.syncQueued) {
          this.syncQueued = false;
          this.scheduleSync();
        }
      });
  }

  private async syncState() {
    let attempts = 0;
    while (attempts < 2) {
      attempts += 1;
      const state = this.buildState(this.revision + 1);
      try {
        const result = await api.realtime.putTabSessionState(this.tabSessionId, state);
        this.revision = result.revision;
        writeStoredRevision(this.revision);
        this.ensureStream();
        return;
      } catch (error) {
        const status = typeof error === 'object' && error && 'status' in error ? Number((error as { status?: number }).status) : 0;
        if (status === 409) {
          const current = await api.realtime.tabSessionState(this.tabSessionId);
          this.revision = current.revision;
          writeStoredRevision(this.revision);
          continue;
        }
        if (status === 404) {
          this.resetSessionIdentity();
          continue;
        }
        if (status === 401) {
          this.closeStream();
          return;
        }
        console.error('tab realtime state sync failed', error);
        return;
      }
    }
  }

  private ensureStream() {
    if (this.disposed || this.source || !this.tabSessionId) return;
    const baseUrl = getBackendUrl();
    const url = new URL(
      `/api/realtime/tab-sessions/${encodeURIComponent(this.tabSessionId)}/stream`,
      baseUrl
    );
    const source = new EventSource(url.toString(), { withCredentials: true });
    source.onmessage = (event) => {
      if (!event.data) return;
      try {
        const payload = JSON.parse(event.data) as TabRealtimeEvent;
        if (typeof payload.stream_seq === 'number' && payload.stream_seq <= this.lastHandledStreamSeq) {
          return;
        }
        this.lastHandledStreamSeq = Math.max(this.lastHandledStreamSeq, Number(payload.stream_seq ?? 0));
        this.dispatchEvent(payload);
      } catch (error) {
        console.error('tab realtime parse failed', error);
      }
    };
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        this.closeStream();
        this.scheduleStreamReconnect();
      }
    };
    this.source = source;
  }

  private scheduleStreamReconnect() {
    if (this.disposed || this.streamReconnectTimer !== null) return;
    this.streamReconnectTimer = window.setTimeout(() => {
      this.streamReconnectTimer = null;
      this.scheduleSync();
      this.ensureStream();
    }, 1000);
  }

  private dispatchEvent(event: TabRealtimeEvent) {
    const subscriptionId = event.source?.subscription_id;
    if (!subscriptionId) {
      if (event.op === 'control' && event.payload.type === 'session_deleted') {
        this.resetSessionIdentity();
        this.scheduleSync();
      }
      return;
    }
    const ownerId = this.subscriptionOwners.get(subscriptionId);
    if (!ownerId) return;
    const contributor = this.contributors.get(ownerId);
    contributor?.onEvent?.(event);
  }

  private closeStream() {
    if (!this.source) return;
    this.source.close();
    this.source = null;
  }

  private resetSessionIdentity() {
    this.closeStream();
    this.lastHandledStreamSeq = 0;
    this.revision = 0;
    writeStoredRevision(0);
    this.tabSessionId = createTabSessionId();
    writeTabSessionId(this.tabSessionId);
  }
}

let singletonClient: TabRealtimeClient | null = null;

export const getTabRealtimeClient = () => {
  if (!browser) return null;
  if (singletonClient === null) {
    singletonClient = new TabRealtimeClient();
  }
  return singletonClient;
};

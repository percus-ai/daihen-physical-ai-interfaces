import { browser } from '$app/environment';
import { api, type TabSessionLifecycle, type TabSessionRoute, type TabSessionStateRequest, type TabSessionSubscription } from '$lib/api/client';
import { getBackendUrl } from '$lib/config';

const TAB_SESSION_ID_KEY = 'percus.realtime.tab_session_id';
const TAB_SESSION_REVISION_KEY = 'percus.realtime.tab_session_revision';
const TAB_SESSION_BROADCAST_CHANNEL = 'percus.realtime.tab_session';

type TabSessionPresenceMessage = {
  type: 'announce' | 'ack';
  tabSessionId: string;
  instanceId: string;
};

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

type ComposedState = {
  state: Omit<TabSessionStateRequest, 'revision'>;
  stateKey: string;
  subscriptionOwners: Map<string, string>;
};

type InFlightState = {
  revision: number;
  composed: ComposedState;
};

export type TabRealtimeContributor = {
  contributorId?: string;
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

const createClientInstanceId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `instance-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
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
    .filter(([key, value]) => key && value)
    .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey));
  return Object.fromEntries(entries);
};

const normalizeJsonValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeJsonValue(item));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, nestedValue]) => nestedValue !== undefined)
        .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
        .map(([key, nestedValue]) => [key, normalizeJsonValue(nestedValue)])
    );
  }
  return value;
};

const cloneSubscription = (subscription: TabSessionSubscription): TabSessionSubscription =>
  normalizeJsonValue(subscription) as TabSessionSubscription;

class TabRealtimeClient {
  private instanceId = createClientInstanceId();
  private tabSessionId = readTabSessionId();
  private appliedRevision = readStoredRevision();
  private route: TabSessionRoute = buildDefaultRoute();
  private lifecycle: TabSessionLifecycle = {
    visibility: document.visibilityState === 'hidden' ? 'background' : 'foreground'
  };
  private contributors = new Map<string, ContributorState>();
  private appliedSubscriptionOwners = new Map<string, string>();
  private source: EventSource | null = null;
  private syncInFlight: Promise<void> | null = null;
  private syncQueued = false;
  private syncKeepaliveRequested = false;
  private deleteAfterSyncRequested = false;
  private streamReconnectTimer: number | null = null;
  private disposed = false;
  private lastHandledStreamSeq = 0;
  private appliedStateKey = '';
  private inFlightState: InFlightState | null = null;
  private presenceChannel: BroadcastChannel | null = null;
  private nextContributorSequence = 0;

  constructor() {
    document.addEventListener('visibilitychange', this.handleVisibilityChange);
    window.addEventListener('online', this.handleOnline);
    window.addEventListener('pagehide', this.handlePageHide);
    this.initializePresenceChannel();
  }

  registerContributor(input: TabRealtimeContributor): TabRealtimeContributorHandle {
    const contributorId = input.contributorId?.trim() || `contributor-${++this.nextContributorSequence}`;
    const contributor: ContributorState = {
      id: contributorId,
      subscriptions: input.subscriptions ? [...input.subscriptions] : [],
      onEvent: input.onEvent
    };
    this.contributors.set(contributorId, contributor);
    this.scheduleSync();

    return {
      setSubscriptions: (subscriptions) => {
        const current = this.contributors.get(contributorId);
        if (!current) return;
        current.subscriptions = [...subscriptions];
        this.scheduleSync();
      },
      setEventHandler: (onEvent) => {
        const current = this.contributors.get(contributorId);
        if (!current) return;
        current.onEvent = onEvent;
      },
      dispose: () => {
        if (!this.contributors.delete(contributorId)) return;
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
    this.lifecycle = {
      visibility: 'closing',
      reason: 'close'
    };
    try {
      this.scheduleSync({ deleteAfterSync: true });
      while (this.syncInFlight) {
        await this.syncInFlight;
      }
    } catch {
      // Ignore close-time failures. The backend TTL will eventually clean up.
    } finally {
      this.disposed = true;
      document.removeEventListener('visibilitychange', this.handleVisibilityChange);
      window.removeEventListener('online', this.handleOnline);
      window.removeEventListener('pagehide', this.handlePageHide);
      this.presenceChannel?.close();
      this.presenceChannel = null;
      this.closeStream();
      if (this.streamReconnectTimer !== null) {
        window.clearTimeout(this.streamReconnectTimer);
        this.streamReconnectTimer = null;
      }
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
    this.closeStream();
    this.scheduleSync({ keepalive: true, deleteAfterSync: true });
  };

  private composeState(): ComposedState {
    const subscriptions: TabSessionSubscription[] = [];
    const seen = new Set<string>();
    const subscriptionOwners = new Map<string, string>();

    for (const contributor of this.contributors.values()) {
      for (const subscription of contributor.subscriptions) {
        if (seen.has(subscription.subscription_id)) {
          throw new Error(`Duplicate realtime subscription_id: ${subscription.subscription_id}`);
        }
        seen.add(subscription.subscription_id);
        subscriptionOwners.set(subscription.subscription_id, contributor.id);
        subscriptions.push(cloneSubscription(subscription));
      }
    }

    subscriptions.sort((left, right) => left.subscription_id.localeCompare(right.subscription_id));

    const state: Omit<TabSessionStateRequest, 'revision'> = {
      lifecycle: normalizeJsonValue(this.lifecycle) as TabSessionLifecycle,
      route: normalizeJsonValue(this.route) as TabSessionRoute,
      subscriptions
    };

    return {
      state,
      stateKey: this.buildStateKey(state),
      subscriptionOwners
    };
  }

  private buildStateKey(state: Omit<TabSessionStateRequest, 'revision'>) {
    return JSON.stringify(normalizeJsonValue(state));
  }

  private buildRequest(composed: ComposedState, revision: number): TabSessionStateRequest {
    return {
      revision,
      lifecycle: composed.state.lifecycle,
      route: composed.state.route,
      subscriptions: composed.state.subscriptions
    };
  }

  private composeStateFromResponse(response: {
    lifecycle: TabSessionLifecycle;
    route: TabSessionRoute;
    subscriptions: TabSessionSubscription[];
  }): ComposedState {
    const desiredOwners = this.composeState().subscriptionOwners;
    const subscriptionOwners = new Map<string, string>();
    const subscriptions = response.subscriptions
      .map((subscription) => {
        const ownerId = desiredOwners.get(subscription.subscription_id);
        if (ownerId) {
          subscriptionOwners.set(subscription.subscription_id, ownerId);
        }
        return cloneSubscription(subscription);
      })
      .sort((left, right) => left.subscription_id.localeCompare(right.subscription_id));

    const state: Omit<TabSessionStateRequest, 'revision'> = {
      lifecycle: normalizeJsonValue(response.lifecycle) as TabSessionLifecycle,
      route: normalizeJsonValue(response.route) as TabSessionRoute,
      subscriptions
    };

    return {
      state,
      stateKey: this.buildStateKey(state),
      subscriptionOwners
    };
  }

  private adoptAppliedState(composed: ComposedState, revision: number) {
    this.appliedRevision = revision;
    this.appliedStateKey = composed.stateKey;
    this.appliedSubscriptionOwners = composed.subscriptionOwners;
    writeStoredRevision(this.appliedRevision);
  }

  private scheduleSync(options: { keepalive?: boolean; deleteAfterSync?: boolean } = {}) {
    if (this.disposed) return;
    if (options.keepalive) {
      this.syncKeepaliveRequested = true;
    }
    if (options.deleteAfterSync) {
      this.deleteAfterSyncRequested = true;
    }
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

  private async syncState(options: { keepalive?: boolean; deleteAfterSync?: boolean } = {}) {
    const keepaliveRequested = options.keepalive ?? this.syncKeepaliveRequested;
    const deleteAfterSync = options.deleteAfterSync ?? this.deleteAfterSyncRequested;
    this.syncKeepaliveRequested = false;
    this.deleteAfterSyncRequested = false;

    for (let attempts = 0; attempts < 8; attempts += 1) {
      const desired = this.composeState();
      if (desired.stateKey === this.appliedStateKey) {
        if (deleteAfterSync) {
          await this.deleteTabSession(this.tabSessionId, { keepalive: keepaliveRequested });
        }
        this.ensureStream();
        return;
      }

      const syncTabSessionId = this.tabSessionId;
      const revision = this.appliedRevision + 1;
      const request = this.buildRequest(desired, revision);
      this.inFlightState = { revision, composed: desired };

      try {
        const result = await this.putTabSessionState(syncTabSessionId, request, {
          keepalive: keepaliveRequested
        });
        this.inFlightState = null;
        if (syncTabSessionId !== this.tabSessionId) {
          continue;
        }
        this.adoptAppliedState(desired, result.revision);
        if (deleteAfterSync) {
          await this.deleteTabSession(syncTabSessionId, { keepalive: keepaliveRequested });
        }
        this.ensureStream();
        return;
      } catch (error) {
        this.inFlightState = null;
        const status = typeof error === 'object' && error && 'status' in error ? Number((error as { status?: number }).status) : 0;
        if (status === 409) {
          const current = await api.realtime.tabSessionState(syncTabSessionId);
          if (syncTabSessionId !== this.tabSessionId) {
            continue;
          }
          const currentComposed = this.composeStateFromResponse(current);
          this.adoptAppliedState(currentComposed, current.revision);

          const latestDesired = this.composeState();
          if (latestDesired.stateKey === currentComposed.stateKey) {
            if (deleteAfterSync) {
              await this.deleteTabSession(syncTabSessionId, { keepalive: keepaliveRequested });
            }
            this.ensureStream();
            return;
          }
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

    console.error('tab realtime state sync exhausted retries');
  }

  private ensureStream() {
    if (this.disposed || this.source || !this.tabSessionId) return;
    if (this.lifecycle.visibility === 'closing') return;
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
    if (
      typeof event.config_revision === 'number' &&
      event.config_revision < this.appliedRevision
    ) {
      return;
    }

    const subscriptionId = event.source?.subscription_id;
    if (!subscriptionId) {
      if (event.op === 'control' && event.payload.type === 'session_deleted') {
        this.resetSessionIdentity();
        this.scheduleSync();
      }
      return;
    }

    const ownerMap =
      event.config_revision === this.appliedRevision
        ? this.appliedSubscriptionOwners
        : event.config_revision === this.inFlightState?.revision
          ? this.inFlightState.composed.subscriptionOwners
          : null;
    if (!ownerMap) return;

    const ownerId = ownerMap.get(subscriptionId);
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
    this.appliedStateKey = '';
    this.appliedRevision = 0;
    this.appliedSubscriptionOwners = new Map();
    this.inFlightState = null;
    this.syncKeepaliveRequested = false;
    this.deleteAfterSyncRequested = false;
    writeStoredRevision(0);
    this.tabSessionId = createTabSessionId();
    writeTabSessionId(this.tabSessionId);
    this.broadcastPresence('announce');
  }

  private async putTabSessionState(
    tabSessionId: string,
    payload: TabSessionStateRequest,
    options: { keepalive: boolean }
  ) {
    if (!options.keepalive) {
      return api.realtime.putTabSessionState(tabSessionId, payload);
    }

    const response = await fetch(
      new URL(`/api/realtime/tab-sessions/${encodeURIComponent(tabSessionId)}/state`, getBackendUrl()).toString(),
      {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true
      }
    );

    if (!response.ok) {
      const message = await response.text().catch(() => '');
      throw { status: response.status, message };
    }

    return response.json() as Promise<{ revision: number }>;
  }

  private async deleteTabSession(tabSessionId: string, options: { keepalive: boolean }) {
    if (!options.keepalive) {
      await api.realtime.deleteTabSession(tabSessionId);
      return;
    }

    const response = await fetch(
      new URL(`/api/realtime/tab-sessions/${encodeURIComponent(tabSessionId)}`, getBackendUrl()).toString(),
      {
        method: 'DELETE',
        credentials: 'include',
        keepalive: true
      }
    );

    if (!response.ok && response.status !== 404) {
      const message = await response.text().catch(() => '');
      throw { status: response.status, message };
    }
  }

  private initializePresenceChannel() {
    if (typeof BroadcastChannel === 'undefined') {
      return;
    }
    const channel = new BroadcastChannel(TAB_SESSION_BROADCAST_CHANNEL);
    channel.onmessage = (message) => {
      this.handlePresenceMessage(message.data as TabSessionPresenceMessage);
    };
    this.presenceChannel = channel;
    this.broadcastPresence('announce');
  }

  private broadcastPresence(type: TabSessionPresenceMessage['type']) {
    if (!this.presenceChannel) {
      return;
    }
    this.presenceChannel.postMessage({
      type,
      tabSessionId: this.tabSessionId,
      instanceId: this.instanceId
    } satisfies TabSessionPresenceMessage);
  }

  private handlePresenceMessage(message: TabSessionPresenceMessage) {
    if (
      !message ||
      typeof message !== 'object' ||
      message.instanceId === this.instanceId ||
      message.tabSessionId !== this.tabSessionId
    ) {
      return;
    }

    if (message.type === 'announce') {
      this.broadcastPresence('ack');
    }

    if (this.instanceId.localeCompare(message.instanceId) < 0) {
      return;
    }

    this.resetSessionIdentity();
    this.scheduleSync();
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

export const registerTabRealtimeContributor = (
  input: TabRealtimeContributor
): TabRealtimeContributorHandle | null => {
  return getTabRealtimeClient()?.registerContributor(input) ?? null;
};

export const setTabRealtimeRoute = (input: {
  id?: string;
  url?: string;
  params?: Record<string, string | undefined>;
}) => {
  getTabRealtimeClient()?.setRoute(input);
};

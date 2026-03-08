import { browser } from '$app/environment';
import { api, type TabSessionLifecycle, type TabSessionRoute, type TabSessionStateRequest, type TabSessionSubscription } from '$lib/api/client';
import { getBackendUrl } from '$lib/config';

const TAB_SESSION_ID_KEY = 'percus.realtime.tab_session_id';
const TAB_SESSION_REVISION_KEY = 'percus.realtime.tab_session_revision';
const TAB_SESSION_BROADCAST_CHANNEL = 'percus.realtime.tab_session';
const TAB_SESSION_DEBUG_KEY = 'percus.realtime.debug';

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

const clearStoredRevision = () => {
  if (!browser) return;
  sessionStorage.removeItem(TAB_SESSION_REVISION_KEY);
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

const readTabSessionRecord = () => {
  if (!browser) return { tabSessionId: '', existed: false };
  const existing = sessionStorage.getItem(TAB_SESSION_ID_KEY);
  if (existing) {
    return { tabSessionId: existing, existed: true };
  }
  const nextId = createTabSessionId();
  sessionStorage.setItem(TAB_SESSION_ID_KEY, nextId);
  return { tabSessionId: nextId, existed: false };
};

const writeTabSessionId = (tabSessionId: string) => {
  if (!browser) return;
  sessionStorage.setItem(TAB_SESSION_ID_KEY, tabSessionId);
};

const clearStoredTabSessionId = () => {
  if (!browser) return;
  sessionStorage.removeItem(TAB_SESSION_ID_KEY);
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
  private readonly initialSession = readTabSessionRecord();
  private instanceId = createClientInstanceId();
  private tabSessionId = this.initialSession.tabSessionId;
  private hasStoredSession = this.initialSession.existed;
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
  private pendingSyncReasons: string[] = [];
  private bootstrapInFlight: Promise<void> | null = null;
  private bootstrapComplete = false;
  private shouldPersistSessionRecord = true;

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
    this.debug('contributor.register', {
      contributorId,
      subscriptionIds: contributor.subscriptions.map((subscription) => subscription.subscription_id),
    });
    this.scheduleSync(`contributor.register:${contributorId}`);

    return {
      setSubscriptions: (subscriptions) => {
        const current = this.contributors.get(contributorId);
        if (!current) return;
        current.subscriptions = [...subscriptions];
        this.debug('contributor.setSubscriptions', {
          contributorId,
          subscriptionIds: subscriptions.map((subscription) => subscription.subscription_id),
        });
        this.scheduleSync(`contributor.setSubscriptions:${contributorId}`);
      },
      setEventHandler: (onEvent) => {
        const current = this.contributors.get(contributorId);
        if (!current) return;
        current.onEvent = onEvent;
      },
      dispose: () => {
        if (!this.contributors.delete(contributorId)) return;
        this.debug('contributor.dispose', { contributorId });
        this.scheduleSync(`contributor.dispose:${contributorId}`);
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
    this.debug('route.set', { route: nextRoute });
    this.scheduleSync('route.set');
  }

  async close(): Promise<void> {
    if (this.disposed) return;
    this.lifecycle = {
      visibility: 'closing',
      reason: 'close'
    };
    this.shouldPersistSessionRecord = false;
    this.clearStoredSessionRecord();
    try {
      this.scheduleSync('client.close', { deleteAfterSync: true });
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
    this.debug('lifecycle.visibilitychange', { lifecycle: this.lifecycle });
    this.scheduleSync('lifecycle.visibilitychange');
  };

  private readonly handleOnline = () => {
    this.debug('network.online');
    this.scheduleSync('network.online');
    this.ensureStream();
  };

  private readonly handlePageHide = () => {
    this.lifecycle = {
      visibility: 'closing',
      reason: 'pagehide'
    };
    this.shouldPersistSessionRecord = false;
    this.clearStoredSessionRecord();
    this.closeStream();
    this.debug('lifecycle.pagehide', { lifecycle: this.lifecycle });
    this.scheduleSync('lifecycle.pagehide', { keepalive: true, deleteAfterSync: true });
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
    if (this.shouldPersistSessionRecord) {
      writeStoredRevision(this.appliedRevision);
    }
  }

  private scheduleSync(
    reason: string,
    options: { keepalive?: boolean; deleteAfterSync?: boolean } = {}
  ) {
    if (this.disposed) return;
    this.pendingSyncReasons.push(reason);
    if (options.keepalive) {
      this.syncKeepaliveRequested = true;
    }
    if (options.deleteAfterSync) {
      this.deleteAfterSyncRequested = true;
    }
    this.debug('sync.schedule', {
      reason,
      queuedReasons: [...this.pendingSyncReasons],
      inFlight: Boolean(this.syncInFlight),
      syncQueued: this.syncQueued,
      keepaliveRequested: this.syncKeepaliveRequested,
      deleteAfterSyncRequested: this.deleteAfterSyncRequested,
      appliedRevision: this.appliedRevision,
      appliedStateKey: this.shortHash(this.appliedStateKey),
    });
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
          this.scheduleSync('sync.queued-drain');
        }
      });
  }

  private async syncState(options: { keepalive?: boolean; deleteAfterSync?: boolean } = {}) {
    const keepaliveRequested = options.keepalive ?? this.syncKeepaliveRequested;
    const deleteAfterSync = options.deleteAfterSync ?? this.deleteAfterSyncRequested;
    const reasons = [...this.pendingSyncReasons];
    this.pendingSyncReasons = [];
    this.syncKeepaliveRequested = false;
    this.deleteAfterSyncRequested = false;
    this.debug('sync.start', {
      reasons,
      keepaliveRequested,
      deleteAfterSync,
      appliedRevision: this.appliedRevision,
      appliedStateKey: this.shortHash(this.appliedStateKey),
    });

    await this.ensureBootstrappedState(reasons);

    for (let attempts = 0; attempts < 8; attempts += 1) {
      const desired = this.composeState();
      this.debug('sync.compose', {
        attempt: attempts + 1,
        reasons,
        desiredStateKey: this.shortHash(desired.stateKey),
        subscriptionCount: desired.state.subscriptions.length,
      });
      if (desired.stateKey === this.appliedStateKey) {
        this.debug('sync.skip-applied-match', {
          reasons,
          deleteAfterSync,
          appliedRevision: this.appliedRevision,
          appliedStateKey: this.shortHash(this.appliedStateKey),
        });
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
      this.debug('sync.put.start', {
        attempt: attempts + 1,
        reasons,
        tabSessionId: syncTabSessionId,
        requestedRevision: revision,
        desiredStateKey: this.shortHash(desired.stateKey),
        keepaliveRequested,
        deleteAfterSync,
      });

      try {
        const result = await this.putTabSessionState(syncTabSessionId, request, {
          keepalive: keepaliveRequested
        });
        this.inFlightState = null;
        this.debug('sync.put.success', {
          attempt: attempts + 1,
          reasons,
          tabSessionId: syncTabSessionId,
          requestedRevision: revision,
          appliedRevision: result.revision,
          desiredStateKey: this.shortHash(desired.stateKey),
        });
        if (syncTabSessionId !== this.tabSessionId) {
          this.debug('sync.put.stale-session-ignored', {
            attempt: attempts + 1,
            reasons,
            syncTabSessionId,
            currentTabSessionId: this.tabSessionId,
          });
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
          this.debug('sync.put.conflict', {
            attempt: attempts + 1,
            reasons,
            tabSessionId: syncTabSessionId,
            requestedRevision: revision,
            currentRevision: current.revision,
            desiredStateKey: this.shortHash(desired.stateKey),
            currentStateKey: this.shortHash(this.buildStateKey({
              lifecycle: current.lifecycle,
              route: current.route,
              subscriptions: current.subscriptions,
            })),
          });
          if (syncTabSessionId !== this.tabSessionId) {
            this.debug('sync.put.conflict.stale-session-ignored', {
              attempt: attempts + 1,
              reasons,
              syncTabSessionId,
              currentTabSessionId: this.tabSessionId,
            });
            continue;
          }
          const currentComposed = this.composeStateFromResponse(current);
          this.adoptAppliedState(currentComposed, current.revision);

          const latestDesired = this.composeState();
          if (latestDesired.stateKey === currentComposed.stateKey) {
            this.debug('sync.put.conflict.adopt-server-state', {
              attempt: attempts + 1,
              reasons,
              tabSessionId: syncTabSessionId,
              adoptedRevision: current.revision,
              adoptedStateKey: this.shortHash(currentComposed.stateKey),
            });
            if (deleteAfterSync) {
              await this.deleteTabSession(syncTabSessionId, { keepalive: keepaliveRequested });
            }
            this.ensureStream();
            return;
          }
          this.debug('sync.put.conflict.retry-latest-desired', {
            attempt: attempts + 1,
            reasons,
            tabSessionId: syncTabSessionId,
            adoptedRevision: current.revision,
            latestDesiredStateKey: this.shortHash(latestDesired.stateKey),
          });
          continue;
        }
        if (status === 404) {
          this.debug('sync.put.session-missing', {
            attempt: attempts + 1,
            reasons,
            tabSessionId: syncTabSessionId,
          });
          this.resetSessionIdentity();
          continue;
        }
        if (status === 401) {
          this.debug('sync.put.unauthorized', {
            attempt: attempts + 1,
            reasons,
            tabSessionId: syncTabSessionId,
          });
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
      this.scheduleSync('stream.reconnect');
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
        this.scheduleSync('control.session_deleted');
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

  private async ensureBootstrappedState(reasons: string[]) {
    if (this.bootstrapComplete || !this.hasStoredSession || !this.tabSessionId) {
      return;
    }
    if (this.bootstrapInFlight) {
      await this.bootstrapInFlight;
      return;
    }

    const bootstrapTabSessionId = this.tabSessionId;
    this.bootstrapInFlight = (async () => {
      this.debug('bootstrap.start', {
        reasons,
        tabSessionId: bootstrapTabSessionId,
        storedRevision: this.appliedRevision,
      });
      try {
        const current = await api.realtime.tabSessionState(bootstrapTabSessionId);
        if (bootstrapTabSessionId !== this.tabSessionId) {
          this.debug('bootstrap.stale-session-ignored', {
            reasons,
            bootstrapTabSessionId,
            currentTabSessionId: this.tabSessionId,
          });
          return;
        }
        const currentComposed = this.composeStateFromResponse(current);
        this.adoptAppliedState(currentComposed, current.revision);
        this.hasStoredSession = false;
        this.bootstrapComplete = true;
        this.debug('bootstrap.adopt-server-state', {
          reasons,
          tabSessionId: bootstrapTabSessionId,
          adoptedRevision: current.revision,
          adoptedStateKey: this.shortHash(currentComposed.stateKey),
        });
      } catch (error) {
        const status =
          typeof error === 'object' && error && 'status' in error
            ? Number((error as { status?: number }).status)
            : 0;
        if (status === 404) {
          this.debug('bootstrap.session-missing', {
            reasons,
            tabSessionId: bootstrapTabSessionId,
          });
          if (bootstrapTabSessionId === this.tabSessionId) {
            this.resetSessionIdentity();
          }
          this.bootstrapComplete = true;
          return;
        }
        if (status === 401) {
          this.debug('bootstrap.unauthorized', {
            reasons,
            tabSessionId: bootstrapTabSessionId,
          });
          this.closeStream();
          this.bootstrapComplete = true;
          return;
        }
        this.debug('bootstrap.failed', {
          reasons,
          tabSessionId: bootstrapTabSessionId,
          status,
          error: error instanceof Error ? error.message : String(error),
        });
      } finally {
        this.bootstrapInFlight = null;
      }
    })();

    await this.bootstrapInFlight;
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
    this.bootstrapInFlight = null;
    this.bootstrapComplete = true;
    this.hasStoredSession = false;
    this.shouldPersistSessionRecord = true;
    writeStoredRevision(0);
    this.tabSessionId = createTabSessionId();
    writeTabSessionId(this.tabSessionId);
    this.broadcastPresence('announce');
  }

  private clearStoredSessionRecord() {
    clearStoredTabSessionId();
    clearStoredRevision();
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
      this.debug('presence.keep-current-session', {
        tabSessionId: this.tabSessionId,
        localInstanceId: this.instanceId,
        remoteInstanceId: message.instanceId,
        messageType: message.type,
      });
      return;
    }

    this.debug('presence.reset-session-identity', {
      tabSessionId: this.tabSessionId,
      localInstanceId: this.instanceId,
      remoteInstanceId: message.instanceId,
      messageType: message.type,
    });
    this.resetSessionIdentity();
    this.scheduleSync('presence.reset-session-identity');
  }

  private isDebugEnabled() {
    if (!browser) return false;
    const fromSession =
      typeof sessionStorage !== 'undefined'
        ? sessionStorage.getItem(TAB_SESSION_DEBUG_KEY)
        : null;
    const fromLocal =
      typeof localStorage !== 'undefined'
        ? localStorage.getItem(TAB_SESSION_DEBUG_KEY)
        : null;
    if (fromSession === '1' || fromLocal === '1') {
      return true;
    }
    const locationSearch =
      typeof window !== 'undefined' && 'location' in window && window.location
        ? window.location.search
        : '';
    return new URLSearchParams(locationSearch).get('realtimeDebug') === '1';
  }

  private shortHash(value: string) {
    if (!value) return 'empty';
    let hash = 0;
    for (let index = 0; index < value.length; index += 1) {
      hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
    }
    return hash.toString(16).padStart(8, '0');
  }

  private debug(event: string, payload: Record<string, unknown> = {}) {
    if (!this.isDebugEnabled()) {
      return;
    }
    console.debug('[tab-realtime]', {
      event,
      instanceId: this.instanceId,
      tabSessionId: this.tabSessionId,
      appliedRevision: this.appliedRevision,
      appliedStateKey: this.shortHash(this.appliedStateKey),
      inFlightRevision: this.inFlightState?.revision ?? null,
      syncQueued: this.syncQueued,
      contributorCount: this.contributors.size,
      ...payload,
    });
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

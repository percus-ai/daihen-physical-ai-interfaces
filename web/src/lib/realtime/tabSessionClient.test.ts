import { beforeEach, describe, expect, it, vi } from 'vitest';

const realtimeApi = {
  tabSessionState: vi.fn(),
  putTabSessionState: vi.fn(),
  deleteTabSession: vi.fn()
};

const authApi = {
  status: vi.fn(),
  refresh: vi.fn()
};

vi.mock('$app/environment', () => ({
  browser: true
}));

vi.mock('$lib/config', () => ({
  getBackendUrl: () => 'http://backend.test'
}));

vi.mock('$lib/api/client', () => ({
  api: {
    realtime: realtimeApi,
    auth: authApi
  }
}));

type ListenerMap = Map<string, Set<(...args: unknown[]) => void>>;

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  static readonly CLOSED = 2;

  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;

  constructor(
    readonly url: string,
    readonly options?: { withCredentials?: boolean }
  ) {
    FakeEventSource.instances.push(this);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
}

class FakeBroadcastChannel {
  static channels = new Map<string, Set<FakeBroadcastChannel>>();

  onmessage: ((event: MessageEvent<unknown>) => void) | null = null;

  constructor(readonly name: string) {
    const channelSet = FakeBroadcastChannel.channels.get(name) ?? new Set<FakeBroadcastChannel>();
    channelSet.add(this);
    FakeBroadcastChannel.channels.set(name, channelSet);
  }

  postMessage(message: unknown) {
    const channelSet = FakeBroadcastChannel.channels.get(this.name) ?? new Set<FakeBroadcastChannel>();
    for (const channel of channelSet) {
      if (channel === this) continue;
      channel.onmessage?.({ data: message } as MessageEvent<unknown>);
    }
  }

  close() {
    const channelSet = FakeBroadcastChannel.channels.get(this.name);
    if (!channelSet) return;
    channelSet.delete(this);
    if (channelSet.size === 0) {
      FakeBroadcastChannel.channels.delete(this.name);
    }
  }
}

const createStorage = () => {
  const storage = new Map<string, string>();
  return {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => {
      storage.set(key, value);
    },
    removeItem: (key: string) => {
      storage.delete(key);
    },
    clear: () => {
      storage.clear();
    }
  };
};

const createEventTarget = () => {
  const listeners: ListenerMap = new Map();
  return {
    listeners,
    addEventListener: (type: string, callback: (...args: unknown[]) => void) => {
      const callbacks = listeners.get(type) ?? new Set<(...args: unknown[]) => void>();
      callbacks.add(callback);
      listeners.set(type, callbacks);
    },
    removeEventListener: (type: string, callback: (...args: unknown[]) => void) => {
      listeners.get(type)?.delete(callback);
    },
    dispatch: (type: string, event?: unknown) => {
      for (const callback of listeners.get(type) ?? []) {
        callback(event);
      }
    }
  };
};

const buildStateResponse = (overrides: Partial<{
  tab_session_id: string;
  revision: number;
  lifecycle: { visibility: 'foreground' | 'background' | 'closing'; reason?: string | null };
  route: { id: string; url: string; params: Record<string, string> };
  subscriptions: Array<{
    subscription_id: string;
    kind: 'profiles.active';
    params: Record<string, never>;
  }>;
}> = {}) => ({
  tab_session_id: overrides.tab_session_id ?? 'tab-test',
  revision: overrides.revision ?? 1,
  lifecycle: overrides.lifecycle ?? { visibility: 'foreground' as const },
  route: overrides.route ?? { id: 'unknown', url: '/', params: {} },
  subscriptions:
    overrides.subscriptions ??
    [
      {
        subscription_id: 'profiles.active',
        kind: 'profiles.active' as const,
        params: {}
      }
    ]
});

const flushClient = async (client: { syncInFlight?: Promise<void> | null }) => {
  for (let attempts = 0; attempts < 10; attempts += 1) {
    const inFlight = client.syncInFlight;
    if (!inFlight) {
      await Promise.resolve();
      return;
    }
    await inFlight;
  }
  throw new Error('sync did not settle');
};

describe('tabSessionClient', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    FakeEventSource.instances = [];
    FakeBroadcastChannel.channels.clear();
    authApi.status.mockResolvedValue({
      authenticated: true,
      expires_at: Math.floor(Date.now() / 1000) + 3600
    });
    authApi.refresh.mockResolvedValue({
      authenticated: true,
      expires_at: Math.floor(Date.now() / 1000) + 3600
    });

    const documentTarget = createEventTarget();
    const windowTarget = createEventTarget();

    vi.stubGlobal('sessionStorage', createStorage());
    vi.stubGlobal('document', {
      ...documentTarget,
      visibilityState: 'visible'
    });
    vi.stubGlobal('window', {
      ...windowTarget,
      setTimeout,
      clearTimeout
    });
    vi.stubGlobal('EventSource', FakeEventSource);
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ revision: 2 }),
        text: async () => ''
      }))
    );
  });

  it('adopts server state after 409 when desired already matches', async () => {
    realtimeApi.putTabSessionState.mockRejectedValueOnce({ status: 409 });
    realtimeApi.tabSessionState.mockResolvedValueOnce(
      buildStateResponse({
        revision: 7
      })
    );

    const { getTabRealtimeClient } = await import('./tabSessionClient');
    const client = getTabRealtimeClient() as unknown as {
      registerContributor: (input: {
        contributorId?: string;
        subscriptions: Array<{
          subscription_id: string;
          kind: 'profiles.active';
          params: Record<string, never>;
        }>;
      }) => unknown;
      appliedRevision?: number;
      syncInFlight?: Promise<void> | null;
    };

    client.registerContributor({
      contributorId: 'profiles',
      subscriptions: [
        {
          subscription_id: 'profiles.active',
          kind: 'profiles.active',
          params: {}
        }
      ]
    });

    await flushClient(client);

    expect(realtimeApi.putTabSessionState).toHaveBeenCalledTimes(1);
    expect(realtimeApi.tabSessionState).toHaveBeenCalledTimes(1);
    expect(client.appliedRevision).toBe(7);
  });

  it('bootstraps stored tab session state before first PUT after reload', async () => {
    sessionStorage.setItem('percus.realtime.tab_session_id', 'tab-reload');
    sessionStorage.setItem('percus.realtime.tab_session_revision', '13');
    realtimeApi.tabSessionState.mockResolvedValueOnce(
      buildStateResponse({
        tab_session_id: 'tab-reload',
        revision: 14
      })
    );

    const { getTabRealtimeClient } = await import('./tabSessionClient');
    const client = getTabRealtimeClient() as unknown as {
      registerContributor: (input: {
        contributorId?: string;
        subscriptions: Array<{
          subscription_id: string;
          kind: 'profiles.active';
          params: Record<string, never>;
        }>;
      }) => unknown;
      appliedRevision?: number;
      syncInFlight?: Promise<void> | null;
    };

    client.registerContributor({
      contributorId: 'profiles',
      subscriptions: [
        {
          subscription_id: 'profiles.active',
          kind: 'profiles.active',
          params: {}
        }
      ]
    });

    await flushClient(client);

    expect(realtimeApi.tabSessionState).toHaveBeenCalledTimes(1);
    expect(realtimeApi.putTabSessionState).not.toHaveBeenCalled();
    expect(client.appliedRevision).toBe(14);
  });

  it('canonicalizes subscription order to avoid redundant PUTs', async () => {
    realtimeApi.putTabSessionState.mockResolvedValue({ revision: 1 });

    const { getTabRealtimeClient } = await import('./tabSessionClient');
    const client = getTabRealtimeClient() as unknown as {
      registerContributor: (input: {
        contributorId?: string;
        subscriptions: Array<{
          subscription_id: string;
          kind: 'profiles.active';
          params: Record<string, never>;
        }>;
      }) => {
        setSubscriptions: (subscriptions: Array<{
          subscription_id: string;
          kind: 'profiles.active';
          params: Record<string, never>;
        }>) => void;
      };
      syncInFlight?: Promise<void> | null;
    };

    const handle = client.registerContributor({
      contributorId: 'profiles',
      subscriptions: [
        { subscription_id: 'b', kind: 'profiles.active', params: {} },
        { subscription_id: 'a', kind: 'profiles.active', params: {} }
      ]
    });
    await flushClient(client);

    handle.setSubscriptions([
      { subscription_id: 'a', kind: 'profiles.active', params: {} },
      { subscription_id: 'b', kind: 'profiles.active', params: {} }
    ]);
    await flushClient(client);

    expect(realtimeApi.putTabSessionState).toHaveBeenCalledTimes(1);
  });

  it('does not send network requests on pagehide', async () => {
    sessionStorage.setItem('percus.realtime.tab_session_id', 'tab-pagehide');
    sessionStorage.setItem('percus.realtime.tab_session_revision', '1');

    const { getTabRealtimeClient } = await import('./tabSessionClient');
    const client = getTabRealtimeClient() as unknown as {
      syncInFlight?: Promise<void> | null;
    };

    (window as unknown as { dispatch: (type: string) => void }).dispatch('pagehide');
    await flushClient(client);

    expect(realtimeApi.putTabSessionState).not.toHaveBeenCalled();
    expect(realtimeApi.deleteTabSession).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('percus.realtime.tab_session_id')).toBeNull();
    expect(sessionStorage.getItem('percus.realtime.tab_session_revision')).toBeNull();
  });

  it('recreates tab session after stream reconnect finds missing server session', async () => {
    vi.useFakeTimers();
    try {
      (window as unknown as { setTimeout: typeof setTimeout; clearTimeout: typeof clearTimeout }).setTimeout = setTimeout;
      (window as unknown as { setTimeout: typeof setTimeout; clearTimeout: typeof clearTimeout }).clearTimeout = clearTimeout;
      realtimeApi.putTabSessionState
        .mockResolvedValueOnce({ revision: 1 })
        .mockResolvedValueOnce({ revision: 1 });
      realtimeApi.tabSessionState.mockRejectedValueOnce({ status: 404 });

      const { getTabRealtimeClient } = await import('./tabSessionClient');
      const client = getTabRealtimeClient() as unknown as {
        registerContributor: (input: {
          contributorId?: string;
          subscriptions: Array<{
            subscription_id: string;
            kind: 'profiles.active';
            params: Record<string, never>;
          }>;
        }) => unknown;
        tabSessionId?: string;
        syncInFlight?: Promise<void> | null;
      };

      client.registerContributor({
        contributorId: 'profiles',
        subscriptions: [
          {
            subscription_id: 'profiles.active',
            kind: 'profiles.active',
            params: {}
          }
        ]
      });
      await flushClient(client);

      const firstSource = FakeEventSource.instances[0];
      const firstTabSessionId = client.tabSessionId;

      firstSource?.onerror?.();
      await vi.advanceTimersByTimeAsync(1000);
      await flushClient(client);

      expect(firstSource?.readyState).toBe(FakeEventSource.CLOSED);
      expect(realtimeApi.tabSessionState).toHaveBeenCalledWith(firstTabSessionId);
      expect(client.tabSessionId).toBeTruthy();
      expect(client.tabSessionId).not.toBe(firstTabSessionId);
      expect(realtimeApi.putTabSessionState).toHaveBeenCalledTimes(2);
      expect(FakeEventSource.instances.at(-1)?.url).toContain(client.tabSessionId ?? '');
    } finally {
      vi.useRealTimers();
    }
  });

  it('resets session identity when another tab announces the same tab_session_id', async () => {
    const { getTabRealtimeClient } = await import('./tabSessionClient');
    const client = getTabRealtimeClient() as unknown as {
      tabSessionId?: string;
      instanceId?: string;
      handlePresenceMessage?: (message: {
        type: 'announce' | 'ack';
        tabSessionId: string;
        instanceId: string;
      }) => void;
    };

    const previousTabSessionId = client.tabSessionId;
    client.handlePresenceMessage?.({
      type: 'announce',
      tabSessionId: previousTabSessionId ?? '',
      instanceId: ''
    });

    expect(client.tabSessionId).toBeTruthy();
    expect(client.tabSessionId).not.toBe(previousTabSessionId);
  });

  it('refreshes auth and reconnects the stream before the token expires', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-21T00:00:00Z'));
    try {
      (window as unknown as { setTimeout: typeof setTimeout; clearTimeout: typeof clearTimeout }).setTimeout = setTimeout;
      (window as unknown as { setTimeout: typeof setTimeout; clearTimeout: typeof clearTimeout }).clearTimeout = clearTimeout;

      const nowSeconds = Math.floor(Date.now() / 1000);
      authApi.status.mockResolvedValueOnce({
        authenticated: true,
        expires_at: nowSeconds + 120
      });
      authApi.refresh.mockResolvedValueOnce({
        authenticated: true,
        expires_at: nowSeconds + 3600
      });
      realtimeApi.putTabSessionState.mockResolvedValue({ revision: 1 });
      realtimeApi.tabSessionState.mockResolvedValue(
        buildStateResponse({
          revision: 1
        })
      );

      const { getTabRealtimeClient } = await import('./tabSessionClient');
      const client = getTabRealtimeClient() as unknown as {
        registerContributor: (input: {
          contributorId?: string;
          subscriptions: Array<{
            subscription_id: string;
            kind: 'profiles.active';
            params: Record<string, never>;
          }>;
        }) => unknown;
        syncInFlight?: Promise<void> | null;
      };

      client.registerContributor({
        contributorId: 'profiles',
        subscriptions: [
          {
            subscription_id: 'profiles.active',
            kind: 'profiles.active',
            params: {}
          }
        ]
      });
      await flushClient(client);
      await Promise.resolve();

      const firstSource = FakeEventSource.instances[0];
      await vi.advanceTimersByTimeAsync(60_000);
      await flushClient(client);

      expect(authApi.refresh).toHaveBeenCalledTimes(1);
      expect(firstSource?.readyState).toBe(FakeEventSource.CLOSED);
      expect(FakeEventSource.instances).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });
});

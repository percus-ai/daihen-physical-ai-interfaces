import { beforeEach, describe, expect, it, vi } from 'vitest';

const eventSources: FakeEventSource[] = [];

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  url: string;
  withCredentials: boolean;
  readyState = FakeEventSource.OPEN;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Array<(event: MessageEvent) => void>>();

  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.withCredentials = Boolean(init?.withCredentials);
    eventSources.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    const handlers = this.listeners.get(type) ?? [];
    handlers.push(listener as (event: MessageEvent) => void);
    this.listeners.set(type, handlers);
  }

  emit(type: string, data: unknown) {
    const event = { data: JSON.stringify(data) } as MessageEvent;
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
}

vi.mock('$app/environment', () => ({ browser: true }));
vi.mock('$lib/config', () => ({ getBackendUrl: () => 'http://backend.local' }));

describe('RealtimeTrackClient', () => {
  beforeEach(() => {
    vi.resetModules();
    eventSources.length = 0;
    const storage = new Map<string, string>();
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear()
    });
    sessionStorage.clear();
    vi.stubGlobal('EventSource', FakeEventSource);
    vi.stubGlobal('crypto', { randomUUID: () => 'tab-1' });
  });

  it('opens one realtime stream and dispatches matching frames', async () => {
    const { registerRealtimeTrackConsumer } = await import('./trackClient');
    const handler = vi.fn();

    const handle = registerRealtimeTrackConsumer({
      tracks: [{ kind: 'system.status', key: 'system' }],
      onEvent: handler
    });

    expect(handle).not.toBeNull();
    expect(eventSources).toHaveLength(1);
    expect(eventSources[0].url).toBe('http://backend.local/api/realtime/stream?tab_id=tab-1');
    expect(eventSources[0].withCredentials).toBe(true);

    eventSources[0].emit('realtime', {
      kind: 'system.status',
      key: 'system',
      revision: 1,
      detail: { backend: 'ok' }
    });

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'system.status',
        key: 'system',
        revision: 1,
        detail: { backend: 'ok' }
      })
    );
  });

  it('filters frames by derived job log key', async () => {
    const { registerRealtimeTrackConsumer } = await import('./trackClient');
    const handler = vi.fn();

    registerRealtimeTrackConsumer({
      tracks: [
        {
          kind: 'training.job.logs',
          params: { job_id: 'job-1', log_type: 'training' }
        }
      ],
      onEvent: handler
    });

    eventSources[0].emit('realtime', {
      kind: 'training.job.logs',
      key: 'job-1:setup',
      revision: 1,
      detail: { lines: ['ignore'] }
    });
    eventSources[0].emit('realtime', {
      kind: 'training.job.logs',
      key: 'job-1:training',
      revision: 2,
      detail: { lines: ['keep'] }
    });

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        kind: 'training.job.logs',
        key: 'job-1:training',
        detail: { lines: ['keep'] }
      })
    );
  });

  it('passes log signal frames without adding an operation type', async () => {
    const { registerRealtimeTrackConsumer } = await import('./trackClient');
    const handler = vi.fn();

    registerRealtimeTrackConsumer({
      tracks: [
        {
          kind: 'training.job.logs',
          params: { job_id: 'job-1', log_type: 'setup' }
        }
      ],
      onEvent: handler
    });

    eventSources[0].emit('realtime', {
      kind: 'training.job.logs',
      key: 'job-1:setup',
      revision: 1,
      detail: { type: 'ip_missing', job_id: 'job-1', log_type: 'setup' }
    });

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'training.job.logs',
        key: 'job-1:setup',
        detail: { type: 'ip_missing', job_id: 'job-1', log_type: 'setup' }
      })
    );
  });
});

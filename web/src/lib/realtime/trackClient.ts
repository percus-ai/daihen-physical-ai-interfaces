import { browser } from '$app/environment';
import { getBackendUrl } from '$lib/config';

const TAB_ID_KEY = 'percus.realtime.tab_id';
const REALTIME_DEBUG_KEY = 'percus.realtime.debug';

export type RealtimeFrame = {
  kind: string;
  key: string;
  revision: number;
  detail: Record<string, unknown>;
};

export type RealtimeTrackSelector = {
  kind: string;
  key?: string;
  params?: Record<string, unknown>;
};

export type RealtimeTrackEvent = RealtimeFrame & {
  source: {
    kind: string;
    key: string;
    params?: Record<string, unknown>;
  };
  op: 'snapshot' | 'append' | 'control' | 'error';
  payload: Record<string, unknown>;
};

type ConsumerState = {
  id: string;
  tracks: RealtimeTrackSelector[];
  onEvent?: (event: RealtimeTrackEvent) => void;
};

export type RealtimeTrackConsumerInput = {
  contributorId?: string;
  tracks?: RealtimeTrackSelector[];
  onEvent?: (event: RealtimeTrackEvent) => void;
};

export type RealtimeTrackConsumerHandle = {
  setTracks: (tracks: RealtimeTrackSelector[]) => void;
  setEventHandler: (onEvent?: (event: RealtimeTrackEvent) => void) => void;
  dispose: () => void;
};

const createTabId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `tab-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};

const readTabId = () => {
  if (!browser) return '';
  const existing = sessionStorage.getItem(TAB_ID_KEY);
  if (existing) return existing;
  const next = createTabId();
  sessionStorage.setItem(TAB_ID_KEY, next);
  return next;
};

const normalizeTracks = (tracks: RealtimeTrackSelector[] | undefined) => {
  return [...(tracks ?? [])].map((track) => ({ ...track }));
};

const detailKeyFromSelector = (selector: RealtimeTrackSelector) => {
  if (selector.key) return selector.key;
  const params = selector.params ?? {};
  const operationId = String(params.operation_id ?? '').trim();
  if (operationId) return operationId;
  const jobId = String(params.job_id ?? '').trim();
  if (selector.kind === 'training.job.logs' && jobId) {
    const logType = String(params.log_type ?? 'training').trim() || 'training';
    return `${jobId}:${logType}`;
  }
  if (jobId) return jobId;
  const sessionId = String(params.session_id ?? '').trim();
  if (sessionId) return sessionId;
  return '';
};

const matchesSelector = (selector: RealtimeTrackSelector, frame: RealtimeFrame) => {
  if (selector.kind !== frame.kind) return false;
  const key = detailKeyFromSelector(selector);
  return !key || key === frame.key;
};

const eventOpForFrame = (frame: RealtimeFrame): RealtimeTrackEvent['op'] => {
  const type = String(frame.detail.type ?? '').trim();
  if (type === 'connected' || type === 'stream_ended' || type === 'job_status') {
    return 'control';
  }
  if (frame.detail.error || frame.detail.failure_reason) {
    return 'error';
  }
  if (frame.kind.endsWith('.logs') || frame.kind === 'builds.logs') {
    return 'append';
  }
  return 'snapshot';
};

const toEvent = (frame: RealtimeFrame, selector: RealtimeTrackSelector): RealtimeTrackEvent => ({
  ...frame,
  source: {
    kind: frame.kind,
    key: frame.key,
    params: selector.params
  },
  op: eventOpForFrame(frame),
  payload: frame.detail
});

class RealtimeClient {
  private tabId = readTabId();
  private source: EventSource | null = null;
  private consumers = new Map<string, ConsumerState>();
  private nextConsumerSequence = 0;
  private reconnectTimer: number | null = null;
  private disposed = false;

  registerConsumer(input: RealtimeTrackConsumerInput): RealtimeTrackConsumerHandle {
    const consumerId = input.contributorId?.trim() || `consumer-${++this.nextConsumerSequence}`;
    const consumer: ConsumerState = {
      id: consumerId,
      tracks: normalizeTracks(input.tracks),
      onEvent: input.onEvent
    };
    this.consumers.set(consumerId, consumer);
    this.debug('consumer.register', { consumerId, tracks: consumer.tracks });
    this.ensureStream();

    const setTracks = (tracks: RealtimeTrackSelector[]) => {
      const current = this.consumers.get(consumerId);
      if (!current) return;
      current.tracks = normalizeTracks(tracks);
      this.debug('consumer.setTracks', { consumerId, tracks: current.tracks });
      this.ensureStream();
    };

    return {
      setTracks,
      setEventHandler: (onEvent) => {
        const current = this.consumers.get(consumerId);
        if (!current) return;
        current.onEvent = onEvent;
      },
      dispose: () => {
        this.consumers.delete(consumerId);
        this.debug('consumer.dispose', { consumerId });
        if (this.consumers.size === 0) {
          this.closeStream();
        }
      }
    };
  }

  close() {
    this.disposed = true;
    this.closeStream();
  }

  private ensureStream() {
    if (!browser || this.disposed || this.source || this.consumers.size === 0 || !this.tabId) return;
    const url = new URL('/api/realtime/stream', getBackendUrl());
    url.searchParams.set('tab_id', this.tabId);
    const source = new EventSource(url.toString(), { withCredentials: true });
    this.source = source;

    source.addEventListener('realtime', (event) => {
      try {
        this.dispatchFrame(JSON.parse(event.data) as RealtimeFrame);
      } catch (error) {
        console.error('[realtime] failed to parse frame', error);
      }
    });
    source.onerror = () => {
      this.closeStream();
      if (this.disposed || this.consumers.size === 0) return;
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = null;
        this.ensureStream();
      }, 1000);
    };
  }

  private closeStream() {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.source?.close();
    this.source = null;
  }

  private dispatchFrame(frame: RealtimeFrame) {
    for (const consumer of this.consumers.values()) {
      const selector = consumer.tracks.find((track) => matchesSelector(track, frame));
      if (!selector) continue;
      consumer.onEvent?.(toEvent(frame, selector));
    }
  }

  private debug(message: string, detail?: Record<string, unknown>) {
    if (!browser || sessionStorage.getItem(REALTIME_DEBUG_KEY) !== '1') return;
    console.debug(`[realtime] ${message}`, detail ?? {});
  }
}

let singletonClient: RealtimeClient | null = null;

export const getRealtimeTrackClient = () => {
  if (!browser) return null;
  if (singletonClient === null) {
    singletonClient = new RealtimeClient();
  }
  return singletonClient;
};

export const registerRealtimeTrackConsumer = (
  input: RealtimeTrackConsumerInput
): RealtimeTrackConsumerHandle | null => {
  return getRealtimeTrackClient()?.registerConsumer(input) ?? null;
};

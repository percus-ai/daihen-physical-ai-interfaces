import { browser } from '$app/environment';
import { getBackendUrl } from '$lib/config';

export type StreamScope = 'route' | 'persistent';

type StreamOptions<T> = {
  path: string;
  onMessage: (payload: T) => void;
  onError?: (event: Event) => void;
  scope?: StreamScope;
};

type ManagedStream = {
  scope: StreamScope;
  close: () => void;
};

const activeStreams = new Map<number, ManagedStream>();
let nextStreamId = 1;

export const closeRouteScopedStreams = () => {
  for (const stream of [...activeStreams.values()]) {
    if (stream.scope === 'route') {
      stream.close();
    }
  }
};

export const connectStream = <T>({ path, onMessage, onError, scope = 'route' }: StreamOptions<T>) => {
  if (!browser) return () => {};

  const baseUrl = getBackendUrl();
  const url = new URL(path, baseUrl);
  const source = new EventSource(url.toString(), { withCredentials: true });
  const streamId = nextStreamId++;
  let closed = false;

  const handleMessage = (event: MessageEvent<string>) => {
    if (!event.data) return;
    try {
      const payload = JSON.parse(event.data) as T;
      onMessage(payload);
    } catch {
      // ignore parse errors
    }
  };

  source.addEventListener('message', handleMessage);

  source.onerror = (event) => {
    onError?.(event);
  };

  const close = () => {
    if (closed) return;
    closed = true;
    activeStreams.delete(streamId);
    source.removeEventListener('message', handleMessage);
    source.close();
  };

  activeStreams.set(streamId, {
    scope,
    close,
  });

  return close;
};

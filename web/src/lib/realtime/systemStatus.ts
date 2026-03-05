import { connectStream } from '$lib/realtime/stream';
import type { SystemStatusSnapshot } from '$lib/types/systemStatus';

export const connectSystemStatusStream = (options: {
  onMessage: (payload: SystemStatusSnapshot) => void;
  onError?: (event: Event) => void;
}) =>
  connectStream<SystemStatusSnapshot>({
    path: '/api/stream/system/status',
    onMessage: options.onMessage,
    onError: options.onError
  });

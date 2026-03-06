import { connectStream } from '$lib/realtime/stream';
import type { RuntimeEnvSnapshot } from '$lib/types/runtimeEnv';

export const connectRuntimeEnvStream = (options: {
  onMessage: (payload: RuntimeEnvSnapshot) => void;
  onError?: (event: Event) => void;
}) =>
  connectStream<RuntimeEnvSnapshot>({
    path: '/api/stream/system/runtime-envs',
    onMessage: options.onMessage,
    onError: options.onError
  });

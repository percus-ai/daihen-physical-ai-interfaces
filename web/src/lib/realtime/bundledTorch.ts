import { connectStream } from '$lib/realtime/stream';
import type { BundledTorchBuildSnapshot } from '$lib/types/bundledTorch';

export const connectBundledTorchStream = (options: {
  onMessage: (payload: BundledTorchBuildSnapshot) => void;
  onError?: (event: Event) => void;
}) =>
  connectStream<BundledTorchBuildSnapshot>({
    path: '/api/stream/system/bundled-torch',
    onMessage: options.onMessage,
    onError: options.onError
  });

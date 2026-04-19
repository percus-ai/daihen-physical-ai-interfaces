export type InferenceUploadProgressRequest = {
  inferenceSessionId: string;
  datasetId: string;
  stopReason: 'manual_stop' | 'batch_declined';
};

type InferenceUploadProgressListener = (request: InferenceUploadProgressRequest) => void;

const listeners = new Set<InferenceUploadProgressListener>();

export const requestInferenceUploadProgress = (request: InferenceUploadProgressRequest) => {
  for (const listener of listeners) {
    listener(request);
  }
};

export const subscribeInferenceUploadProgressRequests = (
  listener: InferenceUploadProgressListener
) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

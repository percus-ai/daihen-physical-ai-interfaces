export type RecordingUploadStatus = {
  dataset_id: string;
  status: string;
  phase: string;
  progress_percent: number;
  message?: string;
  files_done?: number;
  total_files?: number;
  current_file?: string | null;
  error?: string | null;
  updated_at?: string | null;
};

export const createPendingRecordingUploadStatus = (
  datasetId: string,
  message = 'アップロード準備中...'
): RecordingUploadStatus => ({
  dataset_id: datasetId,
  status: 'running',
  phase: 'starting',
  progress_percent: 0,
  message,
  files_done: 0,
  total_files: 0,
  current_file: null,
  error: null,
  updated_at: null
});

export const shouldIgnoreIdleUploadSnapshot = (
  current: RecordingUploadStatus | null,
  incoming: RecordingUploadStatus,
  datasetId: string
) => {
  const targetDatasetId = String(datasetId || '').trim();
  if (!targetDatasetId) return false;

  const currentDatasetId = String(current?.dataset_id || '').trim();
  const incomingDatasetId = String(incoming.dataset_id || '').trim();
  if (currentDatasetId !== targetDatasetId || incomingDatasetId !== targetDatasetId) {
    return false;
  }

  const currentStatus = String(current?.status || '').toLowerCase();
  const currentPhase = String(current?.phase || '').toLowerCase();
  if (currentStatus !== 'running' || currentPhase !== 'starting') {
    return false;
  }

  const incomingStatus = String(incoming.status || '').toLowerCase();
  const incomingPhase = String(incoming.phase || '').toLowerCase();
  return incomingStatus === 'idle' && incomingPhase === 'idle';
};

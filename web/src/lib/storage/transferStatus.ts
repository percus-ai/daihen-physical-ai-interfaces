import type { ModelSyncJobStatus } from '$lib/api/client';
import type { RecordingUploadStatus } from '$lib/recording/uploadStatus';

export type TransferStatusPresentation = {
  kind: 'progress' | 'state';
  label: string;
  tone: 'default' | 'success' | 'error';
};

export const clampTransferPercent = (value: unknown) => {
  const parsed = typeof value === 'number' && Number.isFinite(value) ? value : Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.min(Math.max(parsed, 0), 100);
};

export const formatTransferProgressLabel = (value: unknown) => `${Math.round(clampTransferPercent(value))}%`;

export const presentModelSyncStatus = (
  activeJob: ModelSyncJobStatus | null,
  isLocal: boolean
): TransferStatusPresentation => {
  if (activeJob && (activeJob.state === 'queued' || activeJob.state === 'running')) {
    return {
      kind: 'progress',
      label: formatTransferProgressLabel(activeJob.progress_percent),
      tone: 'default'
    };
  }

  return {
    kind: 'state',
    label: isLocal ? '同期済' : '未同期',
    tone: 'default'
  };
};

export const presentRecordingUploadStatus = (
  status: RecordingUploadStatus | null | undefined,
  isUploaded: boolean
): TransferStatusPresentation => {
  const normalizedStatus = String(status?.status ?? '').toLowerCase();
  if (normalizedStatus === 'running') {
    return {
      kind: 'progress',
      label: formatTransferProgressLabel(status?.progress_percent),
      tone: 'default'
    };
  }
  if (normalizedStatus === 'failed') {
    return {
      kind: 'state',
      label: '失敗',
      tone: 'error'
    };
  }
  return {
    kind: 'state',
    label: isUploaded ? '送信済' : '未送信',
    tone: isUploaded ? 'success' : 'default'
  };
};

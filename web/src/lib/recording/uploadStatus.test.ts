import { describe, expect, it } from 'vitest';

import {
  createPendingRecordingUploadStatus,
  shouldIgnoreIdleUploadSnapshot,
  type RecordingUploadStatus
} from './uploadStatus';

describe('recording upload status helpers', () => {
  it('creates the optimistic pending upload snapshot', () => {
    expect(createPendingRecordingUploadStatus('dataset-1')).toEqual({
      dataset_id: 'dataset-1',
      status: 'running',
      phase: 'starting',
      progress_percent: 0,
      message: 'アップロード準備中...',
      files_done: 0,
      total_files: 0,
      current_file: null,
      error: null,
      updated_at: null
    });
  });

  it('ignores a pre-upload idle snapshot for the active dataset', () => {
    const current = createPendingRecordingUploadStatus('dataset-1');
    const incoming: RecordingUploadStatus = {
      dataset_id: 'dataset-1',
      status: 'idle',
      phase: 'idle',
      progress_percent: 0,
      message: 'No upload activity.'
    };

    expect(shouldIgnoreIdleUploadSnapshot(current, incoming, 'dataset-1')).toBe(true);
  });

  it('accepts non-idle snapshots for the active dataset', () => {
    const current = createPendingRecordingUploadStatus('dataset-1');
    const incoming: RecordingUploadStatus = {
      dataset_id: 'dataset-1',
      status: 'running',
      phase: 'uploading',
      progress_percent: 12.5,
      message: 'Uploading dataset to R2...'
    };

    expect(shouldIgnoreIdleUploadSnapshot(current, incoming, 'dataset-1')).toBe(false);
  });

  it('does not ignore snapshots for another dataset', () => {
    const current = createPendingRecordingUploadStatus('dataset-1');
    const incoming: RecordingUploadStatus = {
      dataset_id: 'dataset-2',
      status: 'idle',
      phase: 'idle',
      progress_percent: 0,
      message: 'No upload activity.'
    };

    expect(shouldIgnoreIdleUploadSnapshot(current, incoming, 'dataset-1')).toBe(false);
  });
});

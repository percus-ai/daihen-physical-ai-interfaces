import { describe, expect, it } from 'vitest';

import { presentModelSyncStatus, presentRecordingUploadStatus } from './transferStatus';

describe('transfer status presentation', () => {
  it('renders active model sync as percentage only', () => {
    expect(
      presentModelSyncStatus(
        {
          job_id: 'job-1',
          model_id: 'model-1',
          state: 'running',
          progress_percent: 42.4,
          message: '',
          detail: {},
          updated_at: ''
        },
        false
      )
    ).toEqual({
      kind: 'progress',
      label: '42%',
      tone: 'default'
    });
  });

  it('renders model sync terminal states from locality', () => {
    expect(presentModelSyncStatus(null, false)).toEqual({
      kind: 'state',
      label: '未同期',
      tone: 'default'
    });
    expect(presentModelSyncStatus(null, true)).toEqual({
      kind: 'state',
      label: '同期済',
      tone: 'default'
    });
  });

  it('renders active recording upload as percentage only', () => {
    expect(
      presentRecordingUploadStatus(
        {
          dataset_id: 'dataset-1',
          status: 'running',
          phase: 'uploading',
          progress_percent: 59.9,
          message: ''
        },
        false
      )
    ).toEqual({
      kind: 'progress',
      label: '60%',
      tone: 'default'
    });
  });

  it('renders recording upload terminal states from upload result', () => {
    expect(presentRecordingUploadStatus(null, false)).toEqual({
      kind: 'state',
      label: '未送信',
      tone: 'default'
    });
    expect(presentRecordingUploadStatus(null, true)).toEqual({
      kind: 'state',
      label: '送信済',
      tone: 'success'
    });
    expect(
      presentRecordingUploadStatus(
        {
          dataset_id: 'dataset-1',
          status: 'failed',
          phase: 'failed',
          progress_percent: 12,
          message: 'failed'
        },
        false
      )
    ).toEqual({
      kind: 'state',
      label: '失敗',
      tone: 'error'
    });
  });
});

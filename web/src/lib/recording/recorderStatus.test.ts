import { describe, expect, it } from 'vitest';

import { getRecorderActiveDatasetId, isRecorderActiveState } from './recorderStatus';

describe('recorder status helpers', () => {
  it('treats only live recorder states as active', () => {
    expect(isRecorderActiveState('recording')).toBe(true);
    expect(isRecorderActiveState('paused')).toBe(true);
    expect(isRecorderActiveState('resetting_paused')).toBe(true);
    expect(isRecorderActiveState('completed')).toBe(false);
    expect(isRecorderActiveState('idle')).toBe(false);
    expect(isRecorderActiveState('failed')).toBe(false);
  });

  it('returns a dataset id only while the recorder is actively controlling a session', () => {
    expect(getRecorderActiveDatasetId({ state: 'recording', dataset_id: ' dataset-1 ' })).toBe('dataset-1');
    expect(getRecorderActiveDatasetId({ state: 'completed', dataset_id: 'dataset-1' })).toBe('');
    expect(getRecorderActiveDatasetId({ state: 'idle', dataset_id: 'dataset-1' })).toBe('');
  });
});

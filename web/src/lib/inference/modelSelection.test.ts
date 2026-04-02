import { describe, expect, it } from 'vitest';

import {
  compareInferenceModelsByRecency,
  resolveInferenceModelId,
  selectInitialInferenceModelId,
  sortInferenceModelsByRecency
} from './modelSelection';

describe('modelSelection', () => {
  it('resolves a trimmed model id', () => {
    expect(resolveInferenceModelId({ model_id: ' model-a ', name: 'ignored' })).toBe('model-a');
    expect(resolveInferenceModelId({ name: ' model-b ' })).toBe('model-b');
  });

  it('sorts models by created_at descending', () => {
    const models = [
      { model_id: 'model-b', created_at: '2026-04-01T10:00:00Z', name: 'B' },
      { model_id: 'model-a', created_at: '2026-04-02T10:00:00Z', name: 'A' },
      { model_id: 'model-c', created_at: '2026-03-30T10:00:00Z', name: 'C' }
    ];

    expect(sortInferenceModelsByRecency(models).map((model) => model.model_id)).toEqual(['model-a', 'model-b', 'model-c']);
    expect(compareInferenceModelsByRecency(models[0], models[1])).toBeGreaterThan(0);
  });

  it('prefers the most recent usable model from history', () => {
    const models = [
      { model_id: 'model-a', created_at: '2026-04-01T10:00:00Z', name: 'A' },
      { model_id: 'model-b', created_at: '2026-04-02T10:00:00Z', name: 'B' }
    ];

    expect(selectInitialInferenceModelId(models, ['missing-model', 'model-a'])).toBe('model-a');
  });

  it('falls back to the newest available model when history is empty', () => {
    const models = [
      { model_id: 'model-a', created_at: '2026-04-01T10:00:00Z', name: 'A' },
      { model_id: 'model-b', created_at: '2026-04-02T10:00:00Z', name: 'B' }
    ];

    expect(selectInitialInferenceModelId(models, [])).toBe('model-b');
  });
});

import { describe, expect, it } from 'vitest';

import { START_PHASE_LABELS } from './startupPhases';

describe('START_PHASE_LABELS', () => {
  it('includes prepare_env label for inference startup', () => {
    expect(START_PHASE_LABELS.prepare_env).toBe('環境準備');
  });
});

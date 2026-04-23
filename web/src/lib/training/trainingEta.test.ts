import { describe, expect, it } from 'vitest';

import { estimateTrainingEta, formatSecondsPerStep } from '$lib/training/trainingEta';

describe('estimateTrainingEta', () => {
  it('estimates remaining time from timed loss metric steps', () => {
    const nowMs = new Date('2026-04-23T01:02:00Z').getTime();
    const eta = estimateTrainingEta(
      [
        { step: 100, ts: '2026-04-23T01:00:00Z' },
        { step: 200, ts: '2026-04-23T01:02:00Z' }
      ],
      500,
      nowMs
    );

    expect(eta?.remainingSteps).toBe(300);
    expect(eta?.secondsPerStep).toBe(1.2);
    expect(eta?.estimatedRemainingMs).toBe(360_000);
    expect(eta?.estimatedEndMs).toBe(new Date('2026-04-23T01:08:00Z').getTime());
  });

  it('returns null when there are not enough timed points', () => {
    const eta = estimateTrainingEta([{ step: 100 }], 500, Date.now());

    expect(eta).toBeNull();
  });

  it('returns zero remaining time after reaching the configured total steps', () => {
    const nowMs = new Date('2026-04-23T01:02:00Z').getTime();
    const eta = estimateTrainingEta([{ step: 500, ts: '2026-04-23T01:02:00Z' }], 500, nowMs);

    expect(eta?.remainingSteps).toBe(0);
    expect(eta?.estimatedRemainingMs).toBe(0);
    expect(eta?.estimatedEndMs).toBe(nowMs);
  });
});

describe('formatSecondsPerStep', () => {
  it('formats seconds per step for compact display', () => {
    expect(formatSecondsPerStep(0.123)).toBe('0.12秒/step');
    expect(formatSecondsPerStep(1.23)).toBe('1.2秒/step');
    expect(formatSecondsPerStep(12.3)).toBe('12秒/step');
  });
});

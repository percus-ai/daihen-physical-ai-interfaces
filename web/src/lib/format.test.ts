import { describe, expect, it } from 'vitest';

import { formatDate, formatElapsedDuration, formatUuidPreview } from '$lib/format';

describe('formatDate', () => {
  it('formats timestamps in Japan time', () => {
    expect(formatDate('2026-04-17T12:34:56Z')).toBe('2026/04/17 21:34:56');
  });

  it('keeps invalid date strings visible', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date');
  });
});

describe('formatElapsedDuration', () => {
  it('formats a completed runtime from start and end timestamps', () => {
    expect(formatElapsedDuration('2026-04-17T00:00:00Z', '2026-04-17T01:02:03Z')).toBe(
      '1時間 2分'
    );
  });

  it('uses the fallback end time for running jobs', () => {
    expect(
      formatElapsedDuration(
        '2026-04-17T00:00:00Z',
        undefined,
        new Date('2026-04-17T00:05:06Z').getTime()
      )
    ).toBe('5分 6秒');
  });

  it('formats durations over a day as total hours', () => {
    expect(formatElapsedDuration('2026-04-17T00:00:00Z', '2026-04-18T00:45:00Z')).toBe(
      '24時間 45分'
    );
  });

  it('does not display negative durations', () => {
    expect(formatElapsedDuration('2026-04-17T01:00:00Z', '2026-04-17T00:00:00Z')).toBe('-');
  });
});

describe('formatUuidPreview', () => {
  it('shows the first two blocks of UUID values', () => {
    expect(formatUuidPreview('12345678-90ab-cdef-1234-567890abcdef')).toBe('12345678-90ab');
  });

  it('keeps non-UUID identifiers unchanged', () => {
    expect(formatUuidPreview('job-20260417')).toBe('job-20260417');
  });
});

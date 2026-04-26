import { describe, expect, it } from 'vitest';
import { buildTableSkeletonRows } from './tableSkeleton';

describe('buildTableSkeletonRows', () => {
  it('returns one placeholder per missing page row', () => {
    expect(buildTableSkeletonRows(5, 2)).toEqual([0, 1, 2]);
  });

  it('does not add placeholders when the page is full', () => {
    expect(buildTableSkeletonRows(5, 5)).toEqual([]);
    expect(buildTableSkeletonRows(5, 8)).toEqual([]);
  });

  it('normalizes invalid counts', () => {
    expect(buildTableSkeletonRows(0, -2)).toEqual([0]);
  });

  it('can be disabled for true empty states', () => {
    expect(buildTableSkeletonRows(10, 0, false)).toEqual([]);
  });
});

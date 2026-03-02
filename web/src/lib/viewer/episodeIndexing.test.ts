import { describe, expect, it } from 'vitest';

import {
  isSelectedEpisodeIndex,
  kthUnselectedEpisodeIndex,
  normalizeSelectedEpisodeIndices,
  unselectedRowForEpisodeIndex,
  unselectedTotalRows
} from '$lib/viewer/episodeIndexing';

describe('episodeIndexing', () => {
  it('normalizeSelectedEpisodeIndices clamps and sorts unique', () => {
    expect(normalizeSelectedEpisodeIndices(5, [4, 4, -1, 99, 0, 2])).toEqual([0, 2, 4]);
    expect(normalizeSelectedEpisodeIndices(0, [0, 1])).toEqual([]);
  });

  it('isSelectedEpisodeIndex detects membership', () => {
    const selected = [0, 2, 4];
    expect(isSelectedEpisodeIndex(selected, 0)).toBe(true);
    expect(isSelectedEpisodeIndex(selected, 1)).toBe(false);
    expect(isSelectedEpisodeIndex(selected, 4)).toBe(true);
  });

  it('unselectedTotalRows returns total - selectedCount', () => {
    expect(unselectedTotalRows(5, [])).toBe(5);
    expect(unselectedTotalRows(5, [0, 2, 4])).toBe(2);
    expect(unselectedTotalRows(0, [])).toBe(0);
  });

  it('kthUnselectedEpisodeIndex maps row -> episode index', () => {
    const total = 5;
    expect(kthUnselectedEpisodeIndex(total, [], 0)).toBe(0);
    expect(kthUnselectedEpisodeIndex(total, [], 4)).toBe(4);
    expect(kthUnselectedEpisodeIndex(total, [], 5)).toBe(null);

    const selected = [0, 2];
    // unselected = [1, 3, 4]
    expect(kthUnselectedEpisodeIndex(total, selected, 0)).toBe(1);
    expect(kthUnselectedEpisodeIndex(total, selected, 1)).toBe(3);
    expect(kthUnselectedEpisodeIndex(total, selected, 2)).toBe(4);
    expect(kthUnselectedEpisodeIndex(total, selected, 3)).toBe(null);
  });

  it('unselectedRowForEpisodeIndex maps episode index -> row (or null if selected)', () => {
    const total = 6;
    const selected = [0, 3, 5];
    // unselected = [1, 2, 4]
    expect(unselectedRowForEpisodeIndex(total, selected, 0)).toBe(null);
    expect(unselectedRowForEpisodeIndex(total, selected, 1)).toBe(0);
    expect(unselectedRowForEpisodeIndex(total, selected, 2)).toBe(1);
    expect(unselectedRowForEpisodeIndex(total, selected, 4)).toBe(2);
    expect(unselectedRowForEpisodeIndex(total, selected, 5)).toBe(null);
    expect(unselectedRowForEpisodeIndex(total, selected, -1)).toBe(null);
    expect(unselectedRowForEpisodeIndex(total, selected, 999)).toBe(null);
  });

  it('row <-> episode is consistent for small cases', () => {
    const total = 20;
    const selected = normalizeSelectedEpisodeIndices(total, [0, 1, 2, 4, 7, 9, 19]);
    const rows = unselectedTotalRows(total, selected);

    for (let row = 0; row < rows; row += 1) {
      const episodeIndex = kthUnselectedEpisodeIndex(total, selected, row);
      expect(episodeIndex).not.toBe(null);
      if (episodeIndex === null) continue;
      expect(isSelectedEpisodeIndex(selected, episodeIndex)).toBe(false);
      expect(unselectedRowForEpisodeIndex(total, selected, episodeIndex)).toBe(row);
    }
  });
});


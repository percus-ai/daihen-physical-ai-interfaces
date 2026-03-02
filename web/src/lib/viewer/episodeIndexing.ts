export const upperBound = (sorted: readonly number[], value: number) => {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (sorted[mid] <= value) lo = mid + 1;
    else hi = mid;
  }
  return lo;
};

export const lowerBound = (sorted: readonly number[], value: number) => {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (sorted[mid] < value) lo = mid + 1;
    else hi = mid;
  }
  return lo;
};

export const isSelectedEpisodeIndex = (sortedSelected: readonly number[], episodeIndex: number) => {
  const pos = lowerBound(sortedSelected, episodeIndex);
  return pos < sortedSelected.length && sortedSelected[pos] === episodeIndex;
};

export const normalizeSelectedEpisodeIndices = (totalEpisodes: number, indices: Iterable<number>) => {
  const total = Math.max(0, Math.floor(Number(totalEpisodes) || 0));
  if (!Number.isFinite(total) || total <= 0) return [] as number[];

  const unique = new Set<number>();
  for (const raw of indices) {
    const index = Math.floor(Number(raw) || 0);
    if (!Number.isFinite(index) || index < 0 || index >= total) continue;
    unique.add(index);
  }
  return [...unique].sort((a, b) => a - b);
};

export const unselectedTotalRows = (totalEpisodes: number, sortedSelected: readonly number[]) => {
  const total = Math.max(0, Math.floor(Number(totalEpisodes) || 0));
  if (!Number.isFinite(total) || total <= 0) return 0;
  return Math.max(0, total - sortedSelected.length);
};

export const kthUnselectedEpisodeIndex = (
  totalEpisodes: number,
  sortedSelected: readonly number[],
  rowIndex: number
) => {
  // rowIndex is 0-indexed among unselected episodes.
  const total = Math.max(0, Math.floor(Number(totalEpisodes) || 0));
  if (!Number.isFinite(total) || total <= 0) return null as number | null;

  const unselectedTotal = unselectedTotalRows(total, sortedSelected);
  if (rowIndex < 0 || rowIndex >= unselectedTotal) return null as number | null;

  const target = rowIndex + 1; // 1-indexed count
  let lo = 0;
  let hi = total - 1;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    const selectedLE = upperBound(sortedSelected, mid);
    const unselectedUpTo = (mid + 1) - selectedLE;
    if (unselectedUpTo >= target) hi = mid;
    else lo = mid + 1;
  }
  return lo;
};

export const unselectedRowForEpisodeIndex = (
  totalEpisodes: number,
  sortedSelected: readonly number[],
  episodeIndex: number
) => {
  const total = Math.max(0, Math.floor(Number(totalEpisodes) || 0));
  if (!Number.isFinite(total) || total <= 0) return null as number | null;

  const index = Math.floor(Number(episodeIndex) || 0);
  if (!Number.isFinite(index) || index < 0 || index >= total) return null as number | null;

  if (isSelectedEpisodeIndex(sortedSelected, index)) return null as number | null;
  const selectedBefore = lowerBound(sortedSelected, index);
  return index - selectedBefore;
};


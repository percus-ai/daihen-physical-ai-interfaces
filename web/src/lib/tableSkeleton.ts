export const buildTableSkeletonRows = (
  pageSize: number,
  visibleRowCount: number,
  enabled = true
): number[] => {
  if (!enabled) return [];

  const normalizedPageSize = Math.max(1, Math.floor(Number(pageSize) || 1));
  const normalizedVisibleRowCount = Math.max(0, Math.floor(Number(visibleRowCount) || 0));
  const rowCount = Math.max(0, normalizedPageSize - normalizedVisibleRowCount);

  return Array.from({ length: rowCount }, (_, index) => index);
};

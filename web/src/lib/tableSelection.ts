export const updateSelectedId = (selectedIds: string[], id: string, selected: boolean): string[] => {
  const normalizedId = id.trim();
  if (!normalizedId) return selectedIds;

  if (selected) {
    if (selectedIds.includes(normalizedId)) return selectedIds;
    return [...selectedIds, normalizedId];
  }

  return selectedIds.filter((selectedId) => selectedId !== normalizedId);
};

export const updateSelectedPageIds = (selectedIds: string[], pageIds: string[], selected: boolean): string[] => {
  const normalizedPageIds = pageIds.map((id) => id.trim()).filter(Boolean);
  if (!normalizedPageIds.length) return selectedIds;

  if (!selected) {
    const pageIdSet = new Set(normalizedPageIds);
    return selectedIds.filter((selectedId) => !pageIdSet.has(selectedId));
  }

  return Array.from(new Set([...selectedIds, ...normalizedPageIds]));
};

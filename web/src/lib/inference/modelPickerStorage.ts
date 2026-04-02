const STORAGE_PREFIX = 'inference-model-picker:v1';
const FAVORITES_KEY = `${STORAGE_PREFIX}:favorites`;
const RECENT_KEY = `${STORAGE_PREFIX}:recent`;

export const RECENT_MODEL_LIMIT = 12;

const normalizeModelIdList = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  const ordered: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    const modelId = String(item ?? '').trim();
    if (!modelId || seen.has(modelId)) continue;
    seen.add(modelId);
    ordered.push(modelId);
  }
  return ordered;
};

const loadModelIdList = (storageKey: string): string[] => {
  if (typeof localStorage === 'undefined') return [];
  const raw = localStorage.getItem(storageKey);
  if (!raw) return [];
  try {
    return normalizeModelIdList(JSON.parse(raw));
  } catch {
    localStorage.removeItem(storageKey);
    return [];
  }
};

const saveModelIdList = (storageKey: string, modelIds: string[]): void => {
  if (typeof localStorage === 'undefined') return;
  localStorage.setItem(storageKey, JSON.stringify(normalizeModelIdList(modelIds)));
};

export const loadFavoriteModelIds = (): string[] => loadModelIdList(FAVORITES_KEY);

export const saveFavoriteModelIds = (modelIds: string[]): void => {
  saveModelIdList(FAVORITES_KEY, modelIds);
};

export const loadRecentModelIds = (): string[] => loadModelIdList(RECENT_KEY);

export const saveRecentModelIds = (modelIds: string[]): void => {
  saveModelIdList(RECENT_KEY, modelIds);
};

export const toggleFavoriteModelId = (modelIds: string[], targetModelId: string): string[] => {
  const normalizedTarget = String(targetModelId ?? '').trim();
  if (!normalizedTarget) return normalizeModelIdList(modelIds);
  const normalizedModelIds = normalizeModelIdList(modelIds);
  if (normalizedModelIds.includes(normalizedTarget)) {
    return normalizedModelIds.filter((modelId) => modelId !== normalizedTarget);
  }
  return [normalizedTarget, ...normalizedModelIds];
};

export const recordRecentModelId = (
  modelIds: string[],
  targetModelId: string,
  limit = RECENT_MODEL_LIMIT
): string[] => {
  const normalizedTarget = String(targetModelId ?? '').trim();
  if (!normalizedTarget) return normalizeModelIdList(modelIds);
  return [normalizedTarget, ...normalizeModelIdList(modelIds).filter((modelId) => modelId !== normalizedTarget)].slice(
    0,
    Math.max(1, Math.floor(limit))
  );
};

export const recordRecentModelUsage = (targetModelId: string, limit = RECENT_MODEL_LIMIT): string[] => {
  const nextModelIds = recordRecentModelId(loadRecentModelIds(), targetModelId, limit);
  saveRecentModelIds(nextModelIds);
  return nextModelIds;
};

export const retainKnownModelIds = (modelIds: string[], availableModelIds: Iterable<string>): string[] => {
  const availableSet = new Set<string>();
  for (const item of availableModelIds) {
    const modelId = String(item ?? '').trim();
    if (modelId) {
      availableSet.add(modelId);
    }
  }
  if (availableSet.size === 0) {
    return normalizeModelIdList(modelIds);
  }
  return normalizeModelIdList(modelIds).filter((modelId) => availableSet.has(modelId));
};

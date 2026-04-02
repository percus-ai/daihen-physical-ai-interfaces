import type { InferenceModel } from '$lib/types/inference';

const normalizeModelId = (value: unknown): string => String(value ?? '').trim();
const normalizeCreatedAt = (value?: string | null): string => String(value ?? '').trim();

export const resolveInferenceModelId = (model: InferenceModel): string => normalizeModelId(model.model_id ?? model.name);

export const compareInferenceModelsByRecency = (left: InferenceModel, right: InferenceModel): number => {
  const leftCreatedAt = normalizeCreatedAt(left.created_at);
  const rightCreatedAt = normalizeCreatedAt(right.created_at);
  if (leftCreatedAt !== rightCreatedAt) {
    return rightCreatedAt.localeCompare(leftCreatedAt, 'en');
  }

  const leftName = normalizeModelId(left.name) || resolveInferenceModelId(left);
  const rightName = normalizeModelId(right.name) || resolveInferenceModelId(right);
  if (leftName !== rightName) {
    return leftName.localeCompare(rightName, 'ja');
  }

  return resolveInferenceModelId(left).localeCompare(resolveInferenceModelId(right), 'ja');
};

export const sortInferenceModelsByRecency = <T extends InferenceModel>(models: T[]): T[] =>
  [...models].filter((model) => resolveInferenceModelId(model)).sort(compareInferenceModelsByRecency);

export const selectInitialInferenceModelId = (models: InferenceModel[], recentModelIds: string[]): string => {
  const sortedModels = sortInferenceModelsByRecency(models);
  if (sortedModels.length === 0) {
    return '';
  }

  const modelIds = new Set(sortedModels.map((model) => resolveInferenceModelId(model)));
  for (const recentModelId of recentModelIds) {
    const normalizedModelId = normalizeModelId(recentModelId);
    if (normalizedModelId && modelIds.has(normalizedModelId)) {
      return normalizedModelId;
    }
  }

  return resolveInferenceModelId(sortedModels[0]);
};

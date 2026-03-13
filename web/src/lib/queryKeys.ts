import type { StorageDatasetListQuery, StorageModelListQuery } from '$lib/api/client';

// Centralized TanStack Query keys to prevent cache fragmentation across pages/modals.
// Keep these stable and repo-wide to avoid duplicate fetches and state skew.

function normalizeQuery<T extends Record<string, unknown>>(query: T = {} as T): T {
  const entries = Object.entries(query).filter(([, value]) => value !== undefined);
  return Object.fromEntries(entries) as T;
}

export const qk = {
  storage: {
    usage: () => ['storage', 'usage'] as const,
    usagePage: () => ['storage', 'usage', 'page'] as const,

    datasetsPrefix: () => ['storage', 'datasets'] as const,
    datasets: (query: StorageDatasetListQuery = {}) =>
      ['storage', 'datasets', normalizeQuery(query)] as const,
    dataset: (datasetId: string) => ['storage', 'dataset', datasetId] as const,

    modelsPrefix: () => ['storage', 'models'] as const,
    models: (query: StorageModelListQuery = {}) =>
      ['storage', 'models', normalizeQuery(query)] as const,
    model: (modelId: string) => ['storage', 'model', modelId] as const,

    datasetViewer: (datasetId: string) => ['storage', 'datasetViewer', datasetId] as const,
    datasetViewerEpisodes: (datasetId: string) => ['storage', 'datasetViewer', datasetId, 'episodes'] as const,
    datasetViewerSignalFields: (datasetId: string) => ['storage', 'datasetViewer', datasetId, 'signals'] as const,
    datasetViewerEpisodeVideoWindow: (datasetId: string, episodeIndex: number) =>
      ['storage', 'datasetViewer', datasetId, 'episodes', episodeIndex, 'videoWindow'] as const,
    datasetSyncJob: (jobId: string) => ['storage', 'datasetSyncJob', jobId] as const
  }
} as const;

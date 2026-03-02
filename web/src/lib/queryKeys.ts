// Centralized TanStack Query keys to prevent cache fragmentation across pages/modals.
// Keep these stable and repo-wide to avoid duplicate fetches and state skew.

export const qk = {
  storage: {
    usage: () => ['storage', 'usage'] as const,
    usagePage: () => ['storage', 'usage', 'page'] as const,

    datasets: () => ['storage', 'datasets'] as const,
    datasetsAll: () => ['storage', 'datasets', 'all'] as const,
    datasetsManage: () => ['storage', 'datasets', 'manage'] as const,
    datasetsLookup: () => ['storage', 'datasets', 'lookup'] as const,
    datasetsByProfile: (profileName: string) => ['storage', 'datasets', 'profile', profileName] as const,
    dataset: (datasetId: string) => ['storage', 'dataset', datasetId] as const,

    models: () => ['storage', 'models'] as const,
    modelsManage: () => ['storage', 'models', 'manage'] as const,
    model: (modelId: string) => ['storage', 'model', modelId] as const,

    archiveManage: () => ['storage', 'archive', 'manage'] as const,
    archiveItem: (itemType: string, itemId: string) => ['storage', 'archive', itemType, itemId] as const,

    datasetViewer: (datasetId: string) => ['storage', 'datasetViewer', datasetId] as const,
    datasetViewerEpisodes: (datasetId: string) => ['storage', 'datasetViewer', datasetId, 'episodes'] as const,
    datasetViewerSignalFields: (datasetId: string) => ['storage', 'datasetViewer', datasetId, 'signals'] as const,
    datasetViewerEpisodeVideoWindow: (datasetId: string, episodeIndex: number) =>
      ['storage', 'datasetViewer', datasetId, 'episodes', episodeIndex, 'videoWindow'] as const,
    datasetSyncJob: (jobId: string) => ['storage', 'datasetSyncJob', jobId] as const
  }
} as const;

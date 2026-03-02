// Centralized TanStack Query keys to prevent cache fragmentation across pages/modals.
// Keep these stable and repo-wide to avoid duplicate fetches and state skew.

export const qk = {
  storage: {
    datasetViewer: (datasetId: string) => ['storage', 'datasetViewer', datasetId] as const,
    datasetViewerEpisodes: (datasetId: string) => ['storage', 'datasetViewer', datasetId, 'episodes'] as const,
    datasetViewerSignalFields: (datasetId: string) => ['storage', 'datasetViewer', datasetId, 'signals'] as const,
    datasetSyncJob: (jobId: string) => ['storage', 'datasetSyncJob', jobId] as const
  }
} as const;


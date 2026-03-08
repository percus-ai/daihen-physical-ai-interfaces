import { derived, get, writable, type Readable } from 'svelte/store';
import { createQuery, type QueryClient } from '@tanstack/svelte-query';

import { api, type DatasetSyncJobStatus, type DatasetViewerResponse, type DatasetViewerSignalFieldsResponse } from '$lib/api/client';
import { getTabRealtimeClient, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';
import { qk } from '$lib/queryKeys';

type NotifyFn = (message: string, level?: 'info' | 'success' | 'error') => void;

export type DatasetAvailabilityController = {
  datasetQuery: ReturnType<typeof createQuery<DatasetViewerResponse>>;
  signalFieldsQuery: ReturnType<typeof createQuery<DatasetViewerSignalFieldsResponse>>;
  syncJobQuery: ReturnType<typeof createQuery<DatasetSyncJobStatus>>;

  isLocal: Readable<boolean>;
  totalEpisodes: Readable<number>;
  cameraKeys: Readable<string[]>;
  signalKeys: Readable<string[]>;

  syncJobId: ReturnType<typeof writable<string>>;
  syncStarting: ReturnType<typeof writable<boolean>>;

  startSync: () => Promise<void>;
  refetch: () => Promise<void>;
  destroy: () => void;
};

export const createDatasetAvailabilityController = (opts: {
  datasetId: Readable<string>;
  enabled: Readable<boolean>;
  queryClient: QueryClient;
  autoStartSync?: boolean;
  notify?: NotifyFn;
  onCompleted?: (datasetId: string) => void;
}): DatasetAvailabilityController => {
  const { datasetId, enabled, queryClient, notify } = opts;
  const autoStartSync = opts.autoStartSync ?? true;

  const syncJobId = writable('');
  const syncStarting = writable(false);
  const syncAutoTriggered = writable(false);
  const syncHandledTerminalState = writable('');

  const datasetQuery = createQuery<DatasetViewerResponse>(
    derived([datasetId, enabled], ([$datasetId, $enabled]) => ({
      queryKey: qk.storage.datasetViewer($datasetId),
      queryFn: () => api.storage.datasetViewer($datasetId),
      enabled: Boolean($enabled) && Boolean($datasetId)
    }))
  );

  const isLocal = derived(datasetQuery, ($q) => Boolean($q.data?.is_local));
  const totalEpisodes = derived(datasetQuery, ($q) => Number($q.data?.total_episodes ?? 0));
  const cameraKeys = derived(datasetQuery, ($q) => ($q.data?.cameras ?? []).map((camera) => camera.key));

  const signalFieldsQuery = createQuery<DatasetViewerSignalFieldsResponse>(
    derived([datasetId, enabled, isLocal], ([$datasetId, $enabled, $isLocal]) => ({
      queryKey: qk.storage.datasetViewerSignalFields($datasetId),
      queryFn: () => api.storage.datasetViewerSignalFields($datasetId),
      enabled: Boolean($enabled) && Boolean($datasetId) && Boolean($isLocal)
    }))
  );

  const signalKeys = derived([signalFieldsQuery, isLocal], ([$q, $isLocal]) => {
    const fields = $q.data?.fields ?? [];
    const keys = fields.map((field) => field.key);
    const loaded = !$q.isLoading && !$q.isFetching;
    const useFallback = Boolean($isLocal) && loaded && keys.length === 0;
    return useFallback ? ['observation.state', 'action'] : keys;
  });

  const syncJobQuery = createQuery<DatasetSyncJobStatus>(
    derived([syncJobId, enabled], ([$jobId, $enabled]) => ({
      queryKey: qk.storage.datasetSyncJob($jobId),
      queryFn: () => api.storage.datasetSyncJob($jobId),
      enabled: Boolean($enabled) && Boolean($jobId)
    }))
  );

  const refetch = async () => {
    const currentDatasetId = get(datasetId);
    if (!currentDatasetId) return;
    await queryClient.invalidateQueries({ queryKey: qk.storage.datasetViewer(currentDatasetId) });
    await queryClient.invalidateQueries({ queryKey: qk.storage.datasetViewerSignalFields(currentDatasetId) });
    await queryClient.invalidateQueries({ queryKey: qk.storage.datasetViewerEpisodes(currentDatasetId) });
  };

  const startSync = async () => {
    const currentDatasetId = get(datasetId);
    if (!currentDatasetId) return;
    if (get(syncStarting)) return;

    syncStarting.set(true);
    try {
      const accepted = await api.storage.syncDataset(currentDatasetId);
      syncJobId.set(accepted.job_id);
      notify?.('データセット同期を開始しました。', 'success');
    } catch (err) {
      const status =
        typeof err === 'object' && err !== null && 'status' in err ? Number((err as { status?: unknown }).status) : 0;
      if (status === 409) {
        // Attach to the existing active job if present.
        try {
          const active = await api.storage.datasetSyncJobs(false);
          const existing = (active.jobs ?? []).find(
            (job) => job.dataset_id === currentDatasetId && (job.state === 'queued' || job.state === 'running')
          );
          if (existing) {
            syncJobId.set(existing.job_id);
            notify?.('同期ジョブが既に実行中です。', 'info');
            return;
          }
        } catch {
          // ignore, fall through to generic error
        }
        notify?.('同期ジョブが既に実行中です。', 'info');
      } else {
        notify?.('データセット同期の開始に失敗しました。', 'error');
      }
    } finally {
      syncStarting.set(false);
    }
  };

  let lastDatasetId = '';
  const unsubDatasetId = datasetId.subscribe((next) => {
    if (next === lastDatasetId) return;
    lastDatasetId = next;
    syncJobId.set('');
    syncAutoTriggered.set(false);
    syncHandledTerminalState.set('');
  });

  const unsubAutoStart = derived([enabled, datasetQuery, isLocal, syncJobId, syncAutoTriggered], (values) => values).subscribe(
    ([$enabled, $datasetQuery, $isLocal, $jobId, $autoTriggered]) => {
      if (!autoStartSync) return;
      const currentDatasetId = get(datasetId);
      if (!$enabled) return;
      if (!currentDatasetId) return;
      if (!$datasetQuery.data) return;
      if ($isLocal) return;
      if ($jobId) return;
      if ($autoTriggered) return;
      syncAutoTriggered.set(true);
      void startSync();
    }
  );

  const unsubTerminal = derived([syncJobQuery, datasetId], (values) => values).subscribe(([$syncJobQuery, $datasetId]) => {
    const state = $syncJobQuery.data?.state ?? '';
    if (!state) return;
    if ($datasetId !== get(datasetId)) return;
    const handled = get(syncHandledTerminalState);
    if (state === handled) return;
    if (state === 'completed') {
      syncHandledTerminalState.set(state);
      // After sync completes, refetch viewer metadata. This flips is_local and enables signal fields fetch.
      void queryClient.invalidateQueries({ queryKey: qk.storage.datasetViewer($datasetId) });
      void queryClient.invalidateQueries({ queryKey: qk.storage.datasetViewerSignalFields($datasetId) });
      void queryClient.invalidateQueries({ queryKey: qk.storage.datasetViewerEpisodes($datasetId) });
      opts.onCompleted?.($datasetId);
    }
  });

  let contributor: TabRealtimeContributorHandle | null = null;
  const unsubStream = derived([syncJobId, enabled], (values) => values).subscribe(([$jobId, $enabled]) => {
    contributor?.dispose();
    contributor = null;
    if (!$enabled || !$jobId) return;
    const client = getTabRealtimeClient();
    if (!client) return;
    const currentJobId = $jobId;
    contributor = client.registerContributor({
      subscriptions: [
        {
          subscription_id: `viewer.dataset-sync.${currentJobId}`,
          kind: 'storage.dataset-sync',
          params: { job_id: currentJobId }
        }
      ],
      onEvent: (event: TabRealtimeEvent) => {
        if (event.op !== 'snapshot' || event.source?.kind !== 'storage.dataset-sync') return;
        queryClient.setQueryData(qk.storage.datasetSyncJob(currentJobId), event.payload as DatasetSyncJobStatus);
      }
    });
  });

  const destroy = () => {
    contributor?.dispose();
    contributor = null;
    unsubDatasetId();
    unsubAutoStart();
    unsubTerminal();
    unsubStream();
  };

  return {
    datasetQuery,
    signalFieldsQuery,
    syncJobQuery,
    isLocal,
    totalEpisodes,
    cameraKeys,
    signalKeys,
    syncJobId,
    syncStarting,
    startSync,
    refetch,
    destroy
  };
};

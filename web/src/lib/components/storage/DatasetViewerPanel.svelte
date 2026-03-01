<script lang="ts">
  import { toStore } from 'svelte/store';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { connectStream } from '$lib/realtime/stream';
  import {
    api,
    type DatasetSyncJobStatus,
    type DatasetViewerSignalField,
    type DatasetViewerSignalFieldsResponse,
    type DatasetViewerSignalSeriesResponse
  } from '$lib/api/client';
  import LayoutNode from '$lib/components/recording/LayoutNode.svelte';
  import JointStateView from '$lib/components/recording/views/JointStateView.svelte';
  import { ensureValidSelection, updateTabsActive, type BlueprintNode } from '$lib/recording/blueprint';

  let {
    datasetId = '',
    episodeIndex = 0,
    onEpisodeChange,
    layoutBlueprint = null
  }: {
    datasetId?: string;
    episodeIndex?: number;
    onEpisodeChange?: (episodeIndex: number) => void;
    layoutBlueprint?: BlueprintNode | null;
  } = $props();

  const queryClient = useQueryClient();
  let selectedEpisode = $state(0);
  let selectedSignalField = $state('');
  let datasetSyncJobId = $state('');
  let datasetSyncAutoTriggered = $state(false);
  let datasetSyncStarting = $state(false);
  let datasetSyncHandledTerminalState = $state('');
  let lastDatasetIdForSync = $state('');
  let resolvedLayoutBlueprint: BlueprintNode | null = $state(null);
  let layoutSelectedId = $state('');

  const viewerQuery = createQuery(
    toStore(() => ({
      queryKey: ['storage', 'dataset-viewer-panel', datasetId, 'viewer'],
      queryFn: () => api.storage.datasetViewer(datasetId),
      enabled: Boolean(datasetId)
    }))
  );

  const episodesQuery = createQuery(
    toStore(() => ({
      queryKey: ['storage', 'dataset-viewer-panel', datasetId, 'episodes'],
      queryFn: () => api.storage.datasetViewerEpisodes(datasetId),
      enabled: Boolean(datasetId) && Boolean($viewerQuery.data?.is_local)
    }))
  );

  const playbackEpisodes = $derived($episodesQuery.data?.total ?? $viewerQuery.data?.total_episodes ?? 0);

  const signalFieldsQuery = createQuery<DatasetViewerSignalFieldsResponse>(
    toStore(() => ({
      queryKey: ['storage', 'dataset-viewer-panel', datasetId, 'signals'],
      queryFn: () => api.storage.datasetViewerSignalFields(datasetId),
      enabled: Boolean(datasetId) && Boolean($viewerQuery.data?.is_local)
    }))
  );

  const signalFields = $derived($signalFieldsQuery.data?.fields ?? []);

  const selectedSignalMeta = $derived(
    signalFields.find((field) => field.key === selectedSignalField) as DatasetViewerSignalField | undefined
  );

  const signalSeriesQuery = createQuery<DatasetViewerSignalSeriesResponse>(
    toStore(() => ({
      queryKey: ['storage', 'dataset-viewer-panel', datasetId, 'signals', selectedEpisode, selectedSignalField],
      queryFn: () => api.storage.datasetViewerSignalSeries(datasetId, selectedEpisode, selectedSignalField),
      enabled:
        Boolean(datasetId) &&
        Boolean($viewerQuery.data?.is_local) &&
        playbackEpisodes > 0 &&
        Boolean(selectedSignalField)
    }))
  );

  const datasetJointSeries = $derived(
    $signalSeriesQuery.data
      ? {
          names: $signalSeriesQuery.data.names,
          positions: $signalSeriesQuery.data.positions,
          timestamps: $signalSeriesQuery.data.timestamps
        }
      : null
  );
  const datasetSignalLabel = $derived(
    selectedSignalMeta ? `${selectedSignalMeta.key} (${selectedSignalMeta.dtype})` : selectedSignalField
  );

  const datasetSyncJobQuery = createQuery<DatasetSyncJobStatus>(
    toStore(() => ({
      queryKey: ['storage', 'dataset-viewer-panel', datasetId, 'dataset-sync', datasetSyncJobId],
      queryFn: () => api.storage.datasetSyncJob(datasetSyncJobId),
      enabled: Boolean(datasetSyncJobId)
    }))
  );

  const refetchViewer = async () => {
    if (!datasetId) return;
    await queryClient.invalidateQueries({
      queryKey: ['storage', 'dataset-viewer-panel', datasetId]
    });
  };

  const startDatasetSyncJob = async () => {
    if (!datasetId || datasetSyncStarting) return;
    datasetSyncStarting = true;
    try {
      const accepted = await api.storage.syncDataset(datasetId);
      datasetSyncJobId = accepted.job_id;
    } catch (err) {
      const status =
        typeof err === 'object' && err !== null && 'status' in err
          ? Number((err as { status?: unknown }).status)
          : 0;
      if (status === 409) {
        try {
          const active = await api.storage.datasetSyncJobs(false);
          const existing = (active.jobs ?? []).find(
            (job) => job.dataset_id === datasetId && (job.state === 'queued' || job.state === 'running')
          );
          if (existing) {
            datasetSyncJobId = existing.job_id;
          }
        } catch {
          // ignore and keep current UI state
        }
      }
    } finally {
      datasetSyncStarting = false;
    }
  };

  const cancelDatasetSyncJob = async () => {
    if (!datasetSyncJobId) return;
    try {
      await api.storage.cancelDatasetSyncJob(datasetSyncJobId);
      await queryClient.invalidateQueries({
        queryKey: ['storage', 'dataset-viewer-panel', datasetId, 'dataset-sync', datasetSyncJobId]
      });
    } catch {
      // no-op
    }
  };

  $effect(() => {
    if (datasetId !== lastDatasetIdForSync) {
      lastDatasetIdForSync = datasetId;
      datasetSyncJobId = '';
      datasetSyncAutoTriggered = false;
      datasetSyncHandledTerminalState = '';
      selectedEpisode = Math.max(0, Math.floor(episodeIndex || 0));
      selectedSignalField = '';
    }
  });

  $effect(() => {
    if (!signalFields.length) {
      selectedSignalField = '';
      return;
    }
    if (!selectedSignalField || !signalFields.some((field) => field.key === selectedSignalField)) {
      selectedSignalField = signalFields[0].key;
    }
  });

  $effect(() => {
    if (playbackEpisodes <= 0) {
      selectedEpisode = 0;
      return;
    }
    if (selectedEpisode < 0) selectedEpisode = 0;
    if (selectedEpisode >= playbackEpisodes) selectedEpisode = playbackEpisodes - 1;
  });

  $effect(() => {
    onEpisodeChange?.(selectedEpisode);
  });

  $effect(() => {
    if (!datasetId) return;
    if ($viewerQuery.data?.is_local) {
      datasetSyncAutoTriggered = false;
      return;
    }
    if (!$viewerQuery.data || datasetSyncJobId || datasetSyncAutoTriggered) return;
    datasetSyncAutoTriggered = true;
    void startDatasetSyncJob();
  });

  $effect(() => {
    const state = $datasetSyncJobQuery.data?.state ?? '';
    if (!state) return;
    if (state === datasetSyncHandledTerminalState) return;
    if (state === 'completed') {
      datasetSyncHandledTerminalState = state;
      void refetchViewer();
    }
  });

  $effect(() => {
    if (!datasetSyncJobId) return;
    const currentJobId = datasetSyncJobId;
    const streamPath = `/api/stream/storage/dataset-sync/jobs/${encodeURIComponent(currentJobId)}`;
    const stop = connectStream<DatasetSyncJobStatus>({
      path: streamPath,
      onMessage: (payload) => {
        queryClient.setQueryData(
          ['storage', 'dataset-viewer-panel', datasetId, 'dataset-sync', currentJobId],
          payload
        );
      }
    });
    return () => {
      stop();
    };
  });

  const cloneBlueprint = (node: BlueprintNode): BlueprintNode =>
    JSON.parse(JSON.stringify(node)) as BlueprintNode;

  $effect(() => {
    if (!layoutBlueprint) {
      resolvedLayoutBlueprint = null;
      layoutSelectedId = '';
      return;
    }
    resolvedLayoutBlueprint = cloneBlueprint(layoutBlueprint);
    layoutSelectedId = ensureValidSelection(resolvedLayoutBlueprint, layoutSelectedId || null);
  });

  const handleLayoutTabChange = (id: string, activeId: string) => {
    if (!resolvedLayoutBlueprint) return;
    resolvedLayoutBlueprint = updateTabsActive(resolvedLayoutBlueprint, id, activeId);
  };
</script>

<div class="flex h-full min-h-0 flex-col rounded-2xl border border-slate-200/70 bg-white/70 p-4">
  {#if !datasetId}
    <p class="text-sm text-slate-500">データセットを選択してください。</p>
  {:else if $viewerQuery.isLoading}
    <p class="text-sm text-slate-500">ビューア情報を読み込み中...</p>
  {:else if $viewerQuery.error}
    <p class="text-sm text-rose-600">
      {$viewerQuery.error instanceof Error ? $viewerQuery.error.message : 'ビューア情報の取得に失敗しました。'}
    </p>
  {:else if !$viewerQuery.data?.is_local}
    <div class="space-y-2">
      <p class="text-sm text-slate-700">ローカル未配置のため、同期が必要です。</p>
      {#if $datasetSyncJobQuery.data}
        <p class="text-xs text-slate-500">
          状態: {$datasetSyncJobQuery.data.state}
          {#if typeof $datasetSyncJobQuery.data.progress_percent === 'number'}
            / {Math.round($datasetSyncJobQuery.data.progress_percent)}%
          {/if}
        </p>
        {#if $datasetSyncJobQuery.data.message}
          <p class="text-xs text-slate-500">{$datasetSyncJobQuery.data.message}</p>
        {/if}
        {#if $datasetSyncJobQuery.data.error}
          <p class="text-xs text-rose-600">{$datasetSyncJobQuery.data.error}</p>
        {/if}
      {/if}
      <div class="flex flex-wrap gap-2">
        <button
          class={`btn-ghost ${datasetSyncStarting ? 'opacity-50 cursor-not-allowed' : ''}`}
          type="button"
          disabled={datasetSyncStarting}
          onclick={startDatasetSyncJob}
        >
          同期を再実行
        </button>
        {#if datasetSyncJobId}
          <button class="btn-ghost" type="button" onclick={cancelDatasetSyncJob}>同期を中断</button>
        {/if}
      </div>
    </div>
  {:else}
    <div class="flex flex-wrap items-end gap-3">
      <div>
        <label class="label" for={`episode-index-${datasetId}`}>エピソード</label>
        <input
          id={`episode-index-${datasetId}`}
          class="input mt-2 w-32"
          type="number"
          min="0"
          max={Math.max(playbackEpisodes - 1, 0)}
          bind:value={selectedEpisode}
        />
      </div>
      <button
        class="btn-ghost"
        type="button"
        disabled={selectedEpisode <= 0}
        onclick={() => (selectedEpisode = Math.max(0, selectedEpisode - 1))}
      >
        前へ
      </button>
      <button
        class="btn-ghost"
        type="button"
        disabled={selectedEpisode >= playbackEpisodes - 1}
        onclick={() => (selectedEpisode = Math.min(playbackEpisodes - 1, selectedEpisode + 1))}
      >
        次へ
      </button>
      <p class="text-xs text-slate-500">
        {selectedEpisode + 1} / {playbackEpisodes} episodes
      </p>
    </div>

    {#if !layoutBlueprint && $viewerQuery.data?.use_videos && ($viewerQuery.data?.cameras?.length ?? 0) > 0}
      <div class="mt-4 grid gap-3 xl:grid-cols-2">
        {#each $viewerQuery.data.cameras as camera}
          <div class="rounded-xl border border-slate-200/70 bg-white/80 p-3">
            <div class="mb-2 flex items-center justify-between">
              <p class="text-xs font-semibold text-slate-800">{camera.label}</p>
              <p class="text-[10px] text-slate-500">
                {camera.width ?? '-'}x{camera.height ?? '-'} / {camera.fps ?? '-'}fps
              </p>
            </div>
            {#key `${camera.key}:${selectedEpisode}`}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video
                class="w-full rounded-xl bg-slate-900"
                controls
                preload="metadata"
                crossorigin="use-credentials"
                src={api.storage.datasetViewerVideoUrl(datasetId, camera.key, selectedEpisode)}
              ></video>
            {/key}
          </div>
        {/each}
      </div>
    {/if}

    <div class="mt-4 flex min-h-0 flex-1 flex-col rounded-xl border border-slate-200/70 bg-white/80 p-3">
      <div class="flex flex-wrap items-end gap-3">
        <div class="min-w-56 flex-1">
          <label class="label" for={`signal-field-${datasetId}`}>トピック（保存フィールド）</label>
          <select id={`signal-field-${datasetId}`} class="input mt-2" bind:value={selectedSignalField}>
            {#each signalFields as field}
              <option value={field.key}>{field.key}</option>
            {/each}
          </select>
        </div>
      </div>
      {#if $signalFieldsQuery.isLoading}
        <p class="mt-3 text-sm text-slate-500">表示可能フィールドを読み込み中...</p>
      {:else if $signalSeriesQuery.isLoading}
        <p class="mt-3 text-sm text-slate-500">系列データを読み込み中...</p>
      {:else if $signalSeriesQuery.error}
        <p class="mt-3 text-sm text-rose-600">
          {$signalSeriesQuery.error instanceof Error
            ? $signalSeriesQuery.error.message
            : '系列データの取得に失敗しました。'}
        </p>
      {:else if !signalFields.length}
        <p class="mt-3 text-sm text-slate-500">可視化できる数値ベクトルフィールドがありません。</p>
      {:else if layoutBlueprint}
        {#if resolvedLayoutBlueprint}
          <div class="mt-3 min-h-0 flex-1 rounded-xl border border-slate-200/70 bg-white/70 p-2">
            <LayoutNode
              node={resolvedLayoutBlueprint}
              selectedId={layoutSelectedId}
              sessionId=""
              sessionKind=""
              mode="recording"
              viewSource="dataset"
              datasetJointSeries={datasetJointSeries}
              datasetSourceLabel={datasetSignalLabel}
              editMode={false}
              viewScale={1}
              onSelect={() => {}}
              onResize={() => {}}
              onTabChange={handleLayoutTabChange}
            />
          </div>
        {:else}
          <p class="mt-3 text-sm text-slate-500">レイアウトを初期化中...</p>
        {/if}
      {:else}
        <div class="mt-3 h-[360px]">
          <JointStateView
            source="dataset"
            sourceLabel={datasetSignalLabel}
            datasetSeries={datasetJointSeries}
            title="Joint State / Dataset"
            showVelocity={true}
          />
        </div>
      {/if}
    </div>
  {/if}
</div>

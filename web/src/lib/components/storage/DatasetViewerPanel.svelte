<script lang="ts">
  import { toStore } from 'svelte/store';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { connectStream } from '$lib/realtime/stream';
	  import {
	    api,
	    type DatasetSyncJobStatus,
	    type DatasetViewerSignalField,
	    type DatasetViewerSignalFieldsResponse
	  } from '$lib/api/client';
  import LayoutNode from '$lib/components/recording/LayoutNode.svelte';
  import JointStateView from '$lib/components/recording/views/JointStateView.svelte';
  import { ensureValidSelection, updateTabsActive, type BlueprintNode } from '$lib/recording/blueprint';

  let {
    datasetId = '',
    episodeIndex = 0,
    onEpisodeChange,
    layoutBlueprint = null,
    autoSelectSignalField = true
  }: {
    datasetId?: string;
    episodeIndex?: number;
    onEpisodeChange?: (episodeIndex: number) => void;
    layoutBlueprint?: BlueprintNode | null;
    autoSelectSignalField?: boolean;
  } = $props();

  const queryClient = useQueryClient();
  let selectedEpisode = $state(0);
  let selectedSignalField = $state('');
  let datasetSyncJobId = $state('');
  let datasetSyncAutoTriggered = $state(false);
  let datasetSyncStarting = $state(false);
  let datasetSyncHandledTerminalState = $state('');
  let lastDatasetIdForSync = $state('');
  let lastNotifiedEpisode: number | null = $state(null);
  let lastLayoutBlueprintSignature = $state('');
  let resolvedLayoutBlueprint: BlueprintNode | null = $state(null);
  let layoutSelectedId = $state('');

  const viewerQuery = createQuery(
    toStore(() => ({
      queryKey: ['storage', 'dataset-viewer-panel', datasetId, 'viewer'],
      queryFn: () => api.storage.datasetViewer(datasetId),
      enabled: Boolean(datasetId)
    }))
  );
  const playbackEpisodes = $derived($viewerQuery.data?.total_episodes ?? 0);

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
	  const datasetSignalLabel = $derived(
	    selectedSignalMeta ? `${selectedSignalMeta.key} (${selectedSignalMeta.dtype})` : selectedSignalField
	  );

	  const applySignalToJointStateViews = (node: BlueprintNode, signalKey: string): BlueprintNode => {
	    if (node.type === 'view') {
	      if (node.viewType !== 'joint_state') return node;
	      const current = typeof node.config?.topic === 'string' ? node.config.topic : '';
	      if (current === signalKey) return node;
	      return {
	        ...node,
	        config: {
	          ...node.config,
	          topic: signalKey
	        }
	      };
	    }
	    if (node.type === 'split') {
	      const left = applySignalToJointStateViews(node.children[0], signalKey);
	      const right = applySignalToJointStateViews(node.children[1], signalKey);
	      if (left === node.children[0] && right === node.children[1]) return node;
	      return { ...node, children: [left, right] };
	    }
	    const nextTabs = node.tabs.map((tab) => {
	      const child = applySignalToJointStateViews(tab.child, signalKey);
	      return child === tab.child ? tab : { ...tab, child };
	    });
	    const changed = nextTabs.some((tab, idx) => tab !== node.tabs[idx]);
	    return changed ? { ...node, tabs: nextTabs } : node;
	  };

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
      const nextEpisode = Math.max(0, Math.floor(episodeIndex || 0));
      if (selectedEpisode !== nextEpisode) {
        selectedEpisode = nextEpisode;
      }
      lastNotifiedEpisode = null;
      if (selectedSignalField !== '') {
        selectedSignalField = '';
      }
    }
  });

		  $effect(() => {
		    if (!signalFields.length) {
	      if (selectedSignalField !== '') {
	        selectedSignalField = '';
	      }
	      return;
	    }
	    if (!autoSelectSignalField) return;
	    if (!selectedSignalField || !signalFields.some((field) => field.key === selectedSignalField)) {
	      const preferred =
	        signalFields.find((field) => /joint|state|position/i.test(field.key)) ?? signalFields[0];
	      const nextField = preferred.key;
	      if (selectedSignalField !== nextField) {
	        selectedSignalField = nextField;
	      }
	    }
		  });

	  $effect(() => {
	    if (!layoutBlueprint) return;
	    if (!resolvedLayoutBlueprint) return;
	    if (!selectedSignalField) return;
	    const nextLayout = applySignalToJointStateViews(resolvedLayoutBlueprint, selectedSignalField);
	    if (nextLayout !== resolvedLayoutBlueprint) {
	      resolvedLayoutBlueprint = nextLayout;
	      layoutSelectedId = ensureValidSelection(nextLayout, layoutSelectedId || null);
	    }
	  });

  $effect(() => {
    if (!Number.isFinite(selectedEpisode)) {
      selectedEpisode = 0;
      return;
    }
    if (playbackEpisodes <= 0) {
      if (selectedEpisode !== 0) {
        selectedEpisode = 0;
      }
      return;
    }
    if (selectedEpisode < 0) {
      selectedEpisode = 0;
      return;
    }
    if (selectedEpisode >= playbackEpisodes) {
      selectedEpisode = playbackEpisodes - 1;
    }
  });

  $effect(() => {
    if (Object.is(lastNotifiedEpisode, selectedEpisode)) return;
    lastNotifiedEpisode = selectedEpisode;
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
    const signature = layoutBlueprint ? JSON.stringify(layoutBlueprint) : '';
    if (signature === lastLayoutBlueprintSignature) return;
    lastLayoutBlueprintSignature = signature;

    if (!layoutBlueprint) {
      if (resolvedLayoutBlueprint !== null) {
        resolvedLayoutBlueprint = null;
      }
      if (layoutSelectedId !== '') {
        layoutSelectedId = '';
      }
      return;
    }
    const nextLayout = cloneBlueprint(layoutBlueprint);
    const nextSelectedId = ensureValidSelection(nextLayout, null);
    resolvedLayoutBlueprint = nextLayout;
    if (layoutSelectedId !== nextSelectedId) {
      layoutSelectedId = nextSelectedId;
    }
  });

  const handleLayoutTabChange = (id: string, activeId: string) => {
    if (!resolvedLayoutBlueprint) return;
    const nextLayout = updateTabsActive(resolvedLayoutBlueprint, id, activeId);
    resolvedLayoutBlueprint = nextLayout;
    const nextSelectedId = ensureValidSelection(nextLayout, layoutSelectedId || null);
    if (layoutSelectedId !== nextSelectedId) {
      layoutSelectedId = nextSelectedId;
    }
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
            <option value="">選択してください</option>
            {#each signalFields as field}
              <option value={field.key}>{field.key}</option>
            {/each}
          </select>
        </div>
      </div>
      {#if $signalFieldsQuery.isLoading}
        <p class="mt-3 text-sm text-slate-500">表示可能フィールドを読み込み中...</p>
      {:else if !signalFields.length}
        <p class="mt-3 text-sm text-slate-500">可視化できる数値ベクトルフィールドがありません。</p>
      {:else if !selectedSignalField}
        <p class="mt-3 text-sm text-slate-500">可視化するフィールドを選択してください。</p>
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
		              datasetId={datasetId}
		              datasetEpisodeIndex={selectedEpisode}
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
            datasetId={datasetId}
            episodeIndex={selectedEpisode}
            topic={selectedSignalField}
            title="Joint State / Dataset"
            showVelocity={true}
          />
        </div>
      {/if}
    </div>
  {/if}
</div>

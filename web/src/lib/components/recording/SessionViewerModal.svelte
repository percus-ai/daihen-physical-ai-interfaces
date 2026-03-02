<script lang="ts">
  import { Button, Dialog } from 'bits-ui';
  import { toStore } from 'svelte/store';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import toast from 'svelte-french-toast';

  import SessionLayoutEditor from '$lib/components/recording/SessionLayoutEditor.svelte';
  import { api, type DatasetSyncJobStatus, type DatasetViewerSignalFieldsResponse } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';

  let {
    open = $bindable(false),
    datasetId = '',
    episodeIndex = 0,
    title = 'Session Viewer',
    initialInspectorTab = 'selection',
    startInEditMode = false
  }: {
    open?: boolean;
    datasetId?: string;
    episodeIndex?: number;
    title?: string;
    initialInspectorTab?: 'blueprint' | 'selection' | 'search';
    startInEditMode?: boolean;
  } = $props();

  const queryClient = useQueryClient();
  let viewerLayoutEditMode = $state(false);
  let selectedEpisodeRaw = $state(0);
  let episodeInputText = $state('1');

  let viewerSyncJobId = $state('');
  let viewerSyncStarting = $state(false);
  let viewerSyncAutoTriggered = $state(false);

  const close = () => {
    open = false;
  };

  $effect(() => {
    if (!open) return;
    viewerLayoutEditMode = Boolean(startInEditMode);
    selectedEpisodeRaw = Math.max(0, Math.floor(Number(episodeIndex) || 0));
    episodeInputText = String(selectedEpisodeRaw + 1);
  });

  const viewerDatasetQuery = createQuery(
    toStore(() => ({
      queryKey: qk.storage.datasetViewer(datasetId),
      queryFn: () => api.storage.datasetViewer(datasetId),
      enabled: Boolean(open) && Boolean(datasetId)
    }))
  );

  const viewerIsLocal = $derived(Boolean($viewerDatasetQuery.data?.is_local));
  const viewerTotalEpisodes = $derived(Number($viewerDatasetQuery.data?.total_episodes ?? 0));
  const viewerEpisodeIndex = $derived.by(() => {
    const next = Math.max(0, Math.floor(Number(selectedEpisodeRaw) || 0));
    if (!Number.isFinite(next)) return 0;
    if (viewerTotalEpisodes <= 0) return next;
    if (next >= viewerTotalEpisodes) return Math.max(0, viewerTotalEpisodes - 1);
    return next;
  });

  const viewerSignalFieldsQuery = createQuery<DatasetViewerSignalFieldsResponse>(
    toStore(() => ({
      queryKey: qk.storage.datasetViewerSignalFields(datasetId),
      queryFn: () => api.storage.datasetViewerSignalFields(datasetId),
      enabled: Boolean(open) && Boolean(datasetId) && viewerIsLocal
    }))
  );

  const viewerSignalFields = $derived($viewerSignalFieldsQuery.data?.fields ?? []);
  const viewerSignalFieldsLoaded = $derived(
    !$viewerSignalFieldsQuery.isLoading && !$viewerSignalFieldsQuery.isFetching
  );
  const viewerDatasetSignalKeys = $derived.by(() => {
    const keys = viewerSignalFields.map((field) => field.key);
    const useFallback = viewerIsLocal && viewerSignalFieldsLoaded && keys.length === 0;
    return useFallback ? ['observation.state', 'action'] : keys;
  });

  const viewerCameraKeys = $derived(($viewerDatasetQuery.data?.cameras ?? []).map((camera) => camera.key));

  const viewerSyncJobQuery = createQuery<DatasetSyncJobStatus>(
    toStore(() => ({
      queryKey: qk.storage.datasetSyncJob(viewerSyncJobId),
      queryFn: () => api.storage.datasetSyncJob(viewerSyncJobId),
      enabled: Boolean(open) && Boolean(viewerSyncJobId)
    }))
  );

  const refetchViewerDataset = async () => {
    if (!datasetId) return;
    await queryClient.invalidateQueries({
      queryKey: qk.storage.datasetViewer(datasetId)
    });
  };

  const startViewerSyncJob = async () => {
    if (!datasetId || viewerSyncStarting) return;
    viewerSyncStarting = true;
    try {
      const accepted = await api.storage.syncDataset(datasetId);
      viewerSyncJobId = accepted.job_id;
      toast.success('データセット同期を開始しました。');
    } catch (err) {
      const status =
        typeof err === 'object' && err !== null && 'status' in err ? Number((err as { status?: unknown }).status) : 0;
      if (status === 409) {
        toast('同期ジョブが既に実行中です。');
      } else {
        toast.error('データセット同期の開始に失敗しました。');
      }
    } finally {
      viewerSyncStarting = false;
    }
  };

  $effect(() => {
    if (!open) return;
    if (!datasetId) return;
    if (!$viewerDatasetQuery.data) return;
    if (viewerIsLocal) return;
    if (viewerSyncJobId) return;
    if (viewerSyncAutoTriggered) return;

    viewerSyncAutoTriggered = true;
    void startViewerSyncJob();
  });

  const clampEpisodeInput = (value: number) => {
    const maxValue = viewerTotalEpisodes > 0 ? viewerTotalEpisodes : Number.POSITIVE_INFINITY;
    return Math.max(1, Math.min(Math.floor(value), maxValue));
  };

  const applyEpisodeInput = () => {
    const parsed = Number(episodeInputText);
    if (!Number.isFinite(parsed)) {
      episodeInputText = String(viewerEpisodeIndex + 1);
      return;
    }
    const clamped = clampEpisodeInput(parsed);
    episodeInputText = String(clamped);
    selectedEpisodeRaw = Math.max(0, clamped - 1);
  };
</script>

<Dialog.Root bind:open={open}>
  <Dialog.Portal>
    <Dialog.Overlay class="fixed inset-0 z-[80] bg-slate-900/45 backdrop-blur-[1px]" />
    <Dialog.Content
      class="fixed inset-[0.75rem] z-[81] overflow-hidden rounded-2xl border border-slate-200/70 bg-white p-4 shadow-xl outline-none"
    >
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-slate-900">{title}</p>
          <p class="text-xs text-slate-500">{datasetId || 'dataset 未選択'}</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button.Root
            class="btn-ghost"
            type="button"
            onclick={() => {
              viewerLayoutEditMode = !viewerLayoutEditMode;
            }}
          >
            {viewerLayoutEditMode ? '閲覧モード' : '編集モード'}
          </Button.Root>
          <Button.Root class="btn-ghost" type="button" onclick={close}>閉じる</Button.Root>
        </div>
      </div>

      <div class="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-slate-200/70 bg-slate-50/60 p-3 text-xs text-slate-600">
        <div class="flex items-center gap-2">
          <span class="font-semibold text-slate-700">エピソード</span>
          <Button.Root
            class="btn-ghost px-2 py-1 text-xs"
            type="button"
            disabled={viewerEpisodeIndex <= 0}
            onclick={() => {
              selectedEpisodeRaw = Math.max(0, viewerEpisodeIndex - 1);
              episodeInputText = String(selectedEpisodeRaw + 1);
            }}
          >
            前へ
          </Button.Root>
          <input
            class="h-8 w-20 rounded-lg border border-slate-200 bg-white px-2 text-xs"
            type="number"
            min="1"
            step="1"
            bind:value={episodeInputText}
            onblur={applyEpisodeInput}
            onkeydown={(e) => {
              if (e.key !== 'Enter') return;
              applyEpisodeInput();
            }}
          />
          <span class="text-slate-500">
            / {viewerTotalEpisodes > 0 ? viewerTotalEpisodes : '-'}
          </span>
          <Button.Root
            class="btn-ghost px-2 py-1 text-xs"
            type="button"
            disabled={viewerTotalEpisodes > 0 ? viewerEpisodeIndex >= viewerTotalEpisodes - 1 : false}
            onclick={() => {
              selectedEpisodeRaw = viewerEpisodeIndex + 1;
              episodeInputText = String(selectedEpisodeRaw + 1);
            }}
          >
            次へ
          </Button.Root>
        </div>

        {#if datasetId && $viewerDatasetQuery.isLoading}
          <span class="text-slate-500">データセット情報を取得中...</span>
        {:else if datasetId && $viewerDatasetQuery.data && !viewerIsLocal}
          <span class="text-slate-500">ローカル未配置: 同期を開始しました。</span>
        {/if}
      </div>

      <div class="mt-3 h-[82vh] min-h-0">
        {#if datasetId && viewerIsLocal}
          <SessionLayoutEditor
            blueprintSessionId={datasetId}
            blueprintSessionKind="recording"
            layoutSessionId={datasetId}
            layoutSessionKind="recording"
            layoutMode="recording"
            viewSource="dataset"
            editMode={viewerLayoutEditMode}
            initialInspectorTab={initialInspectorTab}
            persistBlueprintDraft={false}
            embedded={true}
            datasetId={datasetId}
            datasetEpisodeIndex={viewerEpisodeIndex}
            datasetCameraKeys={viewerCameraKeys}
            datasetSignalKeys={viewerDatasetSignalKeys}
          />
        {:else if datasetId && $viewerDatasetQuery.data && !viewerIsLocal}
          <div class="flex h-full flex-col items-center justify-center gap-3 rounded-xl border border-slate-200/70 bg-white/80 px-6 text-center">
            <p class="text-sm text-slate-700">ローカル未配置のため、データセット同期を実行中です。</p>
            {#if $viewerSyncJobQuery.isLoading}
              <p class="text-xs text-slate-500">同期ジョブ情報を読み込み中...</p>
            {:else if $viewerSyncJobQuery.error}
              <p class="text-xs text-rose-600">
                {$viewerSyncJobQuery.error instanceof Error
                  ? $viewerSyncJobQuery.error.message
                  : '同期ジョブ情報の取得に失敗しました。'}
              </p>
            {:else if $viewerSyncJobQuery.data}
              <p class="text-xs text-slate-500">
                状態: {$viewerSyncJobQuery.data.state}
                {#if typeof $viewerSyncJobQuery.data.progress_percent === 'number'}
                  / {Math.round($viewerSyncJobQuery.data.progress_percent)}%
                {/if}
              </p>
              {#if $viewerSyncJobQuery.data.message}
                <p class="text-xs text-slate-500">{$viewerSyncJobQuery.data.message}</p>
              {/if}
              {#if $viewerSyncJobQuery.data.error}
                <p class="text-xs text-rose-600">{$viewerSyncJobQuery.data.error}</p>
              {/if}
            {/if}
            <div class="flex flex-wrap gap-2">
              <Button.Root class="btn-ghost" type="button" onclick={startViewerSyncJob} disabled={viewerSyncStarting}>
                {viewerSyncStarting ? '同期開始中...' : '同期を再実行'}
              </Button.Root>
              <Button.Root class="btn-ghost" type="button" onclick={refetchViewerDataset}>
                再読み込み
              </Button.Root>
            </div>
          </div>
        {:else if datasetId}
          <div class="flex h-full flex-col items-center justify-center gap-2 rounded-xl border border-slate-200/70 bg-white/80 px-6 text-center">
            <p class="text-sm text-slate-500">表示準備中...</p>
            <p class="text-xs text-slate-500">データセット情報を読み込み中です。</p>
          </div>
        {:else}
          <div class="flex h-full flex-col items-center justify-center gap-2 rounded-xl border border-slate-200/70 bg-white/80 px-6 text-center">
            <p class="text-sm text-slate-500">表示するデータセットがありません。</p>
            <p class="text-xs text-slate-500">データセットを選択してから開いてください。</p>
          </div>
        {/if}
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<script lang="ts">
  import { onDestroy } from 'svelte';
  import { Button } from 'bits-ui';
  import { toStore } from 'svelte/store';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import toast from 'svelte-french-toast';

  import SessionLayoutEditor from '$lib/components/recording/SessionLayoutEditor.svelte';
  import { createDatasetAvailabilityController } from '$lib/viewer/datasetAvailability';
  import ViewerDialogShell from '$lib/viewer/ViewerDialogShell.svelte';
  import { qk } from '$lib/queryKeys';
  import type { DatasetViewerEpisodeVideoWindowResponse } from '$lib/api/client';
  import { api } from '$lib/api/client';

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
  const datasetAvailability = createDatasetAvailabilityController({
    datasetId: toStore(() => datasetId),
    enabled: toStore(() => Boolean(open) && Boolean(datasetId)),
    queryClient,
    notify: (message, level = 'info') => {
      if (level === 'success') toast.success(message);
      else if (level === 'error') toast.error(message);
      else toast(message);
    }
  });
  onDestroy(datasetAvailability.destroy);

  let viewerLayoutEditMode = $state(false);
  let selectedEpisodeRaw = $state(0);
  let episodeInputText = $state('1');

  const close = () => {
    open = false;
  };

  $effect(() => {
    if (!open) return;
    viewerLayoutEditMode = Boolean(startInEditMode);
    selectedEpisodeRaw = Math.max(0, Math.floor(Number(episodeIndex) || 0));
    episodeInputText = String(selectedEpisodeRaw + 1);
  });

  const viewerDatasetQuery = datasetAvailability.datasetQuery;
  const viewerIsLocal = datasetAvailability.isLocal;
  const viewerTotalEpisodes = datasetAvailability.totalEpisodes;
  const viewerIsLocalValue = $derived($viewerIsLocal);
  const viewerEpisodeIndex = $derived.by(() => {
    const next = Math.max(0, Math.floor(Number(selectedEpisodeRaw) || 0));
    if (!Number.isFinite(next)) return 0;
    const total = $viewerTotalEpisodes;
    if (total <= 0) return next;
    if (next >= total) return Math.max(0, total - 1);
    return next;
  });
  const viewerDatasetSignalKeys = datasetAvailability.signalKeys;
  const viewerCameraKeys = datasetAvailability.cameraKeys;
  const viewerSyncJobQuery = datasetAvailability.syncJobQuery;
  const viewerSyncJobId = datasetAvailability.syncJobId;
  const viewerSyncStarting = datasetAvailability.syncStarting;
  const refetchViewerDataset = datasetAvailability.refetch;
  const startViewerSyncJob = datasetAvailability.startSync;

  const videoWindowEnabled = $derived(Boolean(open) && Boolean(datasetId) && viewerIsLocalValue);
  const viewerVideoWindowQuery = createQuery<DatasetViewerEpisodeVideoWindowResponse>(
    toStore(() => ({
      queryKey: qk.storage.datasetViewerEpisodeVideoWindow(datasetId, viewerEpisodeIndex),
      queryFn: () => api.storage.datasetViewerEpisodeVideoWindow(datasetId, viewerEpisodeIndex),
      enabled: videoWindowEnabled
    }))
  );
  const viewerVideoWindows = $derived.by(() => {
    const videos = $viewerVideoWindowQuery.data?.videos ?? [];
    const out: Record<string, { from_s: number; to_s: number }> = {};
    for (const video of videos) {
      out[video.key] = {
        from_s: Number(video.from_s) || 0,
        to_s: Number(video.to_s) || 0
      };
    }
    return out;
  });

  const clampEpisodeInput = (value: number) => {
    const total = $viewerTotalEpisodes;
    const maxValue = total > 0 ? total : Number.POSITIVE_INFINITY;
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

<ViewerDialogShell bind:open={open} zIndexBase={80} inset="0.75rem">
  {#snippet children()}
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
            / {$viewerTotalEpisodes > 0 ? $viewerTotalEpisodes : '-'}
          </span>
          <Button.Root
            class="btn-ghost px-2 py-1 text-xs"
            type="button"
            disabled={$viewerTotalEpisodes > 0 ? viewerEpisodeIndex >= $viewerTotalEpisodes - 1 : false}
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
        {:else if datasetId && $viewerDatasetQuery.data && !$viewerIsLocal}
          <span class="text-slate-500">ローカル未配置: 同期を開始しました。</span>
        {/if}
      </div>

      <div class="mt-3 h-[82vh] min-h-0">
        {#if datasetId && $viewerIsLocal}
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
            datasetCameraKeys={$viewerCameraKeys}
            datasetSignalKeys={$viewerDatasetSignalKeys}
            datasetVideoWindows={viewerVideoWindows}
          />
        {:else if datasetId && $viewerDatasetQuery.data && !$viewerIsLocal}
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
              <Button.Root class="btn-ghost" type="button" onclick={startViewerSyncJob} disabled={$viewerSyncStarting}>
                {$viewerSyncStarting ? '同期開始中...' : '同期を再実行'}
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
  {/snippet}
</ViewerDialogShell>

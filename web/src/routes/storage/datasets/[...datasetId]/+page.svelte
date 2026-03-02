<script lang="ts">
  import { onDestroy } from 'svelte';
  import { Button } from 'bits-ui';
  import { get, toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { api, type DatasetViewerEpisodeVideoWindowResponse } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';
  import { createDatasetAvailabilityController } from '$lib/viewer/datasetAvailability';
  import { sessionViewer } from '$lib/viewer/sessionViewerStore';
  import SessionLayoutEditor from '$lib/components/recording/SessionLayoutEditor.svelte';
  import { formatBytes, formatDate } from '$lib/format';

  type DatasetInfo = {
    id: string;
    name?: string;
    profile_name?: string;
    dataset_type?: string;
    status?: string;
    size_bytes?: number;
    episode_count?: number;
    is_local?: boolean;
    created_at?: string;
    updated_at?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetInfo[];
    total?: number;
  };

  type DatasetMergeResponse = {
    dataset_id?: string;
  };

  const datasetId = $derived(page.params.datasetId ?? '');

  const queryClient = useQueryClient();

  const datasetQuery = createQuery<DatasetInfo>(
    toStore(() => ({
      queryKey: qk.storage.dataset(datasetId),
      queryFn: () => api.storage.dataset(datasetId) as Promise<DatasetInfo>,
      enabled: Boolean(datasetId)
    }))
  );

  const dataset = $derived($datasetQuery.data);
  const profileName = $derived(dataset?.profile_name ?? '');
  const isArchived = $derived(dataset?.status === 'archived');

  const candidatesQuery = createQuery<DatasetListResponse>(
    toStore(() => ({
      queryKey: qk.storage.datasetsByProfile(profileName),
      queryFn: () => api.storage.datasets(profileName) as Promise<DatasetListResponse>,
      enabled: Boolean(profileName)
    }))
  );

  const candidates = $derived(
    ($candidatesQuery.data?.datasets ?? [])
      .filter((item) => item.profile_name === profileName)
      .filter((item) => item.status === 'active' && item.id !== datasetId)
  );

  let mergeSelection: string[] = $state([]);
  let mergeName = $state('');
  let actionMessage = $state('');
  let actionError = $state('');
  let actionLoading = $state(false);

  const mergeDefaultName = $derived(
    datasetId
      ? `${dataset?.name ?? datasetId}_merged`
      : ''
  );
  const canMerge = $derived(!isArchived && mergeSelection.length > 0 && !actionLoading);

  const openViewerModal = () => {
    if (!datasetId) return;
    sessionViewer.open({ datasetId, episodeIndex: selectedEpisode });
  };

  const datasetAvailability = createDatasetAvailabilityController({
    datasetId: toStore(() => datasetId),
    enabled: toStore(() => Boolean(datasetId)),
    queryClient,
    notify: (message, level = 'info') => {
      if (level === 'error') {
        actionError = message;
        return;
      }
      actionError = '';
      actionMessage = message;
    },
    onCompleted: (completedDatasetId) => {
      void queryClient.invalidateQueries({ queryKey: qk.storage.dataset(completedDatasetId) });
    }
  });
  onDestroy(datasetAvailability.destroy);

  const viewerQuery = datasetAvailability.datasetQuery;

  let selectedEpisode = $state(0);
  const playbackEpisodes = $derived($viewerQuery.data?.total_episodes ?? 0);
  const datasetSyncJobId = datasetAvailability.syncJobId;
  const datasetSyncStarting = datasetAvailability.syncStarting;
  const datasetSyncJobQuery = datasetAvailability.syncJobQuery;
  const startDatasetSyncJob = datasetAvailability.startSync;

  const viewerCameraKeys = datasetAvailability.cameraKeys;
  const viewerSignalKeys = datasetAvailability.signalKeys;

  $effect(() => {
    if (playbackEpisodes <= 0) {
      selectedEpisode = 0;
      return;
    }
    if (selectedEpisode < 0) selectedEpisode = 0;
    if (selectedEpisode >= playbackEpisodes) selectedEpisode = playbackEpisodes - 1;
  });

  const videoWindowQuery = createQuery<DatasetViewerEpisodeVideoWindowResponse>(
    toStore(() => ({
      queryKey: qk.storage.datasetViewerEpisodeVideoWindow(datasetId, selectedEpisode),
      queryFn: () => api.storage.datasetViewerEpisodeVideoWindow(datasetId, selectedEpisode),
      enabled: Boolean(datasetId) && Boolean(dataset?.is_local)
    }))
  );
  const viewerVideoWindows = $derived.by(() => {
    const videos = $videoWindowQuery.data?.videos ?? [];
    const out: Record<string, { from_s: number; to_s: number }> = {};
    for (const video of videos) {
      out[video.key] = {
        from_s: Number(video.from_s) || 0,
        to_s: Number(video.to_s) || 0
      };
    }
    return out;
  });

  const refetchDataset = async () => {
    if (!datasetId) return;
    await queryClient.invalidateQueries({ queryKey: qk.storage.dataset(datasetId) });
    await datasetAvailability.refetch();
  };

  const cancelDatasetSyncJob = async () => {
    const currentJobId = get(datasetSyncJobId);
    if (!currentJobId) return;
    actionError = '';
    try {
      await api.storage.cancelDatasetSyncJob(currentJobId);
      await queryClient.invalidateQueries({ queryKey: qk.storage.datasetSyncJob(currentJobId) });
    } catch (err) {
      actionError = err instanceof Error ? err.message : '同期中断に失敗しました。';
    }
  };

  const refetchCandidates = async () => {
    if (!profileName) return;
    await queryClient.invalidateQueries({
      queryKey: qk.storage.datasetsByProfile(profileName)
    });
  };

  async function handleArchive() {
    actionMessage = '';
    actionError = '';

    if (!datasetId) return;
    const confirmed = confirm(`${datasetId} をアーカイブしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.archiveDataset(datasetId);
      await refetchDataset();
      actionMessage = 'アーカイブしました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleRestore() {
    actionMessage = '';
    actionError = '';

    if (!datasetId) return;
    const confirmed = confirm(`${datasetId} を復元しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.restoreDataset(datasetId);
      await refetchDataset();
      actionMessage = '復元しました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleReupload() {
    actionMessage = '';
    actionError = '';

    if (!datasetId) return;
    const confirmed = confirm(`${datasetId} をR2へ再アップロードしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      const result = await api.storage.reuploadDataset(datasetId) as { message?: string };
      await refetchDataset();
      actionMessage = result.message ?? '再アップロードを完了しました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : '再アップロードに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleMerge() {
    actionMessage = '';
    actionError = '';

    if (!datasetId || !profileName) return;
    if (!mergeSelection.length) {
      actionError = 'マージ対象を選択してください。';
      return;
    }

    const datasetName = mergeName.trim() || mergeDefaultName;
    if (!datasetName) {
      actionError = '新しいデータセット名を入力してください。';
      return;
    }

    const confirmed = confirm(`${mergeSelection.length + 1}件を ${datasetName} にマージしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      const result = await api.storage.mergeDatasets({
        dataset_name: datasetName,
        source_dataset_ids: [datasetId, ...mergeSelection]
      }) as DatasetMergeResponse;
      actionMessage = `マージ完了: ${result.dataset_id}`;
      mergeSelection = [];
      mergeName = '';
      await refetchDataset();
      await refetchCandidates();
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'マージに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データセット詳細</h1>
      <p class="mt-2 text-sm text-slate-600">データセットの状態と操作を確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage/datasets">一覧へ戻る</Button.Root>
      <button class="btn-ghost" type="button" onclick={refetchDataset}>更新</button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">基本情報</h2>
  </div>
  {#if $datasetQuery.isLoading}
    <p class="mt-4 text-sm text-slate-600">読み込み中...</p>
  {:else if dataset}
    <div class="mt-4 grid gap-4 text-sm text-slate-600 lg:grid-cols-2">
      <div>
        <p class="label">ID</p>
        <p class="text-base font-semibold text-slate-800">{dataset.id}</p>
      </div>
      <div>
        <p class="label">プロファイル</p>
        <p class="text-base font-semibold text-slate-800">{dataset.profile_name ?? '-'}</p>
      </div>
      <div>
        <p class="label">タイプ</p>
        <p class="text-base font-semibold text-slate-800">{dataset.dataset_type}</p>
      </div>
      <div>
        <p class="label">状態</p>
        <p class="text-base font-semibold text-slate-800">{dataset.status}</p>
      </div>
      <div>
        <p class="label">サイズ</p>
        <p class="text-base font-semibold text-slate-800">{formatBytes(dataset.size_bytes)}</p>
      </div>
      <div>
        <p class="label">エピソード数</p>
        <p class="text-base font-semibold text-slate-800">{dataset.episode_count ?? 0}</p>
      </div>
      <div>
        <p class="label">作成日時</p>
        <p class="text-base font-semibold text-slate-800">{formatDate(dataset.created_at)}</p>
      </div>
      <div>
        <p class="label">更新日時</p>
        <p class="text-base font-semibold text-slate-800">{formatDate(dataset.updated_at)}</p>
      </div>
    </div>
    <div class="mt-6 flex flex-wrap gap-2">
      {#if isArchived}
        <button
          class={`btn-primary ${actionLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
          type="button"
          disabled={actionLoading}
          onclick={handleRestore}
        >
          復元
        </button>
      {:else}
        <button
          class={`btn-primary ${actionLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
          type="button"
          disabled={actionLoading}
          onclick={handleReupload}
        >
          再アップロード
        </button>
        <button
          class={`btn-ghost ${actionLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
          type="button"
          disabled={actionLoading}
          onclick={handleArchive}
        >
          アーカイブ
        </button>
      {/if}
      <button class="btn-ghost" type="button" onclick={() => goto('/storage/archive')}>アーカイブ一覧</button>
    </div>
  {:else}
    <p class="mt-4 text-sm text-slate-600">データセットが見つかりません。</p>
  {/if}
  {#if actionMessage}
    <p class="mt-4 text-sm text-emerald-600">{actionMessage}</p>
  {/if}
  {#if actionError}
    <p class="mt-2 text-sm text-rose-600">{actionError}</p>
  {/if}
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">再生</h2>
    <div class="flex gap-2">
      <button class="btn-ghost" type="button" onclick={openViewerModal}>
        ビューアで開く
      </button>
      <button class="btn-ghost" type="button" onclick={refetchDataset}>
        再読み込み
      </button>
    </div>
  </div>
  <p class="mt-2 text-sm text-slate-600">収録済みエピソードをブラウザで確認できます。</p>
  {#if !dataset?.is_local}
    <div class="mt-4 rounded-xl border border-slate-200/70 bg-white/70 p-4">
      <p class="text-sm text-slate-700">ローカル未配置のため、データセット同期を実行中です。</p>
      {#if $datasetSyncJobQuery.isLoading}
        <p class="mt-2 text-xs text-slate-500">同期ジョブ情報を読み込み中...</p>
      {:else if $datasetSyncJobQuery.error}
        <p class="mt-2 text-xs text-rose-600">
          {$datasetSyncJobQuery.error instanceof Error
            ? $datasetSyncJobQuery.error.message
            : '同期ジョブ情報の取得に失敗しました。'}
        </p>
      {:else if $datasetSyncJobQuery.data}
        <p class="mt-2 text-xs text-slate-500">
          状態: {$datasetSyncJobQuery.data.state}
          {#if typeof $datasetSyncJobQuery.data.progress_percent === 'number'}
            / {Math.round($datasetSyncJobQuery.data.progress_percent)}%
          {/if}
        </p>
        {#if $datasetSyncJobQuery.data.message}
          <p class="mt-1 text-xs text-slate-500">{$datasetSyncJobQuery.data.message}</p>
        {/if}
        {#if $datasetSyncJobQuery.data.error}
          <p class="mt-1 text-xs text-rose-600">{$datasetSyncJobQuery.data.error}</p>
        {/if}
      {/if}
      <div class="mt-3 flex flex-wrap gap-2">
        <button
          class={`btn-ghost ${$datasetSyncStarting ? 'opacity-50 cursor-not-allowed' : ''}`}
          type="button"
          disabled={$datasetSyncStarting}
          onclick={startDatasetSyncJob}
        >
          同期を再実行
        </button>
        {#if $datasetSyncJobId}
          <button
            class="btn-ghost"
            type="button"
            onclick={cancelDatasetSyncJob}
          >
            同期を中断
          </button>
        {/if}
      </div>
    </div>
  {:else if $viewerQuery.isLoading}
    <p class="mt-4 text-sm text-slate-600">再生情報を読み込み中...</p>
  {:else if $viewerQuery.error}
    <p class="mt-4 text-sm text-rose-600">
      {$viewerQuery.error instanceof Error
        ? $viewerQuery.error.message
        : '再生情報の取得に失敗しました。'}
    </p>
  {:else if playbackEpisodes > 0}
    <div class="mt-4 flex flex-wrap items-end gap-3">
      <div>
        <label class="label" for="episode-index">エピソード</label>
        <input
          id="episode-index"
          class="input mt-2 w-36"
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

    <div class="mt-4 h-[82vh] min-h-0">
      <SessionLayoutEditor
        blueprintSessionId={datasetId}
        blueprintSessionKind="recording"
        layoutSessionId={datasetId}
        layoutSessionKind="recording"
        layoutMode="recording"
        viewSource="dataset"
        editMode={false}
        initialInspectorTab="selection"
        persistBlueprintDraft={false}
        embedded={true}
        datasetId={datasetId}
        datasetEpisodeIndex={selectedEpisode}
        datasetCameraKeys={$viewerCameraKeys}
        datasetSignalKeys={$viewerSignalKeys}
        datasetVideoWindows={viewerVideoWindows}
      />
    </div>
  {:else}
    <p class="mt-4 text-sm text-slate-600">再生可能なエピソードがありません。</p>
  {/if}
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">マージ</h2>
    <button class="btn-ghost" type="button" onclick={refetchCandidates}>候補を更新</button>
  </div>
  <p class="mt-2 text-sm text-slate-600">同一プロジェクトの他データセットと統合できます。</p>
  {#if isArchived}
    <p class="mt-4 text-sm text-rose-600">アーカイブ中のデータセットはマージできません。</p>
  {:else if $candidatesQuery.isLoading}
    <p class="mt-4 text-sm text-slate-600">候補を読み込み中...</p>
  {:else if candidates.length}
    <div class="mt-4 grid gap-2">
      {#each candidates as candidate}
        <label class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-2 text-sm text-slate-600">
          <div class="flex items-center gap-3">
            <input
              type="checkbox"
              class="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
              bind:group={mergeSelection}
              value={candidate.id}
            />
            <span class="font-semibold text-slate-800">{candidate.id}</span>
          </div>
          <span class="text-xs text-slate-500">{formatBytes(candidate.size_bytes ?? 0)}</span>
        </label>
      {/each}
    </div>
    <div class="mt-4">
      <label class="label" for="merge-name-detail">新しいデータセット名</label>
      <input
        class="input mt-2"
        id="merge-name-detail"
        placeholder={mergeDefaultName || 'dataset_name'}
        bind:value={mergeName}
      />
    </div>
    <div class="mt-4">
      <button
        class={`btn-primary ${canMerge ? '' : 'opacity-50 cursor-not-allowed'}`}
        type="button"
        disabled={!canMerge}
        onclick={handleMerge}
      >
        マージ実行
      </button>
    </div>
  {:else}
    <p class="mt-4 text-sm text-slate-600">マージ可能なデータセットがありません。</p>
  {/if}
</section>

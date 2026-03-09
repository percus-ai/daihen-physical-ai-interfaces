<script lang="ts">
  import { Button, DropdownMenu } from 'bits-ui';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import { api, type BulkActionResponse } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';
  import { sessionViewer } from '$lib/viewer/sessionViewerStore';
  import { formatBytes, formatDate } from '$lib/format';
  import DatasetMergeProgressModal from '$lib/components/storage/DatasetMergeProgressModal.svelte';
  import StorageArchiveConfirmDialog from '$lib/components/storage/StorageArchiveConfirmDialog.svelte';

  type DatasetSummary = {
    id: string;
    name?: string;
    owner_user_id?: string;
    owner_email?: string;
    owner_name?: string;
    profile_name?: string;
    size_bytes?: number;
    episode_count?: number;
    status?: string;
    created_at?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: qk.storage.datasetsManage(),
    queryFn: () => api.storage.datasets()
  });

  const queryClient = useQueryClient();

  let selectedIds = $state<string[]>([]);
  let mergeName = $state('');
  let actionMessage = $state('');
  let actionError = $state('');
  let actionLoading = $state(false);

  let mergeModalOpen = $state(false);
  let mergeJobId = $state('');
  let lastMergePayload = $state<null | { dataset_name: string; source_dataset_ids: string[] }>(null);
  let archiveDialogOpen = $state(false);
  let archiveTarget = $state<DatasetSummary | null>(null);
  let archivePendingId = $state('');
  let archiveDialogError = $state('');
  let datasetSortKey = $state<'created_at' | 'name' | 'episode_count' | 'size_bytes'>('created_at');
  let datasetSortOrder = $state<'desc' | 'asc'>('desc');
  let datasetOwnerFilter = $state('all');
  let datasetSearch = $state('');

  const datasets = $derived($datasetsQuery.data?.datasets ?? []);
  const normalizeText = (value?: string | null) => String(value ?? '').trim().toLowerCase();
  const compareText = (left?: string | null, right?: string | null) =>
    normalizeText(left).localeCompare(normalizeText(right), 'ja');
  const compareNumber = (left?: number | null, right?: number | null) => Number(left ?? 0) - Number(right ?? 0);
  const compareDate = (left?: string | null, right?: string | null) =>
    (new Date(left ?? 0).getTime() || 0) - (new Date(right ?? 0).getTime() || 0);
  const creatorLabel = (value?: string | null) => {
    const normalized = String(value ?? '').trim();
    if (!normalized) return '-';
    if (normalized.length <= 24) return normalized;
    return `${normalized.slice(0, 20)}...`;
  };
  const ownerLabel = (dataset: DatasetSummary) =>
    creatorLabel(dataset.owner_name ?? dataset.owner_email ?? dataset.owner_user_id);
  const selectedDatasets = $derived(datasets.filter((dataset) => selectedIds.includes(dataset.id)));
  const profileNames = $derived(
    Array.from(
      new Set(selectedDatasets.map((dataset) => dataset.profile_name).filter(Boolean))
    )
  );
  const profileMismatch = $derived(profileNames.length > 1);
  const profileName = $derived(profileNames.length === 1 ? profileNames[0] : '');
  const mergeDefaultName = $derived(
    selectedDatasets.length
      ? `${selectedDatasets[0].name ?? selectedDatasets[0].id}_merged`
      : ''
  );
  const canMerge = $derived(selectedIds.length >= 2 && !profileMismatch && !actionLoading);
  const canArchive = $derived(selectedIds.length > 0 && !actionLoading);
  const canReupload = $derived(selectedIds.length > 0 && !actionLoading);
  const datasetOwnerOptions = $derived.by(() => {
    const options = new Map<string, string>();
    for (const dataset of datasets) {
      const ownerId = String(dataset.owner_user_id ?? '').trim();
      if (!ownerId) continue;
      options.set(ownerId, ownerLabel(dataset));
    }
    return Array.from(options, ([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label, 'ja'));
  });

  const refetchDatasets = async () => {
    await queryClient.invalidateQueries({ queryKey: qk.storage.datasetsManage() });
    await $datasetsQuery?.refetch?.();
  };
  const removeArchivedDatasetsFromCache = (response: BulkActionResponse) => {
    const archivedIds = new Set(
      response.results.filter((result) => result.status === 'succeeded').map((result) => result.id)
    );
    if (archivedIds.size === 0) return;
    queryClient.setQueryData(
      qk.storage.datasetsManage(),
      (current: DatasetListResponse | undefined) => {
        if (!current) return current;
        const nextDatasets = (current.datasets ?? []).filter((dataset) => !archivedIds.has(dataset.id));
        return {
          ...current,
          datasets: nextDatasets,
          total: nextDatasets.length
        };
      }
    );
  };
  const clearSelection = () => {
    selectedIds = [];
  };
  const applyBulkResponseMessage = (response: BulkActionResponse, successLabel: string) => {
    const parts = [`成功 ${response.succeeded}`, `失敗 ${response.failed}`];
    if (response.skipped > 0) {
      parts.push(`スキップ ${response.skipped}`);
    }
    actionMessage = `${successLabel}: ${parts.join(' / ')}`;
    const failedMessages = response.results
      .filter((result) => result.status === 'failed')
      .slice(0, 3)
      .map((result) => `${result.id}: ${result.message}`);
    actionError = failedMessages.join(' / ');
  };

  const displayDatasetLabel = (dataset: DatasetSummary) => dataset.name ?? dataset.id;
  const displayedDatasets = $derived.by(() => {
    const query = normalizeText(datasetSearch);
    const sorted = datasets
      .filter((dataset) => {
        if (datasetOwnerFilter !== 'all' && String(dataset.owner_user_id ?? '') !== datasetOwnerFilter) return false;
        if (!query) return true;
        return [dataset.id, dataset.name, dataset.profile_name, dataset.owner_name, dataset.owner_email].some((value) =>
          normalizeText(value).includes(query)
        );
      })
      .slice();

    sorted.sort((a, b) => {
      const direction = datasetSortOrder === 'asc' ? 1 : -1;
      switch (datasetSortKey) {
        case 'name':
          return compareText(displayDatasetLabel(a), displayDatasetLabel(b)) * direction;
        case 'episode_count':
          return compareNumber(a.episode_count, b.episode_count) * direction;
        case 'size_bytes':
          return compareNumber(a.size_bytes, b.size_bytes) * direction;
        case 'created_at':
        default:
          return compareDate(a.created_at, b.created_at) * direction;
      }
    });
    return sorted;
  });
  const allDisplayedDatasetIds = $derived(displayedDatasets.map((dataset) => dataset.id));
  const allDisplayedDatasetsSelected = $derived(
    allDisplayedDatasetIds.length > 0 && allDisplayedDatasetIds.every((id) => selectedIds.includes(id))
  );
  const toggleSelectAllDisplayedDatasets = () => {
    if (allDisplayedDatasetsSelected) {
      selectedIds = selectedIds.filter((id) => !allDisplayedDatasetIds.includes(id));
      return;
    }
    selectedIds = Array.from(new Set([...selectedIds, ...allDisplayedDatasetIds]));
  };

  const openViewer = (datasetId: string) => {
    sessionViewer.open({ datasetId });
  };
  const isArchivePending = (datasetId: string) => archivePendingId === datasetId;
  const openArchiveDialog = (dataset: DatasetSummary) => {
    if (actionLoading || archivePendingId) return;
    archiveDialogError = '';
    archiveTarget = dataset;
    archiveDialogOpen = true;
  };

  const startMergeJob = async (payload: { dataset_name: string; source_dataset_ids: string[] }) => {
    const accepted = await api.storage.startDatasetMergeJob(payload);
    mergeJobId = accepted.job_id;
    mergeModalOpen = true;
  };

  const handleMergeCompleted = async (datasetId: string) => {
    actionMessage = `マージ完了: ${datasetId}`;
    actionError = '';
    mergeName = '';
    selectedIds = [];
    await refetchDatasets();
  };

  async function handleMerge() {
    actionMessage = '';
    actionError = '';

    if (selectedIds.length < 2) {
      actionError = '2件以上のデータセットを選択してください。';
      return;
    }
    if (profileMismatch || !profileName) {
      actionError = '同一プロファイルのデータセットのみマージできます。';
      return;
    }

    const datasetName = mergeName.trim() || mergeDefaultName;
    if (!datasetName) {
      actionError = '新しいデータセット名を入力してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件のデータセットを ${datasetName} にマージしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    const sourceIds = [...selectedIds];

    try {
      const payload = {
        dataset_name: datasetName,
        source_dataset_ids: sourceIds
      };
      lastMergePayload = payload;
      await startMergeJob(payload);
      actionMessage = 'マージを開始しました。進捗を表示します。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'マージに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleArchiveSelected() {
    actionMessage = '';
    actionError = '';

    if (!selectedIds.length) {
      actionError = 'アーカイブ対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件をアーカイブしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    const ids = [...selectedIds];

    try {
      const response = await api.storage.bulkArchiveDatasets(ids);
      applyBulkResponseMessage(response, 'アーカイブを実行しました');
      removeArchivedDatasetsFromCache(response);
      if (response.failed === 0) {
        clearSelection();
      }
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleReuploadSelected() {
    actionMessage = '';
    actionError = '';

    if (!selectedIds.length) {
      actionError = '再アップロード対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件をR2へ再アップロードしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    const ids = [...selectedIds];

    try {
      const response = await api.storage.bulkReuploadDatasets(ids);
      applyBulkResponseMessage(response, '再アップロードを実行しました');
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : '再アップロードに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleArchiveTarget() {
    actionMessage = '';
    actionError = '';
    archiveDialogError = '';

    const target = archiveTarget;
    if (!target?.id || actionLoading || archivePendingId) return;

    archivePendingId = target.id;
    try {
      await api.storage.archiveDataset(target.id);
      selectedIds = selectedIds.filter((id) => id !== target.id);
      actionMessage = `${displayDatasetLabel(target)} をアーカイブしました。`;
      archiveDialogOpen = false;
      archiveTarget = null;
      await queryClient.invalidateQueries({ queryKey: qk.storage.archiveManage() });
      await refetchDatasets();
    } catch (err) {
      archiveDialogError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
      actionError = archiveDialogError;
    } finally {
      archivePendingId = '';
    }
  }

  $effect(() => {
    if (archiveDialogOpen || archivePendingId) return;
    archiveTarget = null;
    archiveDialogError = '';
  });
</script>

<DatasetMergeProgressModal
  bind:open={mergeModalOpen}
  jobId={mergeJobId}
  onCompleted={handleMergeCompleted}
  onRetry={async () => {
    if (!lastMergePayload) return;
    actionError = '';
    await startMergeJob(lastMergePayload);
  }}
/>

<StorageArchiveConfirmDialog
  bind:open={archiveDialogOpen}
  itemKind="dataset"
  itemLabel={archiveTarget ? displayDatasetLabel(archiveTarget) : ''}
  pending={Boolean(archivePendingId)}
  errorMessage={archiveDialogError}
  onConfirm={handleArchiveTarget}
/>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データセット管理</h1>
      <p class="mt-2 text-sm text-slate-600">アクティブなデータセットを一覧で確認できます。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">戻る</Button.Root>
      <button class="btn-ghost" type="button" onclick={refetchDatasets}>更新</button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">データセット一覧</h2>
    <p class="text-xs text-slate-500">選択して一括操作が可能です。</p>
  </div>
  <div class="mt-4 grid gap-3 md:grid-cols-4">
    <label class="block">
      <span class="label">検索</span>
      <input class="input mt-2" type="text" bind:value={datasetSearch} placeholder="dataset / profile / user" />
    </label>
    <label class="block">
      <span class="label">作成者</span>
      <select class="input mt-2" bind:value={datasetOwnerFilter}>
        <option value="all">全員</option>
        {#each datasetOwnerOptions as owner}
          <option value={owner.id}>{owner.label}</option>
        {/each}
      </select>
    </label>
    <label class="block">
      <span class="label">並び替え</span>
      <select class="input mt-2" bind:value={datasetSortKey}>
        <option value="created_at">作成日時</option>
        <option value="name">名前</option>
        <option value="episode_count">エピソード数</option>
        <option value="size_bytes">サイズ</option>
      </select>
    </label>
    <label class="block">
      <span class="label">順序</span>
      <select class="input mt-2" bind:value={datasetSortOrder}>
        <option value="desc">降順</option>
        <option value="asc">昇順</option>
      </select>
    </label>
  </div>
  {#if selectedIds.length > 0}
    <div class="mt-4 rounded-2xl border border-slate-200/80 bg-slate-50/90 p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-slate-900">選択中: {selectedIds.length} 件</p>
          {#if profileMismatch}
            <p class="mt-1 text-xs text-rose-500">マージは同一プロファイルのデータセットのみ実行できます。</p>
          {:else if profileName}
            <p class="mt-1 text-xs text-slate-500">merge profile: {profileName}</p>
          {/if}
        </div>
        <button class="btn-ghost" type="button" onclick={clearSelection}>選択解除</button>
      </div>
      <div class="mt-4 flex flex-wrap items-end gap-3">
        <label class="min-w-[220px] flex-1">
          <span class="label">マージ先データセット名</span>
          <input
            class="input mt-2"
            placeholder={mergeDefaultName || 'dataset_name'}
            bind:value={mergeName}
          />
        </label>
        <button
          class={`btn-primary ${canMerge ? '' : 'opacity-50 cursor-not-allowed'}`}
          type="button"
          disabled={!canMerge}
          onclick={handleMerge}
        >
          マージ
        </button>
        <button
          class={`btn-primary ${canReupload ? '' : 'opacity-50 cursor-not-allowed'}`}
          type="button"
          disabled={!canReupload}
          onclick={handleReuploadSelected}
        >
          再アップロード
        </button>
        <button
          class={`btn-ghost ${canArchive ? '' : 'opacity-50 cursor-not-allowed'}`}
          type="button"
          disabled={!canArchive}
          onclick={handleArchiveSelected}
        >
          アーカイブ
        </button>
      </div>
    </div>
  {/if}
  {#if actionMessage}
    <p class="mt-3 text-sm text-emerald-600">{actionMessage}</p>
  {/if}
  {#if actionError}
    <p class="mt-2 text-sm text-rose-600">{actionError}</p>
  {/if}
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="w-12 pb-3 align-middle">
            <div class="flex justify-center">
              <input
                type="checkbox"
                class="block h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                checked={allDisplayedDatasetsSelected}
                aria-label="表示中のデータセットを全選択"
                onchange={toggleSelectAllDisplayedDatasets}
              />
            </div>
          </th>
          <th class="pb-3">ID</th>
          <th class="pb-3">作成者</th>
          <th class="pb-3">プロファイル</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">エピソード</th>
          <th class="pb-3">作成日時</th>
          <th class="pb-3 text-right">操作</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $datasetsQuery.isLoading}
          <tr><td class="py-3" colspan="8">読み込み中...</td></tr>
        {:else if displayedDatasets.length}
          {#each displayedDatasets as dataset}
            <tr class="border-t border-slate-200/60">
              <td class="w-12 py-3 align-middle">
                <div class="flex justify-center">
                  <input
                    type="checkbox"
                    class="block h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                    bind:group={selectedIds}
                    value={dataset.id}
                  />
                </div>
              </td>
              <td class="py-3 font-semibold text-slate-800">
                <span class="block max-w-[25ch] truncate" title={dataset.id}>
                  {displayDatasetLabel(dataset)}
                </span>
              </td>
              <td class="py-3">{ownerLabel(dataset)}</td>
              <td class="py-3">{dataset.profile_name ?? '-'}</td>
              <td class="py-3">{formatBytes(dataset.size_bytes ?? 0)}</td>
              <td class="py-3">{dataset.episode_count ?? 0}</td>
              <td class="py-3">{formatDate(dataset.created_at)}</td>
              <td class="py-3 text-right">
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger
                    class="btn-ghost ml-auto h-8 w-8 p-0 text-slate-600"
                    aria-label="操作メニュー"
                    title="アクション"
                  >
                    <DotsThree size={18} weight="bold" />
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Portal>
                    <DropdownMenu.Content
                      class="z-50 min-w-[180px] rounded-xl border border-slate-200/80 bg-white/95 p-2 text-xs text-slate-700 shadow-lg backdrop-blur"
                      sideOffset={6}
                      align="end"
                      preventScroll={false}
                    >
                      <DropdownMenu.Item
                        class="flex items-center rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                        onSelect={() => openViewer(dataset.id)}
                      >
                        ビューアで開く
                      </DropdownMenu.Item>
                      <DropdownMenu.Item
                        class="flex items-center rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                        onSelect={() => {
                          window.location.href = `/storage/datasets/${dataset.id}`;
                        }}
                      >
                        詳細を開く
                      </DropdownMenu.Item>
                      <DropdownMenu.Item
                        class="flex items-center rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                        disabled={actionLoading || Boolean(archivePendingId)}
                        onSelect={() => openArchiveDialog(dataset)}
                      >
                        {#if isArchivePending(dataset.id)}
                          アーカイブ中...
                        {:else}
                          アーカイブ
                        {/if}
                      </DropdownMenu.Item>
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="8">条件に合うデータセットがありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</section>

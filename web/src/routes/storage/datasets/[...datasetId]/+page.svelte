<script lang="ts">
  import { Button } from 'bits-ui';
  import { toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import toast from 'svelte-french-toast';
  import { api } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';
  import { sessionViewer } from '$lib/viewer/sessionViewerStore';
  import StorageRenameDialog from '$lib/components/storage/StorageRenameDialog.svelte';
  import { formatBytes, formatDate } from '$lib/format';

  type DatasetSourceInfo = {
    dataset_id: string;
    name?: string;
    content_hash?: string | null;
    task_detail?: string | null;
  };

  type DatasetInfo = {
    id: string;
    name?: string;
    profile_name?: string;
    dataset_type?: string;
    source_datasets?: DatasetSourceInfo[];
    status?: string;
    size_bytes?: number;
    episode_count?: number;
    is_local?: boolean;
    created_at?: string;
    updated_at?: string;
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
  const isArchived = $derived(dataset?.status === 'archived');
  const sourceDatasets = $derived(dataset?.source_datasets ?? []);
  let actionMessage = $state('');
  let actionError = $state('');
  let actionLoading = $state(false);
  let renameDialogOpen = $state(false);
  let renamePending = $state(false);
  let renameError = $state('');

  const displayName = $derived(dataset?.name ?? datasetId);

  const openViewerModal = () => {
    if (!datasetId) return;
    sessionViewer.open({ datasetId });
  };

  const refetchDataset = async () => {
    if (!datasetId) return;
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.storage.dataset(datasetId) }),
      queryClient.invalidateQueries({ queryKey: qk.storage.datasetsPrefix() })
    ]);
  };

  const resetRenameDialog = () => {
    renameDialogOpen = false;
    renameError = '';
  };

  const handleRename = async (nextName: string) => {
    if (!datasetId) return;
    renameError = '';
    renamePending = true;

    try {
      await api.storage.renameDataset(datasetId, { name: nextName });
      resetRenameDialog();
      toast.success('名前を更新しました。');
      await queryClient.invalidateQueries({ queryKey: qk.storage.datasetsPrefix() });
      await refetchDataset();
    } catch (err) {
      renameError = err instanceof Error ? err.message : '名前変更に失敗しました。';
    } finally {
      renamePending = false;
    }
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
    const confirmed = confirm(`${datasetId} をR2へ再送信しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      const result = await api.storage.reuploadDataset(datasetId) as { message?: string };
      await refetchDataset();
      actionMessage = result.message ?? '再送信を完了しました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : '再送信に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

</script>

<StorageRenameDialog
  bind:open={renameDialogOpen}
  itemKind="dataset"
  currentName={displayName}
  pending={renamePending}
  errorMessage={renameError}
  onConfirm={handleRename}
/>

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
    {#if dataset}
      <button
        class="btn-ghost"
        type="button"
        disabled={actionLoading || renamePending}
        onclick={() => {
          renameError = '';
          renameDialogOpen = true;
        }}
      >
        名前変更
      </button>
    {/if}
  </div>
  {#if $datasetQuery.isLoading}
    <p class="mt-4 text-sm text-slate-600">読み込み中...</p>
  {:else if dataset}
    <div class="mt-4 grid gap-4 text-sm text-slate-600 lg:grid-cols-2">
      <div>
        <p class="label">名前</p>
        <p class="text-base font-semibold text-slate-800">{displayName}</p>
      </div>
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
      <button
        class="btn-ghost"
        type="button"
        disabled={actionLoading}
        onclick={openViewerModal}
      >
        ビューアで開く
      </button>
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
          再送信
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
      <Button.Root class="btn-ghost" href="/storage/datasets">データセット管理</Button.Root>
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

{#if sourceDatasets.length > 0}
  <section class="card p-6">
    <div class="flex items-center justify-between gap-3">
      <div>
        <h2 class="text-xl font-semibold text-slate-900">マージ元</h2>
        <p class="mt-2 text-sm text-slate-600">このデータセットを構成している元データセットです。</p>
      </div>
      <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
        {sourceDatasets.length} datasets
      </div>
    </div>
    <div class="mt-4 grid gap-3 lg:grid-cols-2">
      {#each sourceDatasets as source, index (source.dataset_id)}
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                Source {index + 1}
              </p>
              <a
                class="mt-2 block truncate text-sm font-semibold text-slate-900 underline decoration-slate-300 underline-offset-2"
                href={`/storage/datasets/${encodeURIComponent(source.dataset_id)}`}
              >
                {source.name ?? source.dataset_id}
              </a>
            </div>
            <span class="rounded-full bg-white px-2 py-1 text-[11px] font-medium text-slate-500">
              linked
            </span>
          </div>
          <p class="mt-2 break-all text-xs text-slate-500">{source.dataset_id}</p>
          {#if source.task_detail}
            <div class="mt-3 rounded-xl border border-slate-200 bg-white px-3 py-2">
              <p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Task</p>
              <p class="mt-1 text-sm text-slate-700">{source.task_detail}</p>
            </div>
          {/if}
          {#if source.content_hash}
            <p class="mt-3 text-xs text-slate-500">hash: {source.content_hash}</p>
          {/if}
        </div>
      {/each}
    </div>
  </section>
{/if}

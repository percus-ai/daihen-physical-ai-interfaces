<script lang="ts">
  import { Button } from 'bits-ui';
  import { toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import toast from 'svelte-french-toast';
  import { api, type StorageDatasetInfo } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';
  import { sessionViewer } from '$lib/viewer/sessionViewerStore';
  import StorageRenameDialog from '$lib/components/storage/StorageRenameDialog.svelte';
  import StorageDatasetOverviewCard from '$lib/components/storage/StorageDatasetOverviewCard.svelte';
  import StorageDatasetDetailInfoCard from '$lib/components/storage/StorageDatasetDetailInfoCard.svelte';
  import StorageDatasetLineageTimeline from '$lib/components/storage/StorageDatasetLineageTimeline.svelte';

  const datasetId = $derived(page.params.datasetId ?? '');
  const queryClient = useQueryClient();

  const datasetQuery = createQuery<StorageDatasetInfo>(
    toStore(() => ({
      queryKey: qk.storage.dataset(datasetId),
      queryFn: () => api.storage.dataset(datasetId),
      enabled: Boolean(datasetId)
    }))
  );

  const dataset = $derived($datasetQuery.data);
  const isArchived = $derived(dataset?.status === 'archived');
  const sourceDatasets = $derived(dataset?.source_datasets ?? []);
  const displayName = $derived(dataset?.name ?? datasetId);
  const taskDetail = $derived(String(dataset?.task_detail ?? '').trim());

  let actionMessage = $state('');
  let actionError = $state('');
  let actionLoading = $state(false);
  let syncPending = $state(false);
  let renameDialogOpen = $state(false);
  let renamePending = $state(false);
  let renameError = $state('');

  const clearMessages = () => {
    actionMessage = '';
    actionError = '';
  };

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
      await refetchDataset();
    } catch (err) {
      renameError = err instanceof Error ? err.message : '名前変更に失敗しました。';
    } finally {
      renamePending = false;
    }
  };

  async function handleArchive() {
    clearMessages();
    if (!datasetId) return;
    const confirmed = confirm(`${displayName} をアーカイブしますか？`);
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
    clearMessages();
    if (!datasetId) return;
    const confirmed = confirm(`${displayName} を復元しますか？`);
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
    clearMessages();
    if (!datasetId) return;
    const confirmed = confirm(`${displayName} をR2へ再送信しますか？`);
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

  async function handleSync() {
    clearMessages();
    if (!datasetId) return;
    const confirmed = confirm(`${displayName} の同期を開始しますか？`);
    if (!confirmed) return;

    syncPending = true;
    try {
      const accepted = await api.storage.syncDataset(datasetId);
      actionMessage =
        accepted.message ?? '同期ジョブを登録しました。完了後に更新すると詳細情報が表示されます。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : '同期の開始に失敗しました。';
    } finally {
      syncPending = false;
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
  <div class="flex flex-wrap items-end justify-between gap-4">
    <div>
      <p class="section-title">Storage</p>
      <h1 class="mt-2 text-3xl font-semibold text-slate-950">データセット詳細</h1>
      <p class="mt-2 text-sm text-slate-600">データセットの来歴と収録情報をひとつの画面で確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage/datasets">一覧へ戻る</Button.Root>
      <button class="btn-ghost" type="button" onclick={refetchDataset}>更新</button>
    </div>
  </div>
</section>

{#if $datasetQuery.isLoading}
  <section class="card p-6">
    <p class="text-sm text-slate-600">読み込み中...</p>
  </section>
{:else if dataset}
  <StorageDatasetOverviewCard {dataset} />

  <section class="card p-6">
    <div class="nested-block-header">
      <div>
        <p class="section-title">Task</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-950">タスク詳細</h2>
      </div>
    </div>

    {#if taskDetail}
      <div class="nested-block-pane px-5 py-5">
        <p class="whitespace-pre-wrap text-sm leading-8 text-slate-700">{taskDetail}</p>
      </div>
    {:else}
      <div class="rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 px-5 py-5 text-sm text-slate-500">
        タスク詳細は登録されていません。
      </div>
    {/if}
  </section>

  <StorageDatasetDetailInfoCard {dataset} />

  {#if sourceDatasets.length > 0}
    <StorageDatasetLineageTimeline sources={sourceDatasets} />
  {/if}

  <section class="card p-6">
    <div class="nested-block-header">
      <div>
        <p class="section-title">Actions</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-950">関連操作</h2>
        <p class="mt-2 text-sm text-slate-600">操作導線はここにまとめ、上部の情報読解を邪魔しない構成にしています。</p>
      </div>
    </div>

    <div class="mt-4 flex flex-wrap gap-2">
      <button
        class="btn-ghost"
        type="button"
        disabled={actionLoading || renamePending || syncPending}
        onclick={() => {
          renameError = '';
          renameDialogOpen = true;
        }}
      >
        名前変更
      </button>

      <button
        class="btn-ghost"
        type="button"
        disabled={actionLoading || syncPending}
        onclick={openViewerModal}
      >
        ビューアで開く
      </button>

      {#if !dataset.is_local}
        <button
          class="btn-ghost"
          type="button"
          disabled={actionLoading || syncPending}
          onclick={handleSync}
        >
          同期を開始
        </button>
      {/if}

      {#if isArchived}
        <button
          class="btn-primary"
          type="button"
          disabled={actionLoading || syncPending}
          onclick={handleRestore}
        >
          復元
        </button>
      {:else}
        <button
          class="btn-primary"
          type="button"
          disabled={actionLoading || syncPending}
          onclick={handleReupload}
        >
          再送信
        </button>
        <button
          class="btn-ghost"
          type="button"
          disabled={actionLoading || syncPending}
          onclick={handleArchive}
        >
          アーカイブ
        </button>
      {/if}
    </div>

    {#if actionMessage}
      <p class="mt-4 text-sm text-emerald-600">{actionMessage}</p>
    {/if}
    {#if actionError}
      <p class="mt-2 text-sm text-rose-600">{actionError}</p>
    {/if}
  </section>
{:else}
  <section class="card p-6">
    <p class="text-sm text-slate-600">データセットが見つかりません。</p>
  </section>
{/if}

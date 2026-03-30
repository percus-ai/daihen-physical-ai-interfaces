<script lang="ts">
  import { Button } from 'bits-ui';
  import { toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import toast from 'svelte-french-toast';
  import { api, type StorageModelInfo } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';
  import { formatBytes } from '$lib/format';
  import StorageRenameDialog from '$lib/components/storage/StorageRenameDialog.svelte';
  import StorageModelOverviewCard from '$lib/components/storage/StorageModelOverviewCard.svelte';

  const modelId = $derived(page.params.modelId ?? '');
  const queryClient = useQueryClient();

  const modelQuery = createQuery<StorageModelInfo>(
    toStore(() => ({
      queryKey: qk.storage.model(modelId),
      queryFn: () => api.storage.model(modelId),
      enabled: Boolean(modelId)
    }))
  );

  const model = $derived($modelQuery.data);
  const isArchived = $derived(model?.status === 'archived');
  const displayName = $derived(model?.name ?? modelId);
  const linkedDataset = $derived(model?.dataset ?? null);

  let actionMessage = $state('');
  let actionError = $state('');
  let actionLoading = $state(false);
  let renameDialogOpen = $state(false);
  let renamePending = $state(false);
  let renameError = $state('');

  const clearMessages = () => {
    actionMessage = '';
    actionError = '';
  };

  const refetchModel = async () => {
    if (!modelId) return;
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.storage.model(modelId) }),
      queryClient.invalidateQueries({ queryKey: qk.storage.modelsPrefix() })
    ]);
  };

  const resetRenameDialog = () => {
    renameDialogOpen = false;
    renameError = '';
  };

  const handleRename = async (nextName: string) => {
    if (!modelId) return;
    renameError = '';
    renamePending = true;

    try {
      await api.storage.renameModel(modelId, { name: nextName });
      resetRenameDialog();
      toast.success('名前を更新しました。');
      await refetchModel();
    } catch (err) {
      renameError = err instanceof Error ? err.message : '名前変更に失敗しました。';
    } finally {
      renamePending = false;
    }
  };

  async function handleArchive() {
    clearMessages();
    if (!modelId) return;
    const confirmed = confirm(`${displayName} をアーカイブしますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.archiveModel(modelId);
      await refetchModel();
      actionMessage = 'アーカイブしました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleRestore() {
    clearMessages();
    if (!modelId) return;
    const confirmed = confirm(`${displayName} を復元しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    try {
      await api.storage.restoreModel(modelId);
      await refetchModel();
      actionMessage = '復元しました。';
    } catch (err) {
      actionError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }
</script>

<StorageRenameDialog
  bind:open={renameDialogOpen}
  itemKind="model"
  currentName={displayName}
  pending={renamePending}
  errorMessage={renameError}
  onConfirm={handleRename}
/>

<section class="card-strong p-8">
  <div class="flex flex-wrap items-end justify-between gap-4">
    <div>
      <p class="section-title">Storage</p>
      <h1 class="mt-2 text-3xl font-semibold text-slate-950">モデル詳細</h1>
      <p class="mt-2 text-sm text-slate-600">モデルの同定情報と学習条件を整理して確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage/models">一覧へ戻る</Button.Root>
      <button class="btn-ghost" type="button" onclick={refetchModel}>更新</button>
    </div>
  </div>
</section>

{#if $modelQuery.isLoading}
  <section class="card p-6">
    <p class="text-sm text-slate-600">読み込み中...</p>
  </section>
{:else if model}
  <StorageModelOverviewCard {model} />

  <section class="card p-6">
    <div class="nested-block-header">
      <div>
        <p class="section-title">Dataset</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-950">学習データセット</h2>
      </div>
    </div>

    {#if linkedDataset}
      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div class="nested-block-pane px-4 py-4 md:col-span-2">
          <p class="label">データセット</p>
          <a
            class="mt-2 block break-all text-sm font-semibold text-slate-900 underline decoration-slate-300 underline-offset-2"
            href={`/storage/datasets/${encodeURIComponent(linkedDataset.id)}`}
          >
            {linkedDataset.name}
          </a>
          <p class="mt-1 break-all font-mono text-xs text-slate-500">{linkedDataset.id}</p>
        </div>
        <div class="nested-block-pane px-4 py-4">
          <p class="label">状態</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">
            {linkedDataset.status === 'archived' ? 'アーカイブ済み' : linkedDataset.status ?? '-'}
          </p>
        </div>
        <div class="nested-block-pane px-4 py-4">
          <p class="label">同期状態</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">
            {linkedDataset.is_local ? '同期済み' : '未同期'}
          </p>
        </div>
        <div class="nested-block-pane px-4 py-4">
          <p class="label">プロファイル</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{linkedDataset.profile_name ?? '-'}</p>
        </div>
        <div class="nested-block-pane px-4 py-4">
          <p class="label">エピソード数</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">{linkedDataset.episode_count ?? '-'}</p>
        </div>
        <div class="nested-block-pane px-4 py-4">
          <p class="label">サイズ</p>
          <p class="mt-2 text-sm font-semibold text-slate-900">
            {linkedDataset.size_bytes !== null && linkedDataset.size_bytes !== undefined
              ? formatBytes(linkedDataset.size_bytes)
              : '-'}
          </p>
        </div>
      </div>
    {:else if model.dataset_id}
      <div class="rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 px-5 py-5 text-sm text-slate-500">
        学習データセットの詳細を取得できませんでした。
      </div>
    {:else}
      <div class="rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 px-5 py-5 text-sm text-slate-500">
        学習データセットは紐づいていません。
      </div>
    {/if}
  </section>

  <section class="card p-6">
    <div class="nested-block-header">
      <div>
        <p class="section-title">Training</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-950">学習情報</h2>
      </div>
    </div>

    <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <div class="nested-block-pane px-4 py-4">
        <p class="label">ポリシー種別</p>
        <p class="mt-2 text-sm font-semibold text-slate-900">{model.policy_type ?? '-'}</p>
      </div>
      <div class="nested-block-pane px-4 py-4">
        <p class="label">学習ステップ</p>
        <p class="mt-2 text-sm font-semibold text-slate-900">{model.training_steps ?? '-'}</p>
      </div>
      <div class="nested-block-pane px-4 py-4">
        <p class="label">バッチサイズ</p>
        <p class="mt-2 text-sm font-semibold text-slate-900">{model.batch_size ?? '-'}</p>
      </div>
    </div>
  </section>

  <section class="card p-6">
    <div class="nested-block-header">
      <div>
        <p class="section-title">Actions</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-950">関連操作</h2>
      </div>
    </div>

    <div class="mt-4 flex flex-wrap gap-2">
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

      {#if isArchived}
        <button
          class="btn-primary"
          type="button"
          disabled={actionLoading || renamePending}
          onclick={handleRestore}
        >
          復元
        </button>
      {:else}
        <button
          class="btn-ghost"
          type="button"
          disabled={actionLoading || renamePending}
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
    <p class="text-sm text-slate-600">モデルが見つかりません。</p>
  </section>
{/if}

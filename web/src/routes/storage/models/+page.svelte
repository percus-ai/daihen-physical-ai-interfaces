<script lang="ts">
  import { browser } from '$app/environment';
  import { Button, DropdownMenu } from 'bits-ui';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import { api, type BulkActionResponse, type ModelSyncJobState, type ModelSyncJobStatus, type TabSessionSubscription } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';
  import { formatBytes, formatDate } from '$lib/format';
  import { registerTabRealtimeContributor, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';
  import ModelSyncProgressModal from '$lib/components/storage/ModelSyncProgressModal.svelte';
  import StorageArchiveConfirmDialog from '$lib/components/storage/StorageArchiveConfirmDialog.svelte';
  import { presentModelSyncStatus } from '$lib/storage/transferStatus';

  type ModelSummary = {
    id: string;
    name?: string;
    owner_user_id?: string;
    owner_email?: string;
    owner_name?: string;
    profile_name?: string;
    policy_type?: string;
    dataset_id?: string;
    size_bytes?: number;
    is_local?: boolean;
    created_at?: string;
  };

  type ModelListResponse = {
    models?: ModelSummary[];
    total?: number;
  };

  const modelsQuery = createQuery<ModelListResponse>({
    queryKey: qk.storage.models(),
    queryFn: () => api.storage.models()
  });
  const queryClient = useQueryClient();

  const models = $derived($modelsQuery.data?.models ?? []);
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
  const ownerLabel = (model: ModelSummary) =>
    creatorLabel(model.owner_name ?? model.owner_email ?? model.owner_user_id);

  const displayModelLabel = (model: ModelSummary) => model.name ?? model.id;
  const isActiveJobState = (state?: ModelSyncJobState) => state === 'queued' || state === 'running';
  const isTerminalJobState = (state?: ModelSyncJobState) =>
    state === 'completed' || state === 'failed' || state === 'cancelled';

  let syncAllPending = $state(false);
  let syncMessage = $state('');
  let syncError = $state('');
  let bulkMessage = $state('');
  let bulkError = $state('');
  let bulkPending = $state(false);
  let selectedIds = $state<string[]>([]);
  let modelSortKey = $state<'created_at' | 'name' | 'size_bytes' | 'policy_type'>('created_at');
  let modelSortOrder = $state<'desc' | 'asc'>('desc');
  let modelOwnerFilter = $state('all');
  let modelSearch = $state('');
  let jobsById = $state<Record<string, ModelSyncJobStatus>>({});
  let activeJobsByModelId = $state<Record<string, ModelSyncJobStatus>>({});
  let realtimeContributor: TabRealtimeContributorHandle | null = null;
  let modelSyncModalOpen = $state(false);
  let selectedJobId = $state('');
  let archiveDialogOpen = $state(false);
  let archiveTarget = $state<ModelSummary | null>(null);
  let archivePendingId = $state('');
  let archiveDialogError = $state('');

  const syncPending = $derived(syncAllPending);
  const modelOwnerOptions = $derived.by(() => {
    const options = new Map<string, string>();
    for (const model of models) {
      const ownerId = String(model.owner_user_id ?? '').trim();
      if (!ownerId) continue;
      options.set(ownerId, ownerLabel(model));
    }
    return Array.from(options, ([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label, 'ja'));
  });
  const displayedModels = $derived.by(() => {
    const query = normalizeText(modelSearch);
    const sorted = models
      .filter((model) => {
        if (modelOwnerFilter !== 'all' && String(model.owner_user_id ?? '') !== modelOwnerFilter) return false;
        if (!query) return true;
        return [
          model.id,
          model.name,
          model.profile_name,
          model.policy_type,
          model.dataset_id,
          model.owner_name,
          model.owner_email
        ].some((value) => normalizeText(value).includes(query));
      })
      .slice();

    sorted.sort((a, b) => {
      const direction = modelSortOrder === 'asc' ? 1 : -1;
      switch (modelSortKey) {
        case 'name':
          return compareText(displayModelLabel(a), displayModelLabel(b)) * direction;
        case 'size_bytes':
          return compareNumber(a.size_bytes, b.size_bytes) * direction;
        case 'policy_type':
          return compareText(a.policy_type, b.policy_type) * direction;
        case 'created_at':
        default:
          return compareDate(a.created_at, b.created_at) * direction;
      }
    });
    return sorted;
  });
  const allDisplayedModelIds = $derived(displayedModels.map((model) => model.id));
  const allDisplayedModelsSelected = $derived(
    allDisplayedModelIds.length > 0 && allDisplayedModelIds.every((id) => selectedIds.includes(id))
  );
  const toggleSelectAllDisplayedModels = () => {
    if (allDisplayedModelsSelected) {
      selectedIds = selectedIds.filter((id) => !allDisplayedModelIds.includes(id));
      return;
    }
    selectedIds = Array.from(new Set([...selectedIds, ...allDisplayedModelIds]));
  };
  const clearSelection = () => {
    selectedIds = [];
  };
  const applyBulkResponseMessage = (response: BulkActionResponse, label: string) => {
    const parts = [`成功 ${response.succeeded}`, `失敗 ${response.failed}`];
    if (response.skipped > 0) {
      parts.push(`スキップ ${response.skipped}`);
    }
    bulkMessage = `${label}: ${parts.join(' / ')}`;
    const failedMessages = response.results
      .filter((result) => result.status === 'failed')
      .slice(0, 3)
      .map((result) => `${result.id}: ${result.message}`);
    bulkError = failedMessages.join(' / ');
  };

  const activeJobOf = (modelId: string) => activeJobsByModelId[modelId] ?? null;
  const openModelSyncModal = (jobId: string) => {
    if (!jobId) return;
    selectedJobId = jobId;
    modelSyncModalOpen = true;
  };
  const isArchivePending = (modelId: string) => archivePendingId === modelId;
  const openArchiveDialog = (model: ModelSummary) => {
    if (bulkPending || syncAllPending || archivePendingId) return;
    archiveDialogError = '';
    archiveTarget = model;
    archiveDialogOpen = true;
  };

  const normalizeJob = (job: ModelSyncJobStatus): ModelSyncJobStatus => {
    const progress = Number(job.progress_percent ?? 0);
    const normalizedProgress = Number.isFinite(progress) ? Math.min(100, Math.max(0, progress)) : 0;
    return {
      ...job,
      progress_percent: normalizedProgress,
      detail: {
        files_done: Number(job.detail?.files_done ?? 0),
        total_files: Number(job.detail?.total_files ?? 0),
        transferred_bytes: Number(job.detail?.transferred_bytes ?? 0),
        total_bytes: Number(job.detail?.total_bytes ?? 0),
        current_file: job.detail?.current_file ?? null
      }
    };
  };

  const isNewerJobSnapshot = (next: ModelSyncJobStatus, prev: ModelSyncJobStatus | undefined) => {
    if (!prev) return true;
    const nextTs = Date.parse(next.updated_at ?? '');
    const prevTs = Date.parse(prev.updated_at ?? '');
    if (Number.isNaN(nextTs) || Number.isNaN(prevTs)) return true;
    return nextTs >= prevTs;
  };

  const applyJobSnapshot = (job: ModelSyncJobStatus) => {
    const normalized = normalizeJob(job);
    const previous = jobsById[normalized.job_id];
    if (!isNewerJobSnapshot(normalized, previous)) return;

    jobsById = {
      ...jobsById,
      [normalized.job_id]: normalized
    };

    if (isActiveJobState(normalized.state)) {
      activeJobsByModelId = {
        ...activeJobsByModelId,
        [normalized.model_id]: normalized
      };
      return;
    }

    const activeJob = activeJobsByModelId[normalized.model_id];
    if (activeJob?.job_id === normalized.job_id) {
      const next = { ...activeJobsByModelId };
      delete next[normalized.model_id];
      activeJobsByModelId = next;
    }
    if (isTerminalJobState(normalized.state)) {
      void refetchModels();
    }
  };

  const refetchModels = async () => {
    await $modelsQuery?.refetch?.();
  };

  const selectedModels = $derived(models.filter((model) => selectedIds.includes(model.id)));
  const syncTargets = $derived(selectedModels.filter((model) => !model.is_local));
  const canSyncSelected = $derived(syncTargets.length > 0 && !bulkPending && !syncAllPending);
  const canArchiveSelected = $derived(selectedIds.length > 0 && !bulkPending && !syncAllPending);

  const loadActiveJobs = async () => {
    const response = await api.storage.modelSyncJobs(false);
    const activeJobs = (response.jobs ?? []).map(normalizeJob);

    const nextJobsById = { ...jobsById };
    const nextActive: Record<string, ModelSyncJobStatus> = {};
    const activeJobIds = new Set<string>();

    const preferActiveJob = (next: ModelSyncJobStatus, prev: ModelSyncJobStatus | undefined) => {
      if (!prev) return true;
      if (prev.state === 'running' && next.state === 'queued') return false;
      if (next.state === 'running' && prev.state === 'queued') return true;
      return isNewerJobSnapshot(next, prev);
    };

    for (const job of activeJobs) {
      nextJobsById[job.job_id] = job;
      if (preferActiveJob(job, nextActive[job.model_id])) {
        nextActive[job.model_id] = job;
      }
      activeJobIds.add(job.job_id);
    }

    jobsById = nextJobsById;
    activeJobsByModelId = nextActive;
  };

  const startModelSync = async (modelId: string) => {
    const accepted = await api.storage.syncModel(modelId);
    const snapshot = await api.storage.modelSyncJob(accepted.job_id);
    applyJobSnapshot(snapshot);
    return snapshot;
  };

  const cancelModelSync = async (jobId: string) => {
    await api.storage.cancelModelSyncJob(jobId);
    const snapshot = await api.storage.modelSyncJob(jobId);
    applyJobSnapshot(snapshot);
    return snapshot;
  };

  const waitForTerminalJob = async (jobId: string) => {
    while (true) {
      const snapshot = await api.storage.modelSyncJob(jobId);
      applyJobSnapshot(snapshot);
      if (isTerminalJobState(snapshot.state)) {
        return snapshot;
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  };

  const handleSyncModel = async (model: ModelSummary) => {
    const modelId = model.id;
    if (!modelId) return;
    const activeJob = activeJobOf(modelId);

    syncMessage = '';
    syncError = '';
    bulkMessage = '';
    bulkError = '';

    if (activeJob) {
      try {
        const snapshot = await cancelModelSync(activeJob.job_id);
        syncMessage = snapshot.message ?? `${modelId} の中断を要求しました。`;
        openModelSyncModal(snapshot.job_id);
      } catch (err) {
        syncError = err instanceof Error ? err.message : 'モデル同期の中断に失敗しました。';
      }
      return;
    }

    if (model.is_local || syncAllPending || bulkPending) return;

    try {
      const started = await startModelSync(modelId);
      syncMessage = started.message ?? `${modelId} の同期を開始しました。`;
      openModelSyncModal(started.job_id);
    } catch (err) {
      syncError = err instanceof Error ? err.message : 'モデル同期の開始に失敗しました。';
    }
  };

  const handleSyncAll = async () => {
    if (syncPending || bulkPending) return;

    const targets = models.filter((model) => !model.is_local);
    if (!targets.length) {
      syncMessage = '未同期モデルはありません。';
      syncError = '';
      return;
    }

    syncAllPending = true;
    syncMessage = '';
    syncError = '';
    bulkMessage = '';
    bulkError = '';

    try {
      let enqueued = 0;
      let skipped = 0;
      let failed = 0;
      const failedIds: string[] = [];

      for (const model of targets) {
        try {
          await startModelSync(model.id);
          enqueued += 1;
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.includes('409') || message.includes('already in progress')) {
            skipped += 1;
            continue;
          }
          failed += 1;
          failedIds.push(model.id);
        }
      }

      const summary = [`登録 ${enqueued}`, `スキップ ${skipped}`, `失敗 ${failed}`].join(' / ');
      syncMessage = `全モデル同期ジョブを登録しました: ${summary}`;
      if (failedIds.length) {
        const preview = failedIds.slice(0, 5).join(', ');
        const suffix = failedIds.length > 5 ? ' ...' : '';
        syncError = `失敗モデル: ${preview}${suffix}`;
      }
      await loadActiveJobs();
    } catch (err) {
      syncError = err instanceof Error ? err.message : '全モデル同期に失敗しました。';
    } finally {
      syncAllPending = false;
    }
  };

  const handleRefresh = async () => {
    syncError = '';
    bulkError = '';
    await refetchModels();
    await loadActiveJobs();
  };

  const syncButtonLabel = (model: ModelSummary) => {
    const activeJob = activeJobOf(model.id);
    if (activeJob) return '中断';
    if (model.is_local) return '同期済';
    return '同期';
  };

  const isSyncButtonDisabled = (model: ModelSummary) => {
    const activeJob = activeJobOf(model.id);
    if (activeJob) return false;
    if (model.is_local) return true;
    if (syncAllPending) return true;
    if (bulkPending) return true;
    return false;
  };

  async function handleSyncSelected() {
    bulkMessage = '';
    bulkError = '';
    syncMessage = '';
    syncError = '';

    if (!syncTargets.length) {
      bulkError = '同期対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${syncTargets.length}件のモデル同期ジョブを登録しますか？`);
    if (!confirmed) return;

    bulkPending = true;
    const ids = syncTargets.map((model) => model.id);

    try {
      const response = await api.storage.bulkSyncModels(ids);
      applyBulkResponseMessage(response, '同期ジョブを登録しました');
      await loadActiveJobs();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : '同期ジョブ登録に失敗しました。';
    } finally {
      bulkPending = false;
    }
  }

  async function handleArchiveSelected() {
    bulkMessage = '';
    bulkError = '';
    syncMessage = '';
    syncError = '';

    if (!selectedIds.length) {
      bulkError = 'アーカイブ対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件をアーカイブしますか？（同期中は中断を要求します）`);
    if (!confirmed) return;

    bulkPending = true;
    const ids = [...selectedIds];

    try {
      const response = await api.storage.bulkArchiveModels(ids);
      applyBulkResponseMessage(response, '一括アーカイブを実行しました');
      if (response.failed === 0) {
        clearSelection();
      }
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      bulkPending = false;
    }
  }

  async function handleArchiveTarget() {
    bulkMessage = '';
    bulkError = '';
    syncMessage = '';
    syncError = '';
    archiveDialogError = '';

    const target = archiveTarget;
    if (!target?.id || bulkPending || syncAllPending || archivePendingId) return;

    archivePendingId = target.id;
    try {
      await api.storage.archiveModel(target.id);
      selectedIds = selectedIds.filter((id) => id !== target.id);
      bulkMessage = `${displayModelLabel(target)} をアーカイブしました。`;
      archiveDialogOpen = false;
      archiveTarget = null;
      await queryClient.invalidateQueries({ queryKey: qk.storage.archiveManage() });
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      archiveDialogError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
      bulkError = archiveDialogError;
    } finally {
      archivePendingId = '';
    }
  }

  const activeJobSubscriptions = $derived.by(() =>
    Object.keys(jobsById)
      .map((jobId) => jobsById[jobId])
      .filter((job) => isActiveJobState(job?.state))
      .map(
        (job): TabSessionSubscription => ({
          subscription_id: `storage.model-sync.${job.job_id}`,
          kind: 'storage.model-sync',
          params: { job_id: job.job_id }
        })
      )
  );

  $effect(() => {
    let disposed = false;

    const initialize = async () => {
      try {
        await loadActiveJobs();
      } catch (err) {
        if (disposed) return;
        syncError = err instanceof Error ? err.message : '同期ジョブ状態の取得に失敗しました。';
      }
    };

    void initialize();

    return () => {
      disposed = true;
    };
  });

  $effect(() => {
    if (!browser) return;
    if (realtimeContributor === null) {
      realtimeContributor = registerTabRealtimeContributor({
        subscriptions: activeJobSubscriptions,
        onEvent: (event: TabRealtimeEvent) => {
          if (event.op !== 'snapshot' || event.source?.kind !== 'storage.model-sync') return;
          applyJobSnapshot(event.payload as ModelSyncJobStatus);
        }
      });
      if (!realtimeContributor) {
        return;
      }
      return;
    }
    realtimeContributor.setSubscriptions(activeJobSubscriptions);
  });

  $effect(() => {
    if (archiveDialogOpen || archivePendingId) return;
    archiveTarget = null;
    archiveDialogError = '';
  });
</script>

<ModelSyncProgressModal
  bind:open={modelSyncModalOpen}
  jobId={selectedJobId}
  onCancel={cancelModelSync}
/>

<StorageArchiveConfirmDialog
  bind:open={archiveDialogOpen}
  itemKind="model"
  itemLabel={archiveTarget ? displayModelLabel(archiveTarget) : ''}
  pending={Boolean(archivePendingId)}
  errorMessage={archiveDialogError}
  onConfirm={handleArchiveTarget}
/>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル管理</h1>
      <p class="mt-2 text-sm text-slate-600">アクティブなモデルを一覧で確認できます。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">ビューに戻る</Button.Root>
      <button class="btn-ghost" type="button" onclick={handleSyncAll} disabled={syncPending || bulkPending || !models.length}>
        {syncAllPending ? '全て同期中...' : '全て同期'}
      </button>
      <button class="btn-ghost" type="button" onclick={handleRefresh} disabled={syncAllPending}>
        更新
      </button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">モデル一覧</h2>
    <p class="text-xs text-slate-500">選択して一括操作が可能です。</p>
  </div>
  <div class="mt-4 grid gap-3 md:grid-cols-4">
    <label class="block">
      <span class="label">検索</span>
      <input class="input mt-2" type="text" bind:value={modelSearch} placeholder="model / policy / user" />
    </label>
    <label class="block">
      <span class="label">作成者</span>
      <select class="input mt-2" bind:value={modelOwnerFilter}>
        <option value="all">全員</option>
        {#each modelOwnerOptions as owner}
          <option value={owner.id}>{owner.label}</option>
        {/each}
      </select>
    </label>
    <label class="block">
      <span class="label">並び替え</span>
      <select class="input mt-2" bind:value={modelSortKey}>
        <option value="created_at">作成日時</option>
        <option value="name">名前</option>
        <option value="size_bytes">サイズ</option>
        <option value="policy_type">ポリシー</option>
      </select>
    </label>
    <label class="block">
      <span class="label">順序</span>
      <select class="input mt-2" bind:value={modelSortOrder}>
        <option value="desc">降順</option>
        <option value="asc">昇順</option>
      </select>
    </label>
  </div>
  {#if selectedIds.length > 0}
    <div class="mt-4 rounded-2xl border border-slate-200/80 bg-slate-50/90 p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm font-semibold text-slate-900">選択中: {selectedIds.length} 件</p>
        <button class="btn-ghost" type="button" onclick={clearSelection}>選択解除</button>
      </div>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <button
          class={`btn-primary ${canSyncSelected ? '' : 'opacity-50 cursor-not-allowed'}`}
          type="button"
          disabled={!canSyncSelected}
          onclick={handleSyncSelected}
        >
          同期
        </button>
        <button
          class={`btn-ghost ${canArchiveSelected ? '' : 'opacity-50 cursor-not-allowed'}`}
          type="button"
          disabled={!canArchiveSelected}
          onclick={handleArchiveSelected}
        >
          アーカイブ
        </button>
      </div>
    </div>
  {/if}
  {#if bulkMessage}
    <p class="mt-3 text-sm text-emerald-600">{bulkMessage}</p>
  {/if}
  {#if bulkError}
    <p class="mt-2 text-sm text-rose-600">{bulkError}</p>
  {/if}
  <div class="mt-3 text-xs text-slate-500">選択中: {selectedIds.length} 件</div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="w-12 pb-3 align-middle">
            <div class="flex justify-center">
              <input
                type="checkbox"
                class="block h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                checked={allDisplayedModelsSelected}
                aria-label="表示中のモデルを全選択"
                onchange={toggleSelectAllDisplayedModels}
              />
            </div>
          </th>
          <th class="pb-3">名前</th>
          <th class="pb-3">作成者</th>
          <th class="pb-3">プロファイル</th>
          <th class="pb-3">ポリシー</th>
          <th class="pb-3">データセット</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">作成日時</th>
          <th class="pb-3 text-center">同期状態</th>
          <th class="pb-3 text-right">操作</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $modelsQuery.isLoading}
          <tr><td class="py-3" colspan="10">読み込み中...</td></tr>
        {:else if displayedModels.length}
          {#each displayedModels as model}
            {@const activeJob = activeJobOf(model.id)}
            {@const syncStatus = presentModelSyncStatus(activeJob, Boolean(model.is_local))}
            <tr class="border-t border-slate-200/60">
              <td class="w-12 py-3 align-middle">
                <div class="flex justify-center">
                  <input
                    type="checkbox"
                    class="block h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                    bind:group={selectedIds}
                    value={model.id}
                  />
                </div>
              </td>
              <td class="py-3 font-semibold text-slate-800">
                <span class="block max-w-[25ch] truncate" title={model.id}>
                  {displayModelLabel(model)}
                </span>
              </td>
              <td class="py-3">{ownerLabel(model)}</td>
              <td class="py-3">{model.profile_name ?? '-'}</td>
              <td class="py-3">{model.policy_type ?? '-'}</td>
              <td class="py-3">
                {#if model.dataset_id}
                  <a
                    class="text-brand hover:underline"
                    href={`/storage/datasets/${model.dataset_id}`}
                    title={model.dataset_id}
                  >
                    開く
                  </a>
                {:else}
                  -
                {/if}
              </td>
              <td class="py-3">{formatBytes(model.size_bytes ?? 0)}</td>
              <td class="py-3">{formatDate(model.created_at)}</td>
              <td class="py-3 text-center">
                <div class="flex justify-center">
                  {#if syncStatus.kind === 'progress' && activeJob}
                    <button
                      class="text-xs font-semibold text-brand hover:underline"
                      type="button"
                      onclick={() => openModelSyncModal(activeJob.job_id)}
                    >
                      {syncStatus.label}
                    </button>
                  {:else}
                    <span class="chip">{syncStatus.label}</span>
                  {/if}
                </div>
              </td>
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
                        onSelect={() => {
                          window.location.href = `/storage/models/${model.id}`;
                        }}
                      >
                        詳細を開く
                      </DropdownMenu.Item>
                      <DropdownMenu.Item
                        class="flex items-center rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                        disabled={isSyncButtonDisabled(model)}
                        onSelect={() => {
                          void handleSyncModel(model);
                        }}
                      >
                        {syncButtonLabel(model)}
                      </DropdownMenu.Item>
                      <DropdownMenu.Item
                        class="flex items-center rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                        disabled={bulkPending || syncAllPending || Boolean(archivePendingId)}
                        onSelect={() => openArchiveDialog(model)}
                      >
                        {#if isArchivePending(model.id)}
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
          <tr><td class="py-3" colspan="10">条件に合うモデルがありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
  {#if syncMessage}
    <p class="mt-4 text-sm text-emerald-600">{syncMessage}</p>
  {/if}
  {#if syncError}
    <p class="mt-2 text-sm text-rose-600">{syncError}</p>
  {/if}
</section>

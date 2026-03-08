<script lang="ts">
  import { browser } from '$app/environment';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api, type ModelSyncJobState, type ModelSyncJobStatus, type TabSessionSubscription } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';
  import { formatBytes, formatDate } from '$lib/format';
  import { getTabRealtimeClient, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';

  type ModelSummary = {
    id: string;
    name?: string;
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
    queryKey: qk.storage.modelsManage(),
    queryFn: () => api.storage.models()
  });

  const models = $derived($modelsQuery.data?.models ?? []);

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
  let jobsById = $state<Record<string, ModelSyncJobStatus>>({});
  let activeJobsByModelId = $state<Record<string, ModelSyncJobStatus>>({});
  let realtimeContributor: TabRealtimeContributorHandle | null = null;

  const syncPending = $derived(syncAllPending);

  const activeJobOf = (modelId: string) => activeJobsByModelId[modelId] ?? null;

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
      } catch (err) {
        syncError = err instanceof Error ? err.message : 'モデル同期の中断に失敗しました。';
      }
      return;
    }

    if (model.is_local || syncAllPending || bulkPending) return;

    try {
      const started = await startModelSync(modelId);
      syncMessage = started.message ?? `${modelId} の同期を開始しました。`;
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
      let enqueued = 0;
      let skipped = 0;
      let failed = 0;

      for (const modelId of ids) {
        try {
          await startModelSync(modelId);
          enqueued += 1;
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.includes('409') || message.includes('already in progress')) {
            skipped += 1;
            continue;
          }
          failed += 1;
        }
      }

      const summary = [`登録 ${enqueued}`, `スキップ ${skipped}`, `失敗 ${failed}`].join(' / ');
      bulkMessage = `同期ジョブを登録しました: ${summary}`;
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

    let cancelled = 0;
    let archived = 0;
    let failed = 0;

    try {
      for (const modelId of ids) {
        const activeJob = activeJobOf(modelId);
        if (activeJob) {
          try {
            await cancelModelSync(activeJob.job_id);
            cancelled += 1;
          } catch {
            // Best-effort: proceed to archive even if cancel fails.
          }
        }

        try {
          await api.storage.archiveModel(modelId);
          archived += 1;
        } catch {
          failed += 1;
        }
      }

      const summary = [`中断要求 ${cancelled}`, `アーカイブ ${archived}`, `失敗 ${failed}`].join(' / ');
      bulkMessage = `一括アーカイブを実行しました: ${summary}`;
      selectedIds = [];
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      bulkPending = false;
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
    const client = getTabRealtimeClient();
    if (!client) return;
    if (realtimeContributor === null) {
      realtimeContributor = client.registerContributor({
        contributorId: 'storage.models',
        subscriptions: activeJobSubscriptions,
        onEvent: (event: TabRealtimeEvent) => {
          if (event.op !== 'snapshot' || event.source?.kind !== 'storage.model-sync') return;
          applyJobSnapshot(event.payload as ModelSyncJobStatus);
        }
      });
      return;
    }
    realtimeContributor.setSubscriptions(activeJobSubscriptions);
  });
</script>

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
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">モデル一覧</h2>
    <p class="text-xs text-slate-500">選択して一括操作が可能です。</p>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3"></th>
          <th class="pb-3">ID</th>
          <th class="pb-3">プロファイル</th>
          <th class="pb-3">ポリシー</th>
          <th class="pb-3">データセット</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">作成日時</th>
          <th class="pb-3">同期</th>
          <th class="pb-3">詳細</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $modelsQuery.isLoading}
          <tr><td class="py-3" colspan="9">読み込み中...</td></tr>
        {:else if models.length}
          {#each models as model}
            {@const activeJob = activeJobOf(model.id)}
            {@const progressPercent = Number(activeJob?.progress_percent ?? 0)}
            <tr class="border-t border-slate-200/60">
              <td class="py-3">
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                  bind:group={selectedIds}
                  value={model.id}
                />
              </td>
              <td class="py-3 font-semibold text-slate-800">
                <span class="block max-w-[25ch] truncate" title={model.id}>
                  {displayModelLabel(model)}
                </span>
              </td>
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
              <td class="py-3">
                <button
                  class="btn-ghost"
                  type="button"
                  onclick={() => handleSyncModel(model)}
                  disabled={isSyncButtonDisabled(model)}
                >
                  {syncButtonLabel(model)}
                </button>
                {#if activeJob}
                  <div class="mt-2 max-w-[220px]">
                    <div class="h-1.5 overflow-hidden rounded-full bg-slate-200">
                      <div
                        class="h-full rounded-full bg-brand transition-all duration-200"
                        style={`width: ${Math.min(100, Math.max(0, progressPercent))}%;`}
                      ></div>
                    </div>
                    <p class="mt-1 text-xs text-slate-500">
                      {Math.round(progressPercent)}% {activeJob.message ?? '同期中...'}
                    </p>
                  </div>
                {/if}
              </td>
              <td class="py-3 text-right">
                <Button.Root class="btn-ghost" href={`/storage/models/${model.id}`}>詳細</Button.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="9">モデルがありません。</td></tr>
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

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">一括操作</h2>
      <p class="text-xs text-slate-500">選択済み: {selectedIds.length} 件</p>
    </div>
  </div>
  <div class="mt-4 grid gap-4 lg:grid-cols-2">
    <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
      <p class="text-sm font-semibold text-slate-800">同期</p>
      <p class="mt-1 text-xs text-slate-500">選択済みの未同期モデルをジョブキューへ登録します。</p>
      <div class="mt-4">
        <button
          class={`btn-primary ${canSyncSelected ? '' : 'opacity-50 cursor-not-allowed'}`}
          type="button"
          disabled={!canSyncSelected}
          onclick={handleSyncSelected}
        >
          同期（選択）
        </button>
      </div>
    </div>
    <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
      <p class="text-sm font-semibold text-slate-800">アーカイブ</p>
      <p class="mt-1 text-xs text-slate-500">選択済みモデルをアーカイブへ移動します。</p>
      <div class="mt-4">
        <button
          class={`btn-ghost ${canArchiveSelected ? '' : 'opacity-50 cursor-not-allowed'}`}
          type="button"
          disabled={!canArchiveSelected}
          onclick={handleArchiveSelected}
        >
          アーカイブ（選択）
        </button>
      </div>
    </div>
  </div>
  {#if bulkMessage}
    <p class="mt-4 text-sm text-emerald-600">{bulkMessage}</p>
  {/if}
  {#if bulkError}
    <p class="mt-2 text-sm text-rose-600">{bulkError}</p>
  {/if}
</section>

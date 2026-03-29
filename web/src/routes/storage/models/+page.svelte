<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Button, DropdownMenu, Tabs } from 'bits-ui';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import Archive from 'phosphor-svelte/lib/Archive';
  import ArrowArcLeft from 'phosphor-svelte/lib/ArrowArcLeft';
  import CheckCircle from 'phosphor-svelte/lib/CheckCircle';
  import CloudArrowDown from 'phosphor-svelte/lib/CloudArrowDown';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import FileText from 'phosphor-svelte/lib/FileText';
  import FolderOpen from 'phosphor-svelte/lib/FolderOpen';
  import PencilSimple from 'phosphor-svelte/lib/PencilSimple';
  import StopCircle from 'phosphor-svelte/lib/StopCircle';
  import TrashSimple from 'phosphor-svelte/lib/TrashSimple';
  import { toStore } from 'svelte/store';
  import toast from 'svelte-french-toast';
  import {
    api,
    type ArchiveBulkResponse,
    type BulkActionResponse,
    type ModelSyncJobState,
    type ModelSyncJobStatus,
    type TabSessionSubscription
  } from '$lib/api/client';
  import PaginationControls from '$lib/components/PaginationControls.svelte';
  import { DEFAULT_PAGE_SIZE, buildPageHref, clampPage, parsePageParam } from '$lib/pagination';
  import { qk } from '$lib/queryKeys';
  import { formatBytes, formatDate } from '$lib/format';
  import {
    registerTabRealtimeContributor,
    type TabRealtimeContributorHandle,
    type TabRealtimeEvent
  } from '$lib/realtime/tabSessionClient';
  import ModelSyncProgressModal from '$lib/components/storage/ModelSyncProgressModal.svelte';
  import StorageArchiveConfirmDialog from '$lib/components/storage/StorageArchiveConfirmDialog.svelte';
  import StorageRenameDialog from '$lib/components/storage/StorageRenameDialog.svelte';
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

  type ModelStatusTab = 'active' | 'archived';
  type ModelRowAction = '' | 'restore' | 'delete';

  const queryClient = useQueryClient();

  let modelStatusTab = $state<ModelStatusTab>('active');
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
  let renameDialogOpen = $state(false);
  let renameTarget = $state<ModelSummary | null>(null);
  let renamePending = $state(false);
  let renameError = $state('');
  let rowPendingId = $state('');
  let rowPendingAction = $state<ModelRowAction>('');
  let modelQuerySignature = $state('');

  const PAGE_SIZE = DEFAULT_PAGE_SIZE;
  const currentPage = $derived(parsePageParam(page.url.searchParams.get('page')));

  const modelsQuery = createQuery<ModelListResponse>(
    toStore(() => {
      const status = modelStatusTab;
      const ownerUserId = modelOwnerFilter === 'all' ? undefined : modelOwnerFilter;
      const search = modelSearch || undefined;
      return {
        queryKey: qk.storage.models({
          status,
          ownerUserId,
          search,
          sortBy: modelSortKey,
          sortOrder: modelSortOrder,
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE
        }),
        queryFn: () =>
          api.storage.models({
            status,
            ownerUserId,
            search,
            sortBy: modelSortKey,
            sortOrder: modelSortOrder,
            limit: PAGE_SIZE,
            offset: (currentPage - 1) * PAGE_SIZE
          })
      };
    })
  );

  const models = $derived($modelsQuery.data?.models ?? []);
  const totalModels = $derived($modelsQuery.data?.total ?? 0);
  const displayedModels = $derived(models);
  const isArchiveTab = $derived(modelStatusTab === 'archived');
  const pageDescription = $derived(
    isArchiveTab ? 'アーカイブ済みのモデルを一覧で確認できます。' : 'アクティブなモデルを一覧で確認できます。'
  );
  const helperText = $derived(
    isArchiveTab ? '選択して復元または完全削除が可能です。' : '選択して一括操作が可能です。'
  );
  const emptyStateText = $derived(
    isArchiveTab ? '条件に合うアーカイブ済みモデルがありません。' : '条件に合うモデルがありません。'
  );
  const modelTableColumnCount = $derived(isArchiveTab ? 8 : 9);

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
  const allDisplayedModelIds = $derived(displayedModels.map((model) => model.id));
  const allDisplayedModelsSelected = $derived(
    allDisplayedModelIds.length > 0 && allDisplayedModelIds.every((id) => selectedIds.includes(id))
  );

  const clearSelection = () => {
    selectedIds = [];
  };

  const resetMessages = () => {
    syncMessage = '';
    syncError = '';
    bulkMessage = '';
    bulkError = '';
  };

  const resetArchiveDialog = () => {
    archiveDialogOpen = false;
    archiveTarget = null;
    archiveDialogError = '';
  };

  const resetRenameDialog = () => {
    renameDialogOpen = false;
    renameTarget = null;
    renameError = '';
  };

  const removeSelectedIds = (ids: string[]) => {
    if (!ids.length) return;
    const idSet = new Set(ids);
    selectedIds = selectedIds.filter((id) => !idSet.has(id));
  };

  const navigateToPage = async (nextPage: number) => {
    const href = buildPageHref(page.url, nextPage);
    const currentHref = `${page.url.pathname}${page.url.search}${page.url.hash}`;
    if (href === currentHref) return;
    await goto(href, {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
      invalidateAll: false
    });
  };

  $effect(() => {
    const nextSignature = JSON.stringify([
      modelStatusTab,
      modelOwnerFilter,
      modelSearch,
      modelSortKey,
      modelSortOrder
    ]);
    if (!modelQuerySignature) {
      modelQuerySignature = nextSignature;
      return;
    }
    if (nextSignature === modelQuerySignature) {
      return;
    }
    modelQuerySignature = nextSignature;
    if (currentPage !== 1) {
      void navigateToPage(1);
    }
  });

  $effect(() => {
    if ($modelsQuery.isLoading) {
      return;
    }
    const nextPage = clampPage(currentPage, totalModels, PAGE_SIZE);
    if (nextPage !== currentPage) {
      void navigateToPage(nextPage);
    }
  });

  $effect(() => {
    const visibleIds = new Set(displayedModels.map((model) => model.id));
    const nextSelectedIds = selectedIds.filter((id) => visibleIds.has(id));
    if (
      nextSelectedIds.length !== selectedIds.length ||
      nextSelectedIds.some((id, index) => id !== selectedIds[index])
    ) {
      selectedIds = nextSelectedIds;
    }
  });

  const toggleSelectAllDisplayedModels = () => {
    if (allDisplayedModelsSelected) {
      selectedIds = selectedIds.filter((id) => !allDisplayedModelIds.includes(id));
      return;
    }
    selectedIds = Array.from(new Set([...selectedIds, ...allDisplayedModelIds]));
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

  const applyArchiveBulkMessage = (
    response: ArchiveBulkResponse,
    label: string,
    successIds: string[] | undefined
  ) => {
    const succeeded = successIds?.length ?? 0;
    const failed = response.errors?.length ?? 0;
    bulkMessage = `${label}: 成功 ${succeeded} / 失敗 ${failed}`;
    bulkError = (response.errors ?? []).slice(0, 3).join(' / ');
  };

  const activeJobOf = (modelId: string) => activeJobsByModelId[modelId] ?? null;
  const openModelSyncModal = (jobId: string) => {
    if (!jobId) return;
    selectedJobId = jobId;
    modelSyncModalOpen = true;
  };
  const isArchivePending = (modelId: string) => archivePendingId === modelId;
  const isRowPending = (modelId: string, action: ModelRowAction) =>
    rowPendingId === modelId && rowPendingAction === action;
  const tabTriggerClass = (value: ModelStatusTab) => {
    const isActive = modelStatusTab === value;
    if (value === 'active') {
      return `rounded-full border px-4 py-2 text-sm font-semibold transition ${
        isActive
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700 shadow-sm'
          : 'border-transparent text-slate-600 hover:text-slate-900'
      }`;
    }
    return `rounded-full border px-4 py-2 text-sm font-semibold transition ${
      isActive
        ? 'border-rose-200 bg-rose-50 text-rose-700 shadow-sm'
        : 'border-transparent text-slate-600 hover:text-slate-900'
    }`;
  };

  const handleModelTabChange = (nextValue: string) => {
    const nextTab: ModelStatusTab = nextValue === 'archived' ? 'archived' : 'active';
    if (nextTab === modelStatusTab) return;
    modelStatusTab = nextTab;
    clearSelection();
    resetMessages();
    resetArchiveDialog();
    resetRenameDialog();
    rowPendingId = '';
    rowPendingAction = '';
  };

  const openArchiveDialog = (model: ModelSummary) => {
    if (modelStatusTab !== 'active' || bulkPending || syncAllPending || archivePendingId || rowPendingId || renamePending) return;
    archiveDialogError = '';
    archiveTarget = model;
    archiveDialogOpen = true;
  };

  const openRenameDialog = (model: ModelSummary) => {
    if (bulkPending || syncAllPending || archivePendingId || rowPendingId || renamePending) return;
    renameError = '';
    renameTarget = model;
    renameDialogOpen = true;
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

  const refetchModels = async () => {
    await queryClient.invalidateQueries({ queryKey: qk.storage.modelsPrefix() });
    await $modelsQuery?.refetch?.();
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
      void queryClient.invalidateQueries({ queryKey: qk.storage.modelsPrefix() });
    }
  };

  const selectedModels = $derived(models.filter((model) => selectedIds.includes(model.id)));
  const syncTargets = $derived(selectedModels.filter((model) => !model.is_local));
  const canSyncSelected = $derived(!isArchiveTab && syncTargets.length > 0 && !bulkPending && !syncAllPending);
  const canArchiveSelected = $derived(!isArchiveTab && selectedIds.length > 0 && !bulkPending && !syncAllPending);
  const canRestoreSelected = $derived(isArchiveTab && selectedIds.length > 0 && !bulkPending && !syncAllPending);
  const canDeleteSelected = $derived(isArchiveTab && selectedIds.length > 0 && !bulkPending && !syncAllPending);

  const loadActiveJobs = async () => {
    const response = await api.storage.modelSyncJobs(false);
    const activeJobs = (response.jobs ?? []).map(normalizeJob);

    const nextJobsById = { ...jobsById };
    const nextActive: Record<string, ModelSyncJobStatus> = {};

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

  const handleSyncModel = async (model: ModelSummary) => {
    if (modelStatusTab !== 'active') return;

    const modelId = model.id;
    if (!modelId) return;
    const activeJob = activeJobOf(modelId);

    resetMessages();

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
    if (modelStatusTab !== 'active' || syncPending || bulkPending) return;

    const targets = models.filter((model) => !model.is_local);
    if (!targets.length) {
      syncMessage = '未同期モデルはありません。';
      syncError = '';
      return;
    }

    syncAllPending = true;
    resetMessages();

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
    resetMessages();
    await refetchModels();
    if (modelStatusTab === 'active') {
      await loadActiveJobs();
    }
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
    resetMessages();

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
    resetMessages();

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
      removeSelectedIds(
        response.results.filter((result) => result.status === 'succeeded').map((result) => result.id)
      );
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      bulkPending = false;
    }
  }

  async function handleRestoreSelected() {
    resetMessages();

    if (!selectedIds.length) {
      bulkError = '復元対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件を復元しますか？`);
    if (!confirmed) return;

    bulkPending = true;
    const ids = [...selectedIds];

    try {
      const response = await api.storage.restoreArchive({
        dataset_ids: [],
        model_ids: ids
      });
      applyArchiveBulkMessage(response, '復元を実行しました', response.restored);
      removeSelectedIds(response.restored ?? []);
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      bulkPending = false;
    }
  }

  async function handleDeleteSelected() {
    resetMessages();

    if (!selectedIds.length) {
      bulkError = '完全削除対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件を完全に削除しますか？`);
    if (!confirmed) return;

    bulkPending = true;
    const ids = [...selectedIds];

    try {
      const response = await api.storage.deleteArchive({
        dataset_ids: [],
        model_ids: ids
      });
      applyArchiveBulkMessage(response, '完全削除を実行しました', response.deleted);
      removeSelectedIds(response.deleted ?? []);
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : '完全削除に失敗しました。';
    } finally {
      bulkPending = false;
    }
  }

  async function handleArchiveTarget() {
    resetMessages();
    archiveDialogError = '';

    const target = archiveTarget;
    if (!target?.id || bulkPending || syncAllPending || archivePendingId || rowPendingId) return;

    archivePendingId = target.id;
    try {
      await api.storage.archiveModel(target.id);
      removeSelectedIds([target.id]);
      bulkMessage = `${displayModelLabel(target)} をアーカイブしました。`;
      resetArchiveDialog();
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      archiveDialogError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
      bulkError = archiveDialogError;
    } finally {
      archivePendingId = '';
    }
  }

  async function handleRestoreTarget(model: ModelSummary) {
    resetMessages();

    if (!model.id || bulkPending || syncAllPending || archivePendingId || rowPendingId) return;
    const confirmed = confirm(`${displayModelLabel(model)} を復元しますか？`);
    if (!confirmed) return;

    bulkPending = true;
    rowPendingId = model.id;
    rowPendingAction = 'restore';
    try {
      await api.storage.restoreModel(model.id);
      removeSelectedIds([model.id]);
      bulkMessage = `${displayModelLabel(model)} を復元しました。`;
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      rowPendingId = '';
      rowPendingAction = '';
      bulkPending = false;
    }
  }

  async function handleDeleteTarget(model: ModelSummary) {
    resetMessages();

    if (!model.id || bulkPending || syncAllPending || archivePendingId || rowPendingId) return;
    const confirmed = confirm(`${displayModelLabel(model)} を完全に削除しますか？`);
    if (!confirmed) return;

    bulkPending = true;
    rowPendingId = model.id;
    rowPendingAction = 'delete';
    try {
      await api.storage.deleteArchivedModel(model.id);
      removeSelectedIds([model.id]);
      bulkMessage = `${displayModelLabel(model)} を完全に削除しました。`;
      await refetchModels();
      await loadActiveJobs();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : '完全削除に失敗しました。';
    } finally {
      rowPendingId = '';
      rowPendingAction = '';
      bulkPending = false;
    }
  }

  async function handleRenameTarget(nextName: string) {
    renameError = '';

    const target = renameTarget;
    if (!target?.id || bulkPending || syncAllPending || archivePendingId || rowPendingId) return;

    renamePending = true;
    try {
      await api.storage.renameModel(target.id, { name: nextName });
      await queryClient.invalidateQueries({ queryKey: qk.storage.model(target.id) });
      await refetchModels();
      resetRenameDialog();
      toast.success('名前を更新しました。');
    } catch (err) {
      renameError = err instanceof Error ? err.message : '名前変更に失敗しました。';
    } finally {
      renamePending = false;
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

  $effect(() => {
    if (renameDialogOpen || renamePending) return;
    renameTarget = null;
    renameError = '';
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

<StorageRenameDialog
  bind:open={renameDialogOpen}
  itemKind="model"
  currentName={renameTarget ? displayModelLabel(renameTarget) : ''}
  pending={renamePending}
  errorMessage={renameError}
  onConfirm={handleRenameTarget}
/>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル管理</h1>
      <p class="mt-2 text-sm text-slate-600">{pageDescription}</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">ビューに戻る</Button.Root>
      {#if !isArchiveTab}
        <button class="btn-ghost" type="button" onclick={handleSyncAll} disabled={syncPending || bulkPending || !models.length}>
          {syncAllPending ? '全て同期中...' : '全て同期'}
        </button>
      {/if}
      <button class="btn-ghost" type="button" onclick={handleRefresh} disabled={syncAllPending}>
        更新
      </button>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">モデル一覧</h2>
    <Tabs.Root value={modelStatusTab} onValueChange={handleModelTabChange}>
      <Tabs.List class="inline-grid grid-cols-2 gap-1 rounded-full border border-slate-200/70 bg-slate-100/80 p-1">
        <Tabs.Trigger
          value="active"
          class={tabTriggerClass('active')}
        >
          アクティブ
        </Tabs.Trigger>
        <Tabs.Trigger
          value="archived"
          class={tabTriggerClass('archived')}
        >
          アーカイブ
        </Tabs.Trigger>
      </Tabs.List>
    </Tabs.Root>
  </div>
  <p class="mt-2 text-xs text-slate-500">{helperText}</p>
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
    <div class="mt-4 nested-block-pane p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm font-semibold text-slate-900">選択中: {selectedIds.length} 件</p>
        <button class="btn-ghost" type="button" onclick={clearSelection}>選択解除</button>
      </div>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        {#if isArchiveTab}
          <button
            class={`btn-primary ${canRestoreSelected ? '' : 'opacity-50 cursor-not-allowed'}`}
            type="button"
            disabled={!canRestoreSelected}
            onclick={handleRestoreSelected}
          >
            復元
          </button>
          <button
            class={`btn-ghost ${canDeleteSelected ? '' : 'opacity-50 cursor-not-allowed'}`}
            type="button"
            disabled={!canDeleteSelected}
            onclick={handleDeleteSelected}
          >
            完全削除
          </button>
        {:else}
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
        {/if}
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
          <th class="pb-3">サイズ</th>
          <th class="pb-3">作成日時</th>
          {#if !isArchiveTab}
            <th class="pb-3 text-center">同期状態</th>
          {/if}
          <th class="pb-3 text-right">操作</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $modelsQuery.isLoading}
          <tr><td class="py-3" colspan={modelTableColumnCount}>読み込み中...</td></tr>
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
              <td class="py-3">{formatBytes(model.size_bytes ?? 0)}</td>
              <td class="py-3">{formatDate(model.created_at)}</td>
              {#if !isArchiveTab}
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
                      <span
                        class={`text-xs font-semibold ${
                          syncStatus.tone === 'error'
                            ? 'text-rose-600'
                            : syncStatus.tone === 'success'
                              ? 'text-emerald-600'
                              : 'text-slate-500'
                        }`}
                      >
                        {syncStatus.label}
                      </span>
                    {/if}
                  </div>
                </td>
              {/if}
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
                      <DropdownMenu.Group>
                        <DropdownMenu.GroupHeading
                          class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                        >
                          表示
                        </DropdownMenu.GroupHeading>
                        <DropdownMenu.Item
                          class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                          onSelect={() => {
                            window.location.href = `/storage/models/${model.id}`;
                          }}
                        >
                          <FileText size={16} class="text-slate-500" />
                          詳細を開く
                        </DropdownMenu.Item>
                        {#if model.dataset_id}
                          <DropdownMenu.Item
                            class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                            onSelect={() => {
                              window.location.href = `/storage/datasets/${model.dataset_id}`;
                            }}
                          >
                            <FolderOpen size={16} class="text-slate-500" />
                            データセットを開く
                          </DropdownMenu.Item>
                        {/if}
                      </DropdownMenu.Group>

                      <DropdownMenu.Separator class="-mx-2 my-1 h-px bg-slate-200/70" />

                      <DropdownMenu.Group>
                        <DropdownMenu.GroupHeading
                          class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                        >
                          編集
                        </DropdownMenu.GroupHeading>
                        <DropdownMenu.Item
                          class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                          disabled={bulkPending || syncAllPending || Boolean(archivePendingId) || Boolean(rowPendingId) || renamePending}
                          onSelect={() => openRenameDialog(model)}
                        >
                          <PencilSimple size={16} class="text-slate-500" />
                          名前変更
                        </DropdownMenu.Item>
                      </DropdownMenu.Group>

                      <DropdownMenu.Separator class="-mx-2 my-1 h-px bg-slate-200/70" />

                      <DropdownMenu.Group>
                        <DropdownMenu.GroupHeading
                          class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                        >
                          操作
                        </DropdownMenu.GroupHeading>
                        {#if isArchiveTab}
                          <DropdownMenu.Item
                            class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                            disabled={bulkPending || syncAllPending || Boolean(archivePendingId) || Boolean(rowPendingId) || renamePending}
                            onSelect={() => {
                              void handleRestoreTarget(model);
                            }}
                          >
                            <ArrowArcLeft size={16} class="text-slate-500" />
                            {#if isRowPending(model.id, 'restore')}
                              復元中...
                            {:else}
                              復元
                            {/if}
                          </DropdownMenu.Item>
                          <DropdownMenu.Item
                            class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                            disabled={bulkPending || syncAllPending || Boolean(archivePendingId) || Boolean(rowPendingId) || renamePending}
                            onSelect={() => {
                              void handleDeleteTarget(model);
                            }}
                          >
                            <TrashSimple size={16} class="text-rose-500" />
                            {#if isRowPending(model.id, 'delete')}
                              完全削除中...
                            {:else}
                              完全削除
                            {/if}
                          </DropdownMenu.Item>
                        {:else}
                          <DropdownMenu.Item
                            class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                            disabled={isSyncButtonDisabled(model) || renamePending}
                            onSelect={() => {
                              void handleSyncModel(model);
                            }}
                          >
                            {#if activeJob}
                              <StopCircle size={16} class="text-slate-500" />
                            {:else if model.is_local}
                              <CheckCircle size={16} class="text-slate-500" />
                            {:else}
                              <CloudArrowDown size={16} class="text-slate-500" />
                            {/if}
                            {syncButtonLabel(model)}
                          </DropdownMenu.Item>
                          <DropdownMenu.Item
                            class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                            disabled={bulkPending || syncAllPending || Boolean(archivePendingId) || Boolean(rowPendingId) || renamePending}
                            onSelect={() => openArchiveDialog(model)}
                          >
                            <Archive size={16} class="text-rose-500" />
                            {#if isArchivePending(model.id)}
                              アーカイブ中...
                            {:else}
                              アーカイブ
                            {/if}
                          </DropdownMenu.Item>
                        {/if}
                      </DropdownMenu.Group>
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan={modelTableColumnCount}>{emptyStateText}</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
  <PaginationControls
    currentPage={currentPage}
    pageSize={PAGE_SIZE}
    totalItems={totalModels}
    disabled={$modelsQuery.isLoading}
    onPageChange={navigateToPage}
  />
  {#if syncMessage}
    <p class="mt-4 text-sm text-emerald-600">{syncMessage}</p>
  {/if}
  {#if syncError}
    <p class="mt-2 text-sm text-rose-600">{syncError}</p>
  {/if}
</section>

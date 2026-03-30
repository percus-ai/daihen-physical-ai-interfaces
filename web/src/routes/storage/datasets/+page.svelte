<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Button, DropdownMenu, Tabs } from 'bits-ui';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import Archive from 'phosphor-svelte/lib/Archive';
  import ArrowArcLeft from 'phosphor-svelte/lib/ArrowArcLeft';
  import ArrowDown from 'phosphor-svelte/lib/ArrowDown';
  import ArrowUp from 'phosphor-svelte/lib/ArrowUp';
  import ArrowsMerge from 'phosphor-svelte/lib/ArrowsMerge';
  import CaretUpDown from 'phosphor-svelte/lib/CaretUpDown';
  import CheckCircle from 'phosphor-svelte/lib/CheckCircle';
  import CloudArrowDown from 'phosphor-svelte/lib/CloudArrowDown';
  import CloudArrowUp from 'phosphor-svelte/lib/CloudArrowUp';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import Eye from 'phosphor-svelte/lib/Eye';
  import FileText from 'phosphor-svelte/lib/FileText';
  import PencilSimple from 'phosphor-svelte/lib/PencilSimple';
  import StopCircle from 'phosphor-svelte/lib/StopCircle';
  import TrashSimple from 'phosphor-svelte/lib/TrashSimple';
  import XCircle from 'phosphor-svelte/lib/XCircle';
  import { toStore } from 'svelte/store';
  import toast from 'svelte-french-toast';
  import {
    api,
    type ArchiveBulkResponse,
    type BulkActionResponse,
    type DatasetSyncJobState,
    type DatasetSyncJobStatus,
    type TabSessionSubscription
  } from '$lib/api/client';
  import ListFilterPopover from '$lib/components/ListFilterPopover.svelte';
  import PaginationControls from '$lib/components/PaginationControls.svelte';
  import type { ListFilterField } from '$lib/listFilters';
  import { DEFAULT_PAGE_SIZE, buildPageHref, buildUrlWithQueryState, clampPage, parsePageParam } from '$lib/pagination';
  import { qk } from '$lib/queryKeys';
  import {
    registerTabRealtimeContributor,
    type TabRealtimeContributorHandle,
    type TabRealtimeEvent
  } from '$lib/realtime/tabSessionClient';
  import { sessionViewer } from '$lib/viewer/sessionViewerStore';
  import { formatBytes, formatDate } from '$lib/format';
  import { presentDatasetSyncStatus } from '$lib/storage/transferStatus';
  import DatasetMergeDialog from '$lib/components/storage/DatasetMergeDialog.svelte';
  import DatasetMergeProgressModal from '$lib/components/storage/DatasetMergeProgressModal.svelte';
  import DatasetSyncProgressModal from '$lib/components/storage/DatasetSyncProgressModal.svelte';
  import StorageArchiveConfirmDialog from '$lib/components/storage/StorageArchiveConfirmDialog.svelte';
  import StorageRenameDialog from '$lib/components/storage/StorageRenameDialog.svelte';

  type Props = {
    embedded?: boolean;
  };

  let { embedded = false }: Props = $props();

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
    is_local?: boolean;
    created_at?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
    owner_options?: Array<{
      user_id: string;
      label: string;
      owner_name?: string | null;
      owner_email?: string | null;
      total_count?: number;
      available_count?: number;
    }>;
    profile_options?: Array<{
      value: string;
      label: string;
      total_count?: number;
      available_count?: number;
    }>;
    dataset_type_options?: Array<{
      value: string;
      label: string;
      total_count?: number;
      available_count?: number;
    }>;
    sync_status_options?: Array<{
      value: string;
      label: string;
      total_count?: number;
      available_count?: number;
    }>;
  };

  type DatasetStatusTab = 'active' | 'archived';
  type DatasetRowAction = '' | 'restore' | 'delete';
  const DATASET_SORT_KEYS = ['created_at', 'name', 'owner_name', 'profile_name', 'episode_count', 'size_bytes', 'sync_status'] as const;
  const parseDatasetStatusTab = (value: string | null): DatasetStatusTab => (value === 'archived' ? 'archived' : 'active');
  const parseDatasetSortKey = (value: string | null): 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'sync_status' =>
    DATASET_SORT_KEYS.includes((value ?? '') as (typeof DATASET_SORT_KEYS)[number])
      ? ((value ?? '') as 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'sync_status')
      : 'created_at';
  const parseSortOrder = (value: string | null): 'desc' | 'asc' => (value === 'asc' ? 'asc' : 'desc');

  const queryClient = useQueryClient();

  let filterDialogOpen = $state(false);
  let selectedIds = $state<string[]>([]);
  let mergeDialogOpen = $state(false);
  let mergeDialogError = $state('');
  let actionMessage = $state('');
  let actionError = $state('');
  let actionLoading = $state(false);
  let syncMessage = $state('');
  let syncError = $state('');
  let syncPending = $state(false);

  let mergeModalOpen = $state(false);
  let mergeJobId = $state('');
  let lastMergePayload = $state<null | { dataset_name: string; source_dataset_ids: string[] }>(null);
  let archiveDialogOpen = $state(false);
  let archiveTarget = $state<DatasetSummary | null>(null);
  let archivePendingId = $state('');
  let archiveDialogError = $state('');
  let renameDialogOpen = $state(false);
  let renameTarget = $state<DatasetSummary | null>(null);
  let renamePending = $state(false);
  let renameError = $state('');
  let rowPendingId = $state('');
  let rowPendingAction = $state<DatasetRowAction>('');
  const datasetStatusTab = $derived(parseDatasetStatusTab(page.url.searchParams.get('status')));
  let previousStatusTab = $state<DatasetStatusTab | null>(null);
  const datasetSortKey = $derived(parseDatasetSortKey(page.url.searchParams.get('sort')));
  const datasetSortOrder = $derived(parseSortOrder(page.url.searchParams.get('order')));
  const datasetOwnerFilter = $derived(page.url.searchParams.get('owner') || 'all');
  const datasetProfileFilter = $derived(page.url.searchParams.get('profile') || 'all');
  const datasetTypeFilter = $derived(page.url.searchParams.get('dataset_type') || 'all');
  const datasetSyncFilter = $derived(page.url.searchParams.get('sync_status') || 'all');
  const datasetSearch = $derived(page.url.searchParams.get('search') || '');
  const datasetCreatedFrom = $derived(page.url.searchParams.get('created_from') || '');
  const datasetCreatedTo = $derived(page.url.searchParams.get('created_to') || '');
  const datasetSizeMin = $derived(page.url.searchParams.get('size_min') || '');
  const datasetSizeMax = $derived(page.url.searchParams.get('size_max') || '');
  const datasetEpisodeMin = $derived(page.url.searchParams.get('episodes_min') || '');
  const datasetEpisodeMax = $derived(page.url.searchParams.get('episodes_max') || '');
  let jobsById = $state<Record<string, DatasetSyncJobStatus>>({});
  let activeJobsByDatasetId = $state<Record<string, DatasetSyncJobStatus>>({});
  let realtimeContributor: TabRealtimeContributorHandle | null = null;
  let datasetSyncModalOpen = $state(false);
  let selectedSyncJobId = $state('');

  const PAGE_SIZE = DEFAULT_PAGE_SIZE;
  const currentPage = $derived(parsePageParam(page.url.searchParams.get('page')));
  const parseOptionalInt = (value: string) => {
    const normalized = value.trim();
    if (!normalized) return undefined;
    const parsed = Number.parseInt(normalized, 10);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const datasetsQuery = createQuery<DatasetListResponse>(
    toStore(() => {
      const status = datasetStatusTab;
      const ownerUserId = datasetOwnerFilter === 'all' ? undefined : datasetOwnerFilter;
      const profileName = datasetProfileFilter === 'all' ? undefined : datasetProfileFilter;
      const datasetType = datasetTypeFilter === 'all' ? undefined : datasetTypeFilter;
      const syncStatus = datasetSyncFilter === 'all' ? undefined : datasetSyncFilter;
      const search = datasetSearch || undefined;
      return {
        queryKey: qk.storage.datasets({
          status,
          ownerUserId,
          profileName,
          datasetType,
          syncStatus,
          search,
          createdFrom: datasetCreatedFrom || undefined,
          createdTo: datasetCreatedTo || undefined,
          sizeMin: parseOptionalInt(datasetSizeMin),
          sizeMax: parseOptionalInt(datasetSizeMax),
          episodeCountMin: parseOptionalInt(datasetEpisodeMin),
          episodeCountMax: parseOptionalInt(datasetEpisodeMax),
          sortBy: datasetSortKey,
          sortOrder: datasetSortOrder,
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE
        }),
        queryFn: () =>
          api.storage.datasets({
            status,
            ownerUserId,
            profileName,
            datasetType,
            syncStatus,
            search,
            createdFrom: datasetCreatedFrom || undefined,
            createdTo: datasetCreatedTo || undefined,
            sizeMin: parseOptionalInt(datasetSizeMin),
            sizeMax: parseOptionalInt(datasetSizeMax),
            episodeCountMin: parseOptionalInt(datasetEpisodeMin),
            episodeCountMax: parseOptionalInt(datasetEpisodeMax),
            sortBy: datasetSortKey,
            sortOrder: datasetSortOrder,
            limit: PAGE_SIZE,
            offset: (currentPage - 1) * PAGE_SIZE
          })
      };
    })
  );

  const datasets = $derived($datasetsQuery.data?.datasets ?? []);
  const totalDatasets = $derived($datasetsQuery.data?.total ?? 0);
  const displayedDatasets = $derived(datasets);
  const isArchiveTab = $derived(datasetStatusTab === 'archived');
  const pageDescription = $derived(
    isArchiveTab ? 'アーカイブ済みのデータセットを一覧で確認できます。' : 'アクティブなデータセットを一覧で確認できます。'
  );
  const helperText = $derived(
    isArchiveTab ? '選択して復元または完全削除が可能です。' : '選択して一括操作が可能です。'
  );
  const emptyStateText = $derived(
    isArchiveTab ? '条件に合うアーカイブ済みデータセットがありません。' : '条件に合うデータセットがありません。'
  );
  const datasetTableColumnCount = $derived(isArchiveTab ? 8 : 9);

  const creatorLabel = (value?: string | null) => {
    const normalized = String(value ?? '').trim();
    if (!normalized) return '-';
    if (normalized.length <= 24) return normalized;
    return `${normalized.slice(0, 20)}...`;
  };
  const ownerLabel = (dataset: DatasetSummary) =>
    creatorLabel(dataset.owner_name ?? dataset.owner_email ?? dataset.owner_user_id);
  const displayDatasetLabel = (dataset: DatasetSummary) => dataset.name ?? dataset.id;

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
  const syncTargets = $derived(selectedDatasets.filter((dataset) => !Boolean(dataset.is_local)));
  const canMerge = $derived(!isArchiveTab && selectedIds.length >= 2 && !profileMismatch && !actionLoading);
  const canSyncSelected = $derived(!isArchiveTab && syncTargets.length > 0 && !actionLoading && !syncPending);
  const canArchive = $derived(!isArchiveTab && selectedIds.length > 0 && !actionLoading);
  const canReupload = $derived(!isArchiveTab && selectedIds.length > 0 && !actionLoading);
  const canRestore = $derived(isArchiveTab && selectedIds.length > 0 && !actionLoading);
  const canDelete = $derived(isArchiveTab && selectedIds.length > 0 && !actionLoading);
  const bulkMenuItemClass =
    'flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent';
  const bulkMenuDangerItemClass =
    'flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent';

  const datasetOwnerOptions = $derived($datasetsQuery.data?.owner_options ?? []);
  const datasetProfileOptions = $derived($datasetsQuery.data?.profile_options ?? []);
  const datasetTypeOptions = $derived($datasetsQuery.data?.dataset_type_options ?? []);
  const datasetSyncOptions = $derived($datasetsQuery.data?.sync_status_options ?? []);
  const withAllOption = (
    currentValue: string,
    options: Array<{ value: string; label: string; available_count?: number }>
  ) => {
    const nextOptions = [
      { value: 'all', label: 'すべて' },
      ...options.map((option) => ({
        value: option.value,
        label: option.label,
        disabled: option.available_count === 0 && option.value !== currentValue
      }))
    ];
    if (currentValue !== 'all' && !nextOptions.some((option) => option.value === currentValue)) {
      nextOptions.push({ value: currentValue, label: currentValue });
    }
    return nextOptions;
  };
  const datasetOwnerSelectOptions = $derived.by(() => {
    const options = [
      { value: 'all', label: '全員' },
      ...datasetOwnerOptions.map((owner) => ({
        value: owner.user_id,
        label: owner.label,
        disabled: owner.available_count === 0 && owner.user_id !== datasetOwnerFilter
      }))
    ];
    if (datasetOwnerFilter !== 'all' && !options.some((option) => option.value === datasetOwnerFilter)) {
      options.push({ value: datasetOwnerFilter, label: datasetOwnerFilter });
    }
    return options;
  });
  const datasetProfileSelectOptions = $derived(withAllOption(datasetProfileFilter, datasetProfileOptions));
  const datasetTypeSelectOptions = $derived(withAllOption(datasetTypeFilter, datasetTypeOptions));
  const datasetSyncSelectOptions = $derived(withAllOption(datasetSyncFilter, datasetSyncOptions));
  const datasetFilterDefaults = {
    search: '',
    owner: 'all',
    profile: 'all',
    dataset_type: 'all',
    sync_status: 'all',
    created_from: '',
    created_to: '',
    size_min: '',
    size_max: '',
    episodes_min: '',
    episodes_max: ''
  };
  const datasetFilterValues = $derived({
    search: datasetSearch,
    owner: datasetOwnerFilter,
    profile: datasetProfileFilter,
    dataset_type: datasetTypeFilter,
    sync_status: datasetSyncFilter,
    created_from: datasetCreatedFrom,
    created_to: datasetCreatedTo,
    size_min: datasetSizeMin,
    size_max: datasetSizeMax,
    episodes_min: datasetEpisodeMin,
    episodes_max: datasetEpisodeMax
  });
  const datasetFilterFields = $derived<ListFilterField[]>([
    {
      section: '検索',
      type: 'text',
      key: 'search',
      label: '名前',
      placeholder: '名前で検索'
    },
    {
      section: '条件',
      type: 'select',
      key: 'owner',
      label: '作成者',
      options: datasetOwnerSelectOptions
    },
    {
      section: '条件',
      type: 'select',
      key: 'profile',
      label: 'プロファイル',
      options: datasetProfileSelectOptions
    },
    {
      section: '条件',
      type: 'select',
      key: 'dataset_type',
      label: '種別',
      options: datasetTypeSelectOptions
    },
    {
      section: '条件',
      type: 'select',
      key: 'sync_status',
      label: '同期状態',
      options: datasetSyncSelectOptions
    },
    {
      section: '期間・範囲',
      type: 'date-range',
      keyFrom: 'created_from',
      keyTo: 'created_to',
      label: '作成日時'
    },
    {
      section: '期間・範囲',
      type: 'number-range',
      keyMin: 'size_min',
      keyMax: 'size_max',
      label: 'サイズ',
      min: 0,
      step: 1,
      placeholderMin: '最小',
      placeholderMax: '最大'
    },
    {
      section: '期間・範囲',
      type: 'number-range',
      keyMin: 'episodes_min',
      keyMax: 'episodes_max',
      label: 'エピソード数',
      min: 0,
      step: 1,
      placeholderMin: '最小',
      placeholderMax: '最大'
    }
  ]);
  const hasActiveDatasetFilters = $derived(
    Boolean(datasetSearch) ||
      datasetOwnerFilter !== 'all' ||
      datasetProfileFilter !== 'all' ||
      datasetTypeFilter !== 'all' ||
      datasetSyncFilter !== 'all' ||
      Boolean(datasetCreatedFrom) ||
      Boolean(datasetCreatedTo) ||
      Boolean(datasetSizeMin) ||
      Boolean(datasetSizeMax) ||
      Boolean(datasetEpisodeMin) ||
      Boolean(datasetEpisodeMax)
  );
  const sortIconClass = 'text-slate-400 transition group-hover:text-slate-600';
  const sortableHeaderButtonClass =
    'group inline-flex items-center gap-1 font-semibold text-slate-400 transition hover:text-slate-700';

  const allDisplayedDatasetIds = $derived(displayedDatasets.map((dataset) => dataset.id));
  const allDisplayedDatasetsSelected = $derived(
    allDisplayedDatasetIds.length > 0 && allDisplayedDatasetIds.every((id) => selectedIds.includes(id))
  );

  const clearSelection = () => {
    selectedIds = [];
  };

  const resetMessages = () => {
    actionMessage = '';
    actionError = '';
    syncMessage = '';
    syncError = '';
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

  const resetMergeDialog = () => {
    mergeDialogOpen = false;
    mergeDialogError = '';
  };

  const resetViewState = () => {
    clearSelection();
    resetMessages();
    resetArchiveDialog();
    resetRenameDialog();
    resetMergeDialog();
    rowPendingId = '';
    rowPendingAction = '';
    filterDialogOpen = false;
  };

  const removeSelectedIds = (ids: string[]) => {
    if (!ids.length) return;
    const idSet = new Set(ids);
    selectedIds = selectedIds.filter((id) => !idSet.has(id));
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

  const applyArchiveBulkMessage = (
    response: ArchiveBulkResponse,
    successLabel: string,
    successIds: string[] | undefined
  ) => {
    const succeeded = successIds?.length ?? 0;
    const failed = response.errors?.length ?? 0;
    actionMessage = `${successLabel}: 成功 ${succeeded} / 失敗 ${failed}`;
    actionError = (response.errors ?? []).slice(0, 3).join(' / ');
  };

  const refetchDatasets = async () => {
    await queryClient.invalidateQueries({ queryKey: qk.storage.datasetsPrefix() });
    await $datasetsQuery?.refetch?.();
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
  const applyDatasetFilters = async (values: Record<string, string>) => {
    const nextHref = buildUrlWithQueryState(page.url, {
      status: datasetStatusTab !== 'active' ? datasetStatusTab : null,
      owner: values.owner !== 'all' ? values.owner : null,
      profile: values.profile !== 'all' ? values.profile : null,
      dataset_type: values.dataset_type !== 'all' ? values.dataset_type : null,
      sync_status: values.sync_status !== 'all' ? values.sync_status : null,
      search: values.search || null,
      created_from: values.created_from || null,
      created_to: values.created_to || null,
      size_min: values.size_min || null,
      size_max: values.size_max || null,
      episodes_min: values.episodes_min || null,
      episodes_max: values.episodes_max || null,
      sort: datasetSortKey !== 'created_at' ? datasetSortKey : null,
      order: datasetSortOrder !== 'desc' ? datasetSortOrder : null,
      page: null
    });
    filterDialogOpen = false;
    const currentHref = `${page.url.pathname}${page.url.search}${page.url.hash}`;
    if (nextHref === currentHref) return;
    await goto(nextHref, {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
      invalidateAll: false
    });
  };

  $effect(() => {
    if ($datasetsQuery.isLoading) {
      return;
    }
    const nextPage = clampPage(currentPage, totalDatasets, PAGE_SIZE);
    if (nextPage !== currentPage) {
      void navigateToPage(nextPage);
    }
  });

  $effect(() => {
    const currentStatusTab = datasetStatusTab;
    if (previousStatusTab === null) {
      previousStatusTab = currentStatusTab;
      return;
    }
    if (currentStatusTab === previousStatusTab) return;
    previousStatusTab = currentStatusTab;
    resetViewState();
  });

  $effect(() => {
    const visibleIds = new Set(displayedDatasets.map((dataset) => dataset.id));
    const nextSelectedIds = selectedIds.filter((id) => visibleIds.has(id));
    if (
      nextSelectedIds.length !== selectedIds.length ||
      nextSelectedIds.some((id, index) => id !== selectedIds[index])
    ) {
      selectedIds = nextSelectedIds;
    }
  });

  const normalizeJob = (job: DatasetSyncJobStatus): DatasetSyncJobStatus => {
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

  const isActiveJobState = (state?: DatasetSyncJobState) => state === 'queued' || state === 'running';
  const isTerminalJobState = (state?: DatasetSyncJobState) =>
    state === 'completed' || state === 'failed' || state === 'cancelled';

  const isNewerJobSnapshot = (next: DatasetSyncJobStatus, prev: DatasetSyncJobStatus | undefined) => {
    if (!prev) return true;
    const nextTs = Date.parse(next.updated_at ?? '');
    const prevTs = Date.parse(prev.updated_at ?? '');
    if (Number.isNaN(nextTs) || Number.isNaN(prevTs)) return true;
    return nextTs >= prevTs;
  };

  const applyJobSnapshot = (job: DatasetSyncJobStatus) => {
    const normalized = normalizeJob(job);
    const previous = jobsById[normalized.job_id];
    if (!isNewerJobSnapshot(normalized, previous)) return;

    jobsById = {
      ...jobsById,
      [normalized.job_id]: normalized
    };

    if (isActiveJobState(normalized.state)) {
      activeJobsByDatasetId = {
        ...activeJobsByDatasetId,
        [normalized.dataset_id]: normalized
      };
      return;
    }

    const activeJob = activeJobsByDatasetId[normalized.dataset_id];
    if (activeJob?.job_id === normalized.job_id) {
      const next = { ...activeJobsByDatasetId };
      delete next[normalized.dataset_id];
      activeJobsByDatasetId = next;
    }
    if (isTerminalJobState(normalized.state)) {
      void queryClient.invalidateQueries({ queryKey: qk.storage.datasetsPrefix() });
    }
  };

  const loadActiveJobs = async () => {
    const response = await api.storage.datasetSyncJobs(false);
    const activeJobs = (response.jobs ?? []).map(normalizeJob);

    const nextJobsById = { ...jobsById };
    const nextActive: Record<string, DatasetSyncJobStatus> = {};

    const preferActiveJob = (next: DatasetSyncJobStatus, prev: DatasetSyncJobStatus | undefined) => {
      if (!prev) return true;
      if (prev.state === 'running' && next.state === 'queued') return false;
      if (next.state === 'running' && prev.state === 'queued') return true;
      return isNewerJobSnapshot(next, prev);
    };

    for (const job of activeJobs) {
      nextJobsById[job.job_id] = job;
      if (preferActiveJob(job, nextActive[job.dataset_id])) {
        nextActive[job.dataset_id] = job;
      }
    }

    jobsById = nextJobsById;
    activeJobsByDatasetId = nextActive;
  };

  const activeJobOf = (datasetId: string) => activeJobsByDatasetId[datasetId] ?? null;

  const openDatasetSyncModal = (jobId: string) => {
    if (!jobId) return;
    selectedSyncJobId = jobId;
    datasetSyncModalOpen = true;
  };

  const startDatasetSync = async (datasetId: string) => {
    const accepted = await api.storage.syncDataset(datasetId);
    const snapshot = await api.storage.datasetSyncJob(accepted.job_id);
    applyJobSnapshot(snapshot);
    return snapshot;
  };

  const cancelDatasetSync = async (jobId: string) => {
    await api.storage.cancelDatasetSyncJob(jobId);
    const snapshot = await api.storage.datasetSyncJob(jobId);
    applyJobSnapshot(snapshot);
    return snapshot;
  };

  const syncButtonLabel = (dataset: DatasetSummary) => {
    const activeJob = activeJobOf(dataset.id);
    if (activeJob) return '中断';
    if (dataset.is_local) return '同期済';
    return '同期';
  };

  const isSyncButtonDisabled = (dataset: DatasetSummary) => {
    const activeJob = activeJobOf(dataset.id);
    if (activeJob) return false;
    if (dataset.is_local) return true;
    if (syncPending) return true;
    if (actionLoading) return true;
    return false;
  };

  const handleSyncDataset = async (dataset: DatasetSummary) => {
    if (datasetStatusTab !== 'active') return;

    const datasetId = dataset.id;
    if (!datasetId) return;
    const activeJob = activeJobOf(datasetId);

    resetMessages();

    if (activeJob) {
      try {
        const snapshot = await cancelDatasetSync(activeJob.job_id);
        syncMessage = snapshot.message ?? `${datasetId} の中断を要求しました。`;
        openDatasetSyncModal(snapshot.job_id);
      } catch (err) {
        syncError = err instanceof Error ? err.message : 'データセット同期の中断に失敗しました。';
      }
      return;
    }

    if (dataset.is_local || syncPending || actionLoading) return;

    try {
      const started = await startDatasetSync(datasetId);
      syncMessage = started.message ?? `${datasetId} の同期を開始しました。`;
      openDatasetSyncModal(started.job_id);
    } catch (err) {
      const status =
        typeof err === 'object' && err !== null && 'status' in err ? Number((err as { status?: unknown }).status) : 0;
      if (status === 409) {
        try {
          await loadActiveJobs();
          const existing = activeJobOf(datasetId);
          if (existing) {
            syncMessage = '同期ジョブが既に実行中です。';
            openDatasetSyncModal(existing.job_id);
            return;
          }
        } catch {
          // ignore
        }
        syncError = '同期ジョブが既に実行中です。';
        return;
      }
      syncError = err instanceof Error ? err.message : 'データセット同期の開始に失敗しました。';
    }
  };

  async function handleSyncSelected() {
    resetMessages();

    if (!syncTargets.length) {
      syncError = '同期対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${syncTargets.length}件のデータセット同期ジョブを登録しますか？`);
    if (!confirmed) return;

    syncPending = true;

    try {
      let enqueued = 0;
      let skipped = 0;
      let failed = 0;
      const failedIds: string[] = [];

      for (const dataset of syncTargets) {
        try {
          await api.storage.syncDataset(dataset.id);
          enqueued += 1;
        } catch (err) {
          const status =
            typeof err === 'object' && err !== null && 'status' in err ? Number((err as { status?: unknown }).status) : 0;
          if (status === 409) {
            skipped += 1;
            continue;
          }
          failed += 1;
          failedIds.push(dataset.id);
        }
      }

      const summary = [`登録 ${enqueued}`, `スキップ ${skipped}`, `失敗 ${failed}`].join(' / ');
      syncMessage = `データセット同期ジョブを登録しました: ${summary}`;
      if (failedIds.length) {
        const preview = failedIds.slice(0, 5).join(', ');
        const suffix = failedIds.length > 5 ? ' ...' : '';
        syncError = `失敗データセット: ${preview}${suffix}`;
      }
      await loadActiveJobs();
    } catch (err) {
      syncError = err instanceof Error ? err.message : 'データセット同期の登録に失敗しました。';
    } finally {
      syncPending = false;
    }
  }

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
  const isRowPending = (datasetId: string, action: DatasetRowAction) =>
    rowPendingId === datasetId && rowPendingAction === action;
  const tabTriggerClass = (value: DatasetStatusTab) => {
    const isActive = datasetStatusTab === value;
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

  const handleDatasetTabChange = (nextValue: string) => {
    const nextTab: DatasetStatusTab = nextValue === 'archived' ? 'archived' : 'active';
    if (nextTab === datasetStatusTab) return;
    resetViewState();
    void goto(
      buildUrlWithQueryState(page.url, {
        status: nextTab !== 'active' ? nextTab : null,
        page: null
      }),
      {
        replaceState: true,
        noScroll: true,
        keepFocus: true,
        invalidateAll: false
      }
    );
  };

  const openArchiveDialog = (dataset: DatasetSummary) => {
    if (datasetStatusTab !== 'active' || actionLoading || archivePendingId || rowPendingId || renamePending) return;
    archiveDialogError = '';
    archiveTarget = dataset;
    archiveDialogOpen = true;
  };

  const openRenameDialog = (dataset: DatasetSummary) => {
    if (actionLoading || archivePendingId || rowPendingId || renamePending) return;
    renameError = '';
    renameTarget = dataset;
    renameDialogOpen = true;
  };

  const openMergeDialog = () => {
    if (!canMerge) return;
    mergeDialogError = '';
    mergeDialogOpen = true;
  };

  const isSortedBy = (key: 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'sync_status') => datasetSortKey === key;
  const sortIconFor = (key: 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'sync_status') =>
    !isSortedBy(key) ? CaretUpDown : datasetSortOrder === 'asc' ? ArrowUp : ArrowDown;
  const NameSortIcon = $derived(sortIconFor('name'));
  const OwnerSortIcon = $derived(sortIconFor('owner_name'));
  const ProfileSortIcon = $derived(sortIconFor('profile_name'));
  const EpisodeSortIcon = $derived(sortIconFor('episode_count'));
  const SizeSortIcon = $derived(sortIconFor('size_bytes'));
  const CreatedAtSortIcon = $derived(sortIconFor('created_at'));
  const SyncSortIcon = $derived(sortIconFor('sync_status'));
  const handleSortChange = async (key: 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'sync_status') => {
    const nextOrder: 'asc' | 'desc' = datasetSortKey === key ? (datasetSortOrder === 'asc' ? 'desc' : 'asc') : 'desc';
    const nextHref = buildUrlWithQueryState(page.url, {
      sort: key !== 'created_at' || nextOrder !== 'desc' ? key : null,
      order: nextOrder !== 'desc' ? nextOrder : null,
      page: null
    });
    const currentHref = `${page.url.pathname}${page.url.search}${page.url.hash}`;
    if (nextHref === currentHref) return;
    await goto(nextHref, {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
      invalidateAll: false
    });
  };

  const startMergeJob = async (payload: { dataset_name: string; source_dataset_ids: string[] }) => {
    const accepted = await api.storage.startDatasetMergeJob(payload);
    mergeJobId = accepted.job_id;
    mergeModalOpen = true;
  };

  const handleMergeCompleted = async (datasetId: string) => {
    actionMessage = `マージ完了: ${datasetId}`;
    actionError = '';
    resetMergeDialog();
    selectedIds = [];
    await refetchDatasets();
  };

  async function handleMerge(datasetName: string) {
    resetMessages();
    mergeDialogError = '';

    if (selectedIds.length < 2) {
      const message = '2件以上のデータセットを選択してください。';
      mergeDialogError = message;
      actionError = message;
      return;
    }
    if (profileMismatch || !profileName) {
      const message = '同一プロファイルのデータセットのみマージできます。';
      mergeDialogError = message;
      actionError = message;
      return;
    }

    const normalizedName = datasetName.trim() || mergeDefaultName;
    if (!normalizedName) {
      const message = '新しいデータセット名を入力してください。';
      mergeDialogError = message;
      actionError = message;
      return;
    }

    actionLoading = true;
    const sourceIds = [...selectedIds];

    try {
      const payload = {
        dataset_name: normalizedName,
        source_dataset_ids: sourceIds
      };
      lastMergePayload = payload;
      await startMergeJob(payload);
      mergeDialogOpen = false;
      actionMessage = 'マージを開始しました。進捗を表示します。';
    } catch (err) {
      const message = err instanceof Error ? err.message : 'マージに失敗しました。';
      mergeDialogError = message;
      actionError = message;
    } finally {
      actionLoading = false;
    }
  }

  async function handleArchiveSelected() {
    resetMessages();

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
      removeSelectedIds(
        response.results.filter((result) => result.status === 'succeeded').map((result) => result.id)
      );
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleRestoreSelected() {
    resetMessages();

    if (!selectedIds.length) {
      actionError = '復元対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件を復元しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    const ids = [...selectedIds];

    try {
      const response = await api.storage.restoreArchive({
        dataset_ids: ids,
        model_ids: []
      });
      applyArchiveBulkMessage(response, '復元を実行しました', response.restored);
      removeSelectedIds(response.restored ?? []);
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleDeleteSelected() {
    resetMessages();

    if (!selectedIds.length) {
      actionError = '完全削除対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件を完全に削除しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    const ids = [...selectedIds];

    try {
      const response = await api.storage.deleteArchive({
        dataset_ids: ids,
        model_ids: []
      });
      applyArchiveBulkMessage(response, '完全削除を実行しました', response.deleted);
      removeSelectedIds(response.deleted ?? []);
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : '完全削除に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleReuploadSelected() {
    resetMessages();

    if (!selectedIds.length) {
      actionError = '再送信対象を選択してください。';
      return;
    }

    const confirmed = confirm(`${selectedIds.length}件をR2へ再送信しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    const ids = [...selectedIds];

    try {
      const response = await api.storage.bulkReuploadDatasets(ids);
      applyBulkResponseMessage(response, '再送信を実行しました');
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : '再送信に失敗しました。';
    } finally {
      actionLoading = false;
    }
  }

  async function handleArchiveTarget() {
    resetMessages();
    archiveDialogError = '';

    const target = archiveTarget;
    if (!target?.id || actionLoading || archivePendingId || rowPendingId) return;

    archivePendingId = target.id;
    try {
      await api.storage.archiveDataset(target.id);
      removeSelectedIds([target.id]);
      actionMessage = `${displayDatasetLabel(target)} をアーカイブしました。`;
      resetArchiveDialog();
      await refetchDatasets();
    } catch (err) {
      archiveDialogError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
      actionError = archiveDialogError;
    } finally {
      archivePendingId = '';
    }
  }

  async function handleRestoreTarget(dataset: DatasetSummary) {
    resetMessages();

    if (!dataset.id || actionLoading || archivePendingId || rowPendingId) return;
    const confirmed = confirm(`${displayDatasetLabel(dataset)} を復元しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    rowPendingId = dataset.id;
    rowPendingAction = 'restore';
    try {
      await api.storage.restoreDataset(dataset.id);
      removeSelectedIds([dataset.id]);
      actionMessage = `${displayDatasetLabel(dataset)} を復元しました。`;
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : '復元に失敗しました。';
    } finally {
      rowPendingId = '';
      rowPendingAction = '';
      actionLoading = false;
    }
  }

  async function handleDeleteTarget(dataset: DatasetSummary) {
    resetMessages();

    if (!dataset.id || actionLoading || archivePendingId || rowPendingId) return;
    const confirmed = confirm(`${displayDatasetLabel(dataset)} を完全に削除しますか？`);
    if (!confirmed) return;

    actionLoading = true;
    rowPendingId = dataset.id;
    rowPendingAction = 'delete';
    try {
      await api.storage.deleteArchivedDataset(dataset.id);
      removeSelectedIds([dataset.id]);
      actionMessage = `${displayDatasetLabel(dataset)} を完全に削除しました。`;
      await refetchDatasets();
    } catch (err) {
      actionError = err instanceof Error ? err.message : '完全削除に失敗しました。';
    } finally {
      rowPendingId = '';
      rowPendingAction = '';
      actionLoading = false;
    }
  }

  async function handleRenameTarget(nextName: string) {
    renameError = '';

    const target = renameTarget;
    if (!target?.id || actionLoading || archivePendingId || rowPendingId) return;

    renamePending = true;
    try {
      await api.storage.renameDataset(target.id, { name: nextName });
      await queryClient.invalidateQueries({ queryKey: qk.storage.dataset(target.id) });
      await refetchDatasets();
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
          subscription_id: `storage.dataset-sync.${job.job_id}`,
          kind: 'storage.dataset-sync',
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
          if (event.op !== 'snapshot' || event.source?.kind !== 'storage.dataset-sync') return;
          applyJobSnapshot(event.payload as DatasetSyncJobStatus);
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
    return () => {
      realtimeContributor?.dispose();
      realtimeContributor = null;
    };
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

<DatasetMergeDialog
  bind:open={mergeDialogOpen}
  selectedCount={selectedIds.length}
  suggestedName={mergeDefaultName}
  profileName={profileName ?? ''}
  pending={actionLoading}
  errorMessage={mergeDialogError}
  onConfirm={handleMerge}
/>

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

<DatasetSyncProgressModal
  bind:open={datasetSyncModalOpen}
  jobId={selectedSyncJobId}
  onCancel={cancelDatasetSync}
/>

<StorageArchiveConfirmDialog
  bind:open={archiveDialogOpen}
  itemKind="dataset"
  itemLabel={archiveTarget ? displayDatasetLabel(archiveTarget) : ''}
  pending={Boolean(archivePendingId)}
  errorMessage={archiveDialogError}
  onConfirm={handleArchiveTarget}
/>

<StorageRenameDialog
  bind:open={renameDialogOpen}
  itemKind="dataset"
  currentName={renameTarget ? displayDatasetLabel(renameTarget) : ''}
  pending={renamePending}
  errorMessage={renameError}
  onConfirm={handleRenameTarget}
/>

{#if !embedded}
  <section class="card-strong p-8">
    <p class="section-title">Storage</p>
    <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="text-3xl font-semibold text-slate-900">データセット管理</h1>
        <p class="mt-2 text-sm text-slate-600">{pageDescription}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button.Root class="btn-ghost" href="/storage">戻る</Button.Root>
      </div>
    </div>
  </section>
{/if}

<svelte:element this={embedded ? 'div' : 'section'} class={embedded ? 'mt-4' : 'card p-6'}>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">データセット一覧</h2>
    <div class="flex flex-wrap items-center gap-2">
      {#if selectedIds.length > 0}
        <span class="text-sm font-semibold text-slate-700">選択中: {selectedIds.length} 件</span>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            class="inline-flex h-10 items-center justify-center gap-2 rounded-full border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
            aria-label="一括操作"
          >
            <DotsThree size={18} weight="bold" />
            一括操作
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              class="z-50 min-w-[220px] rounded-xl border border-slate-200/80 bg-white/95 p-2 text-xs text-slate-700 shadow-lg backdrop-blur"
              sideOffset={6}
              align="end"
              preventScroll={false}
            >
              <DropdownMenu.Group>
                <DropdownMenu.GroupHeading
                  class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                >
                  選択
                </DropdownMenu.GroupHeading>
                <DropdownMenu.Item class={bulkMenuItemClass} onSelect={clearSelection}>
                  <XCircle size={16} class="text-slate-500" />
                  選択解除
                </DropdownMenu.Item>
              </DropdownMenu.Group>

              <DropdownMenu.Separator class="-mx-2 my-1 h-px bg-slate-200/70" />

              <DropdownMenu.Group>
                <DropdownMenu.GroupHeading
                  class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                >
                  一括操作
                </DropdownMenu.GroupHeading>
                {#if isArchiveTab}
                  <DropdownMenu.Item class={bulkMenuItemClass} disabled={!canRestore} onSelect={() => void handleRestoreSelected()}>
                    <ArrowArcLeft size={16} class="text-slate-500" />
                    復元
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    class={bulkMenuDangerItemClass}
                    disabled={!canDelete}
                    onSelect={() => void handleDeleteSelected()}
                  >
                    <TrashSimple size={16} class="text-rose-500" />
                    完全削除
                  </DropdownMenu.Item>
                {:else}
                  <DropdownMenu.Item class={bulkMenuItemClass} disabled={!canMerge} onSelect={openMergeDialog}>
                    <ArrowsMerge size={16} class="text-slate-500" />
                    マージ
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    class={bulkMenuItemClass}
                    disabled={!canSyncSelected}
                    onSelect={() => void handleSyncSelected()}
                  >
                    <CloudArrowDown size={16} class="text-slate-500" />
                    同期
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    class={bulkMenuItemClass}
                    disabled={!canReupload}
                    onSelect={() => void handleReuploadSelected()}
                  >
                    <CloudArrowUp size={16} class="text-slate-500" />
                    再送信
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    class={bulkMenuDangerItemClass}
                    disabled={!canArchive}
                    onSelect={() => void handleArchiveSelected()}
                  >
                    <Archive size={16} class="text-rose-500" />
                    アーカイブ
                  </DropdownMenu.Item>
                {/if}
              </DropdownMenu.Group>

              {#if !isArchiveTab && (selectedIds.length < 2 || profileMismatch)}
                <DropdownMenu.Separator class="-mx-2 my-1 h-px bg-slate-200/70" />
                <DropdownMenu.Group>
                  <DropdownMenu.GroupHeading
                    class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                  >
                    情報
                  </DropdownMenu.GroupHeading>
                  {#if selectedIds.length < 2}
                    <div class="px-3 pb-1 pt-0.5 text-[10px] text-slate-400">マージは 2 件以上の選択が必要です。</div>
                  {/if}
                  {#if profileMismatch}
                    <div class="px-3 pb-1 pt-0.5 text-[10px] text-slate-400">マージは同一プロファイルのデータセットのみ実行できます。</div>
                  {/if}
                </DropdownMenu.Group>
              {/if}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      {:else}
        <PaginationControls
          currentPage={currentPage}
          pageSize={PAGE_SIZE}
          totalItems={totalDatasets}
          disabled={$datasetsQuery.isLoading}
          compact={true}
          onPageChange={navigateToPage}
        />
        <ListFilterPopover
          bind:open={filterDialogOpen}
          fields={datasetFilterFields}
          values={datasetFilterValues}
          defaults={datasetFilterDefaults}
          active={hasActiveDatasetFilters}
          onApply={applyDatasetFilters}
        />
      {/if}
      {#if !embedded}
        <Tabs.Root value={datasetStatusTab} onValueChange={handleDatasetTabChange}>
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
      {/if}
    </div>
  </div>
  <p class="mt-2 text-xs text-slate-500">{helperText}</p>
  {#if actionMessage}
    <p class="mt-3 text-sm text-emerald-600">{actionMessage}</p>
  {/if}
  {#if actionError}
    <p class="mt-2 text-sm text-rose-600">{actionError}</p>
  {/if}
  {#if syncMessage}
    <p class="mt-3 text-sm text-emerald-600">{syncMessage}</p>
  {/if}
  {#if syncError}
    <p class="mt-2 text-sm text-rose-600">{syncError}</p>
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
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('name')}>
              名前
              <NameSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('owner_name')}>
              作成者
              <OwnerSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('profile_name')}>
              プロファイル
              <ProfileSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('episode_count')}>
              エピソード
              <EpisodeSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('size_bytes')}>
              サイズ
              <SizeSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('created_at')}>
              作成日時
              <CreatedAtSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          {#if !isArchiveTab}
            <th class="pb-3 text-center">
              <div class="flex justify-center">
                <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('sync_status')}>
                  同期状態
                  <SyncSortIcon size={14} class={sortIconClass} />
                </button>
              </div>
            </th>
          {/if}
          <th class="pb-3 text-right">操作</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $datasetsQuery.isLoading}
          <tr><td class="py-3" colspan={datasetTableColumnCount}>読み込み中...</td></tr>
        {:else if displayedDatasets.length}
          {#each displayedDatasets as dataset}
            {@const activeJob = activeJobOf(dataset.id)}
            {@const syncStatus = presentDatasetSyncStatus(activeJob, Boolean(dataset.is_local))}
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
              <td class="py-3">{dataset.episode_count ?? 0}</td>
              <td class="py-3">{formatBytes(dataset.size_bytes ?? 0)}</td>
              <td class="py-3">{formatDate(dataset.created_at)}</td>
              {#if !isArchiveTab}
                <td class="py-3 text-center">
                  <div class="flex justify-center">
                    {#if syncStatus.kind === 'progress' && activeJob}
                      <button
                        class="text-xs font-semibold text-brand hover:underline"
                        type="button"
                        onclick={() => openDatasetSyncModal(activeJob.job_id)}
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
                            window.location.href = `/storage/datasets/${dataset.id}`;
                          }}
                        >
                          <FileText size={16} class="text-slate-500" />
                          詳細を開く
                        </DropdownMenu.Item>
                        <DropdownMenu.Item
                          class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                          onSelect={() => openViewer(dataset.id)}
                        >
                          <Eye size={16} class="text-slate-500" />
                          ビューアで開く
                        </DropdownMenu.Item>
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
                          disabled={actionLoading || Boolean(archivePendingId) || Boolean(rowPendingId) || renamePending}
                          onSelect={() => openRenameDialog(dataset)}
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
                            disabled={actionLoading || Boolean(archivePendingId) || Boolean(rowPendingId) || renamePending}
                            onSelect={() => {
                              void handleRestoreTarget(dataset);
                            }}
                          >
                            <ArrowArcLeft size={16} class="text-slate-500" />
                            {#if isRowPending(dataset.id, 'restore')}
                              復元中...
                            {:else}
                              復元
                            {/if}
                          </DropdownMenu.Item>
                          <DropdownMenu.Item
                            class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                            disabled={actionLoading || Boolean(archivePendingId) || Boolean(rowPendingId) || renamePending}
                            onSelect={() => {
                              void handleDeleteTarget(dataset);
                            }}
                          >
                            <TrashSimple size={16} class="text-rose-500" />
                            {#if isRowPending(dataset.id, 'delete')}
                              完全削除中...
                            {:else}
                              完全削除
                            {/if}
                          </DropdownMenu.Item>
                        {:else}
                          <DropdownMenu.Item
                            class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                            disabled={isSyncButtonDisabled(dataset) || renamePending}
                            onSelect={() => {
                              void handleSyncDataset(dataset);
                            }}
                          >
                            {#if activeJob}
                              <StopCircle size={16} class="text-slate-500" />
                            {:else if dataset.is_local}
                              <CheckCircle size={16} class="text-slate-500" />
                            {:else}
                              <CloudArrowDown size={16} class="text-slate-500" />
                            {/if}
                            {syncButtonLabel(dataset)}
                          </DropdownMenu.Item>
                          <DropdownMenu.Item
                            class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                            disabled={actionLoading || Boolean(archivePendingId) || Boolean(rowPendingId) || renamePending}
                            onSelect={() => openArchiveDialog(dataset)}
                          >
                            <Archive size={16} class="text-rose-500" />
                            {#if isArchivePending(dataset.id)}
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
          <tr><td class="py-3" colspan={datasetTableColumnCount}>{emptyStateText}</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
  <PaginationControls
    currentPage={currentPage}
    pageSize={PAGE_SIZE}
    totalItems={totalDatasets}
    disabled={$datasetsQuery.isLoading}
    onPageChange={navigateToPage}
  />
</svelte:element>

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
  import CaretUpDown from 'phosphor-svelte/lib/CaretUpDown';
  import CheckCircle from 'phosphor-svelte/lib/CheckCircle';
  import CloudArrowDown from 'phosphor-svelte/lib/CloudArrowDown';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import FileText from 'phosphor-svelte/lib/FileText';
  import FolderOpen from 'phosphor-svelte/lib/FolderOpen';
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
    type ModelSyncJobState,
    type ModelSyncJobStatus
  } from '$lib/api/client';
  import ListFilterPopover from '$lib/components/ListFilterPopover.svelte';
  import PaginationControls from '$lib/components/PaginationControls.svelte';
  import TableSkeletonRows from '$lib/components/TableSkeletonRows.svelte';
  import type { ListFilterField } from '$lib/listFilters';
  import {
    DEFAULT_PAGE_SIZE,
    PAGE_SIZE_OPTIONS,
    buildPageHref,
    buildUrlWithQueryState,
    clampPage,
    parsePageParam,
    parsePageSizeParam
  } from '$lib/pagination';
  import { qk } from '$lib/queryKeys';
  import { formatBytes, formatDate } from '$lib/format';
  import { buildTableSkeletonRows } from '$lib/tableSkeleton';
  import { updateSelectedId, updateSelectedPageIds } from '$lib/tableSelection';
  import {
    registerRealtimeTrackConsumer,
    type RealtimeTrackConsumerHandle,
    type RealtimeTrackEvent,
    type RealtimeTrackSelector
  } from '$lib/realtime/trackClient';
  import ModelSyncProgressModal from '$lib/components/storage/ModelSyncProgressModal.svelte';
  import StorageArchiveConfirmDialog from '$lib/components/storage/StorageArchiveConfirmDialog.svelte';
  import StorageRenameDialog from '$lib/components/storage/StorageRenameDialog.svelte';
  import { presentModelSyncStatus } from '$lib/storage/transferStatus';

  type Props = {
    embedded?: boolean;
  };

  let { embedded = false }: Props = $props();

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
    policy_type_options?: Array<{
      value: string;
      label: string;
      total_count?: number;
      available_count?: number;
    }>;
  };

  type ModelStatusTab = 'active' | 'archived';
  type ModelRowAction = '' | 'restore' | 'delete';
  const MODEL_SORT_KEYS = ['created_at', 'name', 'owner_name', 'profile_name', 'size_bytes', 'policy_type'] as const;
  const parseModelStatusTab = (value: string | null): ModelStatusTab => (value === 'archived' ? 'archived' : 'active');
  const parseModelSortKey = (value: string | null): 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'size_bytes' | 'policy_type' =>
    MODEL_SORT_KEYS.includes((value ?? '') as (typeof MODEL_SORT_KEYS)[number])
      ? ((value ?? '') as 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'size_bytes' | 'policy_type')
      : 'created_at';
  const parseSortOrder = (value: string | null): 'desc' | 'asc' => (value === 'asc' ? 'asc' : 'desc');

  const queryClient = useQueryClient();

  let filterDialogOpen = $state(false);
  let syncAllPending = $state(false);
  let syncMessage = $state('');
  let syncError = $state('');
  let bulkMessage = $state('');
  let bulkError = $state('');
  let bulkPending = $state(false);
  let selectedIds = $state<string[]>([]);
  const modelStatusTab = $derived(parseModelStatusTab(page.url.searchParams.get('status')));
  let previousStatusTab = $state<ModelStatusTab | null>(null);
  const modelSortKey = $derived(parseModelSortKey(page.url.searchParams.get('sort')));
  const modelSortOrder = $derived(parseSortOrder(page.url.searchParams.get('order')));
  const modelOwnerFilter = $derived(page.url.searchParams.get('owner') || 'all');
  const modelProfileFilter = $derived(page.url.searchParams.get('profile') || 'all');
  const modelPolicyFilter = $derived(page.url.searchParams.get('policy') || 'all');
  const modelSearch = $derived(page.url.searchParams.get('search') || '');
  const modelDatasetFilter = $derived(page.url.searchParams.get('dataset') || '');
  const modelCreatedFrom = $derived(page.url.searchParams.get('created_from') || '');
  const modelCreatedTo = $derived(page.url.searchParams.get('created_to') || '');
  const modelSizeMin = $derived(page.url.searchParams.get('size_min') || '');
  const modelSizeMax = $derived(page.url.searchParams.get('size_max') || '');
  let jobsById = $state<Record<string, ModelSyncJobStatus>>({});
  let activeJobsByModelId = $state<Record<string, ModelSyncJobStatus>>({});
  let locallySyncedModelIds = $state<Record<string, boolean>>({});
  let realtimeContributor: RealtimeTrackConsumerHandle | null = null;
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

  const pageSize = $derived(parsePageSizeParam(page.url.searchParams.get('page_size')));
  const currentPage = $derived(parsePageParam(page.url.searchParams.get('page')));
  const parseOptionalInt = (value: string) => {
    const normalized = value.trim();
    if (!normalized) return undefined;
    const parsed = Number.parseInt(normalized, 10);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const modelsQuery = createQuery<ModelListResponse>(
    toStore(() => {
      const status = modelStatusTab;
      const ownerUserId = modelOwnerFilter === 'all' ? undefined : modelOwnerFilter;
      const profileName = modelProfileFilter === 'all' ? undefined : modelProfileFilter;
      const policyType = modelPolicyFilter === 'all' ? undefined : modelPolicyFilter;
      const search = modelSearch || undefined;
      return {
        queryKey: qk.storage.models({
          status,
          ownerUserId,
          profileName,
          policyType,
          datasetId: modelDatasetFilter || undefined,
          search,
          createdFrom: modelCreatedFrom || undefined,
          createdTo: modelCreatedTo || undefined,
          sizeMin: parseOptionalInt(modelSizeMin),
          sizeMax: parseOptionalInt(modelSizeMax),
          sortBy: modelSortKey,
          sortOrder: modelSortOrder,
          limit: pageSize,
          offset: (currentPage - 1) * pageSize
        }),
        queryFn: () =>
          api.storage.models({
            status,
            ownerUserId,
            profileName,
            policyType,
            datasetId: modelDatasetFilter || undefined,
            search,
            createdFrom: modelCreatedFrom || undefined,
            createdTo: modelCreatedTo || undefined,
            sizeMin: parseOptionalInt(modelSizeMin),
            sizeMax: parseOptionalInt(modelSizeMax),
            sortBy: modelSortKey,
            sortOrder: modelSortOrder,
            limit: pageSize,
            offset: (currentPage - 1) * pageSize
          })
      };
    })
  );

  const models = $derived($modelsQuery.data?.models ?? []);
  const totalModels = $derived($modelsQuery.data?.total ?? 0);
  const displayedModels = $derived(models);
  const showModelSkeleton = $derived(
    $modelsQuery.isLoading || ($modelsQuery.isFetching && displayedModels.length === 0)
  );
  const modelSkeletonRows = $derived(
    buildTableSkeletonRows(pageSize, 0, showModelSkeleton)
  );
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
  const modelActiveSkeletonCells = [
    { tdClass: 'w-12 py-3 align-middle', barClass: 'h-4 w-4', wrapperClass: 'flex justify-center' },
    { tdClass: 'py-3 font-semibold text-slate-800', barClass: 'h-4 w-44 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-24 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-28 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-20 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-16 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-28 max-w-full' },
    { tdClass: 'py-3 text-center', barClass: 'h-3 w-16 max-w-full', wrapperClass: 'flex justify-center' },
    { tdClass: 'py-3 pr-3 text-right', barClass: 'h-8 w-8', barRadiusClass: 'rounded-full', wrapperClass: 'ml-auto flex w-8 justify-center' }
  ];
  const modelArchivedSkeletonCells = [
    { tdClass: 'w-12 py-3 align-middle', barClass: 'h-4 w-4', wrapperClass: 'flex justify-center' },
    { tdClass: 'py-3 font-semibold text-slate-800', barClass: 'h-4 w-44 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-24 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-28 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-20 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-16 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-28 max-w-full' },
    { tdClass: 'py-3 pr-3 text-right', barClass: 'h-8 w-8', barRadiusClass: 'rounded-full', wrapperClass: 'ml-auto flex w-8 justify-center' }
  ];
  const modelSkeletonCells = $derived(
    isArchiveTab ? modelArchivedSkeletonCells : modelActiveSkeletonCells
  );

  const creatorLabel = (value?: string | null) => {
    const normalized = String(value ?? '').trim();
    if (!normalized) return '-';
    if (normalized.length <= 24) return normalized;
    return `${normalized.slice(0, 20)}...`;
  };
  const ownerLabel = (model: ModelSummary) =>
    creatorLabel(model.owner_name ?? model.owner_email ?? model.owner_user_id);
  const displayModelLabel = (model: ModelSummary) => model.name ?? model.id;
  const isModelLocal = (model: ModelSummary) => Boolean(model.is_local) || Boolean(locallySyncedModelIds[model.id]);
  const isActiveJobState = (state?: ModelSyncJobState) => state === 'queued' || state === 'running';
  const isTerminalJobState = (state?: ModelSyncJobState) =>
    state === 'completed' || state === 'failed' || state === 'cancelled';

  const syncPending = $derived(syncAllPending);
  const modelOwnerOptions = $derived($modelsQuery.data?.owner_options ?? []);
  const modelProfileOptions = $derived($modelsQuery.data?.profile_options ?? []);
  const modelPolicyOptions = $derived($modelsQuery.data?.policy_type_options ?? []);
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
  const modelOwnerSelectOptions = $derived.by(() => {
    const options = [
      { value: 'all', label: '全員' },
      ...modelOwnerOptions.map((owner) => ({
        value: owner.user_id,
        label: owner.label,
        disabled: owner.available_count === 0 && owner.user_id !== modelOwnerFilter
      }))
    ];
    if (modelOwnerFilter !== 'all' && !options.some((option) => option.value === modelOwnerFilter)) {
      options.push({ value: modelOwnerFilter, label: modelOwnerFilter });
    }
    return options;
  });
  const modelProfileSelectOptions = $derived(withAllOption(modelProfileFilter, modelProfileOptions));
  const modelPolicySelectOptions = $derived(withAllOption(modelPolicyFilter, modelPolicyOptions));
  const modelFilterDefaults = {
    search: '',
    owner: 'all',
    profile: 'all',
    policy: 'all',
    dataset: '',
    created_from: '',
    created_to: '',
    size_min: '',
    size_max: '',
    page_size: String(DEFAULT_PAGE_SIZE)
  };
  const modelFilterValues = $derived({
    search: modelSearch,
    owner: modelOwnerFilter,
    profile: modelProfileFilter,
    policy: modelPolicyFilter,
    dataset: modelDatasetFilter,
    created_from: modelCreatedFrom,
    created_to: modelCreatedTo,
    size_min: modelSizeMin,
    size_max: modelSizeMax,
    page_size: String(pageSize)
  });
  const modelFilterFields = $derived<ListFilterField[]>([
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
      options: modelOwnerSelectOptions
    },
    {
      section: '条件',
      type: 'select',
      key: 'profile',
      label: 'プロファイル',
      options: modelProfileSelectOptions
    },
    {
      section: '条件',
      type: 'select',
      key: 'policy',
      label: 'ポリシー',
      options: modelPolicySelectOptions
    },
    {
      section: '条件',
      type: 'text',
      key: 'dataset',
      label: '元データセット',
      placeholder: 'データセット ID で絞り込み'
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
      section: '表示',
      type: 'select',
      key: 'page_size',
      label: '1ページの件数',
      options: PAGE_SIZE_OPTIONS.map((size) => ({ value: String(size), label: `${size}件` }))
    }
  ]);
  const hasActiveModelFilters = $derived(
    Boolean(modelSearch) ||
      modelOwnerFilter !== 'all' ||
      modelProfileFilter !== 'all' ||
      modelPolicyFilter !== 'all' ||
      Boolean(modelDatasetFilter) ||
      Boolean(modelCreatedFrom) ||
      Boolean(modelCreatedTo) ||
      Boolean(modelSizeMin) ||
      Boolean(modelSizeMax) ||
      pageSize !== DEFAULT_PAGE_SIZE
  );
  const sortIconClass = 'text-slate-400 transition group-hover:text-slate-600';
  const sortableHeaderButtonClass =
    'group inline-flex items-center gap-1 font-semibold text-slate-400 transition hover:text-slate-700';
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

  const resetViewState = () => {
    clearSelection();
    resetMessages();
    resetArchiveDialog();
    resetRenameDialog();
    filterDialogOpen = false;
    rowPendingId = '';
    rowPendingAction = '';
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
  const applyModelFilters = async (values: Record<string, string>) => {
    const nextHref = buildUrlWithQueryState(page.url, {
      status: modelStatusTab !== 'active' ? modelStatusTab : null,
      owner: values.owner !== 'all' ? values.owner : null,
      profile: values.profile !== 'all' ? values.profile : null,
      policy: values.policy !== 'all' ? values.policy : null,
      sync_status: null,
      search: values.search || null,
      dataset: values.dataset || null,
      created_from: values.created_from || null,
      created_to: values.created_to || null,
      size_min: values.size_min || null,
      size_max: values.size_max || null,
      page_size: values.page_size !== String(DEFAULT_PAGE_SIZE) ? values.page_size : null,
      sort: modelSortKey !== 'created_at' ? modelSortKey : null,
      order: modelSortOrder !== 'desc' ? modelSortOrder : null,
      page: null
    });
    filterDialogOpen = false;
    const currentHref = `${page.url.pathname}${page.url.search}${page.url.hash}`;
    if (nextHref === currentHref) return;
    clearSelection();
    await goto(nextHref, {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
      invalidateAll: false
    });
  };

  $effect(() => {
    if ($modelsQuery.isLoading) {
      return;
    }
    const nextPage = clampPage(currentPage, totalModels, pageSize);
    if (nextPage !== currentPage) {
      void navigateToPage(nextPage);
    }
  });

  $effect(() => {
    const nextOverrides = { ...locallySyncedModelIds };
    let changed = false;
    for (const model of models) {
      if (!model.is_local) continue;
      if (!nextOverrides[model.id]) continue;
      delete nextOverrides[model.id];
      changed = true;
    }
    if (changed) {
      locallySyncedModelIds = nextOverrides;
    }
  });

  $effect(() => {
    const currentStatusTab = modelStatusTab;
    if (previousStatusTab === null) {
      previousStatusTab = currentStatusTab;
      return;
    }
    if (currentStatusTab === previousStatusTab) return;
    previousStatusTab = currentStatusTab;
    resetViewState();
  });

  const toggleSelectAllDisplayedModels = () => {
    selectedIds = updateSelectedPageIds(selectedIds, allDisplayedModelIds, !allDisplayedModelsSelected);
  };

  const toggleSelectedModel = (modelId: string, selected: boolean) => {
    selectedIds = updateSelectedId(selectedIds, modelId, selected);
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
  const isSortedBy = (key: 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'size_bytes' | 'policy_type') => modelSortKey === key;
  const sortIconFor = (key: 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'size_bytes' | 'policy_type') =>
    !isSortedBy(key) ? CaretUpDown : modelSortOrder === 'asc' ? ArrowUp : ArrowDown;
  const NameSortIcon = $derived(sortIconFor('name'));
  const OwnerSortIcon = $derived(sortIconFor('owner_name'));
  const ProfileSortIcon = $derived(sortIconFor('profile_name'));
  const PolicySortIcon = $derived(sortIconFor('policy_type'));
  const SizeSortIcon = $derived(sortIconFor('size_bytes'));
  const CreatedAtSortIcon = $derived(sortIconFor('created_at'));
  const handleSortChange = async (key: 'created_at' | 'name' | 'owner_name' | 'profile_name' | 'size_bytes' | 'policy_type') => {
    const nextOrder: 'asc' | 'desc' = modelSortKey === key ? (modelSortOrder === 'asc' ? 'desc' : 'asc') : 'desc';
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
  const openModelDetail = async (modelId: string) => {
    await goto(`/storage/models/${modelId}`);
  };
  const handleRowKeydown = async (event: KeyboardEvent, modelId: string) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    await openModelDetail(modelId);
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
    if (normalized.state === 'completed') {
      locallySyncedModelIds = {
        ...locallySyncedModelIds,
        [normalized.model_id]: true
      };
    } else {
      const nextOverrides = { ...locallySyncedModelIds };
      if (nextOverrides[normalized.model_id]) {
        delete nextOverrides[normalized.model_id];
        locallySyncedModelIds = nextOverrides;
      }
    }
    if (isTerminalJobState(normalized.state)) {
      void queryClient.invalidateQueries({ queryKey: qk.storage.modelsPrefix() });
    }
  };

  const selectedModels = $derived(models.filter((model) => selectedIds.includes(model.id)));
  const syncTargets = $derived(selectedModels.filter((model) => !isModelLocal(model)));
  const canSyncSelected = $derived(!isArchiveTab && syncTargets.length > 0 && !bulkPending && !syncAllPending);
  const canArchiveSelected = $derived(!isArchiveTab && selectedIds.length > 0 && !bulkPending && !syncAllPending);
  const canRestoreSelected = $derived(isArchiveTab && selectedIds.length > 0 && !bulkPending && !syncAllPending);
  const canDeleteSelected = $derived(isArchiveTab && selectedIds.length > 0 && !bulkPending && !syncAllPending);
  const bulkMenuItemClass =
    'flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent';
  const bulkMenuDangerItemClass =
    'flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent';

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

    if (isModelLocal(model) || syncAllPending || bulkPending) return;

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

    const targets = models.filter((model) => !isModelLocal(model));
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

  const syncButtonLabel = (model: ModelSummary) => {
    const activeJob = activeJobOf(model.id);
    if (activeJob) return '中断';
    if (isModelLocal(model)) return '同期済';
    return '同期';
  };

  const isSyncButtonDisabled = (model: ModelSummary) => {
    const activeJob = activeJobOf(model.id);
    if (activeJob) return false;
    if (isModelLocal(model)) return true;
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

  const activeJobTracks = $derived.by(() =>
    Object.keys(jobsById)
      .map((jobId) => jobsById[jobId])
      .filter((job) => isActiveJobState(job?.state))
      .map(
        (job): RealtimeTrackSelector => ({
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
      realtimeContributor = registerRealtimeTrackConsumer({
        tracks: activeJobTracks,
        onEvent: (event: RealtimeTrackEvent) => {
          if (event.kind !== 'storage.model-sync') return;
          applyJobSnapshot(event.detail as ModelSyncJobStatus);
        }
      });
      if (!realtimeContributor) {
        return;
      }
      return;
    }
    realtimeContributor.setTracks(activeJobTracks);
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

{#if !embedded}
  <section class="card-strong p-8">
    <p class="section-title">Storage</p>
    <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="text-3xl font-semibold text-slate-900">モデル</h1>
        <p class="mt-2 text-sm text-slate-600">{pageDescription}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button.Root class="btn-ghost" href="/storage">ビューに戻る</Button.Root>
        {#if !isArchiveTab}
          <button class="btn-ghost" type="button" onclick={handleSyncAll} disabled={syncPending || bulkPending || !models.length}>
            {syncAllPending ? '全て同期中...' : '全て同期'}
          </button>
        {/if}
      </div>
    </div>
  </section>
{/if}

<svelte:element this={embedded ? 'div' : 'section'} class={embedded ? 'mt-4' : 'card p-6'}>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">モデル一覧</h2>
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
                  <DropdownMenu.Item
                    class={bulkMenuItemClass}
                    disabled={!canRestoreSelected}
                    onSelect={() => void handleRestoreSelected()}
                  >
                    <ArrowArcLeft size={16} class="text-slate-500" />
                    復元
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    class={bulkMenuDangerItemClass}
                    disabled={!canDeleteSelected}
                    onSelect={() => void handleDeleteSelected()}
                  >
                    <TrashSimple size={16} class="text-rose-500" />
                    完全削除
                  </DropdownMenu.Item>
                {:else}
                  <DropdownMenu.Item
                    class={bulkMenuItemClass}
                    disabled={!canSyncSelected}
                    onSelect={() => void handleSyncSelected()}
                  >
                    <CloudArrowDown size={16} class="text-slate-500" />
                    同期
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    class={bulkMenuDangerItemClass}
                    disabled={!canArchiveSelected}
                    onSelect={() => void handleArchiveSelected()}
                  >
                    <Archive size={16} class="text-rose-500" />
                    アーカイブ
                  </DropdownMenu.Item>
                {/if}
              </DropdownMenu.Group>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      {:else}
        {#if embedded && !isArchiveTab}
          <button class="btn-ghost" type="button" onclick={handleSyncAll} disabled={syncPending || bulkPending || !models.length}>
            {syncAllPending ? '全て同期中...' : '全て同期'}
          </button>
        {/if}
        <PaginationControls
          currentPage={currentPage}
          pageSize={pageSize}
          totalItems={totalModels}
          disabled={$modelsQuery.isLoading}
          compact={true}
          onPageChange={navigateToPage}
        />
        <ListFilterPopover
          bind:open={filterDialogOpen}
          fields={modelFilterFields}
          values={modelFilterValues}
          defaults={modelFilterDefaults}
          active={hasActiveModelFilters}
          onApply={applyModelFilters}
        />
      {/if}
      {#if !embedded}
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
      {/if}
    </div>
  </div>
  <p class="mt-2 text-xs text-slate-500">{helperText}</p>
  {#if bulkMessage}
    <p class="mt-3 text-sm text-emerald-600">{bulkMessage}</p>
  {/if}
  {#if bulkError}
    <p class="mt-2 text-sm text-rose-600">{bulkError}</p>
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
                checked={allDisplayedModelsSelected}
                aria-label="表示中のモデルを全選択"
                onchange={toggleSelectAllDisplayedModels}
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
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('policy_type')}>
              ポリシー
              <PolicySortIcon size={14} class={sortIconClass} />
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
              <div class="flex justify-center">同期状態</div>
            </th>
          {/if}
          <th class="w-14 pb-3 pr-3">
            <div class="ml-auto flex w-8 justify-center">操作</div>
          </th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if showModelSkeleton}
          <TableSkeletonRows rows={modelSkeletonRows} cells={modelSkeletonCells} />
        {:else if displayedModels.length}
          {#each displayedModels as model}
            {@const activeJob = activeJobOf(model.id)}
            {@const syncStatus = presentModelSyncStatus(activeJob, isModelLocal(model))}
            <tr
              class={`cursor-pointer border-t border-slate-200/60 transition focus-within:bg-slate-100/80 ${
                selectedIds.includes(model.id) ? 'bg-slate-50/80' : 'hover:bg-slate-100/80'
              }`}
              tabindex="0"
              role="link"
              aria-label={`${displayModelLabel(model)} の詳細を開く`}
              onclick={() => void openModelDetail(model.id)}
              onkeydown={(event) => void handleRowKeydown(event, model.id)}
            >
              <td class="w-12 py-3 align-middle" onclick={(event) => event.stopPropagation()}>
                <div class="flex justify-center">
                  <input
                    type="checkbox"
                    class="block h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                    checked={selectedIds.includes(model.id)}
                    value={model.id}
                    onchange={(event) =>
                      toggleSelectedModel(model.id, (event.currentTarget as HTMLInputElement).checked)}
                  />
                </div>
              </td>
              <td class="py-3 font-semibold text-slate-800">
                <span class="block max-w-[25ch] truncate" title={displayModelLabel(model)}>
                  {displayModelLabel(model)}
                </span>
              </td>
              <td class="py-3">{ownerLabel(model)}</td>
              <td class="py-3">{model.profile_name ?? '-'}</td>
              <td class="py-3">{model.policy_type ?? '-'}</td>
              <td class="py-3">{formatBytes(model.size_bytes ?? 0)}</td>
              <td class="py-3">{formatDate(model.created_at)}</td>
              {#if !isArchiveTab}
                <td class="py-3 text-center" onclick={(event) => event.stopPropagation()}>
                  <div class="flex justify-center">
                    {#if syncStatus.kind === 'progress' && activeJob}
                      <button
                        class="text-xs font-semibold text-brand hover:underline"
                        type="button"
                        onclick={() => openModelSyncModal(activeJob.job_id)}
                      >
                        {syncStatus.label}
                      </button>
                    {:else if !isModelLocal(model) && !isArchiveTab}
                      <button
                        class="text-xs font-semibold text-brand hover:underline disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline"
                        type="button"
                        disabled={isSyncButtonDisabled(model)}
                        onclick={() => void handleSyncModel(model)}
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
              <td class="py-3 pr-3 text-right" onclick={(event) => event.stopPropagation()}>
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
                          onSelect={() => void openModelDetail(model.id)}
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
                            {:else if isModelLocal(model)}
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
    pageSize={pageSize}
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
</svelte:element>

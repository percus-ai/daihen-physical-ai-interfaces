<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onDestroy } from 'svelte';
  import { Button, DropdownMenu } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import toast from 'svelte-french-toast';
  import Archive from 'phosphor-svelte/lib/Archive';
  import ArrowDown from 'phosphor-svelte/lib/ArrowDown';
  import ArrowUp from 'phosphor-svelte/lib/ArrowUp';
  import CaretUpDown from 'phosphor-svelte/lib/CaretUpDown';
  import CloudArrowUp from 'phosphor-svelte/lib/CloudArrowUp';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import Eye from 'phosphor-svelte/lib/Eye';
  import XCircle from 'phosphor-svelte/lib/XCircle';
  import { api, type BulkActionResponse } from '$lib/api/client';
  import ListFilterPopover from '$lib/components/ListFilterPopover.svelte';
  import PaginationControls from '$lib/components/PaginationControls.svelte';
  import TableSkeletonRows from '$lib/components/TableSkeletonRows.svelte';
  import { formatBytes, formatDate } from '$lib/format';
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
  import { buildTableSkeletonRows } from '$lib/tableSkeleton';
  import { updateSelectedId, updateSelectedPageIds } from '$lib/tableSelection';
  import {
    registerRealtimeTrackConsumer,
    type RealtimeTrackConsumerHandle,
    type RealtimeTrackEvent,
    type RealtimeTrackSelector
  } from '$lib/realtime/trackClient';
  import { queryClient } from '$lib/queryClient';
  import SystemStatusTab from '$lib/components/system/SystemStatusTab.svelte';
  import DatasetUploadProgressModal from '$lib/components/storage/DatasetUploadProgressModal.svelte';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';
  import {
    RECORDER_STATUS_THROTTLE_MS,
    RECORDER_STATUS_TOPIC,
    getRecorderActiveDatasetId,
    getRecorderDisplayEpisodeNumber,
    parseRecorderPayload,
    type RecorderStatus,
    type RosbridgeStatus
  } from '$lib/recording/recorderStatus';
  import {
    createPendingRecordingUploadStatus,
    shouldIgnoreIdleUploadSnapshot
  } from '$lib/recording/uploadStatus';
  import { presentRecordingUploadStatus } from '$lib/storage/transferStatus';
  import ActiveSessionSection from '$lib/components/ActiveSessionSection.svelte';
  import ActiveSessionCard from '$lib/components/ActiveSessionCard.svelte';
  import { sessionViewer } from '$lib/viewer/sessionViewerStore';
  import type { SystemStatusSnapshot } from '$lib/types/systemStatus';

  type RecordingSummary = {
    recording_id: string;
    dataset_name?: string;
    task?: string;
    profile_name?: string;
    owner_user_id?: string;
    owner_email?: string;
    owner_name?: string;
    created_at?: string;
    episode_count?: number;
    target_total_episodes?: number;
    remaining_episodes?: number;
    episode_time_s?: number;
    reset_time_s?: number;
    continuable?: boolean;
    size_bytes?: number;
    is_local?: boolean;
    is_uploaded?: boolean;
  };

  type RecordingListResponse = {
    recordings?: RecordingSummary[];
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
    upload_status_options?: Array<{
      value: string;
      label: string;
      total_count?: number;
      available_count?: number;
    }>;
  };
  type UserConfigResponse = {
    user_id?: string;
    email?: string;
  };

  type RecordingUploadStatus = {
    dataset_id: string;
    status: 'idle' | 'running' | 'completed' | 'failed' | 'disabled' | string;
    phase: string;
    progress_percent: number;
    message: string;
    files_done: number;
    total_files: number;
    current_file?: string | null;
    error?: string | null;
    updated_at?: string | null;
  };

  type OperateStatusResponse = {
    network?: {
      status?: string;
      details?: {
        zmq?: { status?: string };
        zenoh?: { status?: string };
        rosbridge?: { status?: string };
      };
    };
  };
  type OperateStatusStreamPayload = {
    operate_status?: OperateStatusResponse;
  };

  const operateStatusQuery = createQuery<OperateStatusResponse>({
    queryKey: ['operate', 'status'],
    queryFn: api.operate.status
  });
  const userConfigQuery = createQuery<UserConfigResponse>({
    queryKey: ['user', 'config'],
    queryFn: () => api.user.config() as Promise<UserConfigResponse>
  });

  const RECORDING_SORT_KEYS = ['created_at', 'dataset_name', 'owner_name', 'profile_name', 'episode_count', 'size_bytes', 'status'] as const;
  const parseRecordingSortKey = (value: string | null): 'created_at' | 'dataset_name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'status' =>
    RECORDING_SORT_KEYS.includes((value ?? '') as (typeof RECORDING_SORT_KEYS)[number])
      ? ((value ?? '') as 'created_at' | 'dataset_name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'status')
      : 'created_at';
  const parseSortOrder = (value: string | null): 'desc' | 'asc' => (value === 'asc' ? 'asc' : 'desc');

  let filterDialogOpen = $state(false);
  let selectedRecordingIds = $state<string[]>([]);
  let recordingOwnerFilterInitialized = $state(false);
  let bulkPending = $state(false);
  let bulkMessage = $state('');
  let bulkError = $state('');

  let reuploadBusy = $state<Record<string, boolean>>({});
  let archiveBusy = $state<Record<string, boolean>>({});
  let uploadStatusMap = $state<Record<string, RecordingUploadStatus>>({});
  let systemStatusSnapshot = $state<SystemStatusSnapshot | null>(null);
  let realtimeContributor: RealtimeTrackConsumerHandle | null = null;
  let uploadModalOpen = $state(false);
  let selectedUploadDatasetId = $state('');

  const recordingSortKey = $derived(parseRecordingSortKey(page.url.searchParams.get('sort')));
  const recordingSortOrder = $derived(parseSortOrder(page.url.searchParams.get('order')));
  const recordingOwnerFilter = $derived(page.url.searchParams.get('owner') || 'all');
  const recordingProfileFilter = $derived(page.url.searchParams.get('profile') || 'all');
  const recordingUploadFilter = $derived(page.url.searchParams.get('upload_status') || 'all');
  const recordingSearch = $derived(page.url.searchParams.get('search') || '');
  const recordingCreatedFrom = $derived(page.url.searchParams.get('created_from') || '');
  const recordingCreatedTo = $derived(page.url.searchParams.get('created_to') || '');
  const recordingSizeMin = $derived(page.url.searchParams.get('size_min') || '');
  const recordingSizeMax = $derived(page.url.searchParams.get('size_max') || '');
  const recordingEpisodeMin = $derived(page.url.searchParams.get('episodes_min') || '');
  const recordingEpisodeMax = $derived(page.url.searchParams.get('episodes_max') || '');
  const pageSize = $derived(parsePageSizeParam(page.url.searchParams.get('page_size')));
  const currentPage = $derived(parsePageParam(page.url.searchParams.get('page')));
  const recordingSortQuery = $derived(recordingSortKey === 'status' ? 'upload_status' : recordingSortKey);
  const parseOptionalInt = (value: string) => {
    const normalized = value.trim();
    if (!normalized) return undefined;
    const parsed = Number.parseInt(normalized, 10);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const recordingsQuery = createQuery<RecordingListResponse>(
    toStore(() => ({
      queryKey: [
        'recording',
        'recordings',
        {
          ownerUserId: recordingOwnerFilter === 'all' ? undefined : recordingOwnerFilter,
          profileName: recordingProfileFilter === 'all' ? undefined : recordingProfileFilter,
          uploadStatus: recordingUploadFilter === 'all' ? undefined : recordingUploadFilter,
          search: recordingSearch || undefined,
          createdFrom: recordingCreatedFrom || undefined,
          createdTo: recordingCreatedTo || undefined,
          sizeMin: parseOptionalInt(recordingSizeMin),
          sizeMax: parseOptionalInt(recordingSizeMax),
          episodeCountMin: parseOptionalInt(recordingEpisodeMin),
          episodeCountMax: parseOptionalInt(recordingEpisodeMax),
          sortBy: recordingSortQuery,
          sortOrder: recordingSortOrder,
          limit: pageSize,
          offset: (currentPage - 1) * pageSize
        }
      ],
      queryFn: () =>
        api.recording.list({
          ownerUserId: recordingOwnerFilter === 'all' ? undefined : recordingOwnerFilter,
          profileName: recordingProfileFilter === 'all' ? undefined : recordingProfileFilter,
          uploadStatus: recordingUploadFilter === 'all' ? undefined : recordingUploadFilter,
          search: recordingSearch || undefined,
          createdFrom: recordingCreatedFrom || undefined,
          createdTo: recordingCreatedTo || undefined,
          sizeMin: parseOptionalInt(recordingSizeMin),
          sizeMax: parseOptionalInt(recordingSizeMax),
          episodeCountMin: parseOptionalInt(recordingEpisodeMin),
          episodeCountMax: parseOptionalInt(recordingEpisodeMax),
          sortBy: recordingSortQuery,
          sortOrder: recordingSortOrder,
          limit: pageSize,
          offset: (currentPage - 1) * pageSize
        })
    }))
  );

  const recordings = $derived($recordingsQuery.data?.recordings ?? []);
  const totalRecordings = $derived($recordingsQuery.data?.total ?? 0);
  const displayedRecordings = $derived(recordings);
  const showRecordingSkeleton = $derived(
    $recordingsQuery.isLoading || ($recordingsQuery.isFetching && displayedRecordings.length === 0)
  );
  const recordingSkeletonRows = $derived(
    buildTableSkeletonRows(pageSize, 0, showRecordingSkeleton)
  );
  const recordingSkeletonCells = [
    { tdClass: 'w-12 py-3 align-middle', barClass: 'h-4 w-4', wrapperClass: 'flex justify-center' },
    { tdClass: 'py-3', barClass: 'h-4 w-44 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-24 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-28 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-10 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-16 max-w-full' },
    { tdClass: 'py-3', barClass: 'h-4 w-28 max-w-full' },
    { tdClass: 'py-3 text-center', barClass: 'h-3 w-16 max-w-full', wrapperClass: 'flex justify-center' },
    { tdClass: 'py-3 pr-3 text-right', barClass: 'h-8 w-8', barRadiusClass: 'rounded-full', wrapperClass: 'ml-auto flex w-8 justify-center' }
  ];

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
  const applyRecordFilters = async (values: Record<string, string>) => {
    const nextHref = buildUrlWithQueryState(page.url, {
      owner: values.owner !== 'all' ? values.owner : null,
      profile: values.profile !== 'all' ? values.profile : null,
      upload_status: values.upload_status !== 'all' ? values.upload_status : null,
      search: values.search || null,
      created_from: values.created_from || null,
      created_to: values.created_to || null,
      size_min: values.size_min || null,
      size_max: values.size_max || null,
      episodes_min: values.episodes_min || null,
      episodes_max: values.episodes_max || null,
      page_size: values.page_size !== String(DEFAULT_PAGE_SIZE) ? values.page_size : null,
      sort: recordingSortKey !== 'created_at' ? recordingSortKey : null,
      order: recordingSortOrder !== 'desc' ? recordingSortOrder : null,
      page: null
    });
    filterDialogOpen = false;
    const currentHref = `${page.url.pathname}${page.url.search}${page.url.hash}`;
    if (nextHref === currentHref) return;
    selectedRecordingIds = [];
    await goto(nextHref, {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
      invalidateAll: false
    });
  };
  const UPLOAD_STATUS_LABELS: Record<string, string> = {
    idle: '未開始',
    running: 'アップロード中',
    completed: '完了',
    failed: '失敗',
    disabled: '無効'
  };

  const setReuploadBusy = (recordingId: string, busy: boolean) => {
    reuploadBusy = {
      ...reuploadBusy,
      [recordingId]: busy
    };
  };

  const isReuploadBusy = (recordingId: string) => Boolean(reuploadBusy[recordingId]);
  const setArchiveBusy = (recordingId: string, busy: boolean) => {
    archiveBusy = {
      ...archiveBusy,
      [recordingId]: busy
    };
  };
  const isArchiveBusy = (recordingId: string) => Boolean(archiveBusy[recordingId]);
  const isTerminalUploadStatus = (status: string) =>
    status === 'completed' || status === 'failed' || status === 'disabled';

  const normalizeUploadStatus = (recordingId: string, status?: Partial<RecordingUploadStatus>) => ({
    dataset_id: recordingId,
    status: status?.status ?? 'idle',
    phase: status?.phase ?? 'idle',
    progress_percent: Number(status?.progress_percent ?? 0),
    message: status?.message ?? '',
    files_done: Number(status?.files_done ?? 0),
    total_files: Number(status?.total_files ?? 0),
    current_file: status?.current_file ?? null,
    error: status?.error ?? null,
    updated_at: status?.updated_at ?? null
  });

  const setUploadStatus = (recordingId: string, status: RecordingUploadStatus) => {
    const previous = uploadStatusMap[recordingId];
    uploadStatusMap = {
      ...uploadStatusMap,
      [recordingId]: status
    };
    if (isTerminalUploadStatus(status.status) && previous?.status !== status.status) {
      void $recordingsQuery.refetch?.();
    }
  };

  const uploadStatusLabel = (recordingId: string) => {
    const status = uploadStatusMap[recordingId];
    if (!status) return '-';
    const label = UPLOAD_STATUS_LABELS[status.status] ?? status.status;
    if (status.status === 'running') {
      const progress = Number.isFinite(status.progress_percent)
        ? `${Math.max(0, Math.min(100, status.progress_percent)).toFixed(1)}%`
        : '0.0%';
      return `${label} (${progress})`;
    }
    return label;
  };
  const openUploadProgressModal = (datasetId: string) => {
    const normalized = String(datasetId || '').trim();
    if (!normalized) return;
    selectedUploadDatasetId = normalized;
    uploadModalOpen = true;
  };
  const creatorLabel = (value?: string | null) => {
    const normalized = String(value ?? '').trim();
    if (!normalized) return '-';
    if (normalized.length <= 24) return normalized;
    return `${normalized.slice(0, 20)}...`;
  };
  const ownerLabel = (recording: RecordingSummary) =>
    creatorLabel(recording.owner_name ?? recording.owner_email ?? recording.owner_user_id);
  const recordingOwnerOptions = $derived($recordingsQuery.data?.owner_options ?? []);
  const recordingOwnerSelectOptions = $derived.by(() => {
    const options = [
      { value: 'all', label: '全員' },
      ...recordingOwnerOptions.map((owner) => ({
        value: owner.user_id,
        label: owner.label,
        disabled: owner.available_count === 0 && owner.user_id !== recordingOwnerFilter
      }))
    ];
    if (recordingOwnerFilter !== 'all' && !options.some((option) => option.value === recordingOwnerFilter)) {
      options.push({ value: recordingOwnerFilter, label: recordingOwnerFilter });
    }
    return options;
  });
  const recordingProfileOptions = $derived($recordingsQuery.data?.profile_options ?? []);
  const recordingUploadOptions = $derived($recordingsQuery.data?.upload_status_options ?? []);
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
  const recordingProfileSelectOptions = $derived(withAllOption(recordingProfileFilter, recordingProfileOptions));
  const recordingUploadSelectOptions = $derived(withAllOption(recordingUploadFilter, recordingUploadOptions));
  const recordingFilterDefaults = {
    search: '',
    owner: 'all',
    profile: 'all',
    upload_status: 'all',
    created_from: '',
    created_to: '',
    size_min: '',
    size_max: '',
    episodes_min: '',
    episodes_max: '',
    page_size: String(DEFAULT_PAGE_SIZE)
  };
  const recordingFilterValues = $derived({
    search: recordingSearch,
    owner: recordingOwnerFilter,
    profile: recordingProfileFilter,
    upload_status: recordingUploadFilter,
    created_from: recordingCreatedFrom,
    created_to: recordingCreatedTo,
    size_min: recordingSizeMin,
    size_max: recordingSizeMax,
    episodes_min: recordingEpisodeMin,
    episodes_max: recordingEpisodeMax,
    page_size: String(pageSize)
  });
  const recordingFilterFields = $derived<ListFilterField[]>([
    {
      section: '検索',
      type: 'text',
      key: 'search',
      label: 'データセット名',
      placeholder: 'データセット名で検索'
    },
    {
      section: '条件',
      type: 'select',
      key: 'owner',
      label: '作成者',
      options: recordingOwnerSelectOptions
    },
    {
      section: '条件',
      type: 'select',
      key: 'profile',
      label: 'プロファイル',
      options: recordingProfileSelectOptions
    },
    {
      section: '条件',
      type: 'select',
      key: 'upload_status',
      label: '送信状態',
      options: recordingUploadSelectOptions
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
    },
    {
      section: '表示',
      type: 'select',
      key: 'page_size',
      label: '1ページの件数',
      options: PAGE_SIZE_OPTIONS.map((size) => ({ value: String(size), label: `${size}件` }))
    }
  ]);
  const hasActiveRecordingFilters = $derived(
    Boolean(recordingSearch) ||
      recordingOwnerFilter !== 'all' ||
      recordingProfileFilter !== 'all' ||
      recordingUploadFilter !== 'all' ||
      Boolean(recordingCreatedFrom) ||
      Boolean(recordingCreatedTo) ||
      Boolean(recordingSizeMin) ||
      Boolean(recordingSizeMax) ||
      Boolean(recordingEpisodeMin) ||
      Boolean(recordingEpisodeMax) ||
      pageSize !== DEFAULT_PAGE_SIZE
  );
  const currentUserId = $derived(String($userConfigQuery.data?.user_id ?? '').trim());
  const allDisplayedRecordingIds = $derived(displayedRecordings.map((recording) => recording.recording_id));
  const allDisplayedRecordingsSelected = $derived(
    allDisplayedRecordingIds.length > 0 && allDisplayedRecordingIds.every((id) => selectedRecordingIds.includes(id))
  );
  const toggleSelectAllDisplayedRecordings = () => {
    selectedRecordingIds = updateSelectedPageIds(
      selectedRecordingIds,
      allDisplayedRecordingIds,
      !allDisplayedRecordingsSelected
    );
  };
  const toggleSelectedRecording = (recordingId: string, selected: boolean) => {
    selectedRecordingIds = updateSelectedId(selectedRecordingIds, recordingId, selected);
  };
  const clearRecordingSelection = () => {
    selectedRecordingIds = [];
  };
  const isSortedBy = (key: 'created_at' | 'dataset_name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'status') => recordingSortKey === key;
  const sortIconFor = (key: 'created_at' | 'dataset_name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'status') =>
    !isSortedBy(key) ? CaretUpDown : recordingSortOrder === 'asc' ? ArrowUp : ArrowDown;
  const DatasetNameSortIcon = $derived(sortIconFor('dataset_name'));
  const OwnerSortIcon = $derived(sortIconFor('owner_name'));
  const ProfileSortIcon = $derived(sortIconFor('profile_name'));
  const EpisodeSortIcon = $derived(sortIconFor('episode_count'));
  const SizeSortIcon = $derived(sortIconFor('size_bytes'));
  const CreatedAtSortIcon = $derived(sortIconFor('created_at'));
  const StatusSortIcon = $derived(sortIconFor('status'));
  const handleSortChange = async (key: 'created_at' | 'dataset_name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'status') => {
    const nextOrder: 'asc' | 'desc' = recordingSortKey === key ? (recordingSortOrder === 'asc' ? 'desc' : 'asc') : 'desc';
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
  const selectedRecordings = $derived(recordings.filter((recording) => selectedRecordingIds.includes(recording.recording_id)));
  const selectedLocalRecordings = $derived(selectedRecordings.filter((recording) => Boolean(recording.is_local)));
  const canBulkReupload = $derived(selectedLocalRecordings.length > 0 && !bulkPending);
  const canBulkArchive = $derived(selectedRecordingIds.length > 0 && !bulkPending);
  const bulkMenuItemClass =
    'flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent';
  const bulkMenuDangerItemClass =
    'flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent';
  const sortIconClass = 'text-slate-400 transition group-hover:text-slate-600';
  const sortableHeaderButtonClass =
    'group inline-flex items-center gap-1 font-semibold text-slate-400 transition hover:text-slate-700';
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

  const openDatasetViewer = (datasetId: string) => {
    const normalized = String(datasetId || '').trim();
    if (!normalized) return;
    sessionViewer.open({ datasetId: normalized });
  };

  const reuploadRecording = async (recording: RecordingSummary) => {
    const recordingId = String(recording.recording_id || '').trim();
    if (!recordingId || !recording.is_local || isReuploadBusy(recordingId)) return;
    setUploadStatus(
      recordingId,
      normalizeUploadStatus(recordingId, createPendingRecordingUploadStatus(recordingId, 'Re-uploading dataset to R2...'))
    );
    setReuploadBusy(recordingId, true);
    try {
      await api.storage.reuploadDataset(recordingId);
      toast.success('再送信を受け付けました。');
    } catch (err) {
      const message = err instanceof Error ? err.message : '再送信に失敗しました。';
      setUploadStatus(
        recordingId,
        normalizeUploadStatus(recordingId, {
          status: 'failed',
          phase: 'failed',
          message,
          error: message
        })
      );
      toast.error(message);
    } finally {
      setReuploadBusy(recordingId, false);
    }
  };

  const archiveRecording = async (recording: RecordingSummary) => {
    const recordingId = String(recording.recording_id || '').trim();
    if (!recordingId || isArchiveBusy(recordingId) || isReuploadBusy(recordingId)) return;
    setArchiveBusy(recordingId, true);
    try {
      await api.storage.archiveDataset(recordingId);
      uploadStatusMap = {
        ...uploadStatusMap,
        [recordingId]: normalizeUploadStatus(recordingId, { status: 'idle', phase: 'idle' })
      };
      toast.success('アーカイブしました。');
      await $recordingsQuery.refetch?.();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
      toast.error(message);
    } finally {
      setArchiveBusy(recordingId, false);
    }
  };

  const bulkReuploadRecordings = async () => {
    bulkMessage = '';
    bulkError = '';
    if (!selectedLocalRecordings.length) {
      bulkError = '再送信対象を選択してください。';
      return;
    }
    const confirmed = confirm(`${selectedLocalRecordings.length}件をR2へ再送信しますか？`);
    if (!confirmed) return;
    bulkPending = true;
    try {
      const response = await api.recording.bulkReupload(selectedLocalRecordings.map((recording) => recording.recording_id));
      applyBulkResponseMessage(response, '再送信を実行しました');
      await $recordingsQuery.refetch?.();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : '再送信に失敗しました。';
    } finally {
      bulkPending = false;
    }
  };

  const bulkArchiveRecordings = async () => {
    bulkMessage = '';
    bulkError = '';
    if (!selectedRecordingIds.length) {
      bulkError = 'アーカイブ対象を選択してください。';
      return;
    }
    const confirmed = confirm(`${selectedRecordingIds.length}件をアーカイブしますか？`);
    if (!confirmed) return;
    bulkPending = true;
    try {
      const response = await api.recording.bulkArchive([...selectedRecordingIds]);
      applyBulkResponseMessage(response, 'アーカイブを実行しました');
      if (response.failed === 0) {
        clearRecordingSelection();
      }
      await $recordingsQuery.refetch?.();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      bulkPending = false;
    }
  };

  const STATUS_LABELS: Record<string, string> = {
    idle: '待機',
    warming: '準備中',
    recording: '録画中',
    paused: '一時停止',
    resetting: 'リセット中',
    inactive: '停止',
    completed: '完了',
    failed: '失敗'
  };

  let recorderStatus = $state<RecorderStatus | null>(null);
  let rosbridgeStatus = $state<RosbridgeStatus>('idle');
  let lastStatusAt = $state('');

  $effect(() => {
    if (typeof window === 'undefined') return;
    const client = getRosbridgeClient();
    const unsubscribe = client.subscribe(
      RECORDER_STATUS_TOPIC,
      (message) => {
        recorderStatus = parseRecorderPayload(message);
        lastStatusAt = new Date().toLocaleTimeString();
      },
      { throttle_rate: RECORDER_STATUS_THROTTLE_MS }
    );
    const offStatus = client.onStatusChange((next) => {
      rosbridgeStatus = next;
    });
    rosbridgeStatus = client.getStatus();
    return () => {
      unsubscribe();
      offStatus();
    };
  });

  const activeSessionId = $derived(getRecorderActiveDatasetId(recorderStatus));
  const activeSessionState = $derived(recorderStatus?.state ?? 'unknown');
  const activeSessionLabel = $derived(STATUS_LABELS[activeSessionState] ?? activeSessionState);
  const activeEpisodeIndex = $derived(getRecorderDisplayEpisodeNumber(recorderStatus));
  const activeEpisodeTotal = $derived(recorderStatus?.num_episodes ?? null);
  const activeFrameCount = $derived(recorderStatus?.frame_count ?? null);
  const activeEpisodeFrameCount = $derived(recorderStatus?.episode_frame_count ?? null);
  const rawStatus = $derived(recorderStatus ? JSON.stringify(recorderStatus, null, 2) : '');

  $effect(() => {
    if ($recordingsQuery.isLoading) {
      return;
    }
    const nextPage = clampPage(currentPage, totalRecordings, pageSize);
    if (nextPage !== currentPage) {
      void navigateToPage(nextPage);
    }
  });

  $effect(() => {
    if (recordingOwnerFilterInitialized) return;
    if (!currentUserId) return;
    if (page.url.searchParams.has('owner')) {
      recordingOwnerFilterInitialized = true;
      return;
    }
    if (!recordingOwnerOptions.some((option) => option.user_id === currentUserId)) {
      recordingOwnerFilterInitialized = true;
      return;
    }
    recordingOwnerFilterInitialized = true;
    void goto(
      buildUrlWithQueryState(page.url, {
        owner: currentUserId,
        page: null
      }),
      {
        replaceState: true,
        noScroll: true,
        keepFocus: true,
        invalidateAll: false
      }
    );
  });

  $effect(() => {
    const currentIds = new Set(recordings.map((recording) => String(recording.recording_id || '').trim()));
    const nextMap: Record<string, RecordingUploadStatus> = {};
    for (const [recordingId, status] of Object.entries(uploadStatusMap)) {
      if (currentIds.has(recordingId)) {
        nextMap[recordingId] = status;
      }
    }
    if (Object.keys(nextMap).length !== Object.keys(uploadStatusMap).length) {
      uploadStatusMap = nextMap;
    }
  });

  $effect(() => {
    if (!browser) {
      return;
    }
    if (realtimeContributor === null) {
      realtimeContributor = registerRealtimeTrackConsumer({
        tracks: [],
        onEvent: (event: RealtimeTrackEvent) => {
          if (event.kind === 'system.status') {
            systemStatusSnapshot = event.detail as SystemStatusSnapshot;
            return;
          }
          if (event.kind === 'operate.status') {
            const payload = event.detail as OperateStatusStreamPayload;
            if (payload.operate_status) {
              queryClient.setQueryData(['operate', 'status'], payload.operate_status);
            }
            return;
          }
          if (event.kind === 'recording.upload-status') {
            const payload = event.detail as RecordingUploadStatus;
            const recordingId = String(payload.dataset_id || '').trim();
            if (!recordingId) return;
            if (shouldIgnoreIdleUploadSnapshot(uploadStatusMap[recordingId] ?? null, payload, recordingId)) {
              return;
            }
            setUploadStatus(recordingId, normalizeUploadStatus(recordingId, payload));
          }
        }
      });
      if (!realtimeContributor) {
        return;
      }
    }
    const tracks: RealtimeTrackSelector[] = [
      { kind: 'system.status', key: 'system' },
      { kind: 'operate.status', key: 'operate' },
      ...recordings
        .map((recording) => String(recording.recording_id || '').trim())
        .filter(Boolean)
        .map(
          (recordingId): RealtimeTrackSelector => ({
            kind: 'recording.upload-status',
            params: { session_id: recordingId }
          })
        )
    ];
    realtimeContributor.setTracks(tracks);
  });

  onDestroy(() => {
    realtimeContributor?.dispose();
    realtimeContributor = null;
  });

</script>

<section class="card-strong p-8">
  <p class="section-title">Record</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ録画</h1>
      <p class="mt-2 text-sm text-slate-600">データセット収録の状況を表示します。</p>
    </div>
    <Button.Root class="btn-primary" href="/record/new">新規データセットを作成</Button.Root>
  </div>
</section>

{#if activeSessionId}
  <ActiveSessionSection title="稼働中データセット" description="現在収録中のデータセットを表示します。">
    <ActiveSessionCard>
      {#if rosbridgeStatus !== 'connected'}
        <p class="text-xs text-rose-600">rosbridge が切断されています。状態は更新されません。</p>
      {/if}
      <div class="flex flex-wrap items-center gap-3 text-sm text-slate-700">
        <span class="chip">状態: {activeSessionLabel}</span>
        <span class="chip">Dataset: {activeSessionId}</span>
        {#if activeEpisodeIndex}
          <span class="chip">
            Episode: {activeEpisodeIndex}{activeEpisodeTotal ? ` / ${activeEpisodeTotal}` : ''}
          </span>
        {/if}
        {#if activeFrameCount != null}
          <span class="chip">Frames: {activeFrameCount}</span>
        {/if}
        {#if activeEpisodeFrameCount != null}
          <span class="chip">Episode Frames: {activeEpisodeFrameCount}</span>
        {/if}
        {#if recorderStatus?.last_frame_at}
          <span class="chip">Last: {formatDate(recorderStatus.last_frame_at)}</span>
        {/if}
        <span class="chip">更新: {lastStatusAt || '-'}</span>
        <a class="btn-ghost px-3 py-1 text-xs" href={`/record/sessions/${activeSessionId}`}>収録を開く</a>
      </div>
      <details class="mt-3 nested-block p-3 text-xs text-slate-600">
        <summary class="cursor-pointer text-slate-500">状態の生データ</summary>
        <pre class="mt-2 whitespace-pre-wrap text-[11px] text-slate-700">{rawStatus || '-'}</pre>
      </details>
    </ActiveSessionCard>
  </ActiveSessionSection>
{/if}

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">データセット履歴</h2>
      <p class="text-sm text-slate-600">収録済みデータセットの履歴です。</p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      {#if selectedRecordingIds.length > 0}
        <span class="text-sm font-semibold text-slate-700">選択中: {selectedRecordingIds.length} 件</span>
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
                <DropdownMenu.Item class={bulkMenuItemClass} onSelect={clearRecordingSelection}>
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
                <DropdownMenu.Item
                  class={bulkMenuItemClass}
                  disabled={!canBulkReupload}
                  onSelect={() => void bulkReuploadRecordings()}
                >
                  <CloudArrowUp size={16} class="text-slate-500" />
                  再送信
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  class={bulkMenuDangerItemClass}
                  disabled={!canBulkArchive}
                  onSelect={() => void bulkArchiveRecordings()}
                >
                  <Archive size={16} class="text-rose-500" />
                  アーカイブ
                </DropdownMenu.Item>
              </DropdownMenu.Group>

              {#if selectedRecordingIds.length !== selectedLocalRecordings.length}
                <DropdownMenu.Separator class="-mx-2 my-1 h-px bg-slate-200/70" />
                <DropdownMenu.Group>
                  <DropdownMenu.GroupHeading
                    class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                  >
                    情報
                  </DropdownMenu.GroupHeading>
                  <div class="px-3 pb-1 pt-0.5 text-[10px] text-slate-400">
                    再送信はローカルデータがある {selectedLocalRecordings.length} 件のみ対象です。
                  </div>
                </DropdownMenu.Group>
              {/if}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      {:else}
        <PaginationControls
          currentPage={currentPage}
          pageSize={pageSize}
          totalItems={totalRecordings}
          disabled={$recordingsQuery.isLoading}
          compact={true}
          onPageChange={navigateToPage}
        />
        <ListFilterPopover
          bind:open={filterDialogOpen}
          fields={recordingFilterFields}
          values={recordingFilterValues}
          defaults={recordingFilterDefaults}
          active={hasActiveRecordingFilters}
          onApply={applyRecordFilters}
        />
      {/if}
    </div>
  </div>
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
                checked={allDisplayedRecordingsSelected}
                aria-label="表示中の録画を全選択"
                onchange={toggleSelectAllDisplayedRecordings}
              />
            </div>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('dataset_name')}>
              データセット
              <DatasetNameSortIcon size={14} class={sortIconClass} />
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
          <th class="pb-3 text-center">
            <div class="flex justify-center">
              <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('status')}>
                送信状態
                <StatusSortIcon size={14} class={sortIconClass} />
              </button>
            </div>
          </th>
          <th class="w-14 pb-3 pr-3">
            <div class="ml-auto flex w-8 justify-center">操作</div>
          </th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if showRecordingSkeleton}
          <TableSkeletonRows rows={recordingSkeletonRows} cells={recordingSkeletonCells} />
        {:else if displayedRecordings.length}
          {#each displayedRecordings as recording}
            {@const uploadCellStatus = presentRecordingUploadStatus(
              uploadStatusMap[recording.recording_id] ?? null,
              Boolean(recording.is_uploaded)
            )}
            <tr class="border-t border-slate-200/60">
              <td class="w-12 py-3 align-middle">
                <div class="flex justify-center">
                  <input
                    type="checkbox"
                    class="block h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                    checked={selectedRecordingIds.includes(recording.recording_id)}
                    value={recording.recording_id}
                    onchange={(event) =>
                      toggleSelectedRecording(
                        recording.recording_id,
                        (event.currentTarget as HTMLInputElement).checked
                      )}
                  />
                </div>
              </td>
              <td class="py-3">
                {#if recording.continuable}
                  <a
                    class="text-brand underline underline-offset-2 transition-colors hover:text-brand-hover hover:decoration-brand-hover"
                    href={`/record/new?continue_from_dataset_id=${encodeURIComponent(recording.recording_id)}`}
                  >
                    {recording.dataset_name ?? recording.recording_id}
                  </a>
                {:else}
                  <span class="text-slate-500">{recording.dataset_name ?? recording.recording_id}</span>
                {/if}
              </td>
              <td class="py-3">{ownerLabel(recording)}</td>
              <td class="py-3">{recording.profile_name ?? '-'}</td>
              <td class="py-3">{recording.episode_count ?? '-'}</td>
              <td class="py-3">{formatBytes(recording.size_bytes ?? 0)}</td>
              <td class="py-3">{formatDate(recording.created_at)}</td>
              <td class="py-3 text-center">
                <div class="flex flex-col items-center gap-1">
                  {#if uploadCellStatus.kind === 'progress'}
                    <button
                      class="text-xs font-semibold text-brand underline underline-offset-2 transition-colors hover:text-brand-hover hover:decoration-brand-hover"
                      type="button"
                      onclick={() => openUploadProgressModal(recording.recording_id)}
                    >
                      {uploadCellStatus.label}
                    </button>
                  {:else}
                    <span
                      class={`text-xs font-semibold ${
                        uploadCellStatus.tone === 'error'
                          ? 'text-rose-600'
                          : uploadCellStatus.tone === 'success'
                            ? 'text-emerald-600'
                            : 'text-slate-500'
                      }`}
                    >
                      {uploadCellStatus.label}
                    </span>
                  {/if}
                  {#if uploadStatusMap[recording.recording_id]?.status === 'failed' && uploadStatusMap[recording.recording_id]?.error}
                    <span class="max-w-[260px] truncate text-[10px] text-rose-500">
                      {uploadStatusMap[recording.recording_id]?.error}
                    </span>
                  {/if}
                </div>
              </td>
              <td class="py-3 pr-3 text-right">
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger
                    class="btn-ghost ml-auto h-8 w-8 p-0 text-slate-600"
                    aria-label="操作メニュー"
                    title="操作"
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
                          onSelect={() => openDatasetViewer(recording.recording_id)}
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
                          操作
                        </DropdownMenu.GroupHeading>
                        <DropdownMenu.Item
                          class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                          disabled={!recording.is_local || isReuploadBusy(recording.recording_id)}
                          closeOnSelect={false}
                          onSelect={() => reuploadRecording(recording)}
                        >
                          <CloudArrowUp size={16} class="text-slate-500" />
                          {#if isReuploadBusy(recording.recording_id)}
                            {uploadStatusLabel(recording.recording_id)}
                          {:else}
                            再送信
                          {/if}
                        </DropdownMenu.Item>
                        <DropdownMenu.Item
                          class="flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent"
                          disabled={isArchiveBusy(recording.recording_id) || isReuploadBusy(recording.recording_id)}
                          onSelect={() => archiveRecording(recording)}
                        >
                          <Archive size={16} class="text-rose-500" />
                          {#if isArchiveBusy(recording.recording_id)}
                            アーカイブ中...
                          {:else}
                            アーカイブ
                          {/if}
                        </DropdownMenu.Item>
                      </DropdownMenu.Group>

                      {#if uploadStatusMap[recording.recording_id]?.status === 'running' || !recording.is_local}
                        <DropdownMenu.Separator class="-mx-2 my-1 h-px bg-slate-200/70" />
                        <DropdownMenu.Group>
                          <DropdownMenu.GroupHeading
                            class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                          >
                            情報
                          </DropdownMenu.GroupHeading>
                          {#if uploadStatusMap[recording.recording_id]?.status === 'running'}
                            <div class="px-3 pb-1 pt-0.5 text-[10px] text-slate-400">
                              {uploadStatusMap[recording.recording_id]?.message || 'アップロード中...'}
                            </div>
                          {/if}
                          {#if !recording.is_local}
                            <div class="px-3 pb-1 pt-0.5 text-[10px] text-slate-400">
                              ローカルデータがないため実行できません
                            </div>
                          {/if}
                        </DropdownMenu.Group>
                      {/if}
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="9">条件に合う録画がありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
  <PaginationControls
    currentPage={currentPage}
    pageSize={pageSize}
    totalItems={totalRecordings}
    disabled={$recordingsQuery.isLoading}
    onPageChange={navigateToPage}
  />
</section>

<DatasetUploadProgressModal bind:open={uploadModalOpen} datasetId={selectedUploadDatasetId} />

<SystemStatusTab
  snapshot={systemStatusSnapshot}
  network={$operateStatusQuery.data?.network ?? null}
  showGpuDetails={false}
/>

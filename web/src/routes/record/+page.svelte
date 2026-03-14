<script lang="ts">
  import { browser } from '$app/environment';
  import { onDestroy } from 'svelte';
  import { Button, DropdownMenu } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import toast from 'svelte-french-toast';
  import Archive from 'phosphor-svelte/lib/Archive';
  import CloudArrowUp from 'phosphor-svelte/lib/CloudArrowUp';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import Eye from 'phosphor-svelte/lib/Eye';
  import { api, type BulkActionResponse, type TabSessionSubscription } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';
  import { registerTabRealtimeContributor, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';
  import OperateStatusCards from '$lib/components/OperateStatusCards.svelte';
  import DatasetUploadProgressModal from '$lib/components/storage/DatasetUploadProgressModal.svelte';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';
  import { getRecorderDisplayEpisodeNumber } from '$lib/recording/recorderStatus';
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
    continue_block_reason?: string;
    size_bytes?: number;
    is_local?: boolean;
    is_uploaded?: boolean;
  };

  type RecordingListResponse = {
    recordings?: RecordingSummary[];
    total?: number;
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

  type RecorderStatus = {
    state?: string;
    dataset_id?: string;
    task?: string;
    episode_index?: number | null;
    num_episodes?: number;
    frame_count?: number;
    episode_frame_count?: number;
    last_frame_at?: string | null;
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

  const recordingsQuery = createQuery<RecordingListResponse>({
    queryKey: ['recording', 'recordings'],
    queryFn: () => api.recording.list()
  });

  const operateStatusQuery = createQuery<OperateStatusResponse>({
    queryKey: ['operate', 'status'],
    queryFn: api.operate.status
  });
  const userConfigQuery = createQuery<UserConfigResponse>({
    queryKey: ['user', 'config'],
    queryFn: () => api.user.config() as Promise<UserConfigResponse>
  });

  const recordings = $derived($recordingsQuery.data?.recordings ?? []);
  const sortDateValue = (value?: string) => new Date(value ?? 0).getTime() || 0;
  const normalizeText = (value?: string | null) => String(value ?? '').trim().toLowerCase();
  const compareText = (left?: string | null, right?: string | null) =>
    normalizeText(left).localeCompare(normalizeText(right), 'ja');
  const compareNumber = (left?: number | null, right?: number | null) => Number(left ?? 0) - Number(right ?? 0);

  let recordingSortKey = $state<'created_at' | 'dataset_name' | 'episode_count' | 'status'>('created_at');
  let recordingSortOrder = $state<'desc' | 'asc'>('desc');
  let recordingOwnerFilter = $state('all');
  let recordingSearch = $state('');
  let selectedRecordingIds = $state<string[]>([]);
  let recordingOwnerFilterInitialized = $state(false);
  let bulkPending = $state(false);
  let bulkMessage = $state('');
  let bulkError = $state('');

  let reuploadBusy = $state<Record<string, boolean>>({});
  let archiveBusy = $state<Record<string, boolean>>({});
  let uploadStatusMap = $state<Record<string, RecordingUploadStatus>>({});
  let systemStatusSnapshot = $state<SystemStatusSnapshot | null>(null);
  let realtimeContributor: TabRealtimeContributorHandle | null = null;
  let uploadModalOpen = $state(false);
  let selectedUploadDatasetId = $state('');

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
  const recordingOwnerOptions = $derived.by(() => {
    const options = new Map<string, string>();
    for (const recording of recordings) {
      const ownerId = String(recording.owner_user_id ?? '').trim();
      if (!ownerId) continue;
      options.set(ownerId, ownerLabel(recording));
    }
    return Array.from(options, ([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label, 'ja'));
  });
  const currentUserId = $derived(String($userConfigQuery.data?.user_id ?? '').trim());
  const displayedRecordings = $derived.by(() => {
    const query = normalizeText(recordingSearch);
    const sorted = recordings
      .filter((recording) => {
        if (recordingOwnerFilter !== 'all' && String(recording.owner_user_id ?? '') !== recordingOwnerFilter) return false;
        if (!query) return true;
        return [
          recording.dataset_name,
          recording.recording_id,
          recording.task,
          recording.profile_name,
          recording.owner_name,
          recording.owner_email
        ].some((value) => normalizeText(value).includes(query));
      })
      .slice();

    sorted.sort((a, b) => {
      const direction = recordingSortOrder === 'asc' ? 1 : -1;
      switch (recordingSortKey) {
        case 'dataset_name':
          return compareText(a.dataset_name ?? a.recording_id, b.dataset_name ?? b.recording_id) * direction;
        case 'episode_count':
          return compareNumber(a.episode_count, b.episode_count) * direction;
        case 'status':
          return compareText(uploadStatusMap[a.recording_id]?.status, uploadStatusMap[b.recording_id]?.status) * direction;
        case 'created_at':
        default:
          return (sortDateValue(a.created_at) - sortDateValue(b.created_at)) * direction;
      }
    });
    return sorted;
  });
  const allDisplayedRecordingIds = $derived(displayedRecordings.map((recording) => recording.recording_id));
  const allDisplayedRecordingsSelected = $derived(
    allDisplayedRecordingIds.length > 0 && allDisplayedRecordingIds.every((id) => selectedRecordingIds.includes(id))
  );
  const toggleSelectAllDisplayedRecordings = () => {
    if (allDisplayedRecordingsSelected) {
      selectedRecordingIds = selectedRecordingIds.filter((id) => !allDisplayedRecordingIds.includes(id));
      return;
    }
    selectedRecordingIds = Array.from(new Set([...selectedRecordingIds, ...allDisplayedRecordingIds]));
  };
  const clearRecordingSelection = () => {
    selectedRecordingIds = [];
  };
  const selectedRecordings = $derived(recordings.filter((recording) => selectedRecordingIds.includes(recording.recording_id)));
  const selectedLocalRecordings = $derived(selectedRecordings.filter((recording) => Boolean(recording.is_local)));
  const canBulkReupload = $derived(selectedLocalRecordings.length > 0 && !bulkPending);
  const canBulkArchive = $derived(selectedRecordingIds.length > 0 && !bulkPending);
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
      toast.success('再アップロードを受け付けました。');
    } catch (err) {
      const message = err instanceof Error ? err.message : '再アップロードに失敗しました。';
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
      bulkError = '再アップロード対象を選択してください。';
      return;
    }
    const confirmed = confirm(`${selectedLocalRecordings.length}件をR2へ再アップロードしますか？`);
    if (!confirmed) return;
    bulkPending = true;
    try {
      const response = await api.recording.bulkReupload(selectedLocalRecordings.map((recording) => recording.recording_id));
      applyBulkResponseMessage(response, '再アップロードを実行しました');
      await $recordingsQuery.refetch?.();
    } catch (err) {
      bulkError = err instanceof Error ? err.message : '再アップロードに失敗しました。';
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

  const STATUS_TOPIC = '/lerobot_recorder/status';
  const STATUS_THROTTLE_MS = 66;
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
  let rosbridgeStatus = $state<'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'>('idle');
  let lastStatusAt = $state('');

  const parseRecorderPayload = (msg: Record<string, unknown>): RecorderStatus => {
    if (typeof msg.data === 'string') {
      try {
        return JSON.parse(msg.data) as RecorderStatus;
      } catch {
        return { state: 'unknown' };
      }
    }
    return msg as RecorderStatus;
  };

  $effect(() => {
    if (typeof window === 'undefined') return;
    const client = getRosbridgeClient();
    const unsubscribe = client.subscribe(
      STATUS_TOPIC,
      (message) => {
        recorderStatus = parseRecorderPayload(message);
        lastStatusAt = new Date().toLocaleTimeString();
      },
      { throttle_rate: STATUS_THROTTLE_MS }
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

  const activeSessionId = $derived(recorderStatus?.dataset_id ?? '');
  const activeSessionState = $derived(recorderStatus?.state ?? 'unknown');
  const activeSessionLabel = $derived(STATUS_LABELS[activeSessionState] ?? activeSessionState);
  const activeEpisodeIndex = $derived(getRecorderDisplayEpisodeNumber(recorderStatus));
  const activeEpisodeTotal = $derived(recorderStatus?.num_episodes ?? null);
  const activeFrameCount = $derived(recorderStatus?.frame_count ?? null);
  const activeEpisodeFrameCount = $derived(recorderStatus?.episode_frame_count ?? null);
  const rawStatus = $derived(recorderStatus ? JSON.stringify(recorderStatus, null, 2) : '');

  $effect(() => {
    if (recordingOwnerFilterInitialized) return;
    if (!currentUserId) return;
    if (!recordingOwnerOptions.some((option) => option.id === currentUserId)) {
      recordingOwnerFilterInitialized = true;
      return;
    }
    recordingOwnerFilter = currentUserId;
    recordingOwnerFilterInitialized = true;
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
      realtimeContributor = registerTabRealtimeContributor({
        subscriptions: [],
        onEvent: (event: TabRealtimeEvent) => {
          if (event.op !== 'snapshot') return;
          if (event.source?.kind === 'system.status') {
            systemStatusSnapshot = event.payload as SystemStatusSnapshot;
            return;
          }
          if (event.source?.kind === 'recording.upload-status') {
            const payload = event.payload as RecordingUploadStatus;
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
    const subscriptions: TabSessionSubscription[] = [
      { subscription_id: 'record.page.system-status', kind: 'system.status', params: {} },
      ...recordings
        .map((recording) => String(recording.recording_id || '').trim())
        .filter(Boolean)
        .map(
          (recordingId): TabSessionSubscription => ({
            subscription_id: `record.page.upload.${recordingId}`,
            kind: 'recording.upload-status',
            params: { session_id: recordingId }
          })
        )
    ];
    realtimeContributor.setSubscriptions(subscriptions);
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

<ActiveSessionSection title="稼働中データセット" description="現在収録中のデータセットを表示します。">
  <ActiveSessionCard>
    {#if activeSessionId}
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
    {:else}
      <p class="text-sm text-slate-500">稼働中のデータセットはありません。</p>
    {/if}
  </ActiveSessionCard>
</ActiveSessionSection>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">データセット履歴</h2>
      <p class="text-sm text-slate-600">収録済みデータセットの履歴です。</p>
    </div>
    <Button.Root class="btn-ghost" type="button" onclick={() => $recordingsQuery.refetch?.()}>更新</Button.Root>
  </div>
  <p class="mt-3 text-xs text-slate-500">選択中: {selectedRecordingIds.length} 件</p>
  <div class="mt-4 grid gap-3 md:grid-cols-4">
    <label class="block">
      <span class="label">検索</span>
      <input class="input mt-2" type="text" bind:value={recordingSearch} placeholder="dataset / task / user" />
    </label>
    <label class="block">
      <span class="label">作成者</span>
      <select class="input mt-2" bind:value={recordingOwnerFilter}>
        <option value="all">全員</option>
        {#each recordingOwnerOptions as owner}
          <option value={owner.id}>{owner.label}</option>
        {/each}
      </select>
    </label>
    <label class="block">
      <span class="label">並び替え</span>
      <select class="input mt-2" bind:value={recordingSortKey}>
        <option value="created_at">作成日時</option>
        <option value="dataset_name">名前</option>
        <option value="episode_count">エピソード数</option>
        <option value="status">アップロード状態</option>
      </select>
    </label>
    <label class="block">
      <span class="label">順序</span>
      <select class="input mt-2" bind:value={recordingSortOrder}>
        <option value="desc">降順</option>
        <option value="asc">昇順</option>
      </select>
    </label>
  </div>
  {#if selectedRecordingIds.length > 0}
    <div class="mt-4 nested-block-pane p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-slate-900">選択中: {selectedRecordingIds.length} 件</p>
          {#if selectedRecordingIds.length !== selectedLocalRecordings.length}
            <p class="mt-1 text-xs text-slate-500">
              再アップロードはローカルデータがある {selectedLocalRecordings.length} 件のみ対象です。
            </p>
          {/if}
        </div>
        <button class="btn-ghost" type="button" onclick={clearRecordingSelection}>選択解除</button>
      </div>
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <button
          class={`btn-primary ${canBulkReupload ? '' : 'opacity-50 cursor-not-allowed'}`}
          type="button"
          disabled={!canBulkReupload}
          onclick={bulkReuploadRecordings}
        >
          再アップロード
        </button>
        <button
          class={`btn-ghost ${canBulkArchive ? '' : 'opacity-50 cursor-not-allowed'}`}
          type="button"
          disabled={!canBulkArchive}
          onclick={bulkArchiveRecordings}
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
          <th class="pb-3">データセット</th>
          <th class="pb-3">作成者</th>
          <th class="pb-3">プロファイル</th>
          <th class="pb-3">エピソード</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">作成日時</th>
          <th class="pb-3 text-center">送信状態</th>
          <th class="pb-3 text-right">操作</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $recordingsQuery.isLoading}
          <tr><td class="py-3" colspan="9">読み込み中...</td></tr>
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
                    bind:group={selectedRecordingIds}
                    value={recording.recording_id}
                  />
                </div>
              </td>
              <td class="py-3">
                {#if recording.continuable}
                  <a class="text-brand underline" href={`/record/sessions/${encodeURIComponent(recording.recording_id)}`}>
                    {recording.dataset_name ?? recording.recording_id}
                  </a>
                {:else}
                  <span class="text-slate-500">{recording.dataset_name ?? recording.recording_id}</span>
                  {#if recording.continue_block_reason}
                    <p class="mt-1 text-[11px] text-slate-400">{recording.continue_block_reason}</p>
                  {/if}
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
                      class="text-xs font-semibold text-brand hover:underline"
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
              <td class="py-3 text-right">
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
                            再アップロード
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
</section>

<DatasetUploadProgressModal bind:open={uploadModalOpen} datasetId={selectedUploadDatasetId} />

<OperateStatusCards snapshot={systemStatusSnapshot} network={$operateStatusQuery.data?.network ?? null} />

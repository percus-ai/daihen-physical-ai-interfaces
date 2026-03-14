<script lang="ts">
  import { browser } from '$app/environment';
  import { AlertDialog, Button } from 'bits-ui';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';

  import { api, type ModelSyncJobStatus } from '$lib/api/client';
  import { formatBytes } from '$lib/format';
  import {
    registerTabRealtimeContributor,
    type TabRealtimeContributorHandle,
    type TabRealtimeEvent
  } from '$lib/realtime/tabSessionClient';

  type ThroughputSample = { atMs: number; transferredBytes: number };

  type Props = {
    open?: boolean;
    jobId: string;
    onCancel?: (jobId: string) => Promise<unknown>;
  };

  let {
    open = $bindable(false),
    jobId,
    onCancel
  }: Props = $props();

  let status = $state<ModelSyncJobStatus | null>(null);
  let contributor: TabRealtimeContributorHandle | null = null;
  let loading = $state(false);
  let loadError = $state('');
  let cancelPending = $state(false);

  const THROUGHPUT_WINDOW_MS = 8000;
  let throughputSamples = $state<ThroughputSample[]>([]);

  const disconnect = () => {
    contributor?.dispose();
    contributor = null;
  };

  const resetThroughput = () => {
    throughputSamples = [];
  };

  const recordThroughputSample = (nextStatus: ModelSyncJobStatus) => {
    const transferredBytes = Number(nextStatus.detail?.transferred_bytes ?? 0);
    if (!Number.isFinite(transferredBytes) || transferredBytes < 0) return;
    const now = Date.now();
    const next: ThroughputSample = { atMs: now, transferredBytes };

    let samples = throughputSamples;
    const previous = samples.at(-1);
    if (previous && transferredBytes < previous.transferredBytes) {
      samples = [];
    }
    samples = [...samples, next].filter((sample) => now - sample.atMs <= THROUGHPUT_WINDOW_MS);
    throughputSamples = samples;
  };

  const bytesPerSecond = $derived.by(() => {
    if (throughputSamples.length < 2) return null;
    const first = throughputSamples[0];
    const last = throughputSamples.at(-1);
    if (!last) return null;
    const dtSeconds = (last.atMs - first.atMs) / 1000;
    const deltaBytes = last.transferredBytes - first.transferredBytes;
    if (dtSeconds < 0.8 || deltaBytes <= 0) return null;
    return deltaBytes / dtSeconds;
  });

  const etaSeconds = $derived.by(() => {
    const speed = bytesPerSecond;
    const totalBytes = Number(status?.detail?.total_bytes ?? 0);
    const transferredBytes = Number(status?.detail?.transferred_bytes ?? 0);
    if (!speed || speed <= 0) return null;
    if (!Number.isFinite(totalBytes) || totalBytes <= 0) return null;
    if (!Number.isFinite(transferredBytes) || transferredBytes < 0) return null;
    const remaining = totalBytes - transferredBytes;
    if (remaining <= 0) return 0;
    return remaining / speed;
  });

  const finishAt = $derived.by(() => {
    if (etaSeconds === null) return null;
    return new Date(Date.now() + etaSeconds * 1000);
  });

  const formatSpeed = (bytesPerSec: number | null) => {
    if (!bytesPerSec || !Number.isFinite(bytesPerSec) || bytesPerSec <= 0) return '-';
    const mbps = (bytesPerSec * 8) / 1_000_000;
    const mbpsLabel = mbps >= 100 ? mbps.toFixed(0) : mbps.toFixed(1);
    return `${formatBytes(bytesPerSec)}/s (${mbpsLabel} Mbps)`;
  };

  const formatEta = (seconds: number | null) => {
    if (seconds === null || !Number.isFinite(seconds) || seconds <= 0) return '-';
    const rounded = Math.max(Math.round(seconds), 0);
    const s = rounded % 60;
    const minutesTotal = Math.floor(rounded / 60);
    const m = minutesTotal % 60;
    const h = Math.floor(minutesTotal / 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  };

  const formatFinishAt = (date: Date | null) => {
    if (!date) return '-';
    return date.toLocaleString('ja-JP', { hour12: false });
  };

  const clampPercent = (value: unknown) => {
    const parsed = typeof value === 'number' && Number.isFinite(value) ? value : Number(value);
    if (!Number.isFinite(parsed)) return 0;
    return Math.min(Math.max(parsed, 0), 100);
  };

  const progressPercent = $derived.by(() => clampPercent(status?.progress_percent ?? 0));
  const jobState = $derived(String(status?.state ?? '').toLowerCase());
  const isActive = $derived(jobState === 'queued' || jobState === 'running');

  const loadSnapshot = async () => {
    if (!jobId) return;
    loading = true;
    loadError = '';
    try {
      status = await api.storage.modelSyncJob(jobId);
      if (status) recordThroughputSample(status);
    } catch (error) {
      loadError = error instanceof Error ? error.message : '同期ジョブ状態の取得に失敗しました。';
    } finally {
      loading = false;
    }
  };

  const handleCancel = async () => {
    if (!jobId || cancelPending || !onCancel) return;
    cancelPending = true;
    loadError = '';
    try {
      await onCancel(jobId);
      await loadSnapshot();
    } catch (error) {
      loadError = error instanceof Error ? error.message : '同期の中断に失敗しました。';
    } finally {
      cancelPending = false;
    }
  };

  $effect(() => {
    if (!browser) return;
    if (!open) {
      disconnect();
      return;
    }
    if (!jobId) return;

    status = null;
    resetThroughput();
    void loadSnapshot();
    disconnect();

    contributor = registerTabRealtimeContributor({
      subscriptions: [
        {
          subscription_id: `storage.model-sync.modal.${jobId}`,
          kind: 'storage.model-sync',
          params: { job_id: jobId }
        }
      ],
      onEvent: (event: TabRealtimeEvent) => {
        if (event.op !== 'snapshot' || event.source?.kind !== 'storage.model-sync') return;
        status = event.payload as ModelSyncJobStatus;
        if (status) recordThroughputSample(status);
      }
    });

    return () => {
      disconnect();
    };
  });

</script>

<AlertDialog.Root bind:open={open}>
  <AlertDialog.Portal>
    <AlertDialog.Overlay class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]" />
    <AlertDialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,32rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      <AlertDialog.Title class="text-base font-semibold text-slate-900">モデル同期進捗</AlertDialog.Title>
      <AlertDialog.Description class="mt-2 text-sm text-slate-600">
        モデルのローカル同期状況を表示しています。
      </AlertDialog.Description>

      <div class="mt-4 space-y-3 nested-block-pane p-3">
        {#if loading}
          <p class="text-sm text-slate-500">同期ジョブ情報を読み込み中...</p>
        {:else if loadError}
          <p class="text-sm text-rose-600">{loadError}</p>
        {:else if status}
          <div class="flex items-center justify-between text-xs text-slate-500">
            <span>{status.state}</span>
            <span>{progressPercent.toFixed(1)}%</span>
          </div>
          <div class="h-2 w-full rounded-full bg-slate-200">
            <div class="h-2 rounded-full bg-brand transition-all" style={`width:${progressPercent}%`}></div>
          </div>

          <div class="grid gap-1 text-xs text-slate-600">
            <p class="truncate">model: {status.model_id}</p>
            {#if (status.detail?.total_files ?? 0) > 0}
              <p>files: {status.detail?.files_done ?? 0} / {status.detail?.total_files ?? 0}</p>
            {/if}
            {#if (status.detail?.total_bytes ?? 0) > 0}
              <p>
                bytes: {formatBytes(status.detail?.transferred_bytes ?? 0)} / {formatBytes(status.detail?.total_bytes ?? 0)}
              </p>
            {/if}
            {#if bytesPerSecond}
              <p>speed: {formatSpeed(bytesPerSecond)}</p>
            {/if}
            {#if etaSeconds !== null && etaSeconds > 0}
              <p>eta: {formatEta(etaSeconds)} (finish at: {formatFinishAt(finishAt)})</p>
            {/if}
            {#if status.detail?.current_file}
              <p class="truncate">current file: {status.detail.current_file}</p>
            {/if}
            {#if status.message}
              <p class="truncate text-slate-500">{status.message}</p>
            {/if}
            {#if status.error}
              <p class="text-rose-600">{status.error}</p>
            {/if}
          </div>
        {:else}
          <p class="text-sm text-slate-500">表示する同期ジョブがありません。</p>
        {/if}
      </div>

      <div class="mt-5 flex items-center justify-end gap-2">
        <AlertDialog.Cancel class="btn-ghost" type="button" onclick={() => (open = false)}>
          閉じる
        </AlertDialog.Cancel>
        {#if isActive && onCancel}
          <Button.Root class="btn-primary" type="button" disabled={cancelPending} onclick={handleCancel}>
            {cancelPending ? '中断中...' : '同期を中断'}
          </Button.Root>
        {/if}
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>

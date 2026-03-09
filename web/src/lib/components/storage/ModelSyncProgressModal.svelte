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

  const disconnect = () => {
    contributor?.dispose();
    contributor = null;
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

      <div class="mt-4 space-y-3 rounded-xl border border-slate-200/70 bg-slate-50/70 p-3">
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

<script lang="ts">
  import { browser } from '$app/environment';
  import { AlertDialog, Button } from 'bits-ui';
  import { api } from '$lib/api/client';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';
  import type { RecordingUploadStatus } from '$lib/recording/uploadStatus';
  import {
    createPendingRecordingUploadStatus,
    shouldIgnoreIdleUploadSnapshot
  } from '$lib/recording/uploadStatus';
  import {
    registerTabRealtimeContributor,
    type TabRealtimeContributorHandle,
    type TabRealtimeEvent
  } from '$lib/realtime/tabSessionClient';

  let {
    open = $bindable(false),
    datasetId = ''
  }: {
    open?: boolean;
    datasetId?: string;
  } = $props();

  let contributor: TabRealtimeContributorHandle | null = null;
  let status = $state<RecordingUploadStatus | null>(null);
  let loading = $state(false);
  let loadError = $state('');

  const disconnect = () => {
    contributor?.dispose();
    contributor = null;
  };

  const loadSnapshot = async (targetDatasetId: string) => {
    if (!targetDatasetId) return;
    loading = true;
    loadError = '';
    try {
      status = await (api.recording.sessionUploadStatus(targetDatasetId) as Promise<RecordingUploadStatus>);
    } catch (error) {
      loadError = error instanceof Error ? error.message : 'アップロード状態の取得に失敗しました。';
    } finally {
      loading = false;
    }
  };

  const handleRealtimeEvent = (event: TabRealtimeEvent) => {
    if (event.op !== 'snapshot' || event.source?.kind !== 'recording.upload-status') return;
    const targetDatasetId = String(datasetId || '').trim();
    if (!targetDatasetId) return;
    const nextStatus = event.payload as RecordingUploadStatus;
    if (String(nextStatus.dataset_id || '').trim() !== targetDatasetId) return;
    if (shouldIgnoreIdleUploadSnapshot(status, nextStatus, targetDatasetId)) return;
    status = nextStatus;
  };

  $effect(() => {
    if (!browser) return;
    if (contributor === null) {
      contributor = registerTabRealtimeContributor({
        contributorId: 'storage.dataset-upload.progress-modal',
        subscriptions: [],
        onEvent: handleRealtimeEvent
      });
    }
    contributor?.setEventHandler(handleRealtimeEvent);

    const targetDatasetId = String(datasetId || '').trim();
    if (!open || !targetDatasetId) {
      contributor?.setSubscriptions([]);
      status = null;
      loadError = '';
      loading = false;
      return;
    }

    status = createPendingRecordingUploadStatus(targetDatasetId);
    void loadSnapshot(targetDatasetId);
    contributor?.setSubscriptions([
      {
        subscription_id: `storage.dataset-upload.${targetDatasetId}`,
        kind: 'recording.upload-status',
        params: { session_id: targetDatasetId }
      }
    ]);
  });

  $effect(() => {
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
      <AlertDialog.Title class="text-base font-semibold text-slate-900">アップロード進捗</AlertDialog.Title>
      <AlertDialog.Description class="mt-2 text-sm text-slate-600">
        データセットのR2アップロード状況を表示しています。
      </AlertDialog.Description>

      <div class="mt-4 space-y-3 nested-block-pane p-3">
        {#if loading && !status}
          <p class="text-sm text-slate-500">アップロード状態を読み込み中...</p>
        {:else if loadError}
          <p class="text-sm text-rose-600">{loadError}</p>
        {:else if status}
          <div class="flex items-center justify-between text-xs text-slate-500">
            <span>{status.phase}</span>
            <span>{Math.max(0, Math.min(Number(status.progress_percent ?? 0), 100)).toFixed(1)}%</span>
          </div>
          <div class="h-2 w-full rounded-full bg-slate-200">
            <div
              class="h-2 rounded-full bg-brand transition-all"
              style={`width:${Math.max(0, Math.min(Number(status.progress_percent ?? 0), 100))}%`}
            ></div>
          </div>

          <div class="grid gap-1 text-xs text-slate-600">
            <p class="truncate">dataset: {status.dataset_id}</p>
            {#if (status.total_files ?? 0) > 0}
              <p>files: {status.files_done ?? 0} / {status.total_files ?? 0}</p>
            {/if}
            {#if status.current_file}
              <p class="truncate">current file: {status.current_file}</p>
            {/if}
            {#if status.message}
              <p class="truncate text-slate-500">{status.message}</p>
            {/if}
            {#if status.error}
              <p class="text-rose-600">{status.error}</p>
            {/if}
          </div>
        {:else}
          <p class="text-sm text-slate-500">表示するアップロードはありません。</p>
        {/if}
      </div>

      <div class="mt-5 flex items-center justify-end gap-2">
        <AlertDialog.Cancel class="btn-ghost" type="button" onclick={() => (open = false)}>
          閉じる
        </AlertDialog.Cancel>
        {#if status?.status === 'failed'}
          <Button.Root class="btn-primary" type="button" onclick={() => (open = false)}>
            閉じる
          </Button.Root>
        {/if}
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>

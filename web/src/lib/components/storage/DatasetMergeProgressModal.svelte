<script lang="ts">
  import { browser } from '$app/environment';
  import { AlertDialog, Button } from 'bits-ui';
  import { goto } from '$app/navigation';

  import { getTabRealtimeClient, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';
  import { sessionViewer } from '$lib/viewer/sessionViewerStore';
  import type { DatasetMergeJobStatus } from '$lib/api/client';
  import { formatBytes } from '$lib/format';

  type Props = {
    open?: boolean;
    jobId: string;
    onCompleted?: (datasetId: string) => void;
    onRetry?: () => Promise<void>;
  };

  let {
    open = $bindable(false),
    jobId,
    onCompleted,
    onRetry
  }: Props = $props();

  let status = $state<DatasetMergeJobStatus | null>(null);
  let contributor: TabRealtimeContributorHandle | null = null;
  let completedNotifiedForJobId = $state('');

  const clampPercent = (value: unknown) => {
    const parsed = typeof value === 'number' && Number.isFinite(value) ? value : Number(value);
    if (!Number.isFinite(parsed)) return 0;
    return Math.min(Math.max(parsed, 0), 100);
  };

  const progressPercent = $derived.by(() => clampPercent(status?.progress_percent ?? 0));
  const currentStep = $derived(String(status?.detail?.step ?? '').trim());
  const jobState = $derived(String(status?.state ?? '').toLowerCase());
  const resultDatasetId = $derived(String(status?.result_dataset_id ?? '').trim());
  const showRetry = $derived(jobState === 'failed' && typeof onRetry === 'function');

  const stepLabel = $derived.by(() => {
    if (jobState === 'queued') return '待機中';
    if (jobState === 'failed') return '失敗';
    if (jobState === 'completed') return '完了';
    if (currentStep === 'validate') return '入力チェック';
    if (currentStep === 'download') return 'ローカル同期';
    if (currentStep === 'aggregate') return 'マージ処理';
    if (currentStep === 'upload') return 'R2アップロード';
    return currentStep || '実行中';
  });

  const openViewer = () => {
    if (!resultDatasetId) return;
    sessionViewer.open({ datasetId: resultDatasetId });
  };

  const openDetail = async () => {
    if (!resultDatasetId) return;
    await goto(`/storage/datasets/${encodeURIComponent(resultDatasetId)}`);
  };

  const disconnect = () => {
    contributor?.dispose();
    contributor = null;
  };

  $effect(() => {
    if (!browser) return;
    if (!open) {
      disconnect();
      return;
    }
    if (!jobId) return;

    disconnect();
    status = null;
    completedNotifiedForJobId = '';

    const client = getTabRealtimeClient();
    if (!client) return;
    contributor = client.registerContributor({
      subscriptions: [
        {
          subscription_id: `storage.dataset-merge.${jobId}`,
          kind: 'storage.dataset-merge',
          params: { job_id: jobId }
        }
      ],
      onEvent: (event: TabRealtimeEvent) => {
        if (event.op !== 'snapshot' || event.source?.kind !== 'storage.dataset-merge') return;
        status = event.payload as DatasetMergeJobStatus;
      }
    });

    return () => {
      disconnect();
    };
  });

  $effect(() => {
    if (!jobId) return;
    if (!status) return;
    if (String(status.state) !== 'completed') return;
    if (!resultDatasetId) return;
    if (completedNotifiedForJobId === jobId) return;
    completedNotifiedForJobId = jobId;
    onCompleted?.(resultDatasetId);
  });
</script>

<AlertDialog.Root bind:open={open}>
  <AlertDialog.Portal>
    <AlertDialog.Overlay class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]" />
    <AlertDialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,32rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
    >
      <AlertDialog.Title class="text-base font-semibold text-slate-900">マージ進捗</AlertDialog.Title>
      <AlertDialog.Description class="mt-2 text-sm text-slate-600">
        データセットのマージとR2へのアップロード状況を表示しています。
      </AlertDialog.Description>

      <div class="mt-4 space-y-3 rounded-xl border border-slate-200/70 bg-slate-50/70 p-3">
        <div class="flex items-center justify-between text-xs text-slate-500">
          <span>{stepLabel}</span>
          <span>{progressPercent.toFixed(1)}%</span>
        </div>
        <div class="h-2 w-full rounded-full bg-slate-200">
          <div class="h-2 rounded-full bg-brand transition-all" style={`width:${progressPercent}%`}></div>
        </div>

        <div class="grid gap-1 text-xs text-slate-600">
          {#if status?.detail?.dataset_name}
            <p class="truncate">name: {status.detail.dataset_name}</p>
          {/if}
          {#if status?.detail?.source_dataset_ids?.length}
            <p>sources: {status.detail.source_dataset_ids.length}</p>
          {/if}
          {#if status?.detail?.current_dataset_id}
            <p class="truncate">current dataset: {status.detail.current_dataset_id}</p>
          {/if}
          {#if status?.detail?.current_file}
            <p class="truncate">current file: {status.detail.current_file}</p>
          {/if}
          {#if (status?.detail?.total_files ?? 0) > 0}
            <p>
              files: {status?.detail?.files_done ?? 0} / {status.detail.total_files}
            </p>
          {/if}
          {#if (status?.detail?.total_size ?? 0) > 0}
            <p>size: {formatBytes(status.detail.total_size)}</p>
          {/if}
          {#if status?.message}
            <p class="truncate text-slate-500">{status.message}</p>
          {/if}
          {#if status?.error}
            <p class="text-rose-600">{status.error}</p>
          {/if}
        </div>
      </div>

      <div class="mt-5 flex items-center justify-end gap-2">
        <AlertDialog.Cancel
          class="btn-ghost"
          type="button"
          onclick={() => {
            open = false;
            disconnect();
          }}
        >
          閉じる
        </AlertDialog.Cancel>

        {#if jobState === 'completed' && resultDatasetId}
          <Button.Root class="btn-ghost" type="button" onclick={openDetail}>
            詳細へ
          </Button.Root>
          <Button.Root class="btn-ghost" type="button" onclick={openViewer}>
            ビューアで開く
          </Button.Root>
        {/if}

        {#if showRetry}
          <Button.Root class="btn-primary" type="button" onclick={() => onRetry?.()}>
            再実行
          </Button.Root>
        {/if}
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>

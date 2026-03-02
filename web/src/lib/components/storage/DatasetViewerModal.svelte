<script lang="ts">
  import { Button } from 'bits-ui';
  import DatasetViewerPanel from '$lib/components/storage/DatasetViewerPanel.svelte';

  let {
    open = $bindable(false),
    datasetId = '',
    episodeIndex = 0,
    title = 'Dataset Viewer'
  }: {
    open?: boolean;
    datasetId?: string;
    episodeIndex?: number;
    title?: string;
  } = $props();

  const close = () => {
    open = false;
  };
</script>

{#if open}
  <div class="fixed inset-0 z-50 bg-slate-900/45 backdrop-blur-[1px]">
    <div class="mx-auto mt-5 w-[min(1360px,98vw)] rounded-2xl border border-slate-200/70 bg-white p-4 shadow-xl">
      <div class="flex items-center justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-slate-900">{title}</p>
          <p class="text-xs text-slate-500">{datasetId || 'dataset 未選択'}</p>
        </div>
        <Button.Root class="btn-ghost" type="button" onclick={close}>閉じる</Button.Root>
      </div>
      <div class="mt-4 h-[82vh] min-h-0">
        <DatasetViewerPanel {datasetId} {episodeIndex} />
      </div>
    </div>
  </div>
{/if}

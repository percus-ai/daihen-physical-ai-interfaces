<script lang="ts">
  import type { StorageDatasetInfo } from '$lib/api/client';
  import { buildDatasetDetailMetrics } from '$lib/storage/datasetDetail';

  let { dataset }: { dataset: StorageDatasetInfo } = $props();

  const metrics = $derived(buildDatasetDetailMetrics(dataset));
  const detail = $derived(dataset.detail ?? null);
  const cameras = $derived(detail?.cameras ?? []);
  const signalFields = $derived(detail?.signal_fields ?? []);
</script>

<section class="card p-6">
  <div class="nested-block-header">
    <div>
      <p class="section-title">詳細情報</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-950">収録の中身を確認</h2>
    </div>
  </div>

  {#if !dataset.is_local}
    <div class="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-900">
      ローカル未配置のため、フレーム数・FPS・カメラ情報・信号項目はまだ取得していません。同期後に更新すると詳細が表示されます。
    </div>
  {/if}

  <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
    {#each metrics as metric (metric.label)}
      <div class="nested-block-pane px-4 py-4">
        <p class="label">{metric.label}</p>
        <p class="mt-2 text-lg font-semibold text-slate-900">{metric.value}</p>
      </div>
    {/each}
  </div>

  {#if cameras.length > 0}
    <div class="mt-6">
      <div class="nested-block-header">
        <div>
          <p class="section-title">Cameras</p>
          <h3 class="mt-1 text-lg font-semibold text-slate-900">映像ストリーム</h3>
        </div>
      </div>
      <div class="grid gap-3 lg:grid-cols-2">
        {#each cameras as camera (camera.key)}
          <div class="nested-block-pane px-4 py-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <p class="text-sm font-semibold text-slate-900">{camera.label}</p>
              <span class="chip bg-white">{camera.key}</span>
            </div>
            <div class="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
              {#if camera.width && camera.height}
                <span class="chip bg-white">{camera.width} x {camera.height}</span>
              {/if}
              {#if camera.fps}
                <span class="chip bg-white">{camera.fps.toFixed(1)} FPS</span>
              {/if}
              {#if camera.codec}
                <span class="chip bg-white">{camera.codec}</span>
              {/if}
              {#if camera.pix_fmt}
                <span class="chip bg-white">{camera.pix_fmt}</span>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  {#if signalFields.length > 0}
    <div class="mt-6">
      <div class="nested-block-header">
        <div>
          <p class="section-title">Signals</p>
          <h3 class="mt-1 text-lg font-semibold text-slate-900">利用可能な信号項目</h3>
        </div>
      </div>
      <div class="grid gap-3 lg:grid-cols-2">
        {#each signalFields as field (field.key)}
          <div class="nested-block-pane px-4 py-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <p class="text-sm font-semibold text-slate-900">{field.label}</p>
              <span class="chip bg-white">{field.axis_count} axes</span>
            </div>
            <p class="mt-2 break-all font-mono text-xs text-slate-500">{field.key}</p>
            <div class="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
              {#if field.dtype}
                <span class="chip bg-white">{field.dtype}</span>
              {/if}
              {#each field.names.slice(0, 6) as name (name)}
                <span class="chip bg-white">{name}</span>
              {/each}
              {#if field.names.length > 6}
                <span class="chip bg-white">+{field.names.length - 6}</span>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</section>

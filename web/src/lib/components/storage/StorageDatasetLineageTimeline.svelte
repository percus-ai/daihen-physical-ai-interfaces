<script lang="ts">
  import type { StorageDatasetSourceInfo } from '$lib/api/client';
  import { buildSourceDatasetFacts } from '$lib/storage/datasetDetail';

  let { sources }: { sources: StorageDatasetSourceInfo[] } = $props();
</script>

<section class="card p-6">
  <div class="nested-block-header">
    <div>
      <p class="section-title">Lineage</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-950">このデータセットができるまで</h2>
      <p class="mt-2 text-sm text-slate-600">マージ元を履歴として読み下せる形で表示します。</p>
    </div>
    <span class="chip">{sources.length} sources</span>
  </div>

  <div class="mt-4 space-y-4">
    {#each sources as source, index (source.dataset_id)}
      <div class="grid grid-cols-[1.25rem_1fr] gap-4">
        <div class="flex flex-col items-center pt-2">
          <span class="h-3 w-3 rounded-full bg-brand shadow-[0_0_0_6px_rgba(91,124,250,0.12)]"></span>
          {#if index < sources.length - 1}
            <span class="mt-2 h-full w-px bg-slate-200"></span>
          {/if}
        </div>
        <div class="nested-block-pane px-4 py-4">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="label">Source {index + 1}</p>
              <a
                class="mt-2 block break-words text-base font-semibold text-slate-900 underline decoration-slate-300 underline-offset-2"
                href={`/storage/datasets/${encodeURIComponent(source.dataset_id)}`}
              >
                {source.name}
              </a>
            </div>
            <div class="flex flex-wrap gap-2">
              {#if source.status}
                <span class="chip bg-white">{source.status === 'archived' ? 'アーカイブ済み' : 'アクティブ'}</span>
              {/if}
              {#if source.is_local !== null && source.is_local !== undefined}
                <span class={`chip ${source.is_local ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                  {source.is_local ? '同期済み' : '未同期'}
                </span>
              {/if}
            </div>
          </div>

          <p class="mt-3 break-all font-mono text-xs text-slate-500">{source.dataset_id}</p>

          {#if source.task_detail}
            <div class="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-3">
              <p class="label">Task Detail</p>
              <p class="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">{source.task_detail}</p>
            </div>
          {/if}

          {#if buildSourceDatasetFacts(source).length > 0}
            <div class="mt-4 flex flex-wrap gap-2">
              {#each buildSourceDatasetFacts(source) as fact (fact)}
                <span class="chip bg-white">{fact}</span>
              {/each}
            </div>
          {/if}

          {#if source.content_hash}
            <p class="mt-4 break-all font-mono text-[11px] text-slate-500">{source.content_hash}</p>
          {/if}
        </div>
      </div>
    {/each}
  </div>
</section>

<script lang="ts">
  import type { StorageDatasetSourceInfo } from '$lib/api/client';
  import { buildSourceDatasetFacts } from '$lib/storage/datasetDetail';

  let { sources }: { sources: StorageDatasetSourceInfo[] } = $props();
</script>

<section class="card p-6">
  <div class="nested-block-header">
    <div>
      <p class="section-title">Lineage</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-950">マージ元</h2>
      <p class="mt-2 text-sm text-slate-600">元データセットを一覧で確認できます。</p>
    </div>
    <span class="chip">{sources.length} sources</span>
  </div>

  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full border-separate border-spacing-0 text-sm">
      <thead>
        <tr>
          <th class="border-b border-slate-200 px-3 py-2 text-left text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            データセット
          </th>
          <th class="border-b border-slate-200 px-3 py-2 text-left text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            タスク
          </th>
          <th class="border-b border-slate-200 px-3 py-2 text-left text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            詳細
          </th>
        </tr>
      </thead>
      <tbody>
        {#each sources as source (source.dataset_id)}
          <tr class="align-top">
            <td class="border-b border-slate-100 px-3 py-3">
              <a
                class="block break-words font-semibold text-slate-900 underline decoration-slate-300 underline-offset-2"
                href={`/storage/datasets/${encodeURIComponent(source.dataset_id)}`}
              >
                {source.name}
              </a>
              <p class="mt-1 break-all font-mono text-[11px] text-slate-500">{source.dataset_id}</p>
            </td>
            <td class="border-b border-slate-100 px-3 py-3">
              <p class="whitespace-pre-wrap text-xs leading-6 text-slate-700">{source.task_detail ?? '-'}</p>
            </td>
            <td class="border-b border-slate-100 px-3 py-3">
              <div class="flex flex-wrap gap-2">
                {#if source.status}
                  <span class="chip bg-white">{source.status === 'archived' ? 'アーカイブ済み' : 'アクティブ'}</span>
                {/if}
                {#if source.is_local !== null && source.is_local !== undefined}
                  <span class={`chip ${source.is_local ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                    {source.is_local ? '同期済み' : '未同期'}
                  </span>
                {/if}
                {#each buildSourceDatasetFacts(source).slice(0, 3) as fact (fact)}
                  <span class="chip bg-white">{fact}</span>
                {/each}
              </div>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

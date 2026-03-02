<script lang="ts">
  import { toStore } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import { api, type ExperimentEpisodeLink, type DatasetViewerResponse } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';
  import {
    kthUnselectedEpisodeIndex,
    normalizeSelectedEpisodeIndices,
    unselectedRowForEpisodeIndex,
    unselectedTotalRows as getUnselectedTotalRows
  } from '$lib/viewer/episodeIndexing';

  type DatasetListItem = {
    id: string;
    name?: string;
    status?: string;
  };

  let {
    datasets = [],
    recommendedDatasetId = '',
    previewDatasetId = '',
    previewEpisodeIndex = 0,
    episodeLinks = [],
    onPreview,
    onAdd,
    onRemove
  }: {
    datasets?: DatasetListItem[];
    recommendedDatasetId?: string;
    previewDatasetId?: string;
    previewEpisodeIndex?: number;
    episodeLinks?: ExperimentEpisodeLink[];
    onPreview?: (datasetId: string, episodeIndex: number) => void;
    onAdd?: (datasetId: string, episodeIndex: number) => void;
    onRemove?: (datasetId: string, episodeIndex: number) => void;
  } = $props();

  let step = $state<'dataset' | 'episode'>('dataset');
  let datasetQuery = $state('');
  let selectedDatasetId = $state('');
  let episodeJumpInput = $state('');

  const activeEpisodeLinks = $derived(
    [...(episodeLinks ?? [])].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
  );

  const normalizedPreviewEpisodeIndex = $derived(Math.max(0, Math.floor(Number(previewEpisodeIndex) || 0)));
  const previewKey = $derived(`${previewDatasetId}:${normalizedPreviewEpisodeIndex}`);

  const recommendedDataset = $derived(
    recommendedDatasetId ? datasets.find((item) => item.id === recommendedDatasetId) ?? null : null
  );

  const filteredDatasets = $derived.by(() => {
    const q = datasetQuery.trim().toLowerCase();
    const base = datasets ?? [];
    const items = q
      ? base.filter((item) => {
          const hay = `${item.id} ${item.name ?? ''}`.toLowerCase();
          return hay.includes(q);
        })
      : base;
    return items.filter((item) => item.id !== recommendedDatasetId);
  });

  const selectedDatasetViewerQuery = createQuery<DatasetViewerResponse>(
    toStore(() => ({
      queryKey: qk.storage.datasetViewer(selectedDatasetId),
      queryFn: () => api.storage.datasetViewer(selectedDatasetId),
      enabled: Boolean(selectedDatasetId)
    }))
  );

  const selectedTotalEpisodes = $derived(Number($selectedDatasetViewerQuery.data?.total_episodes ?? 0));

  const selectedIndicesSortedForDataset = $derived.by(() => {
    if (!selectedDatasetId) return [] as number[];
    const total = Math.max(0, Math.floor(Number(selectedTotalEpisodes) || 0));
    if (!Number.isFinite(total) || total <= 0) return [] as number[];

    const indices: number[] = [];
    for (const link of activeEpisodeLinks) {
      if (String(link.dataset_id ?? '') !== selectedDatasetId) continue;
      indices.push(Number(link.episode_index));
    }
    return normalizeSelectedEpisodeIndices(total, indices);
  });

  let unselectedScrollEl = $state<HTMLDivElement | null>(null);
  let unselectedScrollTop = $state(0);
  let unselectedViewportHeight = $state(240);
  const rowHeight = 44;
  const overscan = 6;

  const unselectedTotalRows = $derived.by(() => {
    if (!selectedDatasetId) return 0;
    const total = Math.max(0, Math.floor(Number(selectedTotalEpisodes) || 0));
    if (!Number.isFinite(total) || total <= 0) return 0;
    return getUnselectedTotalRows(total, selectedIndicesSortedForDataset);
  });
  const unselectedStartIndex = $derived(
    Math.max(0, Math.floor((unselectedScrollTop || 0) / rowHeight) - overscan)
  );
  const unselectedVisibleCount = $derived(
    Math.ceil((unselectedViewportHeight || 240) / rowHeight) + overscan * 2
  );
  const unselectedEndIndex = $derived(
    Math.min(unselectedTotalRows, unselectedStartIndex + unselectedVisibleCount)
  );
  const unselectedVisibleEpisodes = $derived.by(() => {
    if (!selectedDatasetId) return [] as number[];
    const total = Math.max(0, Math.floor(Number(selectedTotalEpisodes) || 0));
    if (!Number.isFinite(total) || total <= 0) return [] as number[];

    const result: number[] = [];
    const start = Math.max(0, Math.floor(Number(unselectedStartIndex) || 0));
    const end = Math.min(Math.max(0, Math.floor(Number(unselectedEndIndex) || 0)), unselectedTotalRows);
    for (let row = start; row < end; row += 1) {
      const episodeIndex = kthUnselectedEpisodeIndex(total, selectedIndicesSortedForDataset, row);
      if (episodeIndex !== null) result.push(episodeIndex);
    }
    return result;
  });

  const updateViewportHeight = () => {
    if (!unselectedScrollEl) return;
    const next = Math.max(120, Math.floor(unselectedScrollEl.clientHeight || 0));
    if (unselectedViewportHeight !== next) {
      unselectedViewportHeight = next;
    }
  };

  const handleDatasetPick = (datasetId: string) => {
    selectedDatasetId = datasetId;
    step = 'episode';
    episodeJumpInput = '';
    unselectedScrollTop = 0;
    if (unselectedScrollEl) {
      unselectedScrollEl.scrollTop = 0;
    }
  };

  const handlePreview = (datasetId: string, episodeIndex: number) => {
    onPreview?.(datasetId, Math.max(0, Math.floor(Number(episodeIndex) || 0)));
  };

  const handleAdd = (datasetId: string, episodeIndex: number) => {
    onAdd?.(datasetId, Math.max(0, Math.floor(Number(episodeIndex) || 0)));
  };

  const handleRemove = (datasetId: string, episodeIndex: number) => {
    onRemove?.(datasetId, Math.max(0, Math.floor(Number(episodeIndex) || 0)));
  };

  const handleJump = () => {
    if (!selectedDatasetId) return;
    const raw = Math.floor(Number(episodeJumpInput) || 0);
    if (!Number.isFinite(raw) || raw <= 0) return;
    const total = Math.max(0, Math.floor(Number(selectedTotalEpisodes) || 0));
    if (!Number.isFinite(total) || total <= 0) return;
    const episodeIndex = raw - 1;
    if (episodeIndex < 0 || episodeIndex >= total) return;
    handlePreview(selectedDatasetId, episodeIndex);

    // Best-effort: align the unselected list position to the target when it exists in that list.
    // (If already selected/linked, the episode won't exist in unselected list.)
    if (!unselectedScrollEl) return;
    const rowIndex = unselectedRowForEpisodeIndex(total, selectedIndicesSortedForDataset, episodeIndex);
    if (rowIndex === null) return;
    const nextTop = Math.max(0, rowIndex * rowHeight - rowHeight * 2);
    if (Math.abs(unselectedScrollEl.scrollTop - nextTop) > 1) {
      unselectedScrollEl.scrollTop = nextTop;
      unselectedScrollTop = nextTop;
    }
  };

  $effect(() => {
    // Keep the step selection reasonable when preview dataset changes outside this tab.
    if (previewDatasetId && !selectedDatasetId) {
      selectedDatasetId = previewDatasetId;
      step = 'episode';
    }
  });

  $effect(() => {
    // Resize observer without external deps.
    if (!unselectedScrollEl) return;
    updateViewportHeight();
    const observer = new ResizeObserver(() => {
      updateViewportHeight();
    });
    observer.observe(unselectedScrollEl);
    return () => {
      observer.disconnect();
    };
  });

</script>

{#if step === 'dataset'}
  <div class="space-y-3">
    <div>
      <p class="label">Dataset</p>
      <input
        class="input mt-2"
        type="text"
        placeholder="dataset を検索 (id / name)"
        value={datasetQuery}
        oninput={(event) => {
          datasetQuery = (event.currentTarget as HTMLInputElement).value;
        }}
      />
    </div>

    {#if recommendedDataset}
      <div class="rounded-xl border border-slate-200/70 bg-white/80 p-3">
        <p class="text-xs font-semibold text-slate-700">推奨</p>
        <div class="mt-2 flex items-center justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold text-slate-900">{recommendedDataset.name ?? recommendedDataset.id}</p>
            <p class="truncate text-xs text-slate-500">{recommendedDataset.id}</p>
          </div>
          <button
            class="btn-ghost shrink-0"
            type="button"
            onclick={() => handleDatasetPick(recommendedDataset.id)}
          >
            選ぶ
          </button>
        </div>
      </div>
    {/if}

    <div class="rounded-xl border border-slate-200/70 bg-white/80 p-3">
      <p class="text-xs font-semibold text-slate-700">すべて</p>
      <div class="mt-2 max-h-72 overflow-y-auto pr-1">
        {#if filteredDatasets.length}
          <div class="space-y-2">
            {#each filteredDatasets as item (item.id)}
              <div class="flex items-center justify-between gap-2 rounded-lg border border-slate-200/60 bg-white px-3 py-2">
                <div class="min-w-0">
                  <p class="truncate text-sm font-semibold text-slate-900">{item.name ?? item.id}</p>
                  <p class="truncate text-xs text-slate-500">{item.id}</p>
                </div>
                <button class="btn-ghost shrink-0" type="button" onclick={() => handleDatasetPick(item.id)}>
                  選ぶ
                </button>
              </div>
            {/each}
          </div>
        {:else}
          <p class="text-xs text-slate-500">一致する dataset がありません。</p>
        {/if}
      </div>
    </div>
  </div>
{:else}
  <div class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <button class="btn-ghost" type="button" onclick={() => (step = 'dataset')}>Back</button>
      <div class="min-w-0 text-right">
        <p class="truncate text-xs font-semibold text-slate-700">{selectedDatasetId || 'dataset 未選択'}</p>
        <p class="truncate text-[10px] text-slate-500">
          {#if $selectedDatasetViewerQuery.isLoading}
            エピソード数を取得中...
          {:else}
            total: {selectedTotalEpisodes}
          {/if}
        </p>
      </div>
    </div>

    <div class="rounded-xl border border-slate-200/70 bg-white/80 p-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-xs font-semibold text-slate-700">Episode ジャンプ (1-indexed)</p>
        {#if previewDatasetId}
          <p class="text-[10px] text-slate-500">
            表示中: {previewDatasetId} / ep {normalizedPreviewEpisodeIndex + 1}
          </p>
        {/if}
      </div>
      <div class="mt-2 flex items-center gap-2">
        <input
          class="input flex-1"
          type="number"
          min="1"
          placeholder="例: 1"
          value={episodeJumpInput}
          oninput={(event) => {
            episodeJumpInput = (event.currentTarget as HTMLInputElement).value;
          }}
          onkeydown={(event) => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            handleJump();
          }}
        />
        <button
          class="btn-ghost"
          type="button"
          onclick={handleJump}
          disabled={!selectedDatasetId || $selectedDatasetViewerQuery.isLoading || selectedTotalEpisodes <= 0}
        >
          表示
        </button>
      </div>
    </div>

    <div class="space-y-3">
	      <div class="rounded-xl border border-slate-200/70 bg-white/80 p-3">
	        <p class="text-xs font-semibold text-slate-700">選択済</p>
	        {#if activeEpisodeLinks.length}
	          <div class="mt-2 space-y-2">
	            {#each activeEpisodeLinks as link (link.dataset_id + ':' + link.episode_index)}
	              {@const datasetIdValue = String(link.dataset_id ?? '')}
	              {@const episodeValue = Math.max(0, Math.floor(Number(link.episode_index) || 0))}
	              {@const isActive = `${datasetIdValue}:${episodeValue}` === previewKey}
	              <div
	                class={`flex h-[44px] items-center justify-between gap-2 rounded-lg border bg-white px-3 py-2 ${
	                  isActive ? 'border-brand/50 shadow-sm' : 'border-slate-200/60'
	                }`}
	              >
	                <div class="min-w-0 flex-1">
	                  <p class="truncate text-xs font-semibold text-slate-900">{datasetIdValue}</p>
	                  <p class="truncate text-[10px] text-slate-500">ep {episodeValue + 1}</p>
	                </div>
	                <div class="flex shrink-0 gap-1">
	                  <button
	                    class="btn-ghost whitespace-nowrap px-3 py-1.5 text-xs"
	                    type="button"
	                    onclick={() => handlePreview(datasetIdValue, episodeValue)}
	                  >
	                    プレビュー
	                  </button>
	                  <button
	                    class="btn-ghost whitespace-nowrap border-rose-200/70 px-3 py-1.5 text-xs text-rose-600 hover:border-rose-300/80"
	                    type="button"
	                    onclick={() => handleRemove(datasetIdValue, episodeValue)}
	                  >
	                    削除
	                  </button>
	                </div>
	              </div>
	            {/each}
	          </div>
	        {:else}
	          <p class="mt-2 text-xs text-slate-500">まだ紐付いていません。</p>
	        {/if}
	      </div>

      <div class="rounded-xl border border-slate-200/70 bg-white/80 p-3">
        <p class="text-xs font-semibold text-slate-700">未選択</p>
        <div class="mt-2 h-80 overflow-y-auto pr-1" bind:this={unselectedScrollEl} onscroll={(event) => {
          unselectedScrollTop = (event.currentTarget as HTMLDivElement).scrollTop;
        }}>
          {#if !selectedDatasetId}
            <p class="text-xs text-slate-500">dataset を選択してください。</p>
          {:else if selectedTotalEpisodes <= 0}
            <p class="text-xs text-slate-500">エピソードがありません。</p>
          {:else if !unselectedTotalRows}
            <p class="text-xs text-slate-500">すべて選択済です。</p>
          {:else}
            <div style={`height:${unselectedTotalRows * rowHeight}px; position:relative;`}>
              <div style={`position:absolute; top:${unselectedStartIndex * rowHeight}px; left:0; right:0;`}>
                {#each unselectedVisibleEpisodes as episodeIndex (episodeIndex)}
                  <div class="flex h-[44px] items-center justify-between gap-2 rounded-lg border border-slate-200/60 bg-white px-3 py-2">
                    <div class="min-w-0 flex-1">
                      <p class="truncate text-xs font-semibold text-slate-900">{selectedDatasetId}</p>
                      <p class="truncate text-[10px] text-slate-500">ep {episodeIndex + 1}</p>
                    </div>
                    <div class="flex shrink-0 gap-1">
                      <button
                        class="btn-ghost whitespace-nowrap px-3 py-1.5 text-xs"
                        type="button"
                        onclick={() => handlePreview(selectedDatasetId, episodeIndex)}
                      >
                        プレビュー
                      </button>
                      <button
                        class="btn-ghost whitespace-nowrap px-3 py-1.5 text-xs"
                        type="button"
                        onclick={() => handleAdd(selectedDatasetId, episodeIndex)}
                      >
                        追加
                      </button>
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      </div>
    </div>
  </div>
{/if}

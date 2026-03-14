<script lang="ts">
  import { toStore } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import {
    api,
    type ExperimentEpisodeLink,
    type DatasetViewerEpisodeListResponse,
    type DatasetViewerResponse
  } from '$lib/api/client';
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

  const selectedDatasetEpisodesQuery = createQuery<DatasetViewerEpisodeListResponse>(
    toStore(() => ({
      queryKey: qk.storage.datasetViewerEpisodes(selectedDatasetId),
      queryFn: () => api.storage.datasetViewerEpisodes(selectedDatasetId),
      enabled: Boolean(selectedDatasetId)
    }))
  );

  const selectedTotalEpisodes = $derived(Number($selectedDatasetViewerQuery.data?.total_episodes ?? 0));
  const selectedEpisodeMetaMap = $derived.by(() => {
    const map = new Map<number, { frameCount: number; durationS: number; effectiveFps: number }>();
    const episodes = $selectedDatasetEpisodesQuery.data?.episodes ?? [];
    for (const episode of episodes) {
      const episodeIndex = Math.max(0, Math.floor(Number(episode.episode_index) || 0));
      const frameCount = Math.max(0, Math.floor(Number(episode.frame_count) || 0));
      const durationS = Math.max(0, Number(episode.duration_s) || 0);
      const effectiveFps = Math.max(0, Number(episode.effective_fps) || 0);
      map.set(episodeIndex, { frameCount, durationS, effectiveFps });
    }
    return map;
  });

  const formatEpisodeMeta = (datasetId: string, episodeIndex: number) => {
    if (!datasetId || datasetId !== selectedDatasetId) return '--s ・ --f ・ --FPS';
    const value = selectedEpisodeMetaMap.get(episodeIndex);
    if (!value) return '--s ・ --f ・ --FPS';
    const durationLabel = value.durationS > 0 ? `${value.durationS.toFixed(1)}s` : '--s';
    const frameLabel = value.frameCount > 0 ? `${value.frameCount}f` : '--f';
    const fpsLabel = value.effectiveFps > 0 ? `${value.effectiveFps.toFixed(1)} FPS` : '--FPS';
    return `${durationLabel} ・ ${frameLabel} ・ ${fpsLabel}`;
  };

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
  // Keep in sync with rendered row + gap (`h-[52px]` + `space-y-2`).
  const rowItemHeight = 52;
  const rowGap = 8;
  const rowStride = rowItemHeight + rowGap;
  const overscan = 6;

  const unselectedTotalRows = $derived.by(() => {
    if (!selectedDatasetId) return 0;
    const total = Math.max(0, Math.floor(Number(selectedTotalEpisodes) || 0));
    if (!Number.isFinite(total) || total <= 0) return 0;
    return getUnselectedTotalRows(total, selectedIndicesSortedForDataset);
  });
  const unselectedStartIndex = $derived(
    Math.max(0, Math.floor((unselectedScrollTop || 0) / rowStride) - overscan)
  );
  const unselectedVisibleCount = $derived(
    Math.ceil((unselectedViewportHeight || 240) / rowStride) + overscan * 2
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
    const nextTop = Math.max(0, rowIndex * rowStride - rowStride * 2);
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

<div class="flex h-full min-h-0 flex-col">
{#if step === 'dataset'}
  <div class="flex min-h-0 flex-1 flex-col gap-3">
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
      <div class="nested-block p-3">
        <p class="text-xs font-semibold text-slate-700">推奨</p>
        <div class="mt-2 flex items-center justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold text-slate-900">{recommendedDataset.name ?? recommendedDataset.id}</p>
            <p class="truncate text-xs text-slate-500">{recommendedDataset.id}</p>
          </div>
          <button
            class="btn-ghost inline-flex h-8 w-8 shrink-0 items-center justify-center p-0"
            type="button"
            onclick={() => handleDatasetPick(recommendedDataset.id)}
            aria-label="このデータセットを選択"
            title="選択"
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" class="h-3.5 w-3.5">
              <path d="M5 10h9M10 5l5 5-5 5" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    {/if}

    <div class="flex min-h-0 flex-1 flex-col nested-block p-3">
      <p class="text-xs font-semibold text-slate-700">すべて</p>
      <div class="mt-2 min-h-0 flex-1 overflow-y-auto pr-1">
        {#if filteredDatasets.length}
          <div class="space-y-2">
            {#each filteredDatasets as item (item.id)}
              <div class="flex h-[52px] items-center justify-between gap-2 rounded-lg border border-slate-200/60 bg-white px-3">
                <div class="min-w-0">
                  <p class="truncate text-sm font-semibold text-slate-900">{item.name ?? item.id}</p>
                  <p class="truncate text-xs text-slate-500">{item.id}</p>
                </div>
                <button
                  class="btn-ghost inline-flex h-8 w-8 shrink-0 items-center justify-center p-0"
                  type="button"
                  onclick={() => handleDatasetPick(item.id)}
                  aria-label="このデータセットを選択"
                  title="選択"
                >
                  <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" class="h-3.5 w-3.5">
                    <path d="M5 10h9M10 5l5 5-5 5" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
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
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <button class="btn-ghost" type="button" onclick={() => (step = 'dataset')}>戻る</button>
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

    <div class="nested-block p-3">
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

    <div class="flex min-h-0 flex-1 flex-col gap-3">
	      <div class="shrink-0 nested-block p-3">
	        <p class="text-xs font-semibold text-slate-700">選択済</p>
	        {#if activeEpisodeLinks.length}
	          <div class="mt-2 space-y-2">
	            {#each activeEpisodeLinks as link (link.dataset_id + ':' + link.episode_index)}
	              {@const datasetIdValue = String(link.dataset_id ?? '')}
	              {@const episodeValue = Math.max(0, Math.floor(Number(link.episode_index) || 0))}
	              {@const isActive = `${datasetIdValue}:${episodeValue}` === previewKey}
	              <div
	                class={`flex h-[52px] items-center justify-between gap-2 rounded-lg border bg-white px-3 ${
	                  isActive ? 'border-brand/50 shadow-sm' : 'border-slate-200/60'
	                }`}
	              >
	                <div class="min-w-0 flex-1">
	                  <p class="truncate text-sm font-semibold text-slate-900">エピソード {episodeValue + 1}</p>
	                  <p class="truncate text-xs text-slate-500">{formatEpisodeMeta(datasetIdValue, episodeValue)}</p>
	                </div>
	                <div class="flex shrink-0 gap-1">
	                  <button
	                    class="btn-ghost inline-flex h-8 w-8 items-center justify-center p-0"
	                    type="button"
	                    onclick={() => handlePreview(datasetIdValue, episodeValue)}
	                    aria-label={`エピソード ${episodeValue + 1} をプレビュー`}
	                    title="プレビュー"
	                  >
	                    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" class="h-3.5 w-3.5">
	                      <path d="M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5z" stroke-linecap="round" stroke-linejoin="round" />
	                      <circle cx="10" cy="10" r="2.5" />
	                    </svg>
	                  </button>
	                  <button
	                    class="btn-ghost inline-flex h-8 w-8 items-center justify-center border-rose-200/70 p-0 text-rose-600 hover:border-rose-300/80"
	                    type="button"
	                    onclick={() => handleRemove(datasetIdValue, episodeValue)}
	                    aria-label={`エピソード ${episodeValue + 1} の紐付けを削除`}
	                    title="削除"
	                  >
	                    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" class="h-3.5 w-3.5">
	                      <path d="M4 6h12M8 6V4h4v2M7 6v10m6-10v10M6 16h8" stroke-linecap="round" stroke-linejoin="round" />
	                    </svg>
	                  </button>
	                </div>
	              </div>
	            {/each}
	          </div>
	        {:else}
	          <p class="mt-2 text-xs text-slate-500">まだ紐付いていません。</p>
	        {/if}
	      </div>

      <div class="flex min-h-0 flex-1 flex-col nested-block p-3">
        <p class="text-xs font-semibold text-slate-700">未選択</p>
        <div class="mt-2 min-h-0 flex-1 overflow-y-auto pr-1" bind:this={unselectedScrollEl} onscroll={(event) => {
          unselectedScrollTop = (event.currentTarget as HTMLDivElement).scrollTop;
        }}>
          {#if !selectedDatasetId}
            <p class="text-xs text-slate-500">dataset を選択してください。</p>
          {:else if selectedTotalEpisodes <= 0}
            <p class="text-xs text-slate-500">エピソードがありません。</p>
          {:else if !unselectedTotalRows}
            <p class="text-xs text-slate-500">すべて選択済です。</p>
          {:else}
            <div
              style={`height:${unselectedTotalRows > 0 ? unselectedTotalRows * rowItemHeight + (unselectedTotalRows - 1) * rowGap : 0}px; position:relative;`}
            >
              <div
                class="space-y-2"
                style={`position:absolute; top:${unselectedStartIndex * rowStride}px; left:0; right:0;`}
              >
                {#each unselectedVisibleEpisodes as episodeIndex (episodeIndex)}
                  <div class="flex h-[52px] items-center justify-between gap-2 rounded-lg border border-slate-200/60 bg-white px-3">
                    <div class="min-w-0 flex-1">
                      <p class="truncate text-sm font-semibold text-slate-900">エピソード {episodeIndex + 1}</p>
                      <p class="truncate text-xs text-slate-500">{formatEpisodeMeta(selectedDatasetId, episodeIndex)}</p>
                    </div>
                    <div class="flex shrink-0 gap-1">
                      <button
                        class="btn-ghost inline-flex h-8 w-8 items-center justify-center p-0"
                        type="button"
                        onclick={() => handlePreview(selectedDatasetId, episodeIndex)}
                        aria-label={`エピソード ${episodeIndex + 1} をプレビュー`}
                        title="プレビュー"
                      >
                        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" class="h-3.5 w-3.5">
                          <path d="M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5z" stroke-linecap="round" stroke-linejoin="round" />
                          <circle cx="10" cy="10" r="2.5" />
                        </svg>
                      </button>
                      <button
                        class="btn-ghost inline-flex h-8 w-8 items-center justify-center p-0"
                        type="button"
                        onclick={() => handleAdd(selectedDatasetId, episodeIndex)}
                        aria-label={`エピソード ${episodeIndex + 1} を追加`}
                        title="追加"
                      >
                        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" class="h-3.5 w-3.5">
                          <path d="M10 4v12M4 10h12" stroke-linecap="round" stroke-linejoin="round" />
                        </svg>
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
</div>

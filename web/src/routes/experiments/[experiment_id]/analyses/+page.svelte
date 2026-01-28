<script lang="ts">
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';

  type Experiment = {
    id: string;
    name?: string;
  };

  type AnalysisBlock = {
    name?: string | null;
    purpose?: string | null;
    notes?: string | null;
    image_files?: string[] | null;
  };

  type AnalysisListResponse = {
    analyses?: AnalysisBlock[];
    total?: number;
  };

  type AnalysisDraft = {
    name: string;
    purpose: string;
    notes: string;
    imageText: string;
  };

  const experimentQuery = createQuery<Experiment>(
    derived(page, ($page) => {
      const experimentId = $page.params.experiment_id;
      return {
        queryKey: ['experiments', 'detail', experimentId],
        queryFn: () => api.experiments.get(experimentId),
        enabled: Boolean(experimentId)
      };
    })
  );

  const analysesQuery = createQuery<AnalysisListResponse>(
    derived(page, ($page) => {
      const experimentId = $page.params.experiment_id;
      return {
        queryKey: ['experiments', 'analyses', experimentId],
        queryFn: () => api.experiments.analyses(experimentId),
        enabled: Boolean(experimentId)
      };
    })
  );

  let analysisBlocks: AnalysisDraft[] = [];
  let initializedId = '';
  let submitting = false;
  let error = '';
  let success = '';

  $: experiment = $experimentQuery.data as Experiment | undefined;

  const fromServer = () => {
    const blocks = $analysesQuery.data?.analyses ?? [];
    analysisBlocks = blocks.map((block) => ({
      name: block.name ?? '',
      purpose: block.purpose ?? '',
      notes: block.notes ?? '',
      imageText: block.image_files?.join('\n') ?? ''
    }));
  };

  $: if (experiment && $analysesQuery.data && experiment.id !== initializedId) {
    fromServer();
    initializedId = experiment.id;
  }

  const updateBlock = (index: number, updates: Partial<AnalysisDraft>) => {
    analysisBlocks = analysisBlocks.map((block, idx) =>
      idx === index ? { ...block, ...updates } : block
    );
  };

  const addBlock = () => {
    analysisBlocks = [...analysisBlocks, { name: '', purpose: '', notes: '', imageText: '' }];
  };

  const removeBlock = (index: number) => {
    analysisBlocks = analysisBlocks.filter((_, idx) => idx !== index);
  };

  const parseImageKeys = (text: string) =>
    text
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);

  const handleSave = async () => {
    if (!experiment) return;
    submitting = true;
    error = '';
    success = '';
    try {
      const items = analysisBlocks.map((block) => ({
        name: block.name || null,
        purpose: block.purpose || null,
        notes: block.notes || null,
        image_files: parseImageKeys(block.imageText)
      }));
      await api.experiments.replaceAnalyses(experiment.id, { items });
      const refetch = $analysesQuery?.refetch;
      if (typeof refetch === 'function') {
        await refetch();
      }
      fromServer();
      success = '考察を保存しました。';
    } catch {
      error = '考察の保存に失敗しました。';
    } finally {
      submitting = false;
    }
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Experiments</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">考察入力</h1>
      <p class="mt-2 text-sm text-slate-600">{experiment?.name ?? experiment?.id ?? ''}</p>
    </div>
    <div class="flex flex-wrap gap-2">
      {#if experiment?.id}
        <Button.Root class="btn-ghost" href={`/experiments/${experiment.id}`}>詳細へ</Button.Root>
        <Button.Root class="btn-ghost" href={`/experiments/${experiment.id}/evaluations`}>評価入力へ</Button.Root>
      {/if}
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">考察ブロック</h2>
    <div class="flex flex-wrap gap-2">
      <button class="btn-ghost" type="button" on:click={addBlock}>ブロック追加</button>
      <button class="btn-primary" type="button" on:click={handleSave} disabled={submitting}>
        保存
      </button>
    </div>
  </div>

  {#if error}
    <p class="mt-3 text-sm text-rose-600">{error}</p>
  {/if}
  {#if success}
    <p class="mt-3 text-sm text-emerald-600">{success}</p>
  {/if}

  <div class="mt-4 space-y-4">
    {#if $analysesQuery.isLoading}
      <p class="text-sm text-slate-500">読み込み中...</p>
    {:else if analysisBlocks.length}
      {#each analysisBlocks as block, index}
        <div class="rounded-2xl border border-slate-200/70 bg-white/80 p-4 shadow-sm">
          <div class="flex items-center justify-between">
            <p class="font-semibold text-slate-800">ブロック {index + 1}</p>
            <button class="btn-ghost text-xs" type="button" on:click={() => removeBlock(index)}>
              削除
            </button>
          </div>
          <div class="mt-3 grid gap-3">
            <label class="text-sm font-semibold text-slate-700">
              <span class="label">考察名</span>
              <input
                class="input mt-2"
                type="text"
                value={block.name}
                on:input={(event) =>
                  updateBlock(index, { name: (event.currentTarget as HTMLInputElement).value })
                }
              />
            </label>
            <label class="text-sm font-semibold text-slate-700">
              <span class="label">考察目的</span>
              <input
                class="input mt-2"
                type="text"
                value={block.purpose}
                on:input={(event) =>
                  updateBlock(index, { purpose: (event.currentTarget as HTMLInputElement).value })
                }
              />
            </label>
            <label class="text-sm font-semibold text-slate-700">
              <span class="label">考察内容</span>
              <textarea
                class="input mt-2 min-h-[120px]"
                value={block.notes}
                on:input={(event) =>
                  updateBlock(index, { notes: (event.currentTarget as HTMLTextAreaElement).value })
                }
              ></textarea>
            </label>
            <label class="text-sm font-semibold text-slate-700">
              <span class="label">画像キー（改行区切り）</span>
              <textarea
                class="input mt-2 min-h-[96px]"
                value={block.imageText}
                on:input={(event) =>
                  updateBlock(index, { imageText: (event.currentTarget as HTMLTextAreaElement).value })
                }
              ></textarea>
            </label>
          </div>
        </div>
      {/each}
    {:else}
      <p class="text-sm text-slate-500">考察ブロックがありません。</p>
    {/if}
  </div>
</section>

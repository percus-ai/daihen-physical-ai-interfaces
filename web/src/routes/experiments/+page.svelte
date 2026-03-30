<script lang="ts">
  import { Button, DropdownMenu, Tooltip } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { page } from '$app/state';
  import { toStore } from 'svelte/store';
  import { api } from '$lib/api/client';
  import ListFilterPopover from '$lib/components/ListFilterPopover.svelte';
  import PaginationControls from '$lib/components/PaginationControls.svelte';
  import type { ListFilterField } from '$lib/listFilters';
  import { qk } from '$lib/queryKeys';
  import { formatDate, formatPercent } from '$lib/format';
  import { goto } from '$app/navigation';
  import {
    DEFAULT_PAGE_SIZE,
    PAGE_SIZE_OPTIONS,
    buildPageHref,
    buildUrlWithQueryState,
    clampPage,
    parsePageParam,
    parsePageSizeParam
  } from '$lib/pagination';
  import CheckCircle from 'phosphor-svelte/lib/CheckCircle';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import FileText from 'phosphor-svelte/lib/FileText';
  import Lightbulb from 'phosphor-svelte/lib/Lightbulb';

  type ModelSummary = {
    id: string;
    name?: string;
    dataset_id?: string;
  };

  type Experiment = {
    id: string;
    model_id?: string | null;
    profile_instance_id?: string | null;
    name?: string;
    evaluation_count?: number;
    metric_options?: string[] | null;
    updated_at?: string;
  };

  type ExperimentListResponse = {
    experiments?: Experiment[];
    total?: number;
  };

  type EvaluationSummary = {
    total?: number;
    rates?: Record<string, number>;
  };

  type AnalysisListResponse = {
    analyses?: Array<{ id?: string }>;
    total?: number;
  };

  type RateEntry = {
    label: string;
    value: number;
  };

  const modelsQuery = createQuery<{ models?: ModelSummary[] }>({
    queryKey: qk.storage.models(),
    queryFn: () => api.storage.models()
  });

  let filterDialogOpen = $state(false);
  const pageSize = $derived(parsePageSizeParam(page.url.searchParams.get('page_size')));
  const selectedModel = $derived(page.url.searchParams.get('model_id') || '');
  const selectedProfileInstance = $derived(page.url.searchParams.get('profile_instance_id') || '');
  const updatedFrom = $derived(page.url.searchParams.get('updated_from') || '');
  const updatedTo = $derived(page.url.searchParams.get('updated_to') || '');
  const evaluationCountMin = $derived(page.url.searchParams.get('evaluation_count_min') || '');
  const evaluationCountMax = $derived(page.url.searchParams.get('evaluation_count_max') || '');
  const currentPage = $derived(parsePageParam(page.url.searchParams.get('page')));
  const parseOptionalInt = (value: string) => {
    const normalized = value.trim();
    if (!normalized) return undefined;
    const parsed = Number.parseInt(normalized, 10);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const experimentsQuery = createQuery<ExperimentListResponse>(
    toStore(() => ({
      queryKey: ['experiments', selectedModel, selectedProfileInstance, updatedFrom, updatedTo, evaluationCountMin, evaluationCountMax, currentPage],
      queryFn: () =>
        api.experiments.list({
          model_id: selectedModel || undefined,
          profile_instance_id: selectedProfileInstance || undefined,
          updated_from: updatedFrom || undefined,
          updated_to: updatedTo || undefined,
          evaluation_count_min: parseOptionalInt(evaluationCountMin),
          evaluation_count_max: parseOptionalInt(evaluationCountMax),
          limit: pageSize,
          offset: (currentPage - 1) * pageSize
        })
    }))
  );

  let summaryById = $state<Record<string, EvaluationSummary>>({});
  let analysisById = $state<Record<string, number>>({});
  let summariesLoading = $state(false);
  let summariesError = $state('');
  let summaryKey = $state('');

  const experiments = $derived($experimentsQuery.data?.experiments ?? []);
  const totalExperiments = $derived($experimentsQuery.data?.total ?? 0);
  const modelMap = $derived(
    new Map(($modelsQuery.data?.models ?? []).map((model) => [model.id, model]))
  );
  const experimentsError = $derived.by(() =>
    $experimentsQuery.isError
      ? $experimentsQuery.error instanceof Error
        ? $experimentsQuery.error.message
        : '実験一覧の取得に失敗しました。'
      : ''
  );
  const experimentFilterDefaults = {
    model_id: '',
    profile_instance_id: '',
    updated_from: '',
    updated_to: '',
    evaluation_count_min: '',
    evaluation_count_max: '',
    page_size: String(DEFAULT_PAGE_SIZE)
  };
  const experimentFilterValues = $derived({
    model_id: selectedModel,
    profile_instance_id: selectedProfileInstance,
    updated_from: updatedFrom,
    updated_to: updatedTo,
    evaluation_count_min: evaluationCountMin,
    evaluation_count_max: evaluationCountMax,
    page_size: String(pageSize)
  });
  const experimentFilterFields = $derived<ListFilterField[]>([
    {
      section: '条件',
      type: 'select',
      key: 'model_id',
      label: 'モデル',
      options: [
        { value: '', label: 'すべて' },
        ...($modelsQuery.data?.models ?? []).map((model) => ({
          value: model.id,
          label: model.name ?? model.id
        }))
      ]
    },
    {
      section: '条件',
      type: 'text',
      key: 'profile_instance_id',
      label: 'プロファイル',
      placeholder: 'プロファイル ID で絞り込み'
    },
    {
      section: '期間・範囲',
      type: 'date-range',
      keyFrom: 'updated_from',
      keyTo: 'updated_to',
      label: '更新日時'
    },
    {
      section: '期間・範囲',
      type: 'number-range',
      keyMin: 'evaluation_count_min',
      keyMax: 'evaluation_count_max',
      label: '評価回数',
      min: 0,
      step: 1,
      placeholderMin: '最小',
      placeholderMax: '最大'
    },
    {
      section: '表示',
      type: 'select',
      key: 'page_size',
      label: '1ページの件数',
      options: PAGE_SIZE_OPTIONS.map((size) => ({ value: String(size), label: `${size}件` }))
    }
  ]);
  const hasActiveFilters = $derived(
    Boolean(selectedModel) ||
      Boolean(selectedProfileInstance) ||
      Boolean(updatedFrom) ||
      Boolean(updatedTo) ||
      Boolean(evaluationCountMin) ||
      Boolean(evaluationCountMax) ||
      pageSize !== DEFAULT_PAGE_SIZE
  );

  const navigateToPage = async (nextPage: number) => {
    const href = buildPageHref(page.url, nextPage);
    const currentHref = `${page.url.pathname}${page.url.search}${page.url.hash}`;
    if (href === currentHref) return;
    await goto(href, {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
      invalidateAll: false
    });
  };
  const applyExperimentFilters = async (values: Record<string, string>) => {
    const nextHref = buildUrlWithQueryState(page.url, {
      model_id: values.model_id || null,
      profile_instance_id: values.profile_instance_id || null,
      updated_from: values.updated_from || null,
      updated_to: values.updated_to || null,
      evaluation_count_min: values.evaluation_count_min || null,
      evaluation_count_max: values.evaluation_count_max || null,
      page_size: values.page_size !== String(DEFAULT_PAGE_SIZE) ? values.page_size : null,
      page: null
    });
    filterDialogOpen = false;
    const currentHref = `${page.url.pathname}${page.url.search}${page.url.hash}`;
    if (nextHref === currentHref) return;
    await goto(nextHref, {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
      invalidateAll: false
    });
  };

  $effect(() => {
    const key = experiments.map((exp) => exp.id).join('|');
    if (key !== summaryKey) {
      summaryKey = key;
      void loadSummaries();
    }
  });

  $effect(() => {
    if ($experimentsQuery.isLoading) {
      return;
    }
    const nextPage = clampPage(currentPage, totalExperiments, pageSize);
    if (nextPage !== currentPage) {
      void navigateToPage(nextPage);
    }
  });

  const loadSummaries = async () => {
    if (!experiments.length) {
      summaryById = {};
      analysisById = {};
      summariesError = '';
      return;
    }
    summariesLoading = true;
    summariesError = '';

    const nextSummary: Record<string, EvaluationSummary> = {};
    const nextAnalysis: Record<string, number> = {};
    let hasError = false;

    await Promise.all(
      experiments.map(async (exp) => {
        try {
          const [summary, analyses] = await Promise.all([
            api.experiments.evaluationSummary(exp.id) as Promise<EvaluationSummary>,
            api.experiments.analyses(exp.id) as Promise<AnalysisListResponse>
          ]);
          nextSummary[exp.id] = summary ?? {};
          nextAnalysis[exp.id] = analyses?.total ?? analyses?.analyses?.length ?? 0;
        } catch {
          hasError = true;
        }
      })
    );

    summaryById = nextSummary;
    analysisById = nextAnalysis;
    summariesLoading = false;
    if (hasError) {
      summariesError = '集計情報の取得に失敗しました。';
    }
  };

  const buildRateEntries = (
    options: string[] | null | undefined,
    rates?: Record<string, number>
  ): RateEntry[] => {
    if (!rates) return [];
    const entries: RateEntry[] = [];
    const used = new Set<string>();
    if (options?.length) {
      for (const option of options) {
        if (option in rates) {
          entries.push({ label: option, value: rates[option] });
          used.add(option);
        }
      }
    }
    for (const [label, value] of Object.entries(rates)) {
      if (!used.has(label)) {
        entries.push({ label, value });
      }
    }
    return entries;
  };

  const formatRateValues = (entries: RateEntry[]) => {
    if (!entries.length) return '-';
    const values = entries.map((entry) => Math.round(entry.value));
    return `${values.join('/')}${values.length ? '%' : ''}`;
  };

  const formatRateTooltip = (entries: RateEntry[]) => {
    if (!entries.length) return '-';
    return entries.map((entry) => `${entry.label}: ${formatPercent(entry.value)}`).join(' / ');
  };

  const refreshAll = async () => {
    const refetch = $experimentsQuery?.refetch;
    if (typeof refetch === 'function') {
      await refetch();
    }
    await loadSummaries();
  };
</script>

<section class="card-strong p-8">
  <p class="section-title">Experiments</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">実験管理</h1>
      <p class="mt-2 text-sm text-slate-600">実験の一覧・評価・考察をまとめて管理します。</p>
    </div>
    <Button.Root class="btn-primary" href="/experiments/new">実験を作成</Button.Root>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">実験一覧</h2>
    <div class="flex items-center gap-2">
      <PaginationControls
        currentPage={currentPage}
        pageSize={pageSize}
        totalItems={totalExperiments}
        disabled={$experimentsQuery.isLoading}
        compact={true}
        onPageChange={navigateToPage}
      />
      <ListFilterPopover
        bind:open={filterDialogOpen}
        fields={experimentFilterFields}
        values={experimentFilterValues}
        defaults={experimentFilterDefaults}
        active={hasActiveFilters}
        onApply={applyExperimentFilters}
      />
    </div>
  </div>
  {#if summariesLoading}
    <p class="mt-3 text-xs text-slate-500">集計を取得中...</p>
  {/if}
  {#if summariesError}
    <p class="mt-3 text-xs text-rose-600">{summariesError}</p>
  {/if}
  {#if experimentsError}
    <p class="mt-2 text-xs text-rose-600">{experimentsError}</p>
  {/if}
  <p class="mt-2 text-xs text-slate-500">更新: {formatDate(experiments[0]?.updated_at)}</p>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">実験名</th>
          <th class="pb-3">モデル</th>
          <th class="pb-3">プロファイル</th>
          <th class="pb-3">評価回数</th>
          <th class="pb-3">評価件数</th>
          <th class="pb-3">カテゴリ比率</th>
          <th class="pb-3">考察</th>
          <th class="pb-3">更新日時</th>
          <th class="pb-3 text-right">操作</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $experimentsQuery.isLoading}
          <tr><td class="py-3" colspan="9">読み込み中...</td></tr>
        {:else if experimentsError}
          <tr><td class="py-3" colspan="9">実験一覧の取得に失敗しました。</td></tr>
        {:else if experiments.length}
          {#each experiments as exp}
            <tr class="border-t border-slate-200/60">
              <td class="py-3">{exp.name ?? '-'}</td>
              <td class="py-3">
                {#if exp.model_id}
                  <Tooltip.Root>
                    <Tooltip.Trigger type={null}>
                      {#snippet child({ props })}
                        <a
                          {...props}
                          class="text-xs font-semibold text-brand underline underline-offset-2"
                          href={`/storage/models/${exp.model_id}`}
                        >
                          開く
                        </a>
                      {/snippet}
                    </Tooltip.Trigger>
                    <Tooltip.Portal>
                      <Tooltip.Content
                        class="rounded-lg bg-slate-900/90 px-2 py-1 text-xs text-white shadow-lg"
                        sideOffset={6}
                      >
                        {modelMap.get(exp.model_id)?.name ?? exp.model_id}
                      </Tooltip.Content>
                    </Tooltip.Portal>
                  </Tooltip.Root>
                {:else}
                  <span class="text-xs text-slate-400">未設定</span>
                {/if}
              </td>
              <td class="py-3">
                {#if exp.profile_instance_id}
                  <span class="text-xs font-semibold text-slate-700">{exp.profile_instance_id}</span>
                {:else}
                  <span class="text-xs text-slate-400">未設定</span>
                {/if}
              </td>
              <td class="py-3">{exp.evaluation_count ?? 0}</td>
              <td class="py-3">{summariesLoading ? '-' : summaryById[exp.id]?.total ?? 0}</td>
              <td class="py-3">
                {#if summariesLoading}
                  -
                {:else}
                  {@const rateEntries = buildRateEntries(exp.metric_options, summaryById[exp.id]?.rates)}
                  {#if rateEntries.length}
                    <Tooltip.Root>
                      <Tooltip.Trigger type={null}>
                        {#snippet child({ props })}
                          <span {...props} class="cursor-help">
                            {formatRateValues(rateEntries)}
                          </span>
                        {/snippet}
                      </Tooltip.Trigger>
                      <Tooltip.Portal>
                        <Tooltip.Content
                          class="rounded-lg bg-slate-900/90 px-2 py-1 text-xs text-white shadow-lg"
                          sideOffset={6}
                        >
                          {formatRateTooltip(rateEntries)}
                        </Tooltip.Content>
                      </Tooltip.Portal>
                    </Tooltip.Root>
                  {:else}
                    -
                  {/if}
                {/if}
              </td>
              <td class="py-3">{summariesLoading ? '-' : analysisById[exp.id] ? 'あり' : 'なし'}</td>
              <td class="py-3">{formatDate(exp.updated_at)}</td>
              <td class="py-3 text-right">
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger
                    class="btn-ghost ml-auto h-8 w-8 p-0 text-slate-600"
                    aria-label="操作メニュー"
                    title="操作"
                  >
                    <DotsThree size={18} weight="bold" />
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Portal>
                    <DropdownMenu.Content
                      class="z-50 min-w-[180px] rounded-xl border border-slate-200/80 bg-white/95 p-2 text-xs text-slate-700 shadow-lg backdrop-blur"
                      sideOffset={6}
                      align="end"
                      preventScroll={false}
                    >
                      <DropdownMenu.Group>
                        <DropdownMenu.GroupHeading
                          class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                        >
                          表示
                        </DropdownMenu.GroupHeading>
                        <DropdownMenu.Item
                          class="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                          onSelect={() => goto(`/experiments/${exp.id}`)}
                        >
                          <FileText size={16} class="text-slate-500" />
                          開く
                        </DropdownMenu.Item>
                        <DropdownMenu.Item
                          class="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                          onSelect={() => goto(`/experiments/${exp.id}/evaluations`)}
                        >
                          <CheckCircle size={16} class="text-slate-500" />
                          評価
                        </DropdownMenu.Item>
                        <DropdownMenu.Item
                          class="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100"
                          onSelect={() => goto(`/experiments/${exp.id}/analyses`)}
                        >
                          <Lightbulb size={16} class="text-slate-500" />
                          考察
                        </DropdownMenu.Item>
                      </DropdownMenu.Group>
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="9">実験がありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
  <PaginationControls
    currentPage={currentPage}
    pageSize={pageSize}
    totalItems={totalExperiments}
    disabled={$experimentsQuery.isLoading}
    onPageChange={navigateToPage}
  />
</section>

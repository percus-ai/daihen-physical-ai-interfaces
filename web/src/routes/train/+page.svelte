<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import { api } from '$lib/api/client';
  import ListFilterPopover from '$lib/components/ListFilterPopover.svelte';
  import PaginationControls from '$lib/components/PaginationControls.svelte';
  import { formatDate } from '$lib/format';
  import type { ListFilterField } from '$lib/listFilters';
  import { DEFAULT_PAGE_SIZE, buildPageHref, buildUrlWithQueryState, clampPage, parsePageParam } from '$lib/pagination';

  type TrainingJob = {
    job_id: string;
    job_name?: string;
    owner_user_id?: string;
    owner_email?: string;
    owner_name?: string;
    dataset_id?: string;
    dataset_name?: string;
    policy_type?: string;
    status?: string;
    created_at?: string;
    updated_at?: string;
  };

  type JobListResponse = {
    jobs?: TrainingJob[];
    total?: number;
  };
  const JOB_SORT_KEYS = ['created_at', 'updated_at', 'job_name', 'status'] as const;
  const parseJobSortKey = (value: string | null): 'created_at' | 'updated_at' | 'job_name' | 'status' =>
    JOB_SORT_KEYS.includes((value ?? '') as (typeof JOB_SORT_KEYS)[number])
      ? ((value ?? '') as 'created_at' | 'updated_at' | 'job_name' | 'status')
      : 'created_at';
  const parseSortOrder = (value: string | null): 'desc' | 'asc' => (value === 'asc' ? 'asc' : 'desc');

  let filterDialogOpen = $state(false);
  const jobSortKey = $derived(parseJobSortKey(page.url.searchParams.get('sort')));
  const jobSortOrder = $derived(parseSortOrder(page.url.searchParams.get('order')));
  const jobOwnerFilter = $derived(page.url.searchParams.get('owner') || 'all');
  const jobSearch = $derived(page.url.searchParams.get('search') || '');

  const PAGE_SIZE = DEFAULT_PAGE_SIZE;
  const currentPage = $derived(parsePageParam(page.url.searchParams.get('page')));

  const jobsQuery = createQuery<JobListResponse>(
    toStore(() => ({
      queryKey: [
        'training',
        'jobs',
        {
          ownerUserId: jobOwnerFilter === 'all' ? undefined : jobOwnerFilter,
          search: jobSearch || undefined,
          sortBy: jobSortKey,
          sortOrder: jobSortOrder,
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE
        }
      ],
      queryFn: () =>
        api.training.jobs({
          ownerUserId: jobOwnerFilter === 'all' ? undefined : jobOwnerFilter,
          search: jobSearch || undefined,
          sortBy: jobSortKey,
          sortOrder: jobSortOrder,
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE
        })
    }))
  );

  const jobs = $derived($jobsQuery.data?.jobs ?? []);
  const totalJobs = $derived($jobsQuery.data?.total ?? 0);
  const displayedJobs = $derived(jobs);
  const displayDatasetName = (datasetId?: string | null) => {
    const normalized = String(datasetId ?? '').trim();
    if (!normalized) return '-';
    return normalized;
  };
  const creatorLabel = (value?: string | null) => {
    const normalized = String(value ?? '').trim();
    if (!normalized) return '-';
    if (normalized.length <= 24) return normalized;
    return `${normalized.slice(0, 20)}...`;
  };
  const ownerLabel = (job: TrainingJob) =>
    creatorLabel(job.owner_name ?? job.owner_email ?? job.owner_user_id);
  const jobOwnerOptions = $derived.by(() => {
    const options = new Map<string, string>();
    for (const job of jobs) {
      const ownerId = String(job.owner_user_id ?? '').trim();
      if (!ownerId) continue;
      options.set(ownerId, ownerLabel(job));
    }
    return Array.from(options, ([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label, 'ja'));
  });
  const jobOwnerSelectOptions = $derived.by(() => {
    const options = [{ value: 'all', label: '全員' }, ...jobOwnerOptions.map((owner) => ({ value: owner.id, label: owner.label }))];
    if (jobOwnerFilter !== 'all' && !options.some((option) => option.value === jobOwnerFilter)) {
      options.push({ value: jobOwnerFilter, label: jobOwnerFilter });
    }
    return options;
  });
  const trainingFilterDefaults = {
    search: '',
    owner: 'all',
    sort: 'created_at',
    order: 'desc'
  };
  const trainingFilterValues = $derived({
    search: jobSearch,
    owner: jobOwnerFilter,
    sort: jobSortKey,
    order: jobSortOrder
  });
  const trainingFilterFields = $derived<ListFilterField[]>([
    {
      type: 'text',
      key: 'search',
      label: '検索',
      placeholder: 'job / dataset / user'
    },
    {
      type: 'select',
      key: 'owner',
      label: '作成者',
      options: jobOwnerSelectOptions
    },
    {
      type: 'select',
      key: 'sort',
      label: '並び替え',
      options: [
        { value: 'created_at', label: '作成日時' },
        { value: 'updated_at', label: '更新日時' },
        { value: 'job_name', label: 'ジョブ名' },
        { value: 'status', label: '状態' }
      ]
    },
    {
      type: 'select',
      key: 'order',
      label: '順序',
      options: [
        { value: 'desc', label: '降順' },
        { value: 'asc', label: '昇順' }
      ]
    }
  ]);
  const hasActiveJobFilters = $derived(
    Boolean(jobSearch) || jobOwnerFilter !== 'all' || jobSortKey !== 'created_at' || jobSortOrder !== 'desc'
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
  const applyTrainingFilters = async (values: Record<string, string>) => {
    const nextHref = buildUrlWithQueryState(page.url, {
      owner: values.owner !== 'all' ? values.owner : null,
      search: values.search || null,
      sort: values.sort !== 'created_at' ? values.sort : null,
      order: values.order !== 'desc' ? values.order : null,
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

  const clearJobFilters = async () => {
    const nextHref = buildUrlWithQueryState(page.url, {
      owner: null,
      search: null,
      sort: null,
      order: null,
      page: null
    });
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
    if ($jobsQuery.isLoading) {
      return;
    }
    const nextPage = clampPage(currentPage, totalJobs, PAGE_SIZE);
    if (nextPage !== currentPage) {
      void navigateToPage(nextPage);
    }
  });

</script>

<section class="card-strong p-8">
  <p class="section-title">Train</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル学習</h1>
      <p class="mt-2 text-sm text-slate-600">
        学習ジョブの状態を一覧で確認します。
      </p>
    </div>
    <div class="flex gap-3">
      <Button.Root class="btn-primary" href="/train/new">新規学習</Button.Root>
      <Button.Root class="btn-ghost opacity-50 cursor-not-allowed" disabled title="準備中">
        継続学習
      </Button.Root>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">学習ジョブ一覧</h2>
    <div class="flex items-center gap-2">
      <PaginationControls
        currentPage={currentPage}
        pageSize={PAGE_SIZE}
        totalItems={totalJobs}
        disabled={$jobsQuery.isLoading}
        compact={true}
        onPageChange={navigateToPage}
      />
      <ListFilterPopover
        bind:open={filterDialogOpen}
        fields={trainingFilterFields}
        values={trainingFilterValues}
        defaults={trainingFilterDefaults}
        active={hasActiveJobFilters}
        onApply={applyTrainingFilters}
        onClear={clearJobFilters}
      />
    </div>
  </div>
  <div class="mt-4 space-y-2 text-sm text-slate-600">
    {#if $jobsQuery.isLoading}
      <p>読み込み中...</p>
    {:else if displayedJobs.length}
      {#each displayedJobs as job}
        <a
          class="nested-block nested-block-interactive flex items-center justify-between gap-3 px-3 py-2"
          href={`/train/jobs/${job.job_id}`}
        >
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold text-slate-800">{job.job_name}</p>
            <p class="mt-0.5 truncate text-[11px] text-slate-500">
              {job.dataset_name ?? displayDatasetName(job.dataset_id)} / {job.policy_type ?? '-'}
            </p>
            <p class="mt-0.5 truncate text-[10px] text-slate-400">
              creator: {ownerLabel(job)} / created: {formatDate(job.created_at)}
            </p>
          </div>
          <span class="shrink-0 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-600">
            {job.status}
          </span>
        </a>
      {/each}
    {:else}
      <p>条件に合う学習ジョブがありません。</p>
    {/if}
  </div>
  <PaginationControls
    currentPage={currentPage}
    pageSize={PAGE_SIZE}
    totalItems={totalJobs}
    disabled={$jobsQuery.isLoading}
    onPageChange={navigateToPage}
  />
  <div class="mt-4 text-xs text-slate-500">最終更新: {formatDate(displayedJobs[0]?.updated_at)}</div>
</section>

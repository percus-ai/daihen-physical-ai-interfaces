<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import ArrowDown from 'phosphor-svelte/lib/ArrowDown';
  import ArrowUp from 'phosphor-svelte/lib/ArrowUp';
  import CaretUpDown from 'phosphor-svelte/lib/CaretUpDown';
  import { toStore } from 'svelte/store';
  import { api } from '$lib/api/client';
  import ListFilterPopover from '$lib/components/ListFilterPopover.svelte';
  import PaginationControls from '$lib/components/PaginationControls.svelte';
  import { formatDate, formatRelativeDate } from '$lib/format';
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
    owner_options?: Array<{
      user_id: string;
      label: string;
      owner_name?: string | null;
      owner_email?: string | null;
      total_count?: number;
      available_count?: number;
    }>;
    status_options?: Array<{
      value: string;
      label: string;
      total_count?: number;
      available_count?: number;
    }>;
    policy_options?: Array<{
      value: string;
      label: string;
      total_count?: number;
      available_count?: number;
    }>;
  };
  const JOB_SORT_KEYS = ['created_at', 'updated_at', 'job_name', 'owner_name', 'policy_type', 'status'] as const;
  const parseJobSortKey = (value: string | null): 'created_at' | 'updated_at' | 'job_name' | 'owner_name' | 'policy_type' | 'status' =>
    JOB_SORT_KEYS.includes((value ?? '') as (typeof JOB_SORT_KEYS)[number])
      ? ((value ?? '') as 'created_at' | 'updated_at' | 'job_name' | 'owner_name' | 'policy_type' | 'status')
      : 'created_at';
  const parseSortOrder = (value: string | null): 'desc' | 'asc' => (value === 'asc' ? 'asc' : 'desc');

  let filterDialogOpen = $state(false);
  let nowMs = $state(Date.now());
  const jobSortKey = $derived(parseJobSortKey(page.url.searchParams.get('sort')));
  const jobSortOrder = $derived(parseSortOrder(page.url.searchParams.get('order')));
  const jobOwnerFilter = $derived(page.url.searchParams.get('owner') || 'all');
  const jobStatusFilter = $derived(page.url.searchParams.get('job_status') || 'all');
  const jobPolicyFilter = $derived(page.url.searchParams.get('policy') || 'all');
  const jobSearch = $derived(page.url.searchParams.get('search') || '');
  const createdFrom = $derived(page.url.searchParams.get('created_from') || '');
  const createdTo = $derived(page.url.searchParams.get('created_to') || '');

  const PAGE_SIZE = DEFAULT_PAGE_SIZE;
  const currentPage = $derived(parsePageParam(page.url.searchParams.get('page')));

  const jobsQuery = createQuery<JobListResponse>(
    toStore(() => ({
      queryKey: [
        'training',
        'jobs',
        {
          ownerUserId: jobOwnerFilter === 'all' ? undefined : jobOwnerFilter,
          status: jobStatusFilter === 'all' ? undefined : jobStatusFilter,
          policyType: jobPolicyFilter === 'all' ? undefined : jobPolicyFilter,
          search: jobSearch || undefined,
          createdFrom: createdFrom || undefined,
          createdTo: createdTo || undefined,
          sortBy: jobSortKey,
          sortOrder: jobSortOrder,
          limit: PAGE_SIZE,
          offset: (currentPage - 1) * PAGE_SIZE
        }
      ],
      queryFn: () =>
        api.training.jobs({
          ownerUserId: jobOwnerFilter === 'all' ? undefined : jobOwnerFilter,
          status: jobStatusFilter === 'all' ? undefined : jobStatusFilter,
          policyType: jobPolicyFilter === 'all' ? undefined : jobPolicyFilter,
          search: jobSearch || undefined,
          createdFrom: createdFrom || undefined,
          createdTo: createdTo || undefined,
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
  const presentJobStatus = (status?: string | null) => {
    const normalized = String(status ?? '').trim().toLowerCase();
    if (!normalized) return '-';
    if (normalized === 'starting') return '開始中';
    if (normalized === 'deploying') return 'デプロイ中';
    if (normalized === 'running') return '実行中';
    if (normalized === 'completed') return '完了';
    if (normalized === 'failed') return '失敗';
    if (normalized === 'stopped') return '停止';
    if (normalized === 'terminated') return '終了';
    return status ?? '-';
  };
  const jobOwnerOptions = $derived($jobsQuery.data?.owner_options ?? []);
  const jobStatusOptions = $derived($jobsQuery.data?.status_options ?? []);
  const jobPolicyOptions = $derived($jobsQuery.data?.policy_options ?? []);
  const jobOwnerSelectOptions = $derived.by(() => {
    const options = [
      { value: 'all', label: '全員' },
      ...jobOwnerOptions.map((owner) => ({
        value: owner.user_id,
        label: owner.label,
        disabled: owner.available_count === 0 && owner.user_id !== jobOwnerFilter
      }))
    ];
    if (jobOwnerFilter !== 'all' && !options.some((option) => option.value === jobOwnerFilter)) {
      options.push({ value: jobOwnerFilter, label: jobOwnerFilter });
    }
    return options;
  });
  const jobStatusSelectOptions = $derived.by(() => {
    const options = [
      { value: 'all', label: 'すべて' },
      ...jobStatusOptions.map((status) => ({
        value: status.value,
        label: status.label,
        disabled: status.available_count === 0 && status.value !== jobStatusFilter
      }))
    ];
    if (jobStatusFilter !== 'all' && !options.some((option) => option.value === jobStatusFilter)) {
      options.push({ value: jobStatusFilter, label: jobStatusFilter });
    }
    return options;
  });
  const jobPolicySelectOptions = $derived.by(() => {
    const options = [
      { value: 'all', label: 'すべて' },
      ...jobPolicyOptions.map((policy) => ({
        value: policy.value,
        label: policy.label,
        disabled: policy.available_count === 0 && policy.value !== jobPolicyFilter
      }))
    ];
    if (jobPolicyFilter !== 'all' && !options.some((option) => option.value === jobPolicyFilter)) {
      options.push({ value: jobPolicyFilter, label: jobPolicyFilter });
    }
    return options;
  });
  const trainingFilterDefaults = {
    search: '',
    owner: 'all',
    job_status: 'all',
    policy: 'all',
    created_from: '',
    created_to: ''
  };
  const trainingFilterValues = $derived({
    search: jobSearch,
    owner: jobOwnerFilter,
    job_status: jobStatusFilter,
    policy: jobPolicyFilter,
    created_from: createdFrom,
    created_to: createdTo
  });
  const trainingFilterFields = $derived<ListFilterField[]>([
    {
      section: '検索',
      type: 'text',
      key: 'search',
      label: 'ジョブ名',
      placeholder: 'ジョブ名で検索'
    },
    {
      section: '条件',
      type: 'select',
      key: 'owner',
      label: '作成者',
      options: jobOwnerSelectOptions
    },
    {
      section: '条件',
      type: 'select',
      key: 'job_status',
      label: '状態',
      options: jobStatusSelectOptions
    },
    {
      section: '条件',
      type: 'select',
      key: 'policy',
      label: 'ポリシー',
      options: jobPolicySelectOptions
    },
    {
      section: '期間・範囲',
      type: 'date-range',
      keyFrom: 'created_from',
      keyTo: 'created_to',
      label: '作成日時'
    }
  ]);
  const hasActiveJobFilters = $derived(
    Boolean(jobSearch) ||
      jobOwnerFilter !== 'all' ||
      jobStatusFilter !== 'all' ||
      jobPolicyFilter !== 'all' ||
      Boolean(createdFrom) ||
      Boolean(createdTo)
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
      job_status: values.job_status !== 'all' ? values.job_status : null,
      policy: values.policy !== 'all' ? values.policy : null,
      search: values.search || null,
      created_from: values.created_from || null,
      created_to: values.created_to || null,
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
    if (!browser) return;
    const timer = window.setInterval(() => {
      nowMs = Date.now();
    }, 60_000);
    return () => window.clearInterval(timer);
  });

  $effect(() => {
    if ($jobsQuery.isLoading) {
      return;
    }
    const nextPage = clampPage(currentPage, totalJobs, PAGE_SIZE);
    if (nextPage !== currentPage) {
      void navigateToPage(nextPage);
    }
  });

  const sortIconClass = 'text-slate-400 transition group-hover:text-slate-600';
  const sortableHeaderButtonClass =
    'group inline-flex items-center gap-1 font-semibold text-slate-400 transition hover:text-slate-700';
  const isSortedBy = (key: 'created_at' | 'updated_at' | 'job_name' | 'owner_name' | 'policy_type' | 'status') =>
    jobSortKey === key;
  const sortIconFor = (key: 'created_at' | 'updated_at' | 'job_name' | 'owner_name' | 'policy_type' | 'status') =>
    !isSortedBy(key) ? CaretUpDown : jobSortOrder === 'asc' ? ArrowUp : ArrowDown;
  const JobNameSortIcon = $derived(sortIconFor('job_name'));
  const OwnerSortIcon = $derived(sortIconFor('owner_name'));
  const PolicySortIcon = $derived(sortIconFor('policy_type'));
  const StatusSortIcon = $derived(sortIconFor('status'));
  const CreatedAtSortIcon = $derived(sortIconFor('created_at'));
  const UpdatedAtSortIcon = $derived(sortIconFor('updated_at'));
  const handleSortChange = async (key: 'created_at' | 'updated_at' | 'job_name' | 'owner_name' | 'policy_type' | 'status') => {
    const nextOrder: 'asc' | 'desc' = jobSortKey === key ? (jobSortOrder === 'asc' ? 'desc' : 'asc') : 'desc';
    const nextHref = buildUrlWithQueryState(page.url, {
      sort: key !== 'created_at' || nextOrder !== 'desc' ? key : null,
      order: nextOrder !== 'desc' ? nextOrder : null,
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
  const openJobDetail = async (jobId: string) => {
    await goto(`/train/jobs/${jobId}`);
  };
  const handleRowKeydown = async (event: KeyboardEvent, jobId: string) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    await openJobDetail(jobId);
  };

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
      />
    </div>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('job_name')}>
              ジョブ名
              <JobNameSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('owner_name')}>
              作成者
              <OwnerSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">データセット</th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('policy_type')}>
              ポリシー
              <PolicySortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('status')}>
              状態
              <StatusSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('created_at')}>
              作成日時
              <CreatedAtSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
          <th class="pb-3">
            <button class={sortableHeaderButtonClass} type="button" onclick={() => void handleSortChange('updated_at')}>
              最終更新
              <UpdatedAtSortIcon size={14} class={sortIconClass} />
            </button>
          </th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $jobsQuery.isLoading}
          <tr><td class="py-3" colspan="7">読み込み中...</td></tr>
        {:else if displayedJobs.length}
          {#each displayedJobs as job}
            <tr
              class="cursor-pointer border-t border-slate-200/60 transition hover:bg-slate-50 focus-within:bg-slate-50"
              tabindex="0"
              role="link"
              aria-label={`${job.job_name ?? job.job_id} の詳細を開く`}
              onclick={() => void openJobDetail(job.job_id)}
              onkeydown={(event) => void handleRowKeydown(event, job.job_id)}
            >
              <td class="py-3 text-slate-800">
                <span class="block max-w-[28ch] truncate" title={job.job_name ?? job.job_id}>
                  {job.job_name ?? job.job_id}
                </span>
              </td>
              <td class="py-3">{ownerLabel(job)}</td>
              <td class="py-3">
                <span class="block max-w-[16ch] truncate" title={job.dataset_name ?? displayDatasetName(job.dataset_id)}>
                  {job.dataset_name ?? displayDatasetName(job.dataset_id)}
                </span>
              </td>
              <td class="py-3">{job.policy_type ?? '-'}</td>
              <td class="py-3 text-slate-600">{presentJobStatus(job.status)}</td>
              <td class="py-3 whitespace-nowrap">{formatDate(job.created_at)}</td>
              <td class="py-3 whitespace-nowrap" title={formatDate(job.updated_at)}>
                {formatRelativeDate(job.updated_at, nowMs)}
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="7">条件に合う学習ジョブがありません。</td></tr>
        {/if}
      </tbody>
    </table>
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

<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Button, DropdownMenu } from 'bits-ui';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import Archive from 'phosphor-svelte/lib/Archive';
  import ArrowDown from 'phosphor-svelte/lib/ArrowDown';
  import ArrowUp from 'phosphor-svelte/lib/ArrowUp';
  import CaretUpDown from 'phosphor-svelte/lib/CaretUpDown';
  import DotsThree from 'phosphor-svelte/lib/DotsThree';
  import PencilSimple from 'phosphor-svelte/lib/PencilSimple';
  import XCircle from 'phosphor-svelte/lib/XCircle';
  import { toStore } from 'svelte/store';
  import { api, type BulkActionResponse } from '$lib/api/client';
  import ListFilterPopover from '$lib/components/ListFilterPopover.svelte';
  import PaginationControls from '$lib/components/PaginationControls.svelte';
  import StorageRenameDialog from '$lib/components/storage/StorageRenameDialog.svelte';
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
  let selectedJobIds = $state<string[]>([]);
  let bulkActionPending = $state(false);
  let bulkActionMessage = $state('');
  let bulkActionError = $state('');
  let rowActionPendingJobId = $state('');
  let rowActionPending = $state<'archive' | ''>('');
  let renameDialogOpen = $state(false);
  let renameTarget = $state<TrainingJob | null>(null);
  let renamePending = $state(false);
  let renameError = $state('');
  let selectAllCheckbox: HTMLInputElement | null = null;
  const queryClient = useQueryClient();
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
    if (!normalized) return { label: '-', tone: 'default' as const };
    if (normalized === 'starting') return { label: '開始中', tone: 'info' as const };
    if (normalized === 'deploying') return { label: '配備中', tone: 'info' as const };
    if (normalized === 'running') return { label: '実行中', tone: 'info' as const };
    if (normalized === 'completed') return { label: '完了', tone: 'success' as const };
    if (normalized === 'failed') return { label: '失敗', tone: 'error' as const };
    if (normalized === 'stopped') return { label: '停止', tone: 'muted' as const };
    if (normalized === 'terminated') return { label: '終了', tone: 'muted' as const };
    return { label: status ?? '-', tone: 'default' as const };
  };
  const jobStatusClass = (status?: string | null) => {
    const presentation = presentJobStatus(status);
    if (presentation.tone === 'success') return 'text-emerald-600';
    if (presentation.tone === 'error') return 'text-rose-500';
    if (presentation.tone === 'info') return 'text-sky-600';
    if (presentation.tone === 'muted') return 'text-slate-500';
    return 'text-slate-600';
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
        label: presentJobStatus(status.value).label,
        disabled: status.available_count === 0 && status.value !== jobStatusFilter
      }))
    ];
    if (jobStatusFilter !== 'all' && !options.some((option) => option.value === jobStatusFilter)) {
      options.push({ value: jobStatusFilter, label: presentJobStatus(jobStatusFilter).label });
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
  const bulkMenuItemClass =
    'flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-slate-700 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent';
  const bulkMenuDangerItemClass =
    'flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-rose-600 data-[disabled]:cursor-not-allowed data-[disabled]:text-slate-400 hover:bg-slate-100 data-[disabled]:hover:bg-transparent';
  const allDisplayedJobIds = $derived(displayedJobs.map((job) => job.job_id));
  const allDisplayedJobsSelected = $derived(
    allDisplayedJobIds.length > 0 && allDisplayedJobIds.every((id) => selectedJobIds.includes(id))
  );
  const someDisplayedJobsSelected = $derived(
    allDisplayedJobIds.some((id) => selectedJobIds.includes(id)) && !allDisplayedJobsSelected
  );
  const canArchiveSelectedJobs = $derived(selectedJobIds.length > 0 && !bulkActionPending);

  const clearSelection = () => {
    selectedJobIds = [];
  };
  const resetRenameDialog = () => {
    renameDialogOpen = false;
    renameTarget = null;
    renameError = '';
  };
  const removeSelectedJobIds = (ids: string[]) => {
    if (!ids.length) return;
    const idSet = new Set(ids);
    selectedJobIds = selectedJobIds.filter((id) => !idSet.has(id));
  };
  const resetBulkMessages = () => {
    bulkActionMessage = '';
    bulkActionError = '';
  };
  const resetActionState = () => {
    rowActionPendingJobId = '';
    rowActionPending = '';
  };
  const applyBulkResponseMessage = (response: BulkActionResponse, successLabel: string) => {
    const parts = [`成功 ${response.succeeded}`, `失敗 ${response.failed}`];
    if (response.skipped > 0) {
      parts.push(`スキップ ${response.skipped}`);
    }
    bulkActionMessage = `${successLabel}（${parts.join(' / ')}）`;
  };
  const toggleAllDisplayedJobs = () => {
    const next = new Set(selectedJobIds);
    if (allDisplayedJobsSelected) {
      allDisplayedJobIds.forEach((id) => next.delete(id));
    } else {
      allDisplayedJobIds.forEach((id) => next.add(id));
    }
    selectedJobIds = [...next];
  };
  const handleArchiveSelectedJobs = async () => {
    resetBulkMessages();
    if (!selectedJobIds.length) {
      bulkActionError = 'アーカイブ対象を選択してください。';
      return;
    }
    const confirmed = confirm(`${selectedJobIds.length}件の学習ジョブをアーカイブしますか？`);
    if (!confirmed) return;

    bulkActionPending = true;
    const ids = [...selectedJobIds];
    try {
      const response = await api.training.bulkArchiveJobs(ids);
      applyBulkResponseMessage(response, 'アーカイブを実行しました');
      removeSelectedJobIds(
        response.results.filter((result) => result.status === 'succeeded').map((result) => result.id)
      );
      await queryClient.invalidateQueries({ queryKey: ['training', 'jobs'] });
    } catch (err) {
      bulkActionError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      bulkActionPending = false;
    }
  };
  const openRenameDialog = (job: TrainingJob) => {
    if (renamePending || rowActionPendingJobId) return;
    renameTarget = job;
    renameError = '';
    renameDialogOpen = true;
  };
  const handleRenameJob = async (nextName: string) => {
    const target = renameTarget;
    if (!target?.job_id) return;
    renamePending = true;
    renameError = '';
    try {
      await api.training.updateJob(target.job_id, { job_name: nextName });
      await queryClient.invalidateQueries({ queryKey: ['training', 'jobs'] });
      resetRenameDialog();
      bulkActionMessage = '学習ジョブ名を更新しました。';
      bulkActionError = '';
    } catch (err) {
      renameError = err instanceof Error ? err.message : '名前変更に失敗しました。';
    } finally {
      renamePending = false;
    }
  };
  const handleArchiveJob = async (job: TrainingJob) => {
    resetBulkMessages();
    if (!job.job_id || bulkActionPending || rowActionPendingJobId || renamePending) return;
    const confirmed = confirm(`${job.job_name ?? job.job_id} をアーカイブしますか？`);
    if (!confirmed) return;
    rowActionPendingJobId = job.job_id;
    rowActionPending = 'archive';
    try {
      const response = await api.training.bulkArchiveJobs([job.job_id]);
      applyBulkResponseMessage(response, 'アーカイブを実行しました');
      removeSelectedJobIds(
        response.results.filter((result) => result.status === 'succeeded').map((result) => result.id)
      );
      await queryClient.invalidateQueries({ queryKey: ['training', 'jobs'] });
    } catch (err) {
      bulkActionError = err instanceof Error ? err.message : 'アーカイブに失敗しました。';
    } finally {
      resetActionState();
    }
  };

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

  $effect(() => {
    if (!selectAllCheckbox) return;
    selectAllCheckbox.indeterminate = someDisplayedJobsSelected;
  });

  $effect(() => {
    if (renameDialogOpen || renamePending) return;
    renameTarget = null;
    renameError = '';
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

<StorageRenameDialog
  bind:open={renameDialogOpen}
  itemKind="job"
  currentName={renameTarget?.job_name ?? renameTarget?.job_id ?? ''}
  pending={renamePending}
  errorMessage={renameError}
  onConfirm={handleRenameJob}
/>

<section class="card p-6">
  <div class="flex items-center justify-between gap-3">
    <h2 class="text-xl font-semibold text-slate-900">学習ジョブ一覧</h2>
    <div class="flex items-center gap-2">
      {#if selectedJobIds.length > 0}
        <span class="text-sm font-semibold text-slate-700">選択中: {selectedJobIds.length} 件</span>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            class="inline-flex h-10 items-center justify-center gap-2 rounded-full border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
            aria-label="一括操作"
          >
            <DotsThree size={18} weight="bold" />
            一括操作
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              class="z-50 min-w-[220px] rounded-xl border border-slate-200/80 bg-white/95 p-2 text-xs text-slate-700 shadow-lg backdrop-blur"
              sideOffset={6}
              align="end"
              preventScroll={false}
            >
              <DropdownMenu.Group>
                <DropdownMenu.GroupHeading
                  class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                >
                  選択
                </DropdownMenu.GroupHeading>
                <DropdownMenu.Item class={bulkMenuItemClass} onSelect={clearSelection}>
                  <XCircle size={16} class="text-slate-500" />
                  選択解除
                </DropdownMenu.Item>
              </DropdownMenu.Group>

              <DropdownMenu.Separator class="-mx-2 my-1 h-px bg-slate-200/70" />

              <DropdownMenu.Group>
                <DropdownMenu.GroupHeading
                  class="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
                >
                  一括操作
                </DropdownMenu.GroupHeading>
                <DropdownMenu.Item
                  class={bulkMenuDangerItemClass}
                  disabled={!canArchiveSelectedJobs}
                  onSelect={() => void handleArchiveSelectedJobs()}
                >
                  <Archive size={16} class="text-rose-500" />
                  アーカイブ
                </DropdownMenu.Item>
              </DropdownMenu.Group>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      {:else}
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
      {/if}
    </div>
  </div>
  {#if bulkActionMessage}
    <p class="mt-3 text-sm font-medium text-emerald-600">{bulkActionMessage}</p>
  {/if}
  {#if bulkActionError}
    <p class="mt-3 text-sm font-medium text-rose-500">{bulkActionError}</p>
  {/if}
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="w-12 pb-3">
            <div class="flex justify-center">
              <input
                bind:this={selectAllCheckbox}
                type="checkbox"
                class="block h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                checked={allDisplayedJobsSelected}
                disabled={!displayedJobs.length || $jobsQuery.isLoading || bulkActionPending}
                aria-label="表示中の学習ジョブを全選択"
                onchange={toggleAllDisplayedJobs}
              />
            </div>
          </th>
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
          <th class="w-14 pb-3 pr-3">
            <div class="ml-auto flex w-8 justify-center">操作</div>
          </th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $jobsQuery.isLoading}
          <tr><td class="py-3" colspan="9">読み込み中...</td></tr>
        {:else if displayedJobs.length}
          {#each displayedJobs as job}
            {@const jobStatus = presentJobStatus(job.status)}
            <tr
              class={`cursor-pointer border-t border-slate-200/60 transition focus-within:bg-slate-100/80 ${
                selectedJobIds.includes(job.job_id) ? 'bg-slate-50/80' : 'hover:bg-slate-100/80'
              }`}
              tabindex="0"
              role="link"
              aria-label={`${job.job_name ?? job.job_id} の詳細を開く`}
              onclick={() => void openJobDetail(job.job_id)}
              onkeydown={(event) => void handleRowKeydown(event, job.job_id)}
            >
              <td class="w-12 py-3 align-middle" onclick={(event) => event.stopPropagation()}>
                <div class="flex justify-center">
                  <input
                    type="checkbox"
                    class="block h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand/40"
                    bind:group={selectedJobIds}
                    value={job.job_id}
                    aria-label={`${job.job_name ?? job.job_id} を選択`}
                  />
                </div>
              </td>
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
              <td class="py-3">
                <span class={`text-xs font-semibold ${jobStatusClass(job.status)}`}>
                  {jobStatus.label}
                </span>
              </td>
              <td class="py-3 whitespace-nowrap">{formatDate(job.created_at)}</td>
              <td class="py-3 whitespace-nowrap" title={formatDate(job.updated_at)}>
                {formatRelativeDate(job.updated_at, nowMs)}
              </td>
              <td class="py-3 pr-3 text-right" onclick={(event) => event.stopPropagation()}>
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger
                    class="btn-ghost ml-auto h-8 w-8 p-0 text-slate-600"
                    aria-label="操作メニュー"
                    title="操作"
                    disabled={bulkActionPending || renamePending}
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
                        <DropdownMenu.Item
                          class={bulkMenuItemClass}
                          disabled={bulkActionPending || renamePending || rowActionPendingJobId === job.job_id}
                          onSelect={() => openRenameDialog(job)}
                        >
                          <PencilSimple size={16} class="text-slate-500" />
                          名前変更
                        </DropdownMenu.Item>
                        <DropdownMenu.Item
                          class={bulkMenuDangerItemClass}
                          disabled={bulkActionPending || renamePending || rowActionPendingJobId === job.job_id}
                          onSelect={() => void handleArchiveJob(job)}
                        >
                          <Archive size={16} class="text-rose-500" />
                          {rowActionPendingJobId === job.job_id && rowActionPending === 'archive'
                            ? 'アーカイブ中...'
                            : 'アーカイブ'}
                        </DropdownMenu.Item>
                      </DropdownMenu.Group>
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="9">条件に合う学習ジョブがありません。</td></tr>
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

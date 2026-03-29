<script lang="ts">
	  import { goto } from '$app/navigation';
	  import { page } from '$app/state';
	  import { Button, Tabs } from 'bits-ui';
	  import { createQuery } from '@tanstack/svelte-query';
	  import { get, toStore } from 'svelte/store';
	  import { api } from '$lib/api/client';
	  import PaginationControls from '$lib/components/PaginationControls.svelte';
	  import GpuAvailabilityBoard from '$lib/components/training/GpuAvailabilityBoard.svelte';
	  import { formatDate } from '$lib/format';
	  import { DEFAULT_PAGE_SIZE, buildPageHref, buildUrlWithQueryState, clampPage, parsePageParam } from '$lib/pagination';
	  import { GPU_MODELS } from '$lib/policies';
	  import type { GpuAvailabilityResponse, TrainingProviderCapabilityResponse } from '$lib/types/training';

  type StorageProvider = 'verda' | 'vast';

  type VerdaStorageItem = {
    id: string;
    name?: string | null;
    size_gb?: number;
    status?: string;
    state?: string;
    instance_id?: string | null;
  };

  type VastStorageItem = {
    id: string;
    label?: string;
    size_gb?: number | null;
    state?: string;
    instance_id?: string | null;
  };

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

	  let provider = $state<StorageProvider>('verda');
	  let storageProvider = $state<StorageProvider>('verda');
	  let selectedVolumeIds = $state<string[]>([]);

	  const providerCapabilitiesQuery = createQuery<TrainingProviderCapabilityResponse>({
	    queryKey: ['training', 'provider-capabilities'],
	    queryFn: api.training.providerCapabilities
	  });

	  const isVerdaProviderEnabled = $derived($providerCapabilitiesQuery.data?.verda_enabled ?? true);
	  const isVastProviderEnabled = $derived($providerCapabilitiesQuery.data?.vast_enabled ?? false);

	  const gpuAvailabilityVerdaQuery = createQuery<GpuAvailabilityResponse>({
	    queryKey: ['training', 'gpu-availability', 'verda'],
	    queryFn: () => api.training.gpuAvailability('verda'),
	    enabled: false
	  });

	  const gpuAvailabilityVastQuery = createQuery<GpuAvailabilityResponse>({
	    queryKey: ['training', 'gpu-availability', 'vast'],
	    queryFn: () => api.training.gpuAvailability('vast'),
	    enabled: false
	  });

	  const verdaStorageQuery = createQuery<{ items?: Array<VerdaStorageItem | VastStorageItem> }>({
	    queryKey: ['training', 'cloud-storage', 'verda'],
	    queryFn: api.training.verdaStorage,
	    enabled: false
	  });

	  const vastStorageQuery = createQuery<{ items?: Array<VerdaStorageItem | VastStorageItem> }>({
	    queryKey: ['training', 'cloud-storage', 'vast'],
	    queryFn: api.training.vastStorage,
	    enabled: false
	  });

	  const gpuModelOrder = $derived(GPU_MODELS.map((gpu) => gpu.value));
  let activeTab = $state<'availability' | 'jobs' | 'storage'>('jobs');
  let jobSortKey = $state<'created_at' | 'updated_at' | 'job_name' | 'status'>(
    parseJobSortKey(page.url.searchParams.get('sort'))
  );
  let jobSortOrder = $state<'desc' | 'asc'>(parseSortOrder(page.url.searchParams.get('order')));
  let jobOwnerFilter = $state(page.url.searchParams.get('owner') || 'all');
  let jobSearch = $state(page.url.searchParams.get('search') || '');

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

	  const storageItems = $derived(
	    (
	      storageProvider === 'verda'
	        ? $verdaStorageQuery.data?.items
	        : $vastStorageQuery.data?.items
	    ) ?? []
	  );

	  $effect(() => {
	    if (provider === 'verda' && !isVerdaProviderEnabled && isVastProviderEnabled) {
	      provider = 'vast';
	      return;
	    }
	    if (provider === 'vast' && !isVastProviderEnabled) {
	      provider = 'verda';
	    }
	  });

	  $effect(() => {
	    if (storageProvider === 'verda' && !isVerdaProviderEnabled && isVastProviderEnabled) {
	      storageProvider = 'vast';
	      return;
	    }
	    if (storageProvider === 'vast' && !isVastProviderEnabled) {
	      storageProvider = 'verda';
	    }
	  });

	  $effect(() => {
	    if (activeTab !== 'availability') return;
	    const query = provider === 'verda' ? gpuAvailabilityVerdaQuery : gpuAvailabilityVastQuery;
	    void get(query).refetch?.();
	  });

	  $effect(() => {
	    if (activeTab !== 'storage') return;
	    const query = storageProvider === 'verda' ? verdaStorageQuery : vastStorageQuery;
	    void get(query).refetch?.();
	  });
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
  const buildTrainingJobsHref = (pageNumber: number = currentPage) =>
    buildUrlWithQueryState(page.url, {
      owner: jobOwnerFilter !== 'all' ? jobOwnerFilter : null,
      search: jobSearch || null,
      sort: jobSortKey !== 'created_at' ? jobSortKey : null,
      order: jobSortOrder !== 'desc' ? jobSortOrder : null,
      page: pageNumber > 1 ? pageNumber : null
    });

  $effect(() => {
    const nextOwnerFilter = page.url.searchParams.get('owner') || 'all';
    const nextSearch = page.url.searchParams.get('search') || '';
    const nextSortKey = parseJobSortKey(page.url.searchParams.get('sort'));
    const nextSortOrder = parseSortOrder(page.url.searchParams.get('order'));
    if (jobOwnerFilter !== nextOwnerFilter) {
      jobOwnerFilter = nextOwnerFilter;
    }
    if (jobSearch !== nextSearch) {
      jobSearch = nextSearch;
    }
    if (jobSortKey !== nextSortKey) {
      jobSortKey = nextSortKey;
    }
    if (jobSortOrder !== nextSortOrder) {
      jobSortOrder = nextSortOrder;
    }
  });

  $effect(() => {
    const currentHref = `${page.url.pathname}${page.url.search}${page.url.hash}`;
    const urlOwnerFilter = page.url.searchParams.get('owner') || 'all';
    const urlSearch = page.url.searchParams.get('search') || '';
    const urlSortKey = parseJobSortKey(page.url.searchParams.get('sort'));
    const urlSortOrder = parseSortOrder(page.url.searchParams.get('order'));
    const filtersChanged =
      jobOwnerFilter !== urlOwnerFilter ||
      jobSearch !== urlSearch ||
      jobSortKey !== urlSortKey ||
      jobSortOrder !== urlSortOrder;
    const nextHref = buildTrainingJobsHref(filtersChanged && currentPage !== 1 ? 1 : currentPage);
    if (currentHref === nextHref) {
      return;
    }
    void goto(nextHref, {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
      invalidateAll: false
    });
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

  const toggleVolume = (id: string) => {
    if (selectedVolumeIds.includes(id)) {
      selectedVolumeIds = selectedVolumeIds.filter((v) => v !== id);
      return;
    }
    selectedVolumeIds = [...selectedVolumeIds, id];
  };

  const runStorageAction = async (action: 'delete' | 'restore' | 'purge') => {
    if (!selectedVolumeIds.length) return;
    const payload = { volume_ids: selectedVolumeIds };
    if (storageProvider === 'verda') {
      if (action === 'delete') await api.training.verdaStorageDelete(payload);
      if (action === 'restore') await api.training.verdaStorageRestore(payload);
      if (action === 'purge') await api.training.verdaStoragePurge(payload);
    } else {
      if (action !== 'delete') return;
      await api.training.vastStorageDelete(payload);
	    }
	    selectedVolumeIds = [];
	    const query = storageProvider === 'verda' ? verdaStorageQuery : vastStorageQuery;
	    await get(query).refetch?.();
	  };
	</script>

<section class="card-strong p-8">
  <p class="section-title">Train</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">モデル学習</h1>
      <p class="mt-2 text-sm text-slate-600">
        利用可能なポリシー一覧と、学習ジョブの状態を確認します。
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
  <Tabs.Root bind:value={activeTab}>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <Tabs.List class="inline-grid grid-cols-3 gap-1 rounded-full border border-slate-200/70 bg-slate-100/80 p-1">
        <Tabs.Trigger
          value="jobs"
          class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
        >
          学習ジョブ一覧
        </Tabs.Trigger>
        <Tabs.Trigger
          value="availability"
          class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
        >
          GPU空き状況
        </Tabs.Trigger>
        <Tabs.Trigger
          value="storage"
          class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
        >
          Cloud Storage
        </Tabs.Trigger>
      </Tabs.List>

      {#if activeTab === 'jobs'}
        <Button.Root class="btn-ghost" type="button" onclick={() => $jobsQuery?.refetch?.()}>更新</Button.Root>
      {/if}
      {#if activeTab === 'storage'}
        <Button.Root
          class="btn-ghost"
          type="button"
          onclick={() => (storageProvider === 'verda' ? $verdaStorageQuery?.refetch?.() : $vastStorageQuery?.refetch?.())}
        >
          更新
        </Button.Root>
      {/if}
    </div>

    <Tabs.Content value="availability" class="mt-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-xl font-semibold text-slate-900">GPU 空き状況</h2>
          <p class="mt-1 text-sm text-slate-500">モデルごとに展開して可否・価格・拠点数を確認できます。</p>
        </div>
        <div class="flex items-center gap-2 text-sm">
          <span class="text-slate-500">Provider</span>
          <select
            class="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
            bind:value={provider}
          >
            <option value="verda" disabled={!isVerdaProviderEnabled}>
              {isVerdaProviderEnabled ? 'Verda' : 'Verda (設定不足)'}
            </option>
            <option value="vast" disabled={!isVastProviderEnabled}>
              {isVastProviderEnabled ? 'Vast.ai' : 'Vast.ai (設定不足)'}
            </option>
          </select>
        </div>
      </div>
      <div class="mt-4">
	        <GpuAvailabilityBoard
	          items={
	            provider === 'verda'
	              ? $gpuAvailabilityVerdaQuery.data?.available ?? []
	              : $gpuAvailabilityVastQuery.data?.available ?? []
	          }
	          loading={provider === 'verda' ? $gpuAvailabilityVerdaQuery.isLoading : $gpuAvailabilityVastQuery.isLoading}
	          showOnlyAvailableDefault={true}
	          preferredModelOrder={gpuModelOrder}
	        />
      </div>
    </Tabs.Content>

    <Tabs.Content value="jobs" class="mt-4">
      <h2 class="text-xl font-semibold text-slate-900">学習ジョブ一覧</h2>
      <div class="mt-4 grid gap-3 md:grid-cols-4">
        <label class="block">
          <span class="label">検索</span>
          <input class="input mt-2" type="text" bind:value={jobSearch} placeholder="job / dataset / user" />
        </label>
        <label class="block">
          <span class="label">作成者</span>
          <select class="input mt-2" bind:value={jobOwnerFilter}>
            <option value="all">全員</option>
            {#each jobOwnerOptions as owner}
              <option value={owner.id}>{owner.label}</option>
            {/each}
          </select>
        </label>
        <label class="block">
          <span class="label">並び替え</span>
          <select class="input mt-2" bind:value={jobSortKey}>
            <option value="created_at">作成日時</option>
            <option value="updated_at">更新日時</option>
            <option value="job_name">ジョブ名</option>
            <option value="status">状態</option>
          </select>
        </label>
        <label class="block">
          <span class="label">順序</span>
          <select class="input mt-2" bind:value={jobSortOrder}>
            <option value="desc">降順</option>
            <option value="asc">昇順</option>
          </select>
        </label>
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
    </Tabs.Content>

    <Tabs.Content value="storage" class="mt-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 class="text-xl font-semibold text-slate-900">Cloud Storage</h2>
          <p class="mt-1 text-sm text-slate-500">プロバイダのボリューム一覧と管理操作。</p>
        </div>
        <div class="flex items-center gap-2 text-sm">
          <span class="text-slate-500">Provider</span>
          <select class="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" bind:value={storageProvider}>
            <option value="verda" disabled={!isVerdaProviderEnabled}>
              {isVerdaProviderEnabled ? 'Verda' : 'Verda (設定不足)'}
            </option>
            <option value="vast" disabled={!isVastProviderEnabled}>
              {isVastProviderEnabled ? 'Vast.ai' : 'Vast.ai (設定不足)'}
            </option>
          </select>
        </div>
      </div>
      <div class="mt-4 flex flex-wrap items-center gap-2">
        <Button.Root class="btn-ghost" type="button" disabled={!selectedVolumeIds.length} onclick={() => runStorageAction('delete')}>
          削除
        </Button.Root>
        {#if storageProvider === 'verda'}
          <Button.Root class="btn-ghost" type="button" disabled={!selectedVolumeIds.length} onclick={() => runStorageAction('restore')}>
            復元
          </Button.Root>
          <Button.Root class="btn-ghost" type="button" disabled={!selectedVolumeIds.length} onclick={() => runStorageAction('purge')}>
            完全削除
          </Button.Root>
        {/if}
        <span class="text-xs text-slate-500">選択 {selectedVolumeIds.length}</span>
      </div>

      <div class="mt-4 space-y-2 text-sm">
        {#if storageProvider === 'verda' ? $verdaStorageQuery.isLoading : $vastStorageQuery.isLoading}
          <p class="text-slate-500">読み込み中...</p>
        {:else if storageItems.length}
          {#each storageItems as item}
            <button
              type="button"
              class={`flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left transition ${
                selectedVolumeIds.includes(item.id)
                  ? 'border-brand/40 bg-brand/5 ring-2 ring-brand/20'
                  : 'border-slate-200/60 bg-white/70 hover:border-brand/30'
              }`}
              onclick={() => toggleVolume(item.id)}
            >
              <div class="min-w-0">
                <p class="font-semibold text-slate-800 truncate">
                  {storageProvider === 'verda'
                    ? ((item as VerdaStorageItem).name ?? item.id)
                    : ((item as VastStorageItem).label || item.id)}
                </p>
                <p class="mt-0.5 text-xs text-slate-500">
                  id: {item.id}{' '}
                  {#if (item as any).instance_id}
                    / instance: {(item as any).instance_id}
                  {/if}
                </p>
              </div>
              <div class="text-right text-xs text-slate-500">
                <p>{(item as any).size_gb ?? '-'} GB</p>
                <p class="mt-0.5">{(item as any).state ?? '-'}</p>
              </div>
            </button>
          {/each}
        {:else}
          <p class="text-slate-500">ボリュームがありません。</p>
        {/if}
      </div>
    </Tabs.Content>
  </Tabs.Root>
</section>

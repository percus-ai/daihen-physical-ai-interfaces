<script lang="ts">
	  import { Button, Tabs } from 'bits-ui';
	  import { createQuery } from '@tanstack/svelte-query';
	  import { get } from 'svelte/store';
	  import { api } from '$lib/api/client';
	  import GpuAvailabilityBoard from '$lib/components/training/GpuAvailabilityBoard.svelte';
	  import { formatDate } from '$lib/format';
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
    dataset_id?: string;
    policy_type?: string;
    status?: string;
    updated_at?: string;
  };

  type JobListResponse = {
    jobs?: TrainingJob[];
    total?: number;
  };

  const jobsQuery = createQuery<JobListResponse>({
    queryKey: ['training', 'jobs'],
    queryFn: api.training.jobs
  });

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

	  const gpuModelOrder = $derived(GPU_MODELS.map((gpu) => gpu.name));
	  let activeTab = $state<'availability' | 'jobs' | 'storage'>('jobs');

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
      <div class="mt-4 space-y-3 text-sm text-slate-600">
        {#if $jobsQuery.isLoading}
          <p>読み込み中...</p>
        {:else if $jobsQuery.data?.jobs?.length}
          {#each $jobsQuery.data.jobs as job}
            <a
              class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3 transition hover:border-brand/40 hover:bg-white"
              href={`/train/jobs/${job.job_id}`}
            >
              <div>
                <p class="font-semibold text-slate-800">{job.job_name}</p>
                <p class="text-xs text-slate-500">{job.dataset_id ?? '-'} / {job.policy_type ?? '-'}</p>
              </div>
              <span class="chip">{job.status}</span>
            </a>
          {/each}
        {:else}
          <p>学習ジョブがありません。</p>
        {/if}
      </div>
      <div class="mt-4 text-xs text-slate-500">最終更新: {formatDate($jobsQuery.data?.jobs?.[0]?.updated_at)}</div>
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

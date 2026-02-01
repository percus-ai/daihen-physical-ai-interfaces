<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatBytes, formatDate } from '$lib/format';

  type ProfileInstancesResponse = {
    instances?: Array<{ id: string; class_key?: string; name?: string; is_active?: boolean }>;
    total?: number;
  };

  type DatasetSummary = {
    id: string;
    name?: string;
    profile_instance_id?: string;
    dataset_type?: string;
    created_at?: string;
    size_bytes?: number;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  const profileInstancesQuery = createQuery<ProfileInstancesResponse>({
    queryKey: ['profiles', 'instances'],
    queryFn: api.profiles.instances
  });

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: ['datasets', 'recorded'],
    queryFn: () => api.storage.datasets()
  });

  $: recordedDatasets =
    $datasetsQuery.data?.datasets?.filter(
      (dataset) => !dataset.dataset_type || dataset.dataset_type === 'recorded'
    ) ?? [];

  $: latestRecorded =
    recordedDatasets
      .slice()
      .sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime())[0] ??
    null;
</script>

<section class="card-strong p-8">
  <p class="section-title">Record</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ録画</h1>
      <p class="mt-2 text-sm text-slate-600">プロフィール一覧と録画セッションの状況を表示します。</p>
    </div>
    <Button.Root class="btn-primary">新規録画を開始</Button.Root>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">プロフィール一覧</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $profileInstancesQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $profileInstancesQuery.data?.instances?.length}
        {#each $profileInstancesQuery.data.instances as instance}
          <div class="flex items-center justify-between rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
            <span class="font-semibold text-slate-800">
              {instance.class_key}:{instance.name ?? 'active'}
            </span>
            <span class="chip">{instance.is_active ? 'active' : 'instance'}</span>
          </div>
        {/each}
      {:else}
        <p>プロフィールがありません。</p>
      {/if}
    </div>
  </div>

  <div class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">録画サマリ</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <div>
        <p class="label">総録画数</p>
        <p class="text-base font-semibold text-slate-800">{recordedDatasets.length}</p>
      </div>
      <div>
        <p class="label">最新データセット</p>
        <p class="text-base font-semibold text-slate-800">
          {latestRecorded?.name ?? latestRecorded?.id ?? '-'}
        </p>
      </div>
    </div>
  </div>
</section>

<section class="card p-6">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-semibold text-slate-900">録画一覧</h2>
    <Button.Root class="btn-ghost">更新</Button.Root>
  </div>
  <div class="mt-4 overflow-x-auto">
    <table class="min-w-full text-sm">
      <thead class="text-left text-xs uppercase tracking-widest text-slate-400">
        <tr>
          <th class="pb-3">データセットID</th>
          <th class="pb-3">プロフィール</th>
          <th class="pb-3">サイズ</th>
          <th class="pb-3">作成日時</th>
        </tr>
      </thead>
      <tbody class="text-slate-600">
        {#if $datasetsQuery.isLoading}
          <tr><td class="py-3" colspan="4">読み込み中...</td></tr>
        {:else if recordedDatasets.length}
          {#each recordedDatasets as dataset}
            <tr class="border-t border-slate-200/60">
              <td class="py-3">{dataset.name ?? dataset.id}</td>
              <td class="py-3">{dataset.profile_instance_id ?? '-'}</td>
              <td class="py-3">{formatBytes(dataset.size_bytes ?? 0)}</td>
              <td class="py-3">{formatDate(dataset.created_at)}</td>
            </tr>
          {/each}
        {:else}
          <tr><td class="py-3" colspan="4">録画がありません。</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</section>

<script lang="ts">
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { qk } from '$lib/queryKeys';
  import { formatBytes } from '$lib/format';

  type DatasetSummary = {
    id: string;
    name?: string;
    status?: string;
    size_bytes?: number;
    source?: string;
    dataset_type?: string;
    episode_count?: number;
    created_at?: string;
  };

  type ModelSummary = {
    id: string;
    name?: string;
    status?: string;
    size_bytes?: number;
    policy_type?: string;
    dataset_id?: string;
    created_at?: string;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  type ModelListResponse = {
    models?: ModelSummary[];
    total?: number;
  };

  const latestDatasetQuery = {
    limit: 3,
    sortBy: 'created_at',
    sortOrder: 'desc'
  } as const;

  const latestModelQuery = {
    limit: 3,
    sortBy: 'created_at',
    sortOrder: 'desc'
  } as const;

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: qk.storage.datasets(latestDatasetQuery),
    queryFn: () => api.storage.datasets(latestDatasetQuery)
  });

  const modelsQuery = createQuery<ModelListResponse>({
    queryKey: qk.storage.models(latestModelQuery),
    queryFn: () => api.storage.models(latestModelQuery)
  });

  const displayDatasetLabel = (dataset: DatasetSummary) => dataset.name ?? dataset.id;
  const displayModelLabel = (model: ModelSummary) => model.name ?? model.id;
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">データ管理</h1>
      <p class="mt-2 text-sm text-slate-600">データセットとモデルの状況をまとめて確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage/usage">ストレージ使用量</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6">
  <div class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-xl font-semibold text-slate-900">データセット</h2>
        <p class="text-xs text-slate-500">最新のデータセットを一覧表示</p>
      </div>
      <Button.Root class="btn-ghost" href="/storage/datasets">管理</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $datasetsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $datasetsQuery.data?.datasets?.length}
        {#each $datasetsQuery.data.datasets as dataset}
          <div class="nested-block px-4 py-3">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="min-w-0 break-all font-semibold text-slate-800">{displayDatasetLabel(dataset)}</span>
              <span class="chip">{dataset.status}</span>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span>size: {formatBytes(dataset.size_bytes)}</span>
              <span>source: {dataset.source ?? 'r2'}</span>
              <span>type: {dataset.dataset_type ?? 'recorded'}</span>
              <span>episodes: {dataset.episode_count ?? 0}</span>
            </div>
          </div>
        {/each}
        {#if ($datasetsQuery.data.total ?? 0) > ($datasetsQuery.data.datasets.length ?? 0)}
          <p class="text-xs text-slate-400">ほか {($datasetsQuery.data.total ?? 0) - ($datasetsQuery.data.datasets.length ?? 0)} 件</p>
        {/if}
      {:else}
        <p>データセットがありません。</p>
      {/if}
    </div>
  </div>
</section>

<section class="grid gap-6">
  <div class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-xl font-semibold text-slate-900">モデル管理</h2>
        <p class="text-xs text-slate-500">最新のモデルを一覧表示</p>
      </div>
      <Button.Root class="btn-ghost" href="/storage/models">管理</Button.Root>
    </div>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      {#if $modelsQuery.isLoading}
        <p>読み込み中...</p>
      {:else if $modelsQuery.data?.models?.length}
        {#each $modelsQuery.data.models as model}
          <div class="nested-block px-4 py-3">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="min-w-0 break-all font-semibold text-slate-800">{displayModelLabel(model)}</span>
              <span class="chip">{model.status}</span>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span>size: {formatBytes(model.size_bytes)}</span>
              <span>policy: {model.policy_type ?? '-'}</span>
              <span>dataset: {model.dataset_id ?? '-'}</span>
            </div>
          </div>
        {/each}
        {#if ($modelsQuery.data.total ?? 0) > ($modelsQuery.data.models.length ?? 0)}
          <p class="text-xs text-slate-400">ほか {($modelsQuery.data.total ?? 0) - ($modelsQuery.data.models.length ?? 0)} 件</p>
        {/if}
      {:else}
        <p>モデルがありません。</p>
      {/if}
    </div>
  </div>
</section>

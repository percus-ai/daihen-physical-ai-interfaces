<script lang="ts">
  import { derived } from 'svelte/store';
  import { page } from '$app/stores';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { formatDate } from '$lib/format';

  type EnvironmentInfo = {
    id: string;
    name?: string;
    description?: string | null;
    camera_count?: number | null;
    camera_details?: string | null;
    image_files?: string[] | null;
    notes?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
  };

  const environmentQuery = createQuery<EnvironmentInfo>(
    derived(page, ($page) => {
      const currentId = $page.params.environment_id;
      return {
        queryKey: ['storage', 'environment', currentId],
        queryFn: () => api.storage.environment(currentId) as Promise<EnvironmentInfo>,
        enabled: Boolean(currentId)
      };
    })
  );

  $: environment = $environmentQuery.data;
</script>

<section class="card-strong p-8">
  <p class="section-title">Storage</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">環境詳細</h1>
      <p class="mt-2 text-sm text-slate-600">環境の設定情報を確認します。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button.Root class="btn-ghost" href="/storage">データ管理へ</Button.Root>
    </div>
  </div>
</section>

<section class="card p-6">
  <h2 class="text-xl font-semibold text-slate-900">基本情報</h2>
  {#if $environmentQuery.isLoading}
    <p class="mt-4 text-sm text-slate-600">読み込み中...</p>
  {:else if environment}
    <div class="mt-4 grid gap-4 text-sm text-slate-600 lg:grid-cols-2">
      <div>
        <p class="label">ID</p>
        <p class="text-base font-semibold text-slate-800">{environment.id}</p>
      </div>
      <div>
        <p class="label">名前</p>
        <p class="text-base font-semibold text-slate-800">{environment.name ?? '-'}</p>
      </div>
      <div>
        <p class="label">カメラ台数</p>
        <p class="text-base font-semibold text-slate-800">{environment.camera_count ?? 0}</p>
      </div>
      <div>
        <p class="label">更新日時</p>
        <p class="text-base font-semibold text-slate-800">{formatDate(environment.updated_at ?? undefined)}</p>
      </div>
      <div class="lg:col-span-2">
        <p class="label">説明</p>
        <p class="mt-1 text-base text-slate-700">{environment.description ?? '-'}</p>
      </div>
      <div class="lg:col-span-2">
        <p class="label">カメラ詳細</p>
        <p class="mt-1 text-base text-slate-700">{environment.camera_details ?? '-'}</p>
      </div>
      <div class="lg:col-span-2">
        <p class="label">備考</p>
        <p class="mt-1 text-base text-slate-700">{environment.notes ?? '-'}</p>
      </div>
    </div>
  {:else}
    <p class="mt-4 text-sm text-slate-600">環境が見つかりません。</p>
  {/if}
</section>

<section class="card p-6">
  <h2 class="text-xl font-semibold text-slate-900">画像キー</h2>
  <div class="mt-4 text-sm text-slate-600">
    <pre class="max-h-40 overflow-auto rounded-xl border border-slate-200/70 bg-white/70 p-3 text-xs">{environment?.image_files?.length ? environment.image_files.join('\n') : 'なし'}</pre>
  </div>
</section>

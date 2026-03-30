<script lang="ts">
  import type { StorageDatasetInfo } from '$lib/api/client';
  import { formatDate, formatRelativeDate } from '$lib/format';

  let { dataset }: { dataset: StorageDatasetInfo } = $props();

  const statusLabel = $derived(dataset.status === 'archived' ? 'アーカイブ済み' : 'アクティブ');
  const syncLabel = $derived(dataset.is_local ? '同期済み' : '未同期');
  const ownerLabel = $derived(dataset.owner_name ?? dataset.owner_email ?? dataset.owner_user_id ?? '-');
  const profileLabel = $derived(dataset.profile_name ?? '-');
  const typeLabel = $derived(dataset.dataset_type ?? '-');
  const contentHash = $derived(dataset.content_hash ?? '-');
</script>

<section class="card-strong overflow-hidden">
  <div class="border-b border-slate-200/80 bg-[linear-gradient(140deg,rgba(91,124,250,0.14),rgba(48,213,200,0.08),rgba(255,255,255,0.98))] px-6 py-6">
    <div class="min-w-0 space-y-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="chip">{statusLabel}</span>
        <span class="chip">{typeLabel}</span>
        <span class={`chip ${dataset.is_local ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
          {syncLabel}
        </span>
      </div>
      <div>
        <p class="section-title">Dataset</p>
        <h1 class="mt-2 text-3xl font-semibold text-slate-950">{dataset.name}</h1>
      </div>
    </div>
  </div>

  <div class="grid gap-px bg-slate-200/80 md:grid-cols-2 xl:grid-cols-4">
    <div class="bg-white px-5 py-4">
      <p class="label">所有者</p>
      <p class="mt-2 text-sm font-semibold text-slate-900">{ownerLabel}</p>
    </div>
    <div class="bg-white px-5 py-4">
      <p class="label">プロファイル</p>
      <p class="mt-2 text-sm font-semibold text-slate-900">{profileLabel}</p>
    </div>
    <div class="bg-white px-5 py-4">
      <p class="label">作成日時</p>
      <p class="mt-2 text-sm font-semibold text-slate-900">{formatDate(dataset.created_at)}</p>
    </div>
    <div class="bg-white px-5 py-4">
      <p class="label">最終更新</p>
      <p class="mt-2 text-sm font-semibold text-slate-900">{formatRelativeDate(dataset.updated_at)}</p>
      <p class="mt-1 text-xs text-slate-500">{formatDate(dataset.updated_at)}</p>
    </div>
    <div class="bg-white px-5 py-4">
      <p class="label">Content Hash</p>
      <p class="mt-2 break-all font-mono text-xs font-semibold text-slate-700">{contentHash}</p>
    </div>
    <div class="bg-white px-5 py-4">
      <p class="label">アーカイブ日時</p>
      <p class="mt-2 text-sm font-semibold text-slate-900">{formatDate(dataset.archived_at)}</p>
    </div>
    <div class="bg-white px-5 py-4 md:col-span-2">
      <p class="label">データセットID</p>
      <p class="mt-2 break-all font-mono text-sm font-semibold text-slate-700">{dataset.id}</p>
    </div>
  </div>
</section>

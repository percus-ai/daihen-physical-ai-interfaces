<script lang="ts">
  import type { StorageModelInfo } from '$lib/api/client';
  import { formatBytes, formatDate, formatRelativeDate } from '$lib/format';

  let { model }: { model: StorageModelInfo } = $props();

  const statusLabel = $derived(model.status === 'archived' ? 'アーカイブ済み' : 'アクティブ');
  const syncLabel = $derived(model.is_local ? '同期済み' : '未同期');
  const ownerLabel = $derived(model.owner_name ?? model.owner_email ?? model.owner_user_id ?? '-');
  const profileLabel = $derived(model.profile_name ?? '-');
  const policyLabel = $derived(model.policy_type ?? '-');
</script>

<section class="card-strong overflow-hidden">
  <div class="border-b border-slate-200/80 bg-[linear-gradient(140deg,rgba(91,124,250,0.14),rgba(255,184,107,0.12),rgba(255,255,255,0.98))] px-6 py-6">
    <div class="space-y-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="chip">{statusLabel}</span>
        <span class="chip">{policyLabel}</span>
        <span class={`chip ${model.is_local ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
          {syncLabel}
        </span>
      </div>
      <div>
        <p class="section-title">Model</p>
        <h1 class="mt-2 text-3xl font-semibold text-slate-950">{model.name}</h1>
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
      <p class="mt-2 text-sm font-semibold text-slate-900">{formatDate(model.created_at)}</p>
    </div>
    <div class="bg-white px-5 py-4">
      <p class="label">最終更新</p>
      <p class="mt-2 text-sm font-semibold text-slate-900">{formatRelativeDate(model.updated_at)}</p>
      <p class="mt-1 text-xs text-slate-500">{formatDate(model.updated_at)}</p>
    </div>
    <div class="bg-white px-5 py-4">
      <p class="label">サイズ</p>
      <p class="mt-2 text-sm font-semibold text-slate-900">{formatBytes(model.size_bytes)}</p>
    </div>
    <div class="bg-white px-5 py-4">
      <p class="label">アーカイブ日時</p>
      <p class="mt-2 text-sm font-semibold text-slate-900">{formatDate(model.archived_at)}</p>
    </div>
    <div class="bg-white px-5 py-4 md:col-span-2 xl:col-span-2">
      <p class="label">モデルID</p>
      <p class="mt-2 break-all font-mono text-sm font-semibold text-slate-700">{model.id}</p>
    </div>
  </div>
</section>

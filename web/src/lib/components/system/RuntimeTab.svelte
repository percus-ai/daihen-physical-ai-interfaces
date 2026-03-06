<script lang="ts">
  import BundledTorchTab from '$lib/components/system/BundledTorchTab.svelte';
  import type { BundledTorchBuildSnapshot } from '$lib/types/bundledTorch';
  import type { SystemSettings } from '$lib/types/settings';
  import type { HealthLevel, RuntimeGroupStatus, SystemStatusSnapshot } from '$lib/types/systemStatus';

  let {
    snapshot = null,
    bundledTorchSnapshot = null,
    systemSettings = null,
    bundledTorchActionPending = false,
    bundledTorchActionError = '',
    onBuild,
    onClean,
  }: {
    snapshot?: SystemStatusSnapshot | null;
    bundledTorchSnapshot?: BundledTorchBuildSnapshot | null;
    systemSettings?: SystemSettings | null;
    bundledTorchActionPending?: boolean;
    bundledTorchActionError?: string;
    onBuild: (payload: {
      pytorchVersion: string;
      torchvisionVersion: string;
      force: boolean;
    }) => void | Promise<void>;
    onClean: () => void | Promise<void>;
  } = $props();

  const runtimeGroups = $derived(snapshot?.runtime_groups ?? []);

  const renderStatusLabel = (value?: string) => {
    switch (value) {
      case 'running':
      case 'healthy':
      case 'available':
      case 'completed':
        return '正常';
      case 'degraded':
      case 'partial':
      case 'cleaning':
      case 'building':
        return '注意';
      case 'stopped':
      case 'idle':
        return '停止';
      case 'error':
      case 'failed':
        return 'エラー';
      default:
        return '不明';
    }
  };

  const renderLevelClass = (level?: HealthLevel | string) => {
    switch (level) {
      case 'healthy':
      case 'completed':
      case 'running':
        return 'border-emerald-200 bg-emerald-50 text-emerald-700';
      case 'degraded':
      case 'building':
      case 'cleaning':
      case 'partial':
        return 'border-amber-200 bg-amber-50 text-amber-700';
      case 'error':
      case 'failed':
        return 'border-rose-200 bg-rose-50 text-rose-700';
      default:
        return 'border-slate-200 bg-slate-100 text-slate-600';
    }
  };

  const renderRuntimeSummary = (group: RuntimeGroupStatus) => {
    const torchVersion = group.torch?.version ?? 'torch unknown';
    const cudaVersion = group.torch?.cuda_version ?? 'cuda unknown';
    const source = group.torch?.source ?? 'unknown';
    return `${torchVersion} / ${cudaVersion} / ${source}`;
  };
</script>

<section class="card p-6">
  <div class="flex items-center justify-between gap-4">
    <div>
      <p class="section-title">Runtime</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-900">Torch Runtime Groups</h2>
      <p class="mt-2 text-sm text-slate-600">実行 env を実測したランタイム構成です。</p>
    </div>
    <span class="chip">{runtimeGroups.length} groups</span>
  </div>

  <div class="mt-5 grid gap-4 lg:grid-cols-2">
    {#if runtimeGroups.length}
      {#each runtimeGroups as group}
        <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <p class="text-base font-semibold text-slate-900">{group.env_name}</p>
              <p class="mt-1 text-sm text-slate-600">{renderRuntimeSummary(group)}</p>
            </div>
            <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(group.level)}`}>
              {renderStatusLabel(group.level)}
            </span>
          </div>
          <div class="mt-4 grid gap-2 text-sm text-slate-600 md:grid-cols-2">
            <p>policies: {(group.policies ?? []).join(', ') || '-'}</p>
            <p>torchvision: {group.details?.torchvision_version ?? '-'}</p>
            <p>torchaudio: {group.details?.torchaudio_version ?? '-'}</p>
            <p>bundled: {group.details?.bundled_torch_present ? 'yes' : 'no'}</p>
            <p>capability: {group.torch?.gpu_capability ?? '-'}</p>
            <p>compatible: {group.torch?.cuda_compatible === true ? 'yes' : group.torch?.cuda_compatible === false ? 'no' : '-'}</p>
          </div>
          {#if group.details?.error}
            <p class="mt-3 text-sm text-rose-600">{group.details.error}</p>
          {/if}
        </div>
      {/each}
    {:else}
      <p class="text-sm text-slate-500">runtime 情報を取得できていません。</p>
    {/if}
  </div>
</section>

<BundledTorchTab
  snapshot={bundledTorchSnapshot}
  systemSettings={systemSettings}
  actionPending={bundledTorchActionPending}
  actionError={bundledTorchActionError}
  onBuild={onBuild}
  onClean={onClean}
/>

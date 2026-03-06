<script lang="ts">
  import BundledTorchTab from '$lib/components/system/BundledTorchTab.svelte';
  import type { BundledTorchBuildSnapshot } from '$lib/types/bundledTorch';
  import type { RuntimeEnvSnapshot, RuntimeEnvStatusSnapshot } from '$lib/types/runtimeEnv';
  import type { SystemSettings } from '$lib/types/settings';
  import type { HealthLevel, RuntimeGroupStatus, SystemStatusSnapshot } from '$lib/types/systemStatus';

  let {
    snapshot = null,
    runtimeEnvSnapshot = null,
    bundledTorchSnapshot = null,
    systemSettings = null,
    runtimeEnvActionPending = false,
    runtimeEnvActionError = '',
    bundledTorchActionPending = false,
    bundledTorchActionError = '',
    onRuntimeBuild,
    onRuntimeDelete,
    onBuild,
    onClean,
  }: {
    snapshot?: SystemStatusSnapshot | null;
    runtimeEnvSnapshot?: RuntimeEnvSnapshot | null;
    bundledTorchSnapshot?: BundledTorchBuildSnapshot | null;
    systemSettings?: SystemSettings | null;
    runtimeEnvActionPending?: boolean;
    runtimeEnvActionError?: string;
    bundledTorchActionPending?: boolean;
    bundledTorchActionError?: string;
    onRuntimeBuild: (payload: { envName: string; force: boolean }) => void | Promise<void>;
    onRuntimeDelete: (envName: string) => void | Promise<void>;
    onBuild: (payload: {
      pytorchVersion: string;
      torchvisionVersion: string;
      force: boolean;
    }) => void | Promise<void>;
    onClean: () => void | Promise<void>;
  } = $props();

  const runtimeGroups = $derived(snapshot?.runtime_groups ?? []);
  const runtimeEnvs = $derived(runtimeEnvSnapshot?.envs ?? []);
  const runtimeGroupMap = $derived.by(() => {
    const map = new Map<string, RuntimeGroupStatus>();
    for (const group of runtimeGroups) {
      map.set(group.env_name, group);
    }
    return map;
  });

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
      case 'deleting':
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
      case 'deleting':
      case 'partial':
        return 'border-amber-200 bg-amber-50 text-amber-700';
      case 'error':
      case 'failed':
        return 'border-rose-200 bg-rose-50 text-rose-700';
      default:
        return 'border-slate-200 bg-slate-100 text-slate-600';
    }
  };

  const renderRuntimeSummary = (group?: RuntimeGroupStatus) => {
    if (!group) return 'torch unknown / cuda unknown / unknown';
    const torchVersion = group.torch?.version ?? 'torch unknown';
    const cudaVersion = group.torch?.cuda_version ?? 'cuda unknown';
    const source = group.torch?.source ?? 'unknown';
    return `${torchVersion} / ${cudaVersion} / ${source}`;
  };

  const latestMessage = (env: RuntimeEnvStatusSnapshot) => {
    if (env.last_error) return env.last_error;
    return env.message ?? '-';
  };

  const renderProgressLabel = (env: RuntimeEnvStatusSnapshot) => {
    if (env.state === 'failed') return 'failed';
    if (env.state === 'completed') return '100%';
    if (typeof env.progress_percent === 'number' && env.progress_percent > 0) return `${env.progress_percent}%`;
    if (env.current_step) return `phase: ${env.current_step}`;
    return 'standby';
  };
</script>

<section class="card p-6">
  <div class="flex items-center justify-between gap-4">
    <div>
      <p class="section-title">Runtime</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-900">Environment Runtimes</h2>
      <p class="mt-2 text-sm text-slate-600">policy ごとの仮想環境を構築・再構築・削除します。</p>
    </div>
    <span class="chip">{runtimeEnvs.length} envs</span>
  </div>

  <div class="mt-6 space-y-4">
    {#if runtimeEnvActionError}
      <div class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
        {runtimeEnvActionError}
      </div>
    {/if}

    <div class="space-y-4">
      {#if runtimeEnvs.length}
        {#each runtimeEnvs as env}
          {@const group = runtimeGroupMap.get(env.env_name)}
          <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="text-base font-semibold text-slate-900">{env.env_name}</p>
                <p class="mt-1 text-sm text-slate-600">{env.description ?? renderRuntimeSummary(group)}</p>
              </div>
              <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(env.state)}`}>
                {renderStatusLabel(env.state)}
              </span>
            </div>

            <div class="mt-4 grid gap-2 text-sm text-slate-600 md:grid-cols-2">
              <p>policies: {(env.policies ?? []).join(', ') || '-'}</p>
              <p>exists: {env.exists ? 'yes' : 'no'}</p>
              <p>python: {env.python_path ?? '-'}</p>
              <p>gpu required: {env.gpu_required ? 'yes' : 'no'}</p>
              <p>packages hash: {env.packages_hash ?? '-'}</p>
              <p>runtime: {renderRuntimeSummary(group)}</p>
            </div>

            {#if group}
              <div class="mt-3 grid gap-2 text-sm text-slate-600 md:grid-cols-2">
                <p>torchvision: {group.details?.torchvision_version ?? '-'}</p>
                <p>torchaudio: {group.details?.torchaudio_version ?? '-'}</p>
                <p>bundled: {group.details?.bundled_torch_present ? 'yes' : 'no'}</p>
                <p>compatible: {group.torch?.cuda_compatible === true ? 'yes' : group.torch?.cuda_compatible === false ? 'no' : '-'}</p>
              </div>
            {/if}

            <p class={`mt-3 text-sm ${env.last_error ? 'text-rose-600' : 'text-slate-500'}`}>
              {latestMessage(env)}
            </p>

            <div class="mt-4">
              <div class="flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
                <span>Progress</span>
                <span>{renderProgressLabel(env)}</span>
              </div>
              <div class="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
                <div
                  class={`h-full rounded-full transition-[width] duration-500 ${
                    env.state === 'failed'
                      ? 'bg-rose-500'
                      : env.state === 'completed'
                        ? 'bg-emerald-500'
                        : 'bg-sky-500'
                  }`}
                  style={`width: ${Math.max(0, Math.min(env.progress_percent ?? 0, 100))}%;`}
                ></div>
              </div>
              <p class="mt-2 text-xs text-slate-400">step: {env.current_step ?? '-'}</p>
            </div>

            <div class="mt-4 flex flex-wrap gap-2">
              <button
                class="btn-primary"
                type="button"
                onclick={() => onRuntimeBuild({ envName: env.env_name, force: false })}
                disabled={runtimeEnvActionPending || !env.can_build}
              >
                build
              </button>
              <button
                class="btn-ghost"
                type="button"
                onclick={() => onRuntimeBuild({ envName: env.env_name, force: true })}
                disabled={runtimeEnvActionPending || !env.can_rebuild}
              >
                rebuild
              </button>
              <button
                class="btn-ghost"
                type="button"
                onclick={() => onRuntimeDelete(env.env_name)}
                disabled={runtimeEnvActionPending || !env.can_delete}
              >
                delete
              </button>
            </div>
          </div>
        {/each}
      {:else}
        <p class="text-sm text-slate-500">runtime env 情報を取得できていません。</p>
      {/if}
    </div>
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

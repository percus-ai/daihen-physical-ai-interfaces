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
    if (env.state === 'completed' || env.exists) return `Environment '${env.env_name}' is ready`;
    if (env.state === 'building') return `Building '${env.env_name}'...`;
    if (env.state === 'deleting') return `Deleting '${env.env_name}'...`;
    return env.message ?? 'Not built yet';
  };

  const renderProgressLabel = (env: RuntimeEnvStatusSnapshot) => {
    if (env.state === 'failed') return 'failed';
    if (env.state === 'completed') return '100%';
    if (typeof env.progress_percent === 'number' && env.progress_percent > 0) return `${env.progress_percent}%`;
    if (env.current_step) return `phase: ${env.current_step}`;
    return 'standby';
  };

  const visualStatus = (env: RuntimeEnvStatusSnapshot) => {
    if (env.state === 'building' || env.state === 'deleting') {
      return {
        label: env.state === 'deleting' ? 'In Progress' : 'Building',
        accent: 'bg-amber-500',
        chip: 'border-amber-200 bg-amber-50 text-amber-700',
        panel: 'border-amber-200/80 bg-amber-50/40'
      };
    }
    if (env.state === 'failed' || env.last_error) {
      return {
        label: 'Failed',
        accent: 'bg-rose-500',
        chip: 'border-rose-200 bg-rose-50 text-rose-700',
        panel: 'border-rose-200/80 bg-rose-50/40'
      };
    }
    if (env.exists) {
      return {
        label: 'Ready',
        accent: 'bg-emerald-500',
        chip: 'border-emerald-200 bg-emerald-50 text-emerald-700',
        panel: 'border-emerald-200/80 bg-emerald-50/40'
      };
    }
    return {
      label: 'Not Built',
      accent: 'bg-slate-300',
      chip: 'border-slate-200 bg-slate-100 text-slate-600',
      panel: 'border-slate-200/80 bg-slate-50/70'
    };
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
          {@const status = visualStatus(env)}
          <div class={`overflow-hidden rounded-2xl border p-3 ${status.panel}`}>
            <div class="flex gap-3">
              <div class={`w-1.5 shrink-0 rounded-full ${status.accent}`}></div>
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-start justify-between gap-2">
                  <div class="min-w-0">
                    <div class="flex flex-wrap items-center gap-1.5">
                      <p class="text-base font-semibold text-slate-900">{env.env_name}</p>
                      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${status.chip}`}>
                        {status.label}
                      </span>
                    </div>
                    <p class="mt-0.5 text-xs text-slate-500">{env.description ?? renderRuntimeSummary(group)}</p>
                    <div class="mt-2 flex flex-wrap gap-1.5">
                      {#if (env.policies ?? []).length}
                        {#each env.policies ?? [] as policy}
                          <span class="rounded-full border border-slate-200 bg-white/80 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                            {policy}
                          </span>
                        {/each}
                      {:else}
                        <span class="rounded-full border border-slate-200 bg-white/80 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                          no policies
                        </span>
                      {/if}
                    </div>
                  </div>
                  <div class="text-right">
                    <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Progress</p>
                    <p class="mt-1 text-sm font-semibold text-slate-700">{renderProgressLabel(env)}</p>
                  </div>
                </div>

                <p class={`mt-2 text-xs ${env.last_error ? 'text-rose-600' : 'text-slate-600'}`}>
                  {latestMessage(env)}
                </p>

                <div class="mt-2">
                  <div class="h-1.5 overflow-hidden rounded-full bg-white/80">
                    <div
                      class={`h-full rounded-full transition-[width] duration-500 ${
                        env.state === 'failed'
                          ? 'bg-rose-500'
                          : env.exists && env.state !== 'building' && env.state !== 'deleting'
                            ? 'bg-emerald-500'
                            : 'bg-amber-500'
                      }`}
                      style={`width: ${Math.max(0, Math.min(env.progress_percent ?? 0, 100))}%;`}
                    ></div>
                  </div>
                </div>

                <details class="group mt-2 rounded-xl border border-slate-200/80 bg-white/80 px-3 py-2">
                  <summary class="flex cursor-pointer list-none items-center justify-between gap-3">
                    <div class="flex flex-wrap gap-2">
                      <button
                        class="btn-primary"
                        type="button"
                        onclick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          onRuntimeBuild({ envName: env.env_name, force: false });
                        }}
                        disabled={runtimeEnvActionPending || !env.can_build}
                      >
                        build
                      </button>
                      <button
                        class="btn-ghost"
                        type="button"
                        onclick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          onRuntimeBuild({ envName: env.env_name, force: true });
                        }}
                        disabled={runtimeEnvActionPending || !env.can_rebuild}
                      >
                        rebuild
                      </button>
                      <button
                        class="btn-ghost"
                        type="button"
                        onclick={(event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          onRuntimeDelete(env.env_name);
                        }}
                        disabled={runtimeEnvActionPending || !env.can_delete}
                      >
                        delete
                      </button>
                    </div>
                    <span class="text-sm font-semibold text-slate-700">Technical Details</span>
                    <span class="text-slate-400 transition group-open:rotate-180">⌄</span>
                  </summary> 

                  <div class="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                    <p>exists: {env.exists ? 'yes' : 'no'}</p>
                    <p>gpu required: {env.gpu_required ? 'yes' : 'no'}</p>
                    <p>python: {env.python_path ?? '-'}</p>
                    <p>packages hash: {env.packages_hash ?? '-'}</p>
                    <p>runtime: {renderRuntimeSummary(group)}</p>
                    <p>step: {env.current_step ?? '-'}</p>
                  </div>

                  {#if group}
                    <div class="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                      <p>torchvision: {group.details?.torchvision_version ?? '-'}</p>
                      <p>torchaudio: {group.details?.torchaudio_version ?? '-'}</p>
                      <p>bundled: {group.details?.bundled_torch_present ? 'yes' : 'no'}</p>
                      <p>compatible: {group.torch?.cuda_compatible === true ? 'yes' : group.torch?.cuda_compatible === false ? 'no' : '-'}</p>
                    </div>
                  {/if}
                </details>
              </div>
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

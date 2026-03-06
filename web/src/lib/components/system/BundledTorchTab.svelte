<script lang="ts">
  import { formatDate } from '$lib/format';
  import type { BundledTorchBuildSnapshot } from '$lib/types/bundledTorch';
  import type { SystemSettings } from '$lib/types/settings';

  let {
    snapshot = null,
    systemSettings = null,
    actionPending = false,
    actionError = '',
    onBuild,
    onClean,
  }: {
    snapshot?: BundledTorchBuildSnapshot | null;
    systemSettings?: SystemSettings | null;
    actionPending?: boolean;
    actionError?: string;
    onBuild: (payload: {
      pytorchVersion: string;
      torchvisionVersion: string;
      force: boolean;
    }) => void | Promise<void>;
    onClean: () => void | Promise<void>;
  } = $props();

  let pytorchVersion = $state('');
  let torchvisionVersion = $state('');

  const bundledLogs = $derived(snapshot?.logs ?? []);
  const bundledBusy = $derived(snapshot?.state === 'building' || snapshot?.state === 'cleaning');
  const bundledSupported = $derived(Boolean(snapshot?.platform?.supported));
  const bundledRequired = $derived(Boolean(snapshot?.platform?.pytorch_build_required));
  const latestBundledLogs = $derived(bundledLogs.slice(-120));
  const latestPercentEvent = $derived.by(() =>
    [...bundledLogs].reverse().find((entry) => typeof entry.percent === 'number')
  );
  const estimatedStepPercent = (step?: string | null) => {
    switch (step) {
      case 'setup':
        return 8;
      case 'clean':
        return 12;
      case 'clone_pytorch':
        return 20;
      case 'clone_torchvision':
        return 32;
      case 'build_pytorch':
        return 72;
      case 'build_torchvision':
        return 92;
      case 'complete':
        return 100;
      default:
        return 0;
    }
  };
  const progressPercent = $derived.by(() => {
    if (!snapshot) return 0;
    if (snapshot.state === 'completed') return 100;
    if (typeof latestPercentEvent?.percent === 'number') return latestPercentEvent.percent;
    return estimatedStepPercent(snapshot.current_step);
  });
  const progressLabel = $derived.by(() => {
    if (!snapshot) return 'progress unavailable';
    if (snapshot.state === 'completed') return '100%';
    if (snapshot.state === 'failed') return 'failed';
    if (!bundledBusy) return 'standby';
    if (typeof latestPercentEvent?.percent === 'number') return `${latestPercentEvent.percent}%`;
    return snapshot.current_step ? `phase: ${snapshot.current_step}` : 'starting';
  });
  const bundledTorchHint = $derived.by(() => {
    if (!snapshot) return '状態取得中です。';
    if (bundledRequired) return 'AGX Thor / Jetson 系では bundled-torch が実行ランタイムに使われます。';
    return 'この環境では bundled-torch build は不要です。';
  });
  const bundledTorchBanner = $derived(
    actionError || snapshot?.message || snapshot?.last_error || ''
  );
  const bundledVisualState = $derived.by(() => {
    if (!snapshot || !bundledRequired) {
      return {
        label: 'Not Required',
        chip: 'border-slate-200 bg-slate-100 text-slate-600',
        panel: 'border-slate-200/80 bg-slate-50/80',
        accent: 'bg-slate-300',
        progress: 'bg-slate-400'
      };
    }
    if (snapshot.state === 'building' || snapshot.state === 'cleaning') {
      return {
        label: 'Building',
        chip: 'border-amber-200 bg-amber-50 text-amber-700',
        panel: 'border-amber-200/80 bg-amber-50/40',
        accent: 'bg-amber-500',
        progress: 'bg-amber-500'
      };
    }
    if (snapshot.install?.is_valid) {
      return {
        label: 'Ready',
        chip: 'border-emerald-200 bg-emerald-50 text-emerald-700',
        panel: 'border-emerald-200/80 bg-emerald-50/40',
        accent: 'bg-emerald-500',
        progress: 'bg-emerald-500'
      };
    }
    return {
      label: 'Build Required',
      chip: 'border-rose-200 bg-rose-50 text-rose-700',
      panel: 'border-rose-200/80 bg-rose-50/40',
      accent: 'bg-rose-500',
      progress: 'bg-rose-500'
    };
  });

  $effect(() => {
    const defaults = systemSettings?.bundled_torch;
    if (defaults && !pytorchVersion) {
      pytorchVersion = defaults.pytorch_version;
    }
    if (defaults && !torchvisionVersion) {
      torchvisionVersion = defaults.torchvision_version;
    }
  });

</script>

<section class={`card border p-6 ${bundledVisualState.panel}`}>
  <div class="flex flex-wrap items-end justify-between gap-4">
    <div class="flex min-w-0 items-start gap-3">
      <div class={`mt-1 h-10 w-1.5 shrink-0 rounded-full ${bundledVisualState.accent}`}></div>
      <div>
      <p class="section-title">Bundled Torch</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-900">Bundled Torch Build</h2>
      <p class="mt-2 text-sm text-slate-600">{bundledTorchHint}</p>
      </div>
    </div>
    <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${bundledVisualState.chip}`}>
      {bundledVisualState.label}
    </span>
  </div>

  <div class="mt-6 space-y-6">
    {#if bundledTorchBanner}
      <div class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
        {bundledTorchBanner}
      </div>
    {/if}

    <div class="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <div class="min-w-0 space-y-4">
        <div class="rounded-2xl border border-slate-200/70 bg-white/80 p-4">
          <p class="label">Platform</p>
          <div class="mt-3 space-y-1 text-sm text-slate-600">
            <p>platform: {snapshot?.platform?.platform_name ?? '-'}</p>
            <p>gpu: {snapshot?.platform?.gpu_name ?? '-'}</p>
            <p>cuda: {snapshot?.platform?.cuda_version ?? '-'}</p>
            <p>required: {bundledRequired ? 'yes' : 'no'}</p>
            <p>supported: {bundledSupported ? 'yes' : 'no'}</p>
          </div>
        </div>

        <div class="rounded-2xl border border-slate-200/70 bg-white/80 p-4">
          <p class="label">Install</p>
          <div class="mt-3 space-y-1 text-sm text-slate-600">
            <p>exists: {snapshot?.install?.exists ? 'yes' : 'no'}</p>
            <p>valid: {snapshot?.install?.is_valid ? 'yes' : 'no'}</p>
            <p>pytorch: {snapshot?.install?.pytorch_version ?? '-'}</p>
            <p>torchvision: {snapshot?.install?.torchvision_version ?? '-'}</p>
            <p>numpy: {snapshot?.install?.numpy_version ?? '-'}</p>
            <p>path: {snapshot?.install?.pytorch_path ?? '-'}</p>
          </div>
        </div>
      </div>

      <div class="min-w-0 space-y-4">
        <div class="rounded-2xl border border-slate-200/70 bg-white/80 p-4">
          <div class="flex items-center justify-between gap-4">
            <div>
              <p class="label">Current State</p>
              <p class="mt-1 text-base font-semibold text-slate-900">{snapshot?.message ?? '-'}</p>
            </div>
            <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${bundledVisualState.chip}`}>
              {bundledVisualState.label}
            </span>
          </div>
          <div class="mt-4">
            <div class="flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
              <span>Progress</span>
              <span>{progressLabel}</span>
            </div>
            <div class="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
              <div
                class={`h-full rounded-full transition-[width] duration-500 ${bundledVisualState.progress}`}
                style={`width: ${Math.max(0, Math.min(progressPercent, 100))}%;`}
              ></div>
            </div>
          </div>
          <div class="mt-4 grid gap-2 text-sm text-slate-600 md:grid-cols-2">
            <p>step: {snapshot?.current_step ?? '-'}</p>
            <p>started: {formatDate(snapshot?.started_at)}</p>
            <p>updated: {formatDate(snapshot?.updated_at)}</p>
            <p>finished: {formatDate(snapshot?.finished_at)}</p>
            <p>requested torch: {snapshot?.requested_pytorch_version ?? '-'}</p>
            <p>requested vision: {snapshot?.requested_torchvision_version ?? '-'}</p>
          </div>
          {#if snapshot?.last_error}
            <p class="mt-3 text-sm text-rose-600">{snapshot.last_error}</p>
          {/if}
        </div>

        <div class="rounded-2xl border border-slate-200/70 bg-white/80 p-4">
          <p class="label">Action</p>
          <div class="mt-4 grid gap-3">
            <label class="text-sm text-slate-600">
              <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">PyTorch version</span>
              <input
                bind:value={pytorchVersion}
                class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-slate-400 focus:outline-none"
                placeholder={systemSettings?.bundled_torch?.pytorch_version ?? 'v2.8.0'}
                disabled={actionPending || bundledBusy}
              />
            </label>
            <label class="text-sm text-slate-600">
              <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">torchvision version</span>
              <input
                bind:value={torchvisionVersion}
                class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-slate-400 focus:outline-none"
                placeholder={systemSettings?.bundled_torch?.torchvision_version ?? 'v0.23.0'}
                disabled={actionPending || bundledBusy}
              />
            </label>

            <div class="flex flex-wrap gap-2">
              <button
                class="btn-primary"
                type="button"
                onclick={() => onBuild({
                  pytorchVersion,
                  torchvisionVersion,
                  force: false
                })}
                disabled={actionPending || !(snapshot?.can_build)}
                aria-busy={actionPending && !bundledBusy}
              >
                {bundledBusy ? 'building...' : 'build'}
              </button>
              <button
                class="btn-ghost"
                type="button"
                onclick={() => onBuild({
                  pytorchVersion,
                  torchvisionVersion,
                  force: true
                })}
                disabled={actionPending || !(snapshot?.can_rebuild || snapshot?.can_build)}
                aria-busy={actionPending && !bundledBusy}
              >
                {bundledBusy ? 'building...' : 'rebuild'}
              </button>
              <button
                class="btn-ghost"
                type="button"
                onclick={onClean}
                disabled={actionPending || !(snapshot?.can_clean)}
                aria-busy={actionPending && !bundledBusy}
              >
                {bundledBusy ? 'cleaning...' : 'clean'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="min-w-0 rounded-2xl border border-slate-200/70 bg-slate-950 p-4 text-slate-100">
      <div class="flex items-center justify-between gap-4">
        <p class="label !text-slate-400">Recent Logs</p>
        <span class="text-xs text-slate-400">{bundledLogs.length} entries</span>
      </div>
      <div class="mt-4 max-h-[32rem] min-w-0 overflow-x-auto overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/80 p-3 font-mono text-xs leading-6">
        {#if latestBundledLogs.length}
          {#each latestBundledLogs as entry}
            <div class="min-w-0 border-b border-slate-900/80 py-1 last:border-b-0">
              <span class="text-slate-500">{formatDate(entry.at)}</span>
              <span class="ml-2 text-slate-300">[{entry.type}]</span>
              {#if entry.step}
                <span class="ml-2 text-slate-500">{entry.step}</span>
              {/if}
              <span class="ml-2 break-all text-slate-100">{entry.line ?? entry.message ?? '-'}</span>
            </div>
          {/each}
        {:else}
          <p class="text-slate-500">ログはまだありません。</p>
        {/if}
      </div>
    </div>
  </div>
</section>

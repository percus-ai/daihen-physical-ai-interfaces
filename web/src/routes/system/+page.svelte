<script lang="ts">
  import { onMount } from 'svelte';

  import { api } from '$lib/api/client';
  import OperateStatusCards from '$lib/components/OperateStatusCards.svelte';
  import { formatDate } from '$lib/format';
  import { connectBundledTorchStream } from '$lib/realtime/bundledTorch';
  import { connectStream } from '$lib/realtime/stream';
  import { connectSystemStatusStream } from '$lib/realtime/systemStatus';
  import type { BundledTorchBuildSnapshot } from '$lib/types/bundledTorch';
  import type { HealthLevel, RuntimeGroupStatus, SystemStatusSnapshot } from '$lib/types/systemStatus';

  type OperateNetworkStatus = {
    status?: string;
    message?: string;
    details?: {
      zmq?: { status?: string; message?: string; endpoint?: string };
      zenoh?: { status?: string; message?: string };
      rosbridge?: { status?: string; message?: string };
    };
  };

  type OperateStatusStreamPayload = {
    operate_status?: {
      network?: OperateNetworkStatus;
    };
  };

  type OperateStatusResponse = {
    network?: OperateNetworkStatus;
  };

  let systemStatusSnapshot = $state<SystemStatusSnapshot | null>(null);
  let networkStatus = $state<OperateNetworkStatus | null>(null);
  let bundledTorchSnapshot = $state<BundledTorchBuildSnapshot | null>(null);
  let pytorchVersion = $state('');
  let torchvisionVersion = $state('');
  let bundledTorchActionPending = $state(false);
  let bundledTorchActionError = $state('');

  const alerts = $derived(systemStatusSnapshot?.overall?.active_alerts ?? []);
  const recorder = $derived(systemStatusSnapshot?.services?.recorder ?? null);
  const inference = $derived(systemStatusSnapshot?.services?.inference ?? null);
  const vlabor = $derived(systemStatusSnapshot?.services?.vlabor ?? null);
  const ros2 = $derived(systemStatusSnapshot?.services?.ros2 ?? null);
  const runtimeGroups = $derived(systemStatusSnapshot?.runtime_groups ?? []);
  const gpuDevices = $derived(systemStatusSnapshot?.gpu?.gpus ?? []);
  const bundledLogs = $derived(bundledTorchSnapshot?.logs ?? []);
  const bundledBusy = $derived(
    bundledTorchSnapshot?.state === 'building' || bundledTorchSnapshot?.state === 'cleaning'
  );
  const bundledSupported = $derived(Boolean(bundledTorchSnapshot?.platform?.supported));
  const bundledRequired = $derived(Boolean(bundledTorchSnapshot?.platform?.pytorch_build_required));
  const latestBundledLogs = $derived(bundledLogs.slice(-120));

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

  const bundledTorchHint = $derived.by(() => {
    if (!bundledTorchSnapshot) return '状態取得中です。';
    if (bundledRequired) return 'AGX Thor / Jetson 系では bundled-torch が実行ランタイムに使われます。';
    return 'この環境では bundled-torch build は不要です。';
  });
  const bundledTorchBanner = $derived(
    bundledTorchActionError || bundledTorchSnapshot?.message || bundledTorchSnapshot?.last_error || ''
  );

  const loadInitialState = async () => {
    const [bundledResult, operateResult] = await Promise.allSettled([
      api.system.bundledTorchStatus(),
      api.operate.status()
    ]);

    if (bundledResult.status === 'fulfilled') {
      bundledTorchSnapshot = bundledResult.value;
    } else {
      bundledTorchActionError =
        bundledResult.reason instanceof Error ? bundledResult.reason.message : 'bundled-torch状態の取得に失敗しました。';
    }

    if (operateResult.status === 'fulfilled') {
      networkStatus = (operateResult.value as OperateStatusResponse | null)?.network ?? null;
    }
  };

  const triggerBuild = async (force: boolean) => {
    bundledTorchActionPending = true;
    bundledTorchActionError = '';
    try {
      bundledTorchSnapshot = await api.system.buildBundledTorch({
        pytorch_version: pytorchVersion.trim() || null,
        torchvision_version: torchvisionVersion.trim() || null,
        force
      });
    } catch (error) {
      bundledTorchActionError =
        error instanceof Error ? error.message : 'bundled-torch build の開始に失敗しました。';
    } finally {
      bundledTorchActionPending = false;
    }
  };

  const triggerClean = async () => {
    bundledTorchActionPending = true;
    bundledTorchActionError = '';
    try {
      bundledTorchSnapshot = await api.system.cleanBundledTorch();
    } catch (error) {
      bundledTorchActionError =
        error instanceof Error ? error.message : 'bundled-torch clean の開始に失敗しました。';
    } finally {
      bundledTorchActionPending = false;
    }
  };

  onMount(() => {
    void loadInitialState();

    const stopSystemStatusStream = connectSystemStatusStream({
      onMessage: (payload) => {
        systemStatusSnapshot = payload;
      }
    });
    const stopOperateStream = connectStream<OperateStatusStreamPayload>({
      path: '/api/stream/operate/status',
      onMessage: (payload) => {
        networkStatus = payload.operate_status?.network ?? null;
      }
    });
    const stopBundledTorchStream = connectBundledTorchStream({
      onMessage: (payload) => {
        bundledTorchSnapshot = payload;
      }
    });

    return () => {
      stopSystemStatusStream();
      stopOperateStream();
      stopBundledTorchStream();
    };
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">System</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">システム</h1>
      <p class="mt-2 text-sm text-slate-600">
        詳細な監視スナップショットと bundled-torch build の状態を確認します。
      </p>
    </div>
    <div class="flex flex-wrap gap-2">
      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(systemStatusSnapshot?.overall?.level)}`}>
        {renderStatusLabel(systemStatusSnapshot?.overall?.level)}
      </span>
      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(bundledTorchSnapshot?.state)}`}>
        bundled-torch: {renderStatusLabel(bundledTorchSnapshot?.state)}
      </span>
    </div>
  </div>
</section>

<OperateStatusCards title="概要" snapshot={systemStatusSnapshot} network={networkStatus} />

<section class="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
  <div class="card p-6">
    <div class="flex items-center justify-between gap-4">
      <div>
        <p class="section-title">Alerts</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-900">状態詳細</h2>
      </div>
      <p class="text-xs text-slate-500">更新: {formatDate(systemStatusSnapshot?.generated_at)}</p>
    </div>
    <p class="mt-3 text-sm text-slate-600">{systemStatusSnapshot?.overall?.summary ?? '監視スナップショットを待機中です。'}</p>

    <div class="mt-5 grid gap-4 md:grid-cols-2">
      <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">Recorder</p>
        <p class="mt-1 text-base font-semibold text-slate-900">{renderStatusLabel(recorder?.level ?? recorder?.state)}</p>
        <div class="mt-3 space-y-1 text-sm text-slate-600">
          <p>state: {recorder?.state ?? '-'}</p>
          <p>dataset: {recorder?.dataset_id ?? '-'}</p>
          <p>profile: {recorder?.active_profile ?? '-'}</p>
          <p>camera ready: {String(recorder?.dependencies?.cameras_ready ?? '-')}</p>
          <p>robot ready: {String(recorder?.dependencies?.robot_ready ?? '-')}</p>
          <p>storage ready: {String(recorder?.dependencies?.storage_ready ?? '-')}</p>
          <p>error: {recorder?.last_error ?? '-'}</p>
        </div>
      </div>

      <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">Inference</p>
        <p class="mt-1 text-base font-semibold text-slate-900">{renderStatusLabel(inference?.level ?? inference?.state)}</p>
        <div class="mt-3 space-y-1 text-sm text-slate-600">
          <p>state: {inference?.state ?? '-'}</p>
          <p>policy: {inference?.policy_type ?? '-'}</p>
          <p>model: {inference?.model_id ?? '-'}</p>
          <p>device: {inference?.device ?? '-'}</p>
          <p>env: {inference?.env_name ?? '-'}</p>
          <p>runtime key: {inference?.runtime_key ?? '-'}</p>
          <p>queue: {inference?.queue_length ?? 0}</p>
          <p>error: {inference?.last_error ?? '-'}</p>
        </div>
      </div>

      <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">VLAbor / ROS2</p>
        <p class="mt-1 text-base font-semibold text-slate-900">{renderStatusLabel(vlabor?.level ?? vlabor?.state)}</p>
        <div class="mt-3 space-y-1 text-sm text-slate-600">
          <p>vlabor state: {vlabor?.state ?? '-'}</p>
          <p>ros2 state: {ros2?.state ?? '-'}</p>
          <p>required nodes: {String(ros2?.required_nodes_ok ?? '-')}</p>
          <p>required topics: {String(ros2?.required_topics_ok ?? '-')}</p>
          <p>containers: {(vlabor?.containers ?? []).map((item) => `${item.name}:${item.state}`).join(', ') || '-'}</p>
          <p>missing nodes: {(ros2?.missing_nodes ?? []).join(', ') || '-'}</p>
          <p>missing topics: {(ros2?.missing_topics ?? []).join(', ') || '-'}</p>
        </div>
      </div>

      <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">Network / GPU</p>
        <p class="mt-1 text-base font-semibold text-slate-900">{renderStatusLabel(networkStatus?.status ?? systemStatusSnapshot?.gpu?.level)}</p>
        <div class="mt-3 space-y-1 text-sm text-slate-600">
          <p>ZMQ: {networkStatus?.details?.zmq?.status ?? '-'}</p>
          <p>Zenoh: {networkStatus?.details?.zenoh?.status ?? '-'}</p>
          <p>rosbridge: {networkStatus?.details?.rosbridge?.status ?? '-'}</p>
          <p>gpu: {systemStatusSnapshot?.gpu?.gpus?.[0]?.name ?? '-'}</p>
          <p>cuda: {systemStatusSnapshot?.gpu?.cuda_version ?? '-'}</p>
          <p>driver: {systemStatusSnapshot?.gpu?.driver_version ?? '-'}</p>
        </div>
      </div>
    </div>

    {#if alerts.length}
      <div class="mt-5 rounded-2xl border border-slate-200/70 bg-slate-50/90 p-4">
        <p class="label">Active Alerts</p>
        <div class="mt-3 flex flex-wrap gap-2">
          {#each alerts as alert}
            <span class={`rounded-full border px-3 py-1 text-xs font-medium ${renderLevelClass(alert.level)}`}>
              {alert.source}: {alert.summary}
            </span>
          {/each}
        </div>
      </div>
    {/if}
  </div>

  <div class="card p-6">
    <div class="flex items-center justify-between gap-4">
      <div>
        <p class="section-title">GPU</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-900">GPU詳細</h2>
      </div>
      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(systemStatusSnapshot?.gpu?.level)}`}>
        {renderStatusLabel(systemStatusSnapshot?.gpu?.level)}
      </span>
    </div>

    <div class="mt-5 space-y-3">
      {#if gpuDevices.length}
        {#each gpuDevices as device}
          <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="text-base font-semibold text-slate-900">{device.name}</p>
                <p class="mt-1 text-xs text-slate-500">GPU #{device.index}</p>
              </div>
              <span class="chip">{device.utilization_gpu_pct ?? 0}%</span>
            </div>
            <div class="mt-3 grid gap-2 text-sm text-slate-600 md:grid-cols-2">
              <p>memory total: {device.memory_total_mb ?? '-'} MB</p>
              <p>memory used: {device.memory_used_mb ?? '-'} MB</p>
              <p>utilization: {device.utilization_gpu_pct ?? '-'}%</p>
              <p>temperature: {device.temperature_c ?? '-'} C</p>
            </div>
          </div>
        {/each}
      {:else}
        <p class="text-sm text-slate-500">GPU 情報を取得できていません。</p>
      {/if}
    </div>
  </div>
</section>

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

<details class="card p-6" open>
  <summary class="flex cursor-pointer list-none items-center justify-between gap-4">
    <div>
      <p class="section-title">Bundled Torch</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-900">Bundled Torch Build</h2>
      <p class="mt-2 text-sm text-slate-600">{bundledTorchHint}</p>
    </div>
    <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(bundledTorchSnapshot?.state)}`}>
      {renderStatusLabel(bundledTorchSnapshot?.state)}
    </span>
  </summary>

  <div class="mt-6 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
    {#if bundledTorchBanner}
      <div class="xl:col-span-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
        {bundledTorchBanner}
      </div>
    {/if}

    <div class="space-y-4">
      <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">Platform</p>
        <div class="mt-3 space-y-1 text-sm text-slate-600">
          <p>platform: {bundledTorchSnapshot?.platform?.platform_name ?? '-'}</p>
          <p>gpu: {bundledTorchSnapshot?.platform?.gpu_name ?? '-'}</p>
          <p>cuda: {bundledTorchSnapshot?.platform?.cuda_version ?? '-'}</p>
          <p>required: {bundledRequired ? 'yes' : 'no'}</p>
          <p>supported: {bundledSupported ? 'yes' : 'no'}</p>
        </div>
      </div>

      <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">Install</p>
        <div class="mt-3 space-y-1 text-sm text-slate-600">
          <p>exists: {bundledTorchSnapshot?.install?.exists ? 'yes' : 'no'}</p>
          <p>valid: {bundledTorchSnapshot?.install?.is_valid ? 'yes' : 'no'}</p>
          <p>pytorch: {bundledTorchSnapshot?.install?.pytorch_version ?? '-'}</p>
          <p>torchvision: {bundledTorchSnapshot?.install?.torchvision_version ?? '-'}</p>
          <p>numpy: {bundledTorchSnapshot?.install?.numpy_version ?? '-'}</p>
          <p>path: {bundledTorchSnapshot?.install?.pytorch_path ?? '-'}</p>
        </div>
      </div>

      <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
        <p class="label">Action</p>
        <div class="mt-4 grid gap-3">
          <label class="text-sm text-slate-600">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">PyTorch version</span>
            <input
              bind:value={pytorchVersion}
              class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-slate-400 focus:outline-none"
              placeholder="v2.8.0"
              disabled={bundledTorchActionPending || bundledBusy}
            />
          </label>
          <label class="text-sm text-slate-600">
            <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">torchvision version</span>
            <input
              bind:value={torchvisionVersion}
              class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:border-slate-400 focus:outline-none"
              placeholder="v0.23.0"
              disabled={bundledTorchActionPending || bundledBusy}
            />
          </label>

          <div class="flex flex-wrap gap-2">
            <button
              class="btn-primary"
              type="button"
              onclick={() => triggerBuild(false)}
              disabled={bundledTorchActionPending || !(bundledTorchSnapshot?.can_build)}
              aria-busy={bundledTorchActionPending && !bundledBusy}
            >
              {bundledBusy ? 'building...' : 'build'}
            </button>
            <button
              class="btn-ghost"
              type="button"
              onclick={() => triggerBuild(true)}
              disabled={bundledTorchActionPending || !(bundledTorchSnapshot?.can_rebuild || bundledTorchSnapshot?.can_build)}
              aria-busy={bundledTorchActionPending && !bundledBusy}
            >
              {bundledBusy ? 'building...' : 'rebuild'}
            </button>
            <button
              class="btn-ghost"
              type="button"
              onclick={triggerClean}
              disabled={bundledTorchActionPending || !(bundledTorchSnapshot?.can_clean)}
              aria-busy={bundledTorchActionPending && !bundledBusy}
            >
              {bundledBusy ? 'cleaning...' : 'clean'}
            </button>
          </div>
        </div>
      </div>
    </div>

    <div class="space-y-4">
      <div class="rounded-2xl border border-slate-200/70 bg-white/70 p-4">
        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="label">Current State</p>
            <p class="mt-1 text-base font-semibold text-slate-900">{bundledTorchSnapshot?.message ?? '-'}</p>
          </div>
          <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(bundledTorchSnapshot?.state)}`}>
            {bundledTorchSnapshot?.state ?? 'unknown'}
          </span>
        </div>
        <div class="mt-4 grid gap-2 text-sm text-slate-600 md:grid-cols-2">
          <p>step: {bundledTorchSnapshot?.current_step ?? '-'}</p>
          <p>started: {formatDate(bundledTorchSnapshot?.started_at)}</p>
          <p>updated: {formatDate(bundledTorchSnapshot?.updated_at)}</p>
          <p>finished: {formatDate(bundledTorchSnapshot?.finished_at)}</p>
          <p>requested torch: {bundledTorchSnapshot?.requested_pytorch_version ?? '-'}</p>
          <p>requested vision: {bundledTorchSnapshot?.requested_torchvision_version ?? '-'}</p>
        </div>
        {#if bundledTorchSnapshot?.last_error}
          <p class="mt-3 text-sm text-rose-600">{bundledTorchSnapshot.last_error}</p>
        {/if}
      </div>

      <div class="rounded-2xl border border-slate-200/70 bg-slate-950 p-4 text-slate-100">
        <div class="flex items-center justify-between gap-4">
          <p class="label !text-slate-400">Recent Logs</p>
          <span class="text-xs text-slate-400">{bundledLogs.length} entries</span>
        </div>
        <div class="mt-4 max-h-[32rem] overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/80 p-3 font-mono text-xs leading-6">
          {#if latestBundledLogs.length}
            {#each latestBundledLogs as entry}
              <div class="border-b border-slate-900/80 py-1 last:border-b-0">
                <span class="text-slate-500">{formatDate(entry.at)}</span>
                <span class="ml-2 text-slate-300">[{entry.type}]</span>
                {#if entry.step}
                  <span class="ml-2 text-slate-500">{entry.step}</span>
                {/if}
                <span class="ml-2 text-slate-100">{entry.line ?? entry.message ?? '-'}</span>
              </div>
            {/each}
          {:else}
            <p class="text-slate-500">ログはまだありません。</p>
          {/if}
        </div>
      </div>
    </div>
  </div>
</details>

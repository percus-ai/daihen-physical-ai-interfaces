<script lang="ts">
  import { formatDate } from '$lib/format';
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

  let {
    snapshot = null,
    network = null
  }: {
    snapshot?: SystemStatusSnapshot | null;
    network?: OperateNetworkStatus | null;
  } = $props();

  const alerts = $derived(snapshot?.overall?.active_alerts ?? []);
  const recorder = $derived(snapshot?.services?.recorder ?? null);
  const inference = $derived(snapshot?.services?.inference ?? null);
  const vlabor = $derived(snapshot?.services?.vlabor ?? null);
  const ros2 = $derived(snapshot?.services?.ros2 ?? null);
  const runtimeGroups = $derived(snapshot?.runtime_groups ?? []);
  const gpuDevices = $derived(snapshot?.gpu?.gpus ?? []);

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

<section class="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
  <div class="card p-6">
    <div class="flex items-center justify-between gap-4">
      <div>
        <p class="section-title">Alerts</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-900">状態詳細</h2>
      </div>
      <p class="text-xs text-slate-500">更新: {formatDate(snapshot?.generated_at)}</p>
    </div>
    <p class="mt-3 text-sm text-slate-600">{snapshot?.overall?.summary ?? '監視スナップショットを待機中です。'}</p>

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
        <p class="mt-1 text-base font-semibold text-slate-900">{renderStatusLabel(network?.status ?? snapshot?.gpu?.level)}</p>
        <div class="mt-3 space-y-1 text-sm text-slate-600">
          <p>ZMQ: {network?.details?.zmq?.status ?? '-'}</p>
          <p>Zenoh: {network?.details?.zenoh?.status ?? '-'}</p>
          <p>rosbridge: {network?.details?.rosbridge?.status ?? '-'}</p>
          <p>gpu: {snapshot?.gpu?.gpus?.[0]?.name ?? '-'}</p>
          <p>cuda: {snapshot?.gpu?.cuda_version ?? '-'}</p>
          <p>driver: {snapshot?.gpu?.driver_version ?? '-'}</p>
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
      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(snapshot?.gpu?.level)}`}>
        {renderStatusLabel(snapshot?.gpu?.level)}
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

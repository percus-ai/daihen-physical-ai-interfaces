<script lang="ts">
  import { formatDate } from '$lib/format';
  import type { HealthLevel, SystemStatusSnapshot } from '$lib/types/systemStatus';

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

  const visualStatus = (level?: HealthLevel | string) => {
    switch (level) {
      case 'healthy':
      case 'completed':
      case 'running':
        return {
          label: 'Ready',
          chip: 'border-emerald-200 bg-emerald-50 text-emerald-700',
          panel: 'border-emerald-200/80 bg-emerald-50/40',
          accent: 'bg-emerald-500'
        };
      case 'degraded':
      case 'building':
      case 'cleaning':
      case 'partial':
        return {
          label: 'Attention',
          chip: 'border-amber-200 bg-amber-50 text-amber-700',
          panel: 'border-amber-200/80 bg-amber-50/40',
          accent: 'bg-amber-500'
        };
      case 'error':
      case 'failed':
        return {
          label: 'Error',
          chip: 'border-rose-200 bg-rose-50 text-rose-700',
          panel: 'border-rose-200/80 bg-rose-50/40',
          accent: 'bg-rose-500'
        };
      default:
        return {
          label: 'Unknown',
          chip: 'border-slate-200 bg-slate-100 text-slate-600',
          panel: 'border-slate-200/80 bg-slate-50/70',
          accent: 'bg-slate-300'
        };
    }
  };

  const networkLevel = $derived.by(() => {
    const statuses = [
      network?.details?.zmq?.status,
      network?.details?.zenoh?.status,
      network?.details?.rosbridge?.status
    ].filter(Boolean);
    if (!statuses.length) return 'unknown';
    if (statuses.some((status) => status === 'error')) return 'error';
    if (statuses.some((status) => status === 'degraded' || status === 'partial')) return 'degraded';
    if (statuses.every((status) => status === 'running' || status === 'healthy')) return 'healthy';
    return 'unknown';
  });
  const vlaborVisual = $derived(visualStatus(vlabor?.level ?? ros2?.level ?? vlabor?.state));
  const networkVisual = $derived(visualStatus(networkLevel === 'healthy' ? snapshot?.gpu?.level ?? 'healthy' : networkLevel));
  const recorderVisual = $derived(visualStatus(recorder?.level ?? recorder?.state));
  const inferenceVisual = $derived(visualStatus(inference?.level ?? inference?.state));

</script>

<section class="space-y-6">
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
      <div class={`overflow-hidden rounded-2xl border p-4 ${vlaborVisual.panel}`}>
        <div class="flex gap-3">
          <div class={`w-1.5 shrink-0 rounded-full ${vlaborVisual.accent}`}></div>
          <div class="min-w-0 flex-1">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="label">VLAbor / ROS2</p>
                <p class="mt-1 text-base font-semibold text-slate-900">{vlabor?.state ?? 'unknown'}</p>
              </div>
              <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${vlaborVisual.chip}`}>
                {vlaborVisual.label}
              </span>
            </div>
            <div class="mt-3 grid gap-2 text-sm text-slate-600">
              <p>vlabor: {vlabor?.state ?? '-'}</p>
              <p>ros2: {ros2?.state ?? '-'}</p>
              <p>required graph: {ros2?.required_nodes_ok === true && ros2?.required_topics_ok === true ? 'ok' : 'check'}</p>
              <p>missing: {[...(ros2?.missing_nodes ?? []), ...(ros2?.missing_topics ?? [])].slice(0, 2).join(', ') || '-'}</p>
            </div>
          </div>
        </div>
      </div>

      <div class={`overflow-hidden rounded-2xl border p-4 ${networkVisual.panel}`}>
        <div class="flex gap-3">
          <div class={`w-1.5 shrink-0 rounded-full ${networkVisual.accent}`}></div>
          <div class="min-w-0 flex-1">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="label">Network / GPU</p>
                <p class="mt-1 text-base font-semibold text-slate-900">{snapshot?.gpu?.gpus?.[0]?.name ?? 'network/gpu'}</p>
              </div>
              <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${networkVisual.chip}`}>
                {networkVisual.label}
              </span>
            </div>
            <div class="mt-3 grid gap-2 text-sm text-slate-600">
              <p>ZMQ / Zenoh / rosbridge: {network?.details?.zmq?.status ?? '-'} / {network?.details?.zenoh?.status ?? '-'} / {network?.details?.rosbridge?.status ?? '-'}</p>
              <p>cuda: {snapshot?.gpu?.cuda_version ?? '-'}</p>
              <p>driver: {snapshot?.gpu?.driver_version ?? '-'}</p>
              <p>utilization: {snapshot?.gpu?.gpus?.[0]?.utilization_gpu_pct ?? '-'}%</p>
            </div>
          </div>
        </div>
      </div>

      <div class={`overflow-hidden rounded-2xl border p-4 ${recorderVisual.panel}`}>
        <div class="flex gap-3">
          <div class={`w-1.5 shrink-0 rounded-full ${recorderVisual.accent}`}></div>
          <div class="min-w-0 flex-1">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="label">Recorder</p>
                <p class="mt-1 text-base font-semibold text-slate-900">{recorder?.state ?? 'unknown'}</p>
              </div>
              <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${recorderVisual.chip}`}>
                {recorderVisual.label}
              </span>
            </div>
            <div class="mt-3 grid gap-2 text-sm text-slate-600">
              <p>profile: {recorder?.active_profile ?? '-'}</p>
              <p>dataset: {recorder?.dataset_id ?? '-'}</p>
              <p>inputs: {recorder?.dependencies?.cameras_ready === true && recorder?.dependencies?.robot_ready === true ? 'ready' : 'check'}</p>
              <p>storage: {String(recorder?.dependencies?.storage_ready ?? '-')}</p>
            </div>
          </div>
        </div>
      </div>

      <div class={`overflow-hidden rounded-2xl border p-4 ${inferenceVisual.panel}`}>
        <div class="flex gap-3">
          <div class={`w-1.5 shrink-0 rounded-full ${inferenceVisual.accent}`}></div>
          <div class="min-w-0 flex-1">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="label">Inference</p>
                <p class="mt-1 text-base font-semibold text-slate-900">{inference?.state ?? 'unknown'}</p>
              </div>
              <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${inferenceVisual.chip}`}>
                {inferenceVisual.label}
              </span>
            </div>
            <div class="mt-3 grid gap-2 text-sm text-slate-600">
              <p>policy: {inference?.policy_type ?? '-'}</p>
              <p>model: {inference?.model_id ?? '-'}</p>
              <p>device: {inference?.device ?? '-'}</p>
              <p>queue: {inference?.queue_length ?? 0}</p>
            </div>
          </div>
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
        <h2 class="mt-2 text-xl font-semibold text-slate-900">一覧</h2>
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

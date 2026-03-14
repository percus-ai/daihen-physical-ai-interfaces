<script lang="ts">
  import type { HealthLevel, SystemStatusSnapshot } from '$lib/types/systemStatus';

  type OperateNetworkStatus = {
    status?: string;
    details?: {
      zmq?: { status?: string };
      zenoh?: { status?: string };
      rosbridge?: { status?: string };
    };
  };

  let { title = 'システム状態', snapshot = null, network = null }: {
    title?: string;
    snapshot?: SystemStatusSnapshot | null;
    network?: OperateNetworkStatus | null;
  } = $props();

  const renderStatusLabel = (value?: string) => {
    switch (value) {
      case 'running':
      case 'healthy':
      case 'available':
        return '正常';
      case 'degraded':
      case 'partial':
        return '注意';
      case 'stopped':
        return '停止';
      case 'error':
        return 'エラー';
      default:
        return '不明';
    }
  };

  const renderLevelClass = (level?: HealthLevel) => {
    switch (level) {
      case 'healthy':
        return 'border-emerald-200 bg-emerald-50 text-emerald-700';
      case 'degraded':
        return 'border-amber-200 bg-amber-50 text-amber-700';
      case 'error':
        return 'border-rose-200 bg-rose-50 text-rose-700';
      default:
        return 'border-slate-200 bg-slate-100 text-slate-600';
    }
  };

  const alerts = $derived(snapshot?.overall?.active_alerts ?? []);
  const recorder = $derived(snapshot?.services?.recorder ?? null);
  const inference = $derived(snapshot?.services?.inference ?? null);
  const vlabor = $derived(snapshot?.services?.vlabor ?? null);
  const ros2 = $derived(snapshot?.services?.ros2 ?? null);
  const gpu = $derived(snapshot?.gpu ?? null);
  const summaryAlerts = $derived(alerts.slice(0, 2));
  const hiddenAlertCount = $derived(Math.max(0, alerts.length - summaryAlerts.length));

  const renderGpuSummary = () => {
    const deviceName = gpu?.gpus?.[0]?.name ?? '-';
    const cuda = gpu?.cuda_version ? `CUDA ${gpu.cuda_version}` : 'CUDA -';
    return `${deviceName} / ${cuda}`;
  };

  const networkDetails = $derived(network?.details ?? null);
</script>

<section class="card p-6">
  <div class="flex items-center justify-between gap-4">
    <div>
      <h2 class="text-xl font-semibold text-slate-900">{title}</h2>
      <p class="mt-2 text-sm text-slate-600">{snapshot?.overall?.summary ?? '監視スナップショットを待機中です。'}</p>
    </div>
    <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(snapshot?.overall?.level)}`}>
      {renderStatusLabel(snapshot?.overall?.level)}
    </span>
  </div>

  {#if alerts.length}
    <div class="mt-4 flex flex-wrap gap-2">
      {#each summaryAlerts as alert}
        <span class={`rounded-full border px-3 py-1 text-xs font-medium ${renderLevelClass(alert.level)}`}>
          {alert.source}: {alert.summary}
        </span>
      {/each}
      {#if hiddenAlertCount > 0}
        <span class="rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          +{hiddenAlertCount} more
        </span>
      {/if}
    </div>
  {/if}

  <div class="mt-4 grid gap-4 text-sm text-slate-600 sm:grid-cols-2 xl:grid-cols-5">
    <div class="nested-block p-3">
      <p class="label">VLAbor</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(vlabor?.level ?? vlabor?.state)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>state: {vlabor?.state ?? '-'}</p>
        <p>ros2: {ros2?.state ?? '-'}</p>
        <p>topics: {ros2?.required_topics_ok === false ? 'missing' : 'ok'}</p>
      </div>
    </div>
    <div class="nested-block p-3">
      <p class="label">Recorder</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(recorder?.level ?? recorder?.state)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>state: {recorder?.state ?? '-'}</p>
        <p>dataset: {recorder?.dataset_id ?? '-'}</p>
        <p>profile: {recorder?.active_profile ?? '-'}</p>
      </div>
    </div>
    <div class="nested-block p-3">
      <p class="label">Inference</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(inference?.level ?? inference?.state)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>state: {inference?.state ?? '-'}</p>
        <p>policy: {inference?.policy_type ?? '-'}</p>
        <p>model: {inference?.model_id ?? '-'}</p>
        <p>device: {inference?.device ?? '-'}</p>
      </div>
    </div>
    <div class="nested-block p-3">
      <p class="label">Network</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(network?.status)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>ZMQ: {networkDetails?.zmq?.status ?? '-'}</p>
        <p>Zenoh: {networkDetails?.zenoh?.status ?? '-'}</p>
        <p>rosbridge: {networkDetails?.rosbridge?.status ?? '-'}</p>
      </div>
    </div>
    <div class="nested-block p-3">
      <p class="label">GPU</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(gpu?.level)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>{renderGpuSummary()}</p>
        <p>driver: {gpu?.driver_version ?? '-'}</p>
      </div>
    </div>
  </div>
</section>

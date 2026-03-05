<script lang="ts">
  import type { HealthLevel, RuntimeGroupStatus, SystemStatusSnapshot } from '$lib/types/systemStatus';

  let { title = 'システム状態', snapshot = null }: {
    title?: string;
    snapshot?: SystemStatusSnapshot | null;
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

  const formatPercent = (value?: number | null) =>
    Number.isFinite(value) ? `${Math.round(Math.max(0, Number(value)))}%` : '-';

  const formatMemory = (value?: number | null) =>
    Number.isFinite(value) ? `${Number(value).toFixed(0)} MB` : '-';

  const runtimeGroups = $derived(snapshot?.runtime_groups ?? []);
  const alerts = $derived(snapshot?.overall?.active_alerts ?? []);
  const recorder = $derived(snapshot?.services?.recorder ?? null);
  const inference = $derived(snapshot?.services?.inference ?? null);
  const vlabor = $derived(snapshot?.services?.vlabor ?? null);
  const ros2 = $derived(snapshot?.services?.ros2 ?? null);
  const gpu = $derived(snapshot?.gpu ?? null);

  const summarizeRuntime = (group: RuntimeGroupStatus) => {
    const torch = group.torch?.version ?? 'unknown';
    const cuda = group.torch?.cuda_version ?? 'unknown';
    const source = group.torch?.source ?? 'unknown';
    return `torch ${torch} / cuda ${cuda} / ${source}`;
  };

  const isActiveRuntimeGroup = (group: RuntimeGroupStatus) => {
    if (!inference?.session_id) return false;
    if (inference.runtime_key && group.runtime_key === inference.runtime_key) return true;
    return Boolean(inference.env_name && group.env_name === inference.env_name);
  };
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
      {#each alerts as alert}
        <span class={`rounded-full border px-3 py-1 text-xs font-medium ${renderLevelClass(alert.level)}`}>
          {alert.source}: {alert.summary}
        </span>
      {/each}
    </div>
  {/if}

  <div class="mt-4 grid gap-4 text-sm text-slate-600 sm:grid-cols-2 lg:grid-cols-5">
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">Recorder</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(recorder?.level ?? recorder?.state)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>state: {recorder?.state ?? '-'}</p>
        <p>dataset: {recorder?.dataset_id ?? '-'}</p>
        <p>profile: {recorder?.active_profile ?? '-'}</p>
      </div>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">Inference</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(inference?.level ?? inference?.state)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>state: {inference?.state ?? '-'}</p>
        <p>session: {inference?.session_id ?? '-'}</p>
        <p>policy: {inference?.policy_type ?? '-'}</p>
        <p>model: {inference?.model_id ?? '-'}</p>
        <p>device: {inference?.device ?? '-'}</p>
        <p>env: {inference?.env_name ?? '-'}</p>
        <p>queue: {inference?.queue_length ?? 0}</p>
      </div>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">VLAbor</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(vlabor?.level ?? vlabor?.state)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>state: {vlabor?.state ?? '-'}</p>
        <p>container: {vlabor?.containers?.[0]?.state ?? '-'}</p>
      </div>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">ROS2</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(ros2?.level ?? ros2?.state)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>state: {ros2?.state ?? '-'}</p>
        <p>
          topics:
          {ros2?.required_topics_ok === null || ros2?.required_topics_ok === undefined
            ? '-'
            : ros2.required_topics_ok
              ? 'ok'
              : 'missing'}
        </p>
        <p>error: {ros2?.last_error ?? '-'}</p>
      </div>
    </div>
    <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
      <p class="label">GPU</p>
      <p class="mt-1 text-base font-semibold text-slate-800">{renderStatusLabel(gpu?.level)}</p>
      <div class="mt-2 space-y-1 text-xs text-slate-500">
        <p>cuda: {gpu?.cuda_version ?? '-'}</p>
        <p>driver: {gpu?.driver_version ?? '-'}</p>
        <p>device: {gpu?.gpus?.[0]?.name ?? '-'}</p>
      </div>
    </div>
  </div>

  <div class="mt-5 rounded-2xl border border-slate-200/70 bg-slate-50/70 p-4">
    <div class="flex items-center justify-between gap-4">
      <div>
        <p class="label">Torch Runtime Groups</p>
        <p class="mt-1 text-xs text-slate-500">実行 env を実測したランタイム構成です。</p>
      </div>
      <span class="text-xs text-slate-400">{runtimeGroups.length} groups</span>
    </div>
    <div class="mt-3 grid gap-3 lg:grid-cols-2">
      {#if runtimeGroups.length}
        {#each runtimeGroups as group}
          <div class={`rounded-xl border bg-white/80 p-3 ${isActiveRuntimeGroup(group) ? 'border-emerald-300 ring-2 ring-emerald-100' : 'border-slate-200/80'}`}>
            <div class="flex items-start justify-between gap-3">
              <div>
                <p class="text-sm font-semibold text-slate-900">{group.env_name}</p>
                <p class="mt-1 text-xs text-slate-500">{summarizeRuntime(group)}</p>
              </div>
              <div class="flex flex-col items-end gap-1">
                <span class={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${renderLevelClass(group.level)}`}>
                  {renderStatusLabel(group.level)}
                </span>
                {#if isActiveRuntimeGroup(group)}
                  <span class="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">
                    active inference
                  </span>
                {/if}
              </div>
            </div>
            <div class="mt-3 grid gap-1 text-xs text-slate-500 sm:grid-cols-2">
              <p>policies: {group.policies?.join(', ') ?? '-'}</p>
              <p>torchvision: {group.details?.torchvision_version ?? '-'}</p>
              <p>torchaudio: {group.details?.torchaudio_version ?? '-'}</p>
              <p>bundled: {group.details?.bundled_torch_present ? 'yes' : 'no'}</p>
              <p>capability: {group.torch?.gpu_capability ?? '-'}</p>
              <p>
                compatible:
                {group.torch?.cuda_compatible === null || group.torch?.cuda_compatible === undefined
                  ? '-'
                  : group.torch.cuda_compatible
                    ? 'yes'
                    : 'no'}
              </p>
            </div>
            {#if group.details?.error}
              <p class="mt-2 text-xs text-rose-600">{group.details.error}</p>
            {/if}
          </div>
        {/each}
      {:else}
        <div class="rounded-xl border border-dashed border-slate-200 bg-white/70 p-4 text-sm text-slate-500">
          ランタイム情報を収集中です。
        </div>
      {/if}
    </div>
  </div>

  {#if gpu?.gpus?.length}
    <div class="mt-5 grid gap-3 md:grid-cols-2">
      {#each gpu.gpus as device}
        <div class="rounded-xl border border-slate-200/70 bg-white/75 p-3 text-xs text-slate-500">
          <div class="flex items-start justify-between gap-3">
            <div>
              <p class="text-sm font-semibold text-slate-900">{device.name}</p>
              <p class="mt-1 text-slate-500">GPU #{device.index}</p>
            </div>
            <span class="chip">{formatPercent(device.utilization_gpu_pct)}</span>
          </div>
          <div class="mt-3 grid gap-1 sm:grid-cols-2">
            <p>memory total: {formatMemory(device.memory_total_mb)}</p>
            <p>memory used: {formatMemory(device.memory_used_mb)}</p>
            <p>utilization: {formatPercent(device.utilization_gpu_pct)}</p>
            <p>temperature: {device.temperature_c ?? '-'} C</p>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</section>

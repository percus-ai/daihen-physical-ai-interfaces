<script lang="ts">
  import { formatDate } from '$lib/format';
  import { isRecorderActiveState } from '$lib/recording/recorderStatus';
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

  const effectiveSnapshot = $derived(snapshot);
  const effectiveNetwork = $derived(network);

  const alerts = $derived(effectiveSnapshot?.overall?.active_alerts ?? []);
  const recorder = $derived(effectiveSnapshot?.services?.recorder ?? null);
  const inference = $derived(effectiveSnapshot?.services?.inference ?? null);
  const vlabor = $derived(effectiveSnapshot?.services?.vlabor ?? null);
  const ros2 = $derived(effectiveSnapshot?.services?.ros2 ?? null);
  const gpuDevices = $derived(effectiveSnapshot?.gpu?.gpus ?? []);

  type CardState = 'normal' | 'error' | 'stopped' | 'checking';

  type StatusCard = {
    id: string;
    title: string;
    state: CardState;
    label: string;
    message: string;
  };

  type StatusIssue = {
    id: string;
    area: string;
    title: string;
    impact: string;
    technicalDetails?: string[];
  };

  const STATUS_STYLES: Record<
    CardState,
    {
      label: string;
      dot: string;
      panel: string;
      text: string;
      badge: string;
    }
  > = {
    normal: {
      label: '正常',
      dot: 'bg-emerald-500',
      panel: 'border-emerald-200/80 bg-emerald-50/40',
      text: 'text-emerald-800',
      badge: 'border-emerald-200 bg-emerald-50 text-emerald-700'
    },
    error: {
      label: '異常',
      dot: 'bg-rose-500',
      panel: 'border-rose-200/80 bg-rose-50/50',
      text: 'text-rose-800',
      badge: 'border-rose-200 bg-rose-50 text-rose-700'
    },
    stopped: {
      label: '停止',
      dot: 'bg-slate-400',
      panel: 'border-slate-200 bg-white/80',
      text: 'text-slate-800',
      badge: 'border-slate-200 bg-slate-100 text-slate-600'
    },
    checking: {
      label: '確認中',
      dot: 'bg-slate-300',
      panel: 'border-slate-200 bg-white/70',
      text: 'text-slate-700',
      badge: 'border-slate-200 bg-slate-100 text-slate-600'
    }
  };

  const styleForState = (state: CardState) => STATUS_STYLES[state];

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
      case 'error':
      case 'failed':
        return '異常';
      case 'stopped':
      case 'idle':
        return '停止';
      default:
        return '確認中';
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
      case 'error':
      case 'failed':
        return 'border-rose-200 bg-rose-50 text-rose-700';
      default:
        return 'border-slate-200 bg-slate-100 text-slate-600';
    }
  };

  const isProblemState = (value?: string | null) =>
    ['degraded', 'partial', 'error', 'failed'].includes(String(value ?? '').toLowerCase());
  const isStoppedState = (value?: string | null) =>
    ['stopped', 'idle', 'exited', 'dead'].includes(String(value ?? '').toLowerCase());
  const isHealthyState = (value?: string | null) =>
    ['healthy', 'running', 'available', 'completed', 'ok', 'connected'].includes(String(value ?? '').toLowerCase());

  const networkLevel = $derived.by(() => {
    const statuses = [
      effectiveNetwork?.details?.zmq?.status,
      effectiveNetwork?.details?.zenoh?.status,
      effectiveNetwork?.details?.rosbridge?.status
    ].filter(Boolean);
    if (!statuses.length) return 'unknown';
    if (statuses.some((status) => isProblemState(status) || isStoppedState(status) || status === 'disconnected')) {
      return 'error';
    }
    if (statuses.every((status) => isHealthyState(status))) return 'healthy';
    return 'unknown';
  });
  const ros2GraphReady = $derived(ros2?.required_nodes_ok === true && ros2?.required_topics_ok === true);
  const missingRos2Items = $derived([...(ros2?.missing_nodes ?? []), ...(ros2?.missing_topics ?? [])]);

  const recorderDependencyProblem = $derived.by(() => {
    const dependencies = recorder?.dependencies;
    return (
      dependencies?.cameras_ready === false ||
      dependencies?.robot_ready === false ||
      dependencies?.storage_ready === false
    );
  });
  const recorderStorageUnknownOnly = $derived(
    recorder?.last_error === 'recorder storage readiness is unknown' &&
      recorder?.dependencies?.storage_ready == null
  );
  const recorderSessionActive = $derived(
    Boolean(recorder?.session_id) && isRecorderActiveState(recorder?.state)
  );
  const isRecorderStorageUnknownAlert = (alert: { source?: string; summary?: string }) =>
    alert.source === 'recorder' && alert.summary === 'recorder storage readiness is unknown';
  const recorderHasBlockingError = $derived(
    Boolean(recorder?.last_error && !recorderStorageUnknownOnly) ||
      (isProblemState(recorder?.level) && !recorderStorageUnknownOnly) ||
      recorderDependencyProblem
  );

  const recorderCard = $derived.by((): StatusCard => {
    if (!effectiveSnapshot) {
      return {
        id: 'recorder',
        title: '録画',
        state: 'checking',
        label: STATUS_STYLES.checking.label,
        message: '録画の状態を確認しています。'
      };
    }
    if (recorderHasBlockingError) {
      return {
        id: 'recorder',
        title: '録画',
        state: 'error',
        label: STATUS_STYLES.error.label,
        message: '録画を開始できません。'
      };
    }
    if (recorderSessionActive) {
      return {
        id: 'recorder',
        title: '録画',
        state: 'normal',
        label: STATUS_STYLES.normal.label,
        message: '録画セッションが稼働しています。'
      };
    }
    return {
      id: 'recorder',
      title: '録画',
      state: 'stopped',
      label: STATUS_STYLES.stopped.label,
      message: '録画は開始可能です。'
    };
  });

  const inferenceCardState = $derived.by(() => {
    if (!effectiveSnapshot) return 'checking';
    if (inference?.last_error || isProblemState(inference?.level) || isProblemState(inference?.state)) {
      return 'error';
    }
    if (inference?.session_id || inference?.worker_alive || inference?.state === 'running') {
      return 'normal';
    }
    return 'stopped';
  });

  const inferenceCard = $derived.by((): StatusCard => {
    switch (inferenceCardState) {
      case 'normal':
        return {
          id: 'inference',
          title: '推論',
          state: 'normal',
          label: STATUS_STYLES.normal.label,
          message: '推論セッションが稼働しています。'
        };
      case 'error':
        return {
          id: 'inference',
          title: '推論',
          state: 'error',
          label: STATUS_STYLES.error.label,
          message: '推論を起動できません。'
        };
      case 'stopped':
        return {
          id: 'inference',
          title: '推論',
          state: 'stopped',
          label: STATUS_STYLES.stopped.label,
          message: '推論は起動可能です。'
        };
      default:
        return {
          id: 'inference',
          title: '推論',
          state: 'checking',
          label: STATUS_STYLES.checking.label,
          message: '推論の状態を確認しています。'
        };
    }
  });

  const vlaborCardState = $derived.by((): CardState => {
    if (!effectiveSnapshot) return 'checking';
    if (vlabor?.last_error || ros2?.last_error || isProblemState(vlabor?.level) || isProblemState(ros2?.level)) {
      return 'error';
    }
    if (!ros2GraphReady && (ros2?.required_nodes_ok === false || ros2?.required_topics_ok === false)) {
      return 'error';
    }
    if (isStoppedState(vlabor?.state)) return 'stopped';
    if (isHealthyState(vlabor?.level) || isHealthyState(vlabor?.state)) return 'normal';
    return 'stopped';
  });

  const vlaborCard = $derived.by((): StatusCard => {
    switch (vlaborCardState) {
      case 'normal':
        return {
          id: 'vlabor',
          title: 'VLAbor',
          state: 'normal',
          label: STATUS_STYLES.normal.label,
          message: 'VLAborに接続しています。'
        };
      case 'error':
        return {
          id: 'vlabor',
          title: 'VLAbor',
          state: 'error',
          label: STATUS_STYLES.error.label,
          message: 'VLAborの確認が必要です。'
        };
      case 'stopped':
        return {
          id: 'vlabor',
          title: 'VLAbor',
          state: 'stopped',
          label: STATUS_STYLES.stopped.label,
          message: 'VLAborは停止しています。'
        };
      default:
        return {
          id: 'vlabor',
          title: 'VLAbor',
          state: 'checking',
          label: STATUS_STYLES.checking.label,
          message: 'VLAborの状態を確認しています。'
        };
    }
  });

  const communicationTechnicalDetails = $derived.by(() => {
    const details = effectiveNetwork?.details;
    return [
      details?.zmq?.status ? `ZMQ: ${details.zmq.status}${details.zmq.message ? ` - ${details.zmq.message}` : ''}` : '',
      details?.zenoh?.status ? `Zenoh: ${details.zenoh.status}${details.zenoh.message ? ` - ${details.zenoh.message}` : ''}` : '',
      details?.rosbridge?.status ? `rosbridge: ${details.rosbridge.status}${details.rosbridge.message ? ` - ${details.rosbridge.message}` : ''}` : ''
    ].filter(Boolean);
  });

  const communicationCard = $derived.by((): StatusCard => {
    if (!effectiveNetwork || networkLevel === 'unknown') {
      return {
        id: 'communication',
        title: '通信',
        state: 'checking',
        label: STATUS_STYLES.checking.label,
        message: '画面の状態更新を確認しています。'
      };
    }
    if (networkLevel === 'error') {
      return {
        id: 'communication',
        title: '通信',
        state: 'error',
        label: STATUS_STYLES.error.label,
        message: '画面の状態更新に影響があります。'
      };
    }
    return {
      id: 'communication',
      title: '通信',
      state: 'normal',
      label: STATUS_STYLES.normal.label,
      message: '画面は最新状態を受け取れます。'
    };
  });

  const statusCards = $derived([recorderCard, inferenceCard, vlaborCard, communicationCard]);

  const statusIssues = $derived.by(() => {
    const issues: StatusIssue[] = [];

    if (recorderCard.state === 'error') {
      issues.push({
        id: 'recorder',
        area: '録画',
        title: '録画を開始できません',
        impact: '録画セッションの開始に影響します。',
        technicalDetails: [
          recorder?.last_error ? `last_error: ${recorder.last_error}` : '',
          recorder?.state ? `state: ${recorder.state}` : '',
          `process_alive: ${String(recorder?.process_alive ?? '-')}`,
          `cameras_ready: ${String(recorder?.dependencies?.cameras_ready ?? '-')}`,
          `robot_ready: ${String(recorder?.dependencies?.robot_ready ?? '-')}`,
          `storage_ready: ${String(recorder?.dependencies?.storage_ready ?? '-')}`
        ].filter(Boolean)
      });
    }

    if (inferenceCard.state === 'error') {
      issues.push({
        id: 'inference',
        area: '推論',
        title: '推論を起動できません',
        impact: '推論セッションの開始に影響します。',
        technicalDetails: [
          inference?.last_error ? `last_error: ${inference.last_error}` : '',
          inference?.state ? `state: ${inference.state}` : '',
          inference?.device ? `device: ${inference.device}` : '',
          inference?.env_name ? `env: ${inference.env_name}` : ''
        ].filter(Boolean)
      });
    }

    if (vlaborCard.state === 'error') {
      issues.push({
        id: 'vlabor',
        area: 'VLAbor',
        title: 'VLAborの確認が必要です',
        impact: '録画・推論・テレオペに影響する可能性があります。',
        technicalDetails: [
          vlabor?.last_error ? `VLAbor error: ${vlabor.last_error}` : '',
          ros2?.last_error ? `ROS2 error: ${ros2.last_error}` : '',
          vlabor?.state ? `VLAbor: ${vlabor.state}` : '',
          ros2?.state ? `ROS2: ${ros2.state}` : '',
          missingRos2Items.length ? `不足: ${missingRos2Items.slice(0, 4).join(', ')}` : ''
        ].filter(Boolean)
      });
    }

    if (communicationCard.state === 'error') {
      issues.push({
        id: 'communication',
        area: '通信',
        title: '画面の状態更新に影響があります',
        impact: '録画・推論の表示が最新でない可能性があります。',
        technicalDetails: [
          effectiveNetwork?.message ? `message: ${effectiveNetwork.message}` : '',
          ...communicationTechnicalDetails
        ].filter(Boolean)
      });
    }

    const existingIssueIds = new Set(issues.map((issue) => issue.id));
    for (const alert of alerts) {
      if (isRecorderStorageUnknownAlert(alert)) continue;
      if (existingIssueIds.has(alert.source)) continue;
      issues.push({
        id: `alert-${alert.code}`,
        area: alert.source,
        title: `${alert.source} の確認が必要です`,
        impact: 'システムの一部に影響している可能性があります。',
        technicalDetails: [`summary: ${alert.summary}`, `level: ${alert.level}`, `code: ${alert.code}`]
      });
    }

    return issues;
  });

  const operationalStatus = $derived.by(() => {
    if (!effectiveSnapshot) {
      return {
        state: 'checking' as CardState,
        label: STATUS_STYLES.checking.label,
        message: '監視データを読み込んでいます。'
      };
    }
    if (statusIssues.length > 0) {
      return {
        state: 'error' as CardState,
        label: STATUS_STYLES.error.label,
        message: statusIssues[0]?.impact ?? '確認が必要な項目があります。'
      };
    }
    if (statusCards.some((card) => card.state === 'checking')) {
      return {
        state: 'checking' as CardState,
        label: STATUS_STYLES.checking.label,
        message: '一部の状態を確認しています。'
      };
    }
    return {
      state: 'normal' as CardState,
      label: STATUS_STYLES.normal.label,
      message: 'システムは利用できます。必要な操作を開始できます。'
    };
  });

</script>

<section class="space-y-6">
  <div class="card p-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="section-title">状態</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-900">運用状態</h2>
        <p class="mt-3 max-w-2xl text-sm leading-6 text-slate-600">{operationalStatus.message}</p>
      </div>
      <div class="flex flex-col items-start gap-2 sm:items-end">
        <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${styleForState(operationalStatus.state).badge}`}>
          {operationalStatus.label}
        </span>
        <p class="text-xs text-slate-500">更新: {formatDate(effectiveSnapshot?.generated_at)}</p>
      </div>
    </div>

    <div class="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {#each statusCards as card}
        {@const cardStyle = styleForState(card.state)}
        <div class={`min-h-[9rem] rounded-xl border p-4 ${cardStyle.panel}`}>
          <div class="flex items-center justify-between gap-3">
            <p class="label">{card.title}</p>
            <span class={`h-2.5 w-2.5 shrink-0 rounded-full ${cardStyle.dot}`}></span>
          </div>
          <p class={`mt-4 text-2xl font-semibold ${cardStyle.text}`}>{card.label}</p>
          <p class="mt-2 text-sm leading-5 text-slate-600">{card.message}</p>
        </div>
      {/each}
    </div>

    {#if statusIssues.length}
      <div class="mt-5 rounded-xl border border-rose-200 bg-rose-50/60 p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p class="section-title text-rose-500">確認が必要</p>
            <h3 class="mt-2 text-lg font-semibold text-rose-950">運用に影響する項目があります</h3>
          </div>
          <span class="rounded-full border border-rose-200 bg-white/70 px-3 py-1 text-xs font-semibold text-rose-700">
            {statusIssues.length}件
          </span>
        </div>
        <div class="mt-4 divide-y divide-rose-200/70">
          {#each statusIssues as issue}
            <article class="py-4 first:pt-0 last:pb-0">
              <div class="flex flex-wrap items-center gap-2">
                <span class="rounded-full bg-white/80 px-2.5 py-1 text-xs font-semibold text-rose-700">
                  {issue.area}
                </span>
                <h4 class="text-sm font-semibold text-rose-950">{issue.title}</h4>
              </div>
              <p class="mt-2 text-sm leading-6 text-rose-900">{issue.impact}</p>
              {#if issue.technicalDetails?.length}
                <details class="mt-2 text-xs text-rose-900/70">
                  <summary class="cursor-pointer font-semibold">技術詳細</summary>
                  <ul class="mt-2 space-y-1">
                    {#each issue.technicalDetails as detail}
                      <li class="break-all">{detail}</li>
                    {/each}
                  </ul>
                </details>
              {/if}
            </article>
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
      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(effectiveSnapshot?.gpu?.level)}`}>
        {renderStatusLabel(effectiveSnapshot?.gpu?.level)}
      </span>
    </div>

    <div class="mt-5 space-y-3">
      {#if gpuDevices.length}
        {#each gpuDevices as device}
          <div class="nested-block p-4">
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

<script lang="ts">
  import {
    buildLossChartModel,
    type CheckpointMarker,
    type CheckpointMarkerStatus,
    formatLossValue,
    formatStepValue,
    LOSS_CHART_HEIGHT,
    LOSS_CHART_PADDING,
    LOSS_CHART_WIDTH,
    type LossMetricPoint
  } from '$lib/training/lossChart';
  import { formatDurationMs } from '$lib/format';
  import { estimateTrainingEta } from '$lib/training/trainingEta';

  type LossPreviewMetricPoint = LossMetricPoint & {
    ts?: string | null;
  };

  let {
    trainSeries = [],
    valSeries = [],
    totalSteps = null,
    saveFreq = null,
    saveCheckpoint = true,
    uploadedCheckpointSteps = [],
    activeCheckpointUploadStep = null,
    startedAt = null,
    updatedAt = null,
    nowMs = Date.now(),
    loading = false,
    error = ''
  }: {
    trainSeries?: LossPreviewMetricPoint[];
    valSeries?: LossPreviewMetricPoint[];
    totalSteps?: number | null;
    saveFreq?: number | null;
    saveCheckpoint?: boolean;
    uploadedCheckpointSteps?: number[];
    activeCheckpointUploadStep?: number | null;
    startedAt?: string | null;
    updatedAt?: string | null;
    nowMs?: number;
    loading?: boolean;
    error?: string;
  } = $props();

  const parseTimestampMs = (value: string | null | undefined): number | null => {
    if (!value) return null;
    const parsed = new Date(value).getTime();
    return Number.isFinite(parsed) ? parsed : null;
  };
  const formatElapsedLabel = (valueMs: number | null): string => {
    if (valueMs === null) return '-';
    return formatDurationMs(valueMs);
  };
  const formatAgoLabel = (valueMs: number | null): string => {
    if (valueMs === null) return '-';
    return `${formatDurationMs(valueMs)}前`;
  };

  const latestTrainPoint = $derived(trainSeries.length ? trainSeries[trainSeries.length - 1] : null);
  const latestValPoint = $derived(valSeries.length ? valSeries[valSeries.length - 1] : null);
  const latestStep = $derived(latestTrainPoint?.step ?? latestValPoint?.step ?? null);
  const latestUpdatedMs = $derived.by<number | null>(() => {
    const timestamps = [latestTrainPoint?.ts, latestValPoint?.ts, updatedAt]
      .map((value) => parseTimestampMs(value))
      .filter((value): value is number => value !== null);
    return timestamps.length ? Math.max(...timestamps) : null;
  });
  const startedAtMs = $derived(parseTimestampMs(startedAt));
  const lastUpdatedLabel = $derived(
    latestUpdatedMs === null ? '-' : formatAgoLabel(Math.max(0, nowMs - latestUpdatedMs))
  );
  const runtimeLabel = $derived(
    startedAtMs === null ? '-' : formatElapsedLabel(Math.max(0, nowMs - startedAtMs))
  );
  const remainingSteps = $derived(
    totalSteps && latestStep !== null ? Math.max(0, Math.ceil(totalSteps - latestStep)) : null
  );
  const progressPercent = $derived(
    totalSteps && latestStep !== null ? Math.min(100, Math.max(0, (latestStep / totalSteps) * 100)) : null
  );
  const trainingEta = $derived(estimateTrainingEta(trainSeries, totalSteps, nowMs));
  const uploadedCheckpointStepSet = $derived(new Set(uploadedCheckpointSteps));
  const checkpointMarkers = $derived.by<CheckpointMarker[]>(() => {
    if (!saveCheckpoint || !saveFreq || !totalSteps || saveFreq <= 0 || totalSteps <= 0) return [];
    const markers: CheckpointMarker[] = [];
    for (let step = saveFreq; step <= totalSteps; step += saveFreq) {
      let status: CheckpointMarkerStatus = 'pending';
      if (latestStep !== null && latestStep >= step) {
        status = 'saved';
      }
      if (uploadedCheckpointStepSet.has(step)) {
        status = 'uploaded';
      }
      if (activeCheckpointUploadStep === step) {
        status = 'uploading';
      }
      markers.push({ step, status });
    }
    return markers;
  });
  const chart = $derived(buildLossChartModel(trainSeries, valSeries, totalSteps, checkpointMarkers));
  const plotLeft = LOSS_CHART_PADDING.left;
  const plotRight = LOSS_CHART_WIDTH - LOSS_CHART_PADDING.right;
  const plotTop = LOSS_CHART_PADDING.top;
  const plotBottom = LOSS_CHART_HEIGHT - LOSS_CHART_PADDING.bottom;
  const previewPadding = 4;
  const previewViewBoxX = $derived(plotLeft - previewPadding);
  const previewViewBoxY = $derived(plotTop - previewPadding);
  const previewViewBoxWidth = $derived(plotRight - plotLeft + previewPadding * 2);
  const previewViewBoxHeight = $derived(plotBottom - plotTop + previewPadding * 2);
  const checkpointMarkerClass = (status: CheckpointMarkerStatus) => {
    if (status === 'uploaded') return 'stroke-emerald-500';
    if (status === 'uploading') return 'stroke-sky-500';
    if (status === 'saved') return 'stroke-orange-400';
    return 'stroke-slate-300';
  };
</script>

<div class="w-[440px] text-left">
  <div class="flex items-center justify-between gap-3">
    <p class="text-sm font-semibold text-slate-900">loss推移</p>
    <p class="text-xs text-slate-500">
      step {formatStepValue(latestStep)} / {formatStepValue(totalSteps)}
    </p>
  </div>

  {#if error}
    <p class="mt-3 text-sm text-rose-600">{error}</p>
  {:else if loading && !chart.hasData}
    <div class="mt-3 h-36 animate-pulse rounded-lg bg-slate-100"></div>
  {:else if chart.hasData}
    <svg
      class="mt-3 h-36 w-full select-none overflow-hidden"
      viewBox={`${previewViewBoxX} ${previewViewBoxY} ${previewViewBoxWidth} ${previewViewBoxHeight}`}
      role="img"
      aria-label="loss推移"
    >
      <rect
        x={plotLeft}
        y={plotTop}
        width={plotRight - plotLeft}
        height={plotBottom - plotTop}
        rx="8"
        class="fill-white"
      />
      {#each chart.yTicks as tick}
        {@const y = plotBottom - (tick / chart.yMax) * (plotBottom - plotTop)}
        <line x1={plotLeft} y1={y} x2={plotRight} y2={y} class="stroke-slate-200" />
      {/each}
      <line x1={plotLeft} y1={plotBottom} x2={plotRight} y2={plotBottom} class="stroke-slate-300" />
      <line x1={plotLeft} y1={plotTop} x2={plotLeft} y2={plotBottom} class="stroke-slate-300" />
      {#each chart.checkpointMarkers as marker}
        <line
          x1={marker.x}
          y1={plotTop}
          x2={marker.x}
          y2={plotBottom}
          class={`${checkpointMarkerClass(marker.status)} opacity-80`}
          stroke-width="2"
          stroke-dasharray="8 8"
        />
      {/each}
      {#if chart.trainPath}
        <path d={chart.trainPath} class="fill-none stroke-brand" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
      {/if}
      {#if chart.valPath}
        <path d={chart.valPath} class="fill-none stroke-orange-400" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
      {/if}
    </svg>
    <div class="mt-3">
      <div class="flex items-center justify-between gap-3 text-xs font-semibold text-slate-500">
        <span>進捗 {progressPercent === null ? '-' : `${progressPercent.toFixed(1)}%`}</span>
        <span>残り {remainingSteps === null ? '-' : `${formatStepValue(remainingSteps)} step`}</span>
      </div>
      <div class="mt-2 h-2 overflow-hidden rounded-full bg-slate-200/80">
        <div class="h-full rounded-full bg-brand transition-all" style={`width: ${progressPercent ?? 0}%`}></div>
      </div>
    </div>

    <div class="mt-4 grid grid-cols-3 gap-2 text-xs">
      <div class="rounded-md border border-slate-200/80 bg-slate-50 px-3 py-2">
        <p class="font-semibold text-slate-500">最終更新</p>
        <p class="mt-1 font-semibold text-slate-900">{lastUpdatedLabel}</p>
      </div>
      <div class="rounded-md border border-slate-200/80 bg-slate-50 px-3 py-2">
        <p class="font-semibold text-slate-500">実行時間</p>
        <p class="mt-1 font-semibold text-slate-900">{runtimeLabel}</p>
      </div>
      <div class="rounded-md border border-slate-200/80 bg-slate-50 px-3 py-2">
        <p class="font-semibold text-slate-500">残り時間（推定）</p>
        <p class="mt-1 font-semibold text-slate-900">
          {trainingEta ? formatDurationMs(trainingEta.estimatedRemainingMs) : '-'}
        </p>
      </div>
    </div>

    <div class="mt-4 flex items-center justify-between gap-3 text-xs text-slate-500">
      <span class="flex items-center gap-1.5">
        <span class="h-2 w-2 rounded-full bg-brand"></span>
        train {formatLossValue(latestTrainPoint?.loss)}
      </span>
      <span class="flex items-center gap-1.5">
        <span class="h-2 w-2 rounded-full bg-orange-400"></span>
        val {formatLossValue(latestValPoint?.loss)}
      </span>
    </div>
  {:else}
    <div class="mt-3 flex h-36 items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">
      まだデータがありません。
    </div>
  {/if}
</div>

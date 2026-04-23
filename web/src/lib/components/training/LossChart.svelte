<script lang="ts">
  import {
    buildLossChartModel,
    formatLossValue,
    formatStepValue,
    getLossChartHover,
    LOSS_CHART_HEIGHT,
    LOSS_CHART_PADDING,
    LOSS_CHART_WIDTH,
    type CheckpointMarker,
    type LossChartHover,
    type LossMetricPoint
  } from '$lib/training/lossChart';

  let {
    trainSeries = [],
    valSeries = [],
    totalSteps = null,
    checkpointMarkers = []
  }: {
    trainSeries?: LossMetricPoint[];
    valSeries?: LossMetricPoint[];
    totalSteps?: number | null;
    checkpointMarkers?: CheckpointMarker[];
  } = $props();

  let hover: LossChartHover | null = $state(null);

  const chart = $derived(buildLossChartModel(trainSeries, valSeries, totalSteps, checkpointMarkers));
  const plotLeft = LOSS_CHART_PADDING.left;
  const plotRight = LOSS_CHART_WIDTH - LOSS_CHART_PADDING.right;
  const plotTop = LOSS_CHART_PADDING.top;
  const plotBottom = LOSS_CHART_HEIGHT - LOSS_CHART_PADDING.bottom;
  const tooltipX = $derived(
    hover ? Math.min(LOSS_CHART_WIDTH - 170, Math.max(68, hover.x + 12)) : 0
  );
  const tooltipY = $derived(
    hover
      ? Math.max(
          18,
          Math.min(
            LOSS_CHART_HEIGHT - 94,
            (hover.trainPoint?.y ?? hover.valPoint?.y ?? LOSS_CHART_HEIGHT / 2) - 54
          )
        )
      : 0
  );

  const handlePointerMove = (event: PointerEvent) => {
    const target = event.currentTarget;
    if (!(target instanceof SVGSVGElement)) {
      hover = null;
      return;
    }

    const rect = target.getBoundingClientRect();
    const viewBoxX = ((event.clientX - rect.left) / rect.width) * LOSS_CHART_WIDTH;
    hover = getLossChartHover(chart, viewBoxX);
  };

  const clearHover = () => {
    hover = null;
  };
</script>

<div class="relative">
  <svg
    class="h-[340px] w-full select-none overflow-visible"
    viewBox={`0 0 ${LOSS_CHART_WIDTH} ${LOSS_CHART_HEIGHT}`}
    role="img"
    aria-label="loss推移"
    onpointermove={handlePointerMove}
    onpointerleave={clearHover}
  >
    <rect
      x={plotLeft}
      y={plotTop}
      width={plotRight - plotLeft}
      height={plotBottom - plotTop}
      rx="6"
      class="fill-white"
    />

    {#each chart.yTicks as tick}
      {@const y = plotBottom - (tick / chart.yMax) * (plotBottom - plotTop)}
      <line x1={plotLeft} y1={y} x2={plotRight} y2={y} class="stroke-slate-200" />
      <text x={plotLeft - 12} y={y + 4} text-anchor="end" class="fill-slate-500 text-[11px]">
        {formatLossValue(tick)}
      </text>
    {/each}

    {#each chart.xTicks as tick}
      {@const x = plotLeft + (tick / chart.xMax) * (plotRight - plotLeft)}
      <line x1={x} y1={plotTop} x2={x} y2={plotBottom} class="stroke-slate-100" />
      <text x={x} y={LOSS_CHART_HEIGHT - 14} text-anchor="middle" class="fill-slate-500 text-[11px]">
        {formatStepValue(tick)}
      </text>
    {/each}

    <line x1={plotLeft} y1={plotBottom} x2={plotRight} y2={plotBottom} class="stroke-slate-300" />
    <line x1={plotLeft} y1={plotTop} x2={plotLeft} y2={plotBottom} class="stroke-slate-300" />
    <text x={plotRight} y={LOSS_CHART_HEIGHT - 2} text-anchor="end" class="fill-slate-500 text-[11px]">
      step
    </text>
    <text x={plotLeft - 28} y={plotTop - 14} class="fill-slate-500 text-[11px]">
      loss
    </text>

    {#each chart.checkpointMarkers as marker}
      <line
        x1={marker.x}
        y1={plotTop}
        x2={marker.x}
        y2={plotBottom}
        class={`${
          marker.status === 'uploaded'
            ? 'stroke-emerald-500'
            : marker.status === 'uploading'
              ? 'stroke-sky-500'
              : marker.status === 'saved'
                ? 'stroke-orange-400'
                : 'stroke-slate-300'
        }`}
        stroke-width="2"
        stroke-dasharray="5 6"
        stroke-linecap="round"
      />
    {/each}

    {#if chart.trainPath}
      <path d={chart.trainPath} class="fill-none stroke-brand" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
      {#each chart.trainPoints as point}
        <circle cx={point.x} cy={point.y} r="2.5" class="fill-brand" />
      {/each}
    {/if}

    {#if chart.valPath}
      <path d={chart.valPath} class="fill-none stroke-orange-400" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
      {#each chart.valPoints as point}
        <circle cx={point.x} cy={point.y} r="3" class="fill-orange-400" />
      {/each}
    {/if}

    {#if hover}
      <line x1={hover.x} y1={plotTop} x2={hover.x} y2={plotBottom} class="stroke-slate-500" stroke-dasharray="4 4" />
      {#if hover.trainPoint}
        <circle cx={hover.trainPoint.x} cy={hover.trainPoint.y} r="5" class="fill-white stroke-brand" stroke-width="2" />
      {/if}
      {#if hover.valPoint}
        <circle cx={hover.valPoint.x} cy={hover.valPoint.y} r="5" class="fill-white stroke-orange-400" stroke-width="2" />
      {/if}
      <g transform={`translate(${tooltipX}, ${tooltipY})`}>
        <rect width="154" height="82" rx="8" class="fill-slate-900 opacity-95" />
        <text x="12" y="20" class="fill-white text-[12px] font-semibold">
          step {formatStepValue(hover.step)}
        </text>
        <text x="12" y="43" class="fill-slate-200 text-[12px]">
          train: {formatLossValue(hover.trainPoint?.loss)}
        </text>
        <text x="12" y="64" class="fill-slate-200 text-[12px]">
          val: {formatLossValue(hover.valPoint?.loss)}
        </text>
      </g>
    {/if}
  </svg>

  {#if !chart.hasData}
    <div class="absolute inset-0 flex items-center justify-center text-sm text-slate-500">
      まだデータがありません。
    </div>
  {/if}
</div>

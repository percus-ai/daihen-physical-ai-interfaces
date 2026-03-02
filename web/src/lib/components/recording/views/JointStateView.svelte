<script lang="ts">
  import { getContext } from 'svelte';
  import { AxisX, AxisY, GridY, Line, Plot, RuleX } from 'svelteplot';
  import { api } from '$lib/api/client';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';
  import type { DatasetPlaybackState } from '$lib/recording/datasetPlayback';
  import { VIEWER_RUNTIME, type ViewerRuntimeStore } from '$lib/viewer/runtimeContext';

  type DatasetSeries = {
    names?: string[];
    positions?: number[][];
    timestamps?: number[];
  };

  let {
    topic = '',
    label = '',
    title = 'Joint State',
    maxPoints = 160,
    showVelocity = false,
    renderFps = 60
  }: {
    topic?: string;
    label?: string;
    title?: string;
    maxPoints?: number;
    showVelocity?: boolean;
    renderFps?: number;
  } = $props();

  const runtimeStore = getContext<ViewerRuntimeStore>(VIEWER_RUNTIME);
  const runtime = $derived($runtimeStore);
  const isDataset = $derived(runtime.kind === 'dataset');

  type SeriesPoint = { i: number; value: number };
  type RingSeries = {
    name: string;
    color: string;
    buffer: SeriesPoint[];
    nextWrite: number;
    size: number;
  };
  type JointSeries = { name: string; color: string; data: SeriesPoint[] };
  type PendingSample = {
    names: string[];
    positions: number[];
    velocities: number[];
  };

  const palette = [
    '#5b7cfa',
    '#30d5c8',
    '#f48b3a',
    '#8f6fff',
    '#22c55e',
    '#ef4444',
    '#0ea5e9',
    '#f97316'
  ];

  let jointNames = $state<string[]>([]);
  let posSeries = $state<JointSeries[]>([]);
  let velSeries = $state<JointSeries[]>([]);
  let posRing = $state<RingSeries[]>([]);
  let velRing = $state<RingSeries[]>([]);
  let lastRawPositions = $state<number[]>([]);
  let index = $state(0);
  let status = $state('idle');
  let plotWidth = $state(0);
  let posHeight = $state(0);
  let velHeight = $state(0);
  let unsubscribe: (() => void) | null = null;
  let pendingSample: PendingSample | null = null;
  let animationFrameId: number | null = null;
  let lastRenderAt = 0;
	  let datasetError = $state('');
	  let lastDatasetSignature = $state('');
	  let activeDatasetRequestId = $state(0);
	  let datasetTimestamps = $state<number[]>([]);
	  let datasetTimestampsSorted = $state(true);
	  let datasetSeriesFps = $state<number | null>(null);
	  let playbackState = $state<DatasetPlaybackState>({
	    playing: false,
	    currentTime: 0,
	    duration: 0,
    rate: 1,
    ready: false
  });
  const normalizedRenderFps = $derived(
    Math.min(Math.max(Number(renderFps) || 24, 1), 60)
  );
  const renderIntervalMs = $derived(1000 / normalizedRenderFps);
  const sourceText = $derived(isDataset ? label || topic || 'dataset series' : topic || 'no topic');

  const buildRing = (names: string[]): RingSeries[] =>
    names.map((name, idx) => ({
      name,
      color: palette[idx % palette.length],
      buffer: [],
      nextWrite: 0,
      size: 0
    }));

  const appendToRing = (rings: RingSeries[], values: number[], nextIndex: number) => {
    for (let idx = 0; idx < rings.length; idx += 1) {
      const ring = rings[idx];
      const point = { i: nextIndex, value: values[idx] ?? 0 };
      if (ring.size < maxPoints) {
        ring.buffer.push(point);
        ring.size += 1;
        ring.nextWrite = ring.size % maxPoints;
        continue;
      }
      ring.buffer[ring.nextWrite] = point;
      ring.nextWrite = (ring.nextWrite + 1) % maxPoints;
    }
  };

  const materializeSeries = (rings: RingSeries[]): JointSeries[] =>
    rings.map((ring) => {
      if (ring.size < maxPoints) {
        return { name: ring.name, color: ring.color, data: ring.buffer.slice(0, ring.size) };
      }
      return {
        name: ring.name,
        color: ring.color,
        data: [...ring.buffer.slice(ring.nextWrite), ...ring.buffer.slice(0, ring.nextWrite)]
      };
    });

  const scheduleRender = () => {
    if (typeof window === 'undefined') return;
    if (animationFrameId != null) return;
    animationFrameId = window.requestAnimationFrame((timestamp) => {
      animationFrameId = null;
      if (timestamp - lastRenderAt < renderIntervalMs) {
        scheduleRender();
        return;
      }
      lastRenderAt = timestamp;

      if (!pendingSample) return;
      const sample = pendingSample;
      pendingSample = null;

      const needsReset =
        sample.names.length !== jointNames.length ||
        sample.names.some((name, idx) => jointNames[idx] !== name);

      if (needsReset) {
        jointNames = [...sample.names];
        posRing = buildRing(sample.names);
        velRing = buildRing(sample.names);
        index = 0;
      }

      index += 1;
      appendToRing(posRing, sample.positions, index);
      appendToRing(velRing, sample.velocities, index);
      posSeries = materializeSeries(posRing);
      velSeries = materializeSeries(velRing);
    });
  };

  const resetViewState = () => {
    posSeries = [];
    velSeries = [];
    posRing = [];
    velRing = [];
    jointNames = [];
    index = 0;
    lastRawPositions = [];
    pendingSample = null;
    datasetTimestamps = [];
    datasetTimestampsSorted = true;
  };

  const buildDatasetSeries = (series: DatasetSeries | null) => {
    const positions = Array.isArray(series?.positions) ? series.positions : [];
    if (!positions.length) {
      resetViewState();
      status = 'empty';
      return;
    }

    const axisDim = positions[0]?.length ?? 0;
    if (axisDim <= 0) {
      resetViewState();
      status = 'empty';
      return;
    }

    const names =
      Array.isArray(series?.names) && series.names.length === axisDim
        ? series.names
        : positions[0].map((_, idx) => `joint_${idx + 1}`);
    jointNames = [...names];
    datasetTimestamps = Array.isArray(series?.timestamps) && series.timestamps.length === positions.length
      ? series.timestamps.map((value) => Number(value) || 0)
      : [];
    datasetTimestampsSorted = true;
    for (let idx = 1; idx < datasetTimestamps.length; idx += 1) {
      if (datasetTimestamps[idx] < datasetTimestamps[idx - 1]) {
        datasetTimestampsSorted = false;
        break;
      }
    }

    posSeries = names.map((name, axisIdx) => ({
      name,
      color: palette[axisIdx % palette.length],
      data: positions.map((values, frameIdx) => ({ i: frameIdx + 1, value: values[axisIdx] ?? 0 }))
    }));

    velSeries = names.map((name, axisIdx) => ({
      name,
      color: palette[axisIdx % palette.length],
      data: positions.map((values, frameIdx) => ({
        i: frameIdx + 1,
        value:
          frameIdx === 0
            ? 0
            : (values[axisIdx] ?? 0) - (positions[frameIdx - 1]?.[axisIdx] ?? 0)
      }))
    }));

    status = 'dataset';
  };

	  const findNearestIndex = (values: number[], target: number, isSorted: boolean) => {
	    if (!values.length) return null;
	    if (!Number.isFinite(target)) return 0;

    if (!isSorted) {
      let best = 0;
      let bestDist = Math.abs((values[0] ?? 0) - target);
      for (let idx = 1; idx < values.length; idx += 1) {
        const dist = Math.abs((values[idx] ?? 0) - target);
        if (dist < bestDist) {
          bestDist = dist;
          best = idx;
        }
      }
      return best;
    }

    let lo = 0;
    let hi = values.length - 1;
    if (target <= values[0]) return 0;
    if (target >= values[hi]) return hi;
    while (lo + 1 < hi) {
      const mid = Math.floor((lo + hi) / 2);
      const value = values[mid];
      if (value === target) return mid;
      if (value < target) lo = mid;
      else hi = mid;
    }
	    return target - values[lo] <= values[hi] - target ? lo : hi;
	  };

	  const datasetTimeAxisS = $derived.by(() => {
	    if (!datasetTimestamps.length) return [];
	    const t0 = Number(datasetTimestamps[0] ?? 0);
	    const deltas = datasetTimestamps.map((value) => (Number(value) || 0) - (Number.isFinite(t0) ? t0 : 0));
	    if (!deltas.length) return [];

	    const span = deltas[deltas.length - 1] ?? 0;
	    const fps = datasetSeriesFps ?? null;
	    if (fps && Number.isFinite(fps) && fps > 0 && Number.isFinite(span) && span > 0) {
	      const expected = (deltas.length - 1) / fps;
	      const scales = [1, 1e-3, 1e-6, 1e-9];
	      let bestScale = 1;
	      let bestError = Number.POSITIVE_INFINITY;
	      for (const scale of scales) {
	        const error = Math.abs(span * scale - expected);
	        if (error < bestError) {
	          bestError = error;
	          bestScale = scale;
	        }
	      }
	      return deltas.map((value) => value * bestScale);
	    }
	    return deltas;
	  });

	  const playheadSampleIndex = $derived.by(() => {
	    if (!isDataset) return null;
	    if (runtime.kind !== 'dataset') return null;
	    if (!runtime.playback) return null;
	    if (!playbackState.ready) return null;
	    if (!datasetTimeAxisS.length) return null;
	    const nearest = findNearestIndex(datasetTimeAxisS, playbackState.currentTime, datasetTimestampsSorted);
	    if (nearest == null) return null;
	    return nearest + 1;
	  });
  const playheadData = $derived(
    typeof playheadSampleIndex === 'number' && playheadSampleIndex > 0 ? [{ i: playheadSampleIndex }] : []
  );

	  const loadDatasetSeries = async (
	    signalKey: string,
	    datasetIdValue: string,
	    episode: number,
	    requestId: number
	  ) => {
	    datasetError = '';
	    status = 'loading';
	    resetViewState();
	    datasetSeriesFps = null;
	    try {
	      const payload = await api.storage.datasetViewerSignalSeries(datasetIdValue, episode, signalKey);
	      if (requestId !== activeDatasetRequestId) return;
	      datasetSeriesFps = Number(payload.fps) || null;
	      buildDatasetSeries({
	        names: payload.names,
	        positions: payload.positions,
	        timestamps: payload.timestamps
	      });
    } catch (err) {
      if (requestId !== activeDatasetRequestId) return;
      const message =
        err instanceof Error
          ? err.message
          : typeof err === 'string'
            ? err
            : '系列データの取得に失敗しました。';
      datasetError = message;
      status = 'error';
      resetViewState();
    }
  };

  const handleMessage = (msg: Record<string, unknown>) => {
    const positions = (msg.position as number[] | undefined) ?? [];
    const velocities = (msg.velocity as number[] | undefined) ?? [];
    if (!positions.length) return;

    const names =
      (msg.name as string[] | undefined) ??
      positions.map((_, idx) => `joint_${idx + 1}`);

    const resolvedVelocities =
      velocities.length === positions.length
        ? velocities
        : lastRawPositions.length === positions.length
          ? positions.map((value, idx) => value - (lastRawPositions[idx] ?? 0))
          : positions.map(() => 0);

    lastRawPositions = positions;
    pendingSample = {
      names: [...names],
      positions: [...positions],
      velocities: [...resolvedVelocities]
    };
    scheduleRender();
  };

  const subscribe = () => {
    if (!topic) return;
    const client = getRosbridgeClient();
    unsubscribe?.();
    unsubscribe = client.subscribe(topic, handleMessage, {
      type: 'sensor_msgs/JointState',
      throttle_rate: 60
    });
    status = client.getStatus();
  };

  $effect(() => {
    unsubscribe?.();
    unsubscribe = null;
    if (animationFrameId != null && typeof window !== 'undefined') {
      window.cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }

    if (isDataset) {
      const signalKey = (topic || '').trim();
      const datasetIdValue = runtime.kind === 'dataset' ? (runtime.datasetId || '').trim() : '';
      const episode = runtime.kind === 'dataset' ? runtime.episodeIndex : 0;
      if (!datasetIdValue || !signalKey) {
        resetViewState();
        status = 'idle';
        return;
      }
      if (signalKey.startsWith('/')) {
        // Guard: dataset viewer expects dataset signal keys (e.g. `observation.state`),
        // not ROS topic names like `/follower_arm/joint_states`.
        datasetError = 'データセットのシグナルキーが未選択です。';
        status = 'error';
        resetViewState();
        return;
      }
      const signature = `${datasetIdValue}:${episode}:${signalKey}`;
      if (signature === lastDatasetSignature) return;
      lastDatasetSignature = signature;
      activeDatasetRequestId += 1;
      const requestId = activeDatasetRequestId;
      void loadDatasetSeries(signalKey, datasetIdValue, episode, requestId);
      return;
    }

    if (!topic) {
      resetViewState();
      status = 'idle';
      return;
    }

    resetViewState();
    subscribe();
    return () => {
      unsubscribe?.();
      unsubscribe = null;
      pendingSample = null;
      if (animationFrameId != null && typeof window !== 'undefined') {
        window.cancelAnimationFrame(animationFrameId);
        animationFrameId = null;
      }
    };
  });

  $effect(() => {
    if (!isDataset) return;
    if (runtime.kind !== 'dataset') return;
    if (!runtime.playback) return;
    playbackState = runtime.playback.getState();
    const unsubState = runtime.playback.subscribeState((next) => {
      playbackState = next;
    });
    const unsubTime = runtime.playback.subscribeTime((time) => {
      playbackState = { ...playbackState, currentTime: time };
    }, { maxFps: 5 });

    return () => {
      unsubState?.();
      unsubTime?.();
    };
  });
</script>

<div class="flex h-full min-w-0 flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{sourceText}</span>
  </div>
  <div class="flex min-h-0 flex-1 flex-col rounded-2xl border border-slate-200/60 bg-white/70 p-3">
    {#if posSeries.length}
      <div class="flex flex-wrap gap-2 text-[10px] text-slate-500">
        {#each posSeries as series}
          <span class="flex items-center gap-1">
            <span class="h-2 w-2 rounded-full" style={`background:${series.color}`}></span>
            {series.name}
          </span>
        {/each}
      </div>
      <div class="mt-2 flex min-h-0 flex-1 flex-col gap-3" bind:clientWidth={plotWidth}>
        <div class="flex min-h-0 flex-1 flex-col">
          <div class="text-[10px] uppercase tracking-widest text-slate-400">Position</div>
          <div class="min-h-0 flex-1" bind:clientHeight={posHeight}>
            {#if plotWidth && posHeight}
              <Plot width={plotWidth} height={posHeight} grid>
                <GridY />
                <AxisX tickCount={4} />
                <AxisY tickCount={4} />
                {#each posSeries as series}
                  <Line data={series.data} x="i" y="value" stroke={series.color} strokeWidth={2} />
                {/each}
                {#if playheadData.length}
                  <RuleX data={playheadData} x="i" stroke="#0ea5e9" strokeWidth={2} strokeOpacity={0.9} />
                {/if}
              </Plot>
            {/if}
          </div>
        </div>
        {#if showVelocity}
          <div class="flex min-h-0 flex-1 flex-col">
            <div class="text-[10px] uppercase tracking-widest text-slate-400">Velocity</div>
            <div class="min-h-0 flex-1" bind:clientHeight={velHeight}>
              {#if plotWidth && velHeight}
                <Plot width={plotWidth} height={velHeight} grid>
                  <GridY />
                  <AxisX tickCount={4} />
                  <AxisY tickCount={4} />
                  {#each velSeries as series}
                    <Line
                      data={series.data}
                      x="i"
                      y="value"
                      stroke={series.color}
                      strokeWidth={1.5}
                      strokeOpacity={0.7}
                    />
                  {/each}
                  {#if playheadData.length}
                    <RuleX data={playheadData} x="i" stroke="#0ea5e9" strokeWidth={2} strokeOpacity={0.9} />
                  {/if}
                </Plot>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    {:else}
      <div class="flex h-full min-h-[160px] items-center justify-center text-xs text-slate-400">
        {#if isDataset && status === 'error'}
          {datasetError || '系列データの取得に失敗しました。'} ({status})
        {:else}
          {isDataset ? 'データを読み込み中…' : 'joint_states を待機中…'} ({status})
        {/if}
      </div>
    {/if}
  </div>
</div>

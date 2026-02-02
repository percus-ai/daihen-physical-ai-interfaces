<script lang="ts">
  import { AxisX, AxisY, GridY, Line, Plot } from 'svelteplot';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';

  let {
    topic = '',
    title = 'Joint State',
    maxPoints = 160,
    showVelocity = true
  }: {
    topic?: string;
    title?: string;
    maxPoints?: number;
    showVelocity?: boolean;
  } = $props();

  type SeriesPoint = { i: number; value: number };

  let posSeries = $state<SeriesPoint[]>([]);
  let velSeries = $state<SeriesPoint[]>([]);
  let lastPositions = $state<number[]>([]);
  let index = $state(0);
  let status = $state('idle');
  let unsubscribe: (() => void) | null = null;

  const handleMessage = (msg: Record<string, unknown>) => {
    const positions = (msg.position as number[] | undefined) ?? [];
    const velocities = (msg.velocity as number[] | undefined) ?? [];
    if (!positions.length) return;

    const posMean = positions.reduce((sum, v) => sum + Math.abs(v), 0) / positions.length;
    let velMean = 0;
    if (velocities.length) {
      velMean = velocities.reduce((sum, v) => sum + Math.abs(v), 0) / velocities.length;
    } else if (lastPositions.length === positions.length) {
      velMean =
        positions.reduce((sum, v, idx) => sum + Math.abs(v - (lastPositions[idx] ?? 0)), 0) /
        positions.length;
    }

    index += 1;
    posSeries = [...posSeries, { i: index, value: posMean }].slice(-maxPoints);
    velSeries = [...velSeries, { i: index, value: velMean }].slice(-maxPoints);
    lastPositions = positions;
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
    if (!topic) {
      unsubscribe?.();
      unsubscribe = null;
      posSeries = [];
      velSeries = [];
      index = 0;
      return;
    }
    subscribe();
    return () => {
      unsubscribe?.();
      unsubscribe = null;
    };
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{topic || 'no topic'}</span>
  </div>
  <div class="flex-1 rounded-2xl border border-slate-200/60 bg-white/70 p-3">
    {#if posSeries.length}
      <Plot height={160} grid>
        <GridY />
        <AxisX tickCount={4} />
        <AxisY tickCount={4} />
        <Line data={posSeries} x="i" y="value" stroke="#5b7cfa" strokeWidth={2} />
        {#if showVelocity}
          <Line data={velSeries} x="i" y="value" stroke="#30d5c8" strokeWidth={2} />
        {/if}
      </Plot>
    {:else}
      <div class="flex h-full min-h-[160px] items-center justify-center text-xs text-slate-400">
        joint_states を待機中… ({status})
      </div>
    {/if}
  </div>
</div>

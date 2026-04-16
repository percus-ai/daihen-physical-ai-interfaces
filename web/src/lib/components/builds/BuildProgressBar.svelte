<script lang="ts">
  type Props = {
    currentPercent?: number | null;
    currentStepIndex?: number | null;
    totalSteps?: number | null;
    running?: boolean;
  };

  let {
    currentPercent = 0,
    currentStepIndex = 0,
    totalSteps = 0,
    running = false
  }: Props = $props();

  let displayedPercent = $state(0);

  const clampPercent = (value: number) => Math.max(0, Math.min(100, value));

  const currentValue = $derived(clampPercent(Number(currentPercent ?? 0)));
  const stepCount = $derived(Math.max(0, Number(totalSteps ?? 0)));
  const completedSteps = $derived(Math.max(0, Number(currentStepIndex ?? 0)));

  const animatedCap = $derived.by(() => {
    if (!running || stepCount <= 0) return currentValue;
    const stepWidth = 100 / stepCount;
    const nextBoundary = Math.min(99, (completedSteps + 1) * stepWidth);
    const cap = nextBoundary - stepWidth * 0.15;
    return clampPercent(Math.max(currentValue, cap));
  });

  $effect(() => {
    if (!running) {
      displayedPercent = currentValue;
      return;
    }

    displayedPercent = Math.max(displayedPercent, currentValue);
    const timer = window.setInterval(() => {
      if (displayedPercent >= animatedCap) return;
      const remaining = animatedCap - displayedPercent;
      displayedPercent = clampPercent(displayedPercent + Math.max(0.2, remaining * 0.06));
    }, 160);

    return () => {
      window.clearInterval(timer);
    };
  });
</script>

<div class="h-2 w-full overflow-hidden rounded-full bg-slate-200">
  <div
    class={`h-full rounded-full transition-[width] duration-300 ${running ? 'bg-brand' : 'bg-emerald-500'}`}
    style={`width:${displayedPercent}%`}
  ></div>
</div>

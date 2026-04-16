<script lang="ts">
  import { Button } from 'bits-ui';

  import type { BuildJobSummary } from '$lib/api/client';
  import BuildProgressBar from '$lib/components/builds/BuildProgressBar.svelte';

  type Props = {
    job: BuildJobSummary;
    title?: string;
    description?: string;
    logLines?: string[];
    cancelling?: boolean;
    onCancel?: (jobId: string) => Promise<void>;
  };

  let {
    job,
    title = '',
    description = '',
    logLines = [],
    cancelling = false,
    onCancel
  }: Props = $props();

  const clampPercent = (value: number) => Math.max(0, Math.min(100, value));
  const initialDisplayPercentFor = (currentJob: BuildJobSummary) => {
    const currentValue = clampPercent(Number(currentJob.progress_percent ?? 0));
    const totalSteps = Math.max(0, Number(currentJob.total_steps ?? 0));
    const currentStepIndex = Math.max(0, Number(currentJob.current_step_index ?? 0));
    if (totalSteps <= 0) return currentValue;
    const stepWidth = 100 / totalSteps;
    const nextBoundary = Math.min(99, (currentStepIndex + 1) * stepWidth);
    const cap = nextBoundary - stepWidth * 0.15;
    return clampPercent(Math.max(currentValue, cap));
  };

  let displayedPercent = $state(0);
  let displayedJobId = $state('');

  $effect(() => {
    if (displayedJobId === job.job_id) return;
    displayedJobId = job.job_id;
    displayedPercent = initialDisplayPercentFor(job);
  });

  const kindLabel = $derived(job.kind === 'env' ? '環境構築' : '共有パッケージ');
  const badgeClass = $derived(
    job.kind === 'env'
      ? 'border-sky-200 bg-sky-50 text-sky-700'
      : 'border-violet-200 bg-violet-50 text-violet-700'
  );

  const progressLabel = $derived(`${displayedPercent.toFixed(1)}%`);
  const currentStep = $derived(job.current_step_name?.trim() || '準備中');
  const displayedLogs = $derived(logLines);

  const handleCancel = async () => {
    if (!onCancel || cancelling) return;
    await onCancel(job.job_id);
  };
</script>

<article class="nested-block-pane flex min-w-0 flex-col gap-4 overflow-hidden p-4">
  <div class="flex min-w-0 items-start justify-between gap-3">
    <div class="min-w-0 space-y-2">
      <div class={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${badgeClass}`}>
        {kindLabel}
      </div>
      <div class="min-w-0">
        <h3 class="truncate text-lg font-semibold text-slate-900">{title || job.setting_id}</h3>
        <p class="mt-1 truncate text-sm text-slate-600">{description || job.message || '構築を進めています。'}</p>
      </div>
    </div>

    <Button.Root class="btn-ghost shrink-0" type="button" disabled={cancelling} onclick={handleCancel}>
      {cancelling ? '中止中...' : '中止'}
    </Button.Root>
  </div>

  <div class="space-y-2">
    <div class="flex items-center justify-between text-xs font-semibold text-slate-500">
      <span class="min-w-0 truncate pr-3">{currentStep}</span>
      <span class="shrink-0">{progressLabel}</span>
    </div>
    <BuildProgressBar
      currentPercent={job.progress_percent ?? 0}
      currentStepIndex={job.current_step_index ?? 0}
      totalSteps={job.total_steps ?? 0}
      running={true}
      bind:displayPercent={displayedPercent}
    />
  </div>

  <div class="min-w-0 rounded-2xl border border-slate-200/70 bg-slate-950 p-4 text-slate-100">
    <div class="mb-2 flex items-center justify-between text-[11px] uppercase tracking-[0.18em] text-slate-400">
      <span>直近ログ</span>
      <span class="min-w-0 truncate pl-3">{currentStep}</span>
    </div>

    <div class="mt-4 max-h-40 min-w-0 overflow-x-auto overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/80 p-3 font-mono text-xs leading-6">
      {#if displayedLogs.length === 0}
        <p class="text-slate-400">ログ待機中...</p>
      {:else}
        {#each displayedLogs as line}
          <div class="min-w-0 border-b border-slate-900/80 py-1 last:border-b-0">
            <span class="break-all text-slate-100">{line}</span>
          </div>
        {/each}
      {/if}
    </div>
  </div>
</article>

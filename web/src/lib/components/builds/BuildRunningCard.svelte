<script lang="ts">
  import { Button } from 'bits-ui';

  import type { BuildJobSummary } from '$lib/api/client';
  import BuildProgressBar from '$lib/components/builds/BuildProgressBar.svelte';

  type Props = {
    job: BuildJobSummary;
    logLines?: string[];
    cancelling?: boolean;
    onCancel?: (jobId: string) => Promise<void>;
  };

  let {
    job,
    logLines = [],
    cancelling = false,
    onCancel
  }: Props = $props();

  let displayedPercent = $state(0);
  let displayedJobId = $state('');

  $effect(() => {
    if (displayedJobId === job.job_id) return;
    displayedJobId = job.job_id;
    displayedPercent = Number(job.progress_percent ?? 0);
  });

  const kindLabel = $derived(job.kind === 'env' ? '環境構築' : '共有パッケージ');
  const badgeClass = $derived(
    job.kind === 'env'
      ? 'border-sky-200 bg-sky-50 text-sky-700'
      : 'border-violet-200 bg-violet-50 text-violet-700'
  );

  const progressLabel = $derived(`${displayedPercent.toFixed(1)}%`);
  const currentStep = $derived(job.current_step_name?.trim() || '準備中');
  const displayedLogs = $derived(logLines.slice(-6));

  const handleCancel = async () => {
    if (!onCancel || cancelling) return;
    await onCancel(job.job_id);
  };
</script>

<article class="nested-block-pane flex flex-col gap-4 p-4">
  <div class="flex items-start justify-between gap-3">
    <div class="space-y-2">
      <div class={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${badgeClass}`}>
        {kindLabel}
      </div>
      <div>
        <h3 class="text-lg font-semibold text-slate-900">{job.setting_id}</h3>
        <p class="mt-1 text-sm text-slate-600">{job.message ?? '構築を進めています。'}</p>
      </div>
    </div>

    <Button.Root class="btn-ghost shrink-0" type="button" disabled={cancelling} onclick={handleCancel}>
      {cancelling ? '中止中...' : '中止'}
    </Button.Root>
  </div>

  <div class="space-y-2">
    <div class="flex items-center justify-between text-xs font-semibold text-slate-500">
      <span>{currentStep}</span>
      <span>{progressLabel}</span>
    </div>
    <BuildProgressBar
      currentPercent={job.progress_percent ?? 0}
      currentStepIndex={job.current_step_index ?? 0}
      totalSteps={job.total_steps ?? 0}
      running={true}
      bind:displayPercent={displayedPercent}
    />
  </div>

  <div class="nested-block bg-slate-950 px-3 py-2 text-xs text-slate-100">
    <div class="mb-2 flex items-center justify-between text-[11px] uppercase tracking-[0.18em] text-slate-400">
      <span>直近ログ</span>
      <span>{currentStep}</span>
    </div>

    {#if displayedLogs.length === 0}
      <p class="truncate text-slate-400">ログ待機中...</p>
    {:else}
      <div class="space-y-1 font-mono">
        {#each displayedLogs as line}
          <p class="truncate">{line}</p>
        {/each}
      </div>
    {/if}
  </div>
</article>

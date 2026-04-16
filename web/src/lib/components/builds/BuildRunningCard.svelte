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

  const kindLabel = $derived(job.kind === 'env' ? '環境構築' : '共有パッケージ');
  const badgeClass = $derived(
    job.kind === 'env'
      ? 'border-sky-200 bg-sky-50 text-sky-700'
      : 'border-violet-200 bg-violet-50 text-violet-700'
  );

  const progressLabel = $derived(`${Number(job.progress_percent ?? 0).toFixed(1)}%`);
  const currentStep = $derived(job.current_step_name?.trim() || '準備中');
  const displayedLogs = $derived(logLines.slice(-6));
  const startedAtLabel = $derived(job.started_at ? new Date(job.started_at).toLocaleString('ja-JP') : '開始時刻未記録');

  const handleCancel = async () => {
    if (!onCancel || cancelling) return;
    await onCancel(job.job_id);
  };
</script>

<article class="relative overflow-hidden rounded-[1.75rem] border border-slate-200/80 bg-[linear-gradient(145deg,rgba(255,251,235,0.92),rgba(255,255,255,0.98))] p-5 shadow-sm">
  <div class="absolute inset-x-0 top-0 h-1.5 bg-[linear-gradient(90deg,#f59e0b,#f97316)]"></div>

  <div class="flex flex-col gap-5">
    <div class="flex items-start justify-between gap-3">
      <div class="space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <div class={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${badgeClass}`}>
            {kindLabel}
          </div>
          <div class="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
            実行中
          </div>
        </div>
        <div>
          <h3 class="text-xl font-semibold text-slate-900">{job.setting_id}</h3>
          <p class="mt-1 text-sm leading-6 text-slate-600">{job.message ?? '構築を進めています。'}</p>
        </div>
      </div>

      <Button.Root class="btn-ghost shrink-0 bg-white/80" type="button" disabled={cancelling} onclick={handleCancel}>
      {cancelling ? '中止中...' : '中止'}
      </Button.Root>
    </div>

    <div class="grid gap-3 md:grid-cols-3">
      <div class="nested-block-pane p-3">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">現在ステップ</p>
        <p class="mt-2 text-sm font-semibold text-slate-700">{currentStep}</p>
      </div>
      <div class="nested-block-pane p-3">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">build id</p>
        <p class="mt-2 text-sm font-semibold text-slate-700">{job.build_id}</p>
      </div>
      <div class="nested-block-pane p-3">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">開始</p>
        <p class="mt-2 text-sm font-semibold text-slate-700">{startedAtLabel}</p>
      </div>
    </div>

    <div class="rounded-2xl border border-amber-200/80 bg-white/80 p-4 shadow-sm">
      <div class="flex items-center justify-between text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
        <span>進捗</span>
        <span>{progressLabel}</span>
      </div>
      <div class="mt-3">
        <BuildProgressBar
          currentPercent={job.progress_percent ?? 0}
          currentStepIndex={job.current_step_index ?? 0}
          totalSteps={job.total_steps ?? 0}
          running={true}
        />
      </div>
    </div>

    <div class="nested-block bg-slate-950 px-3 py-3 text-xs text-slate-100">
      <div class="mb-2 flex items-center justify-between text-[11px] uppercase tracking-[0.18em] text-slate-400">
        <span>直近ログ</span>
        <span>{currentStep}</span>
      </div>

      {#if displayedLogs.length === 0}
        <p class="truncate text-slate-400">ログ待機中...</p>
      {:else}
        <div class="space-y-1.5 font-mono">
          {#each displayedLogs as line}
            <p class="truncate rounded bg-white/5 px-2 py-1">{line}</p>
          {/each}
        </div>
      {/if}
    </div>
  </div>
</article>

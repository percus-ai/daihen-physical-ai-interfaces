<script lang="ts">
  import { Button } from 'bits-ui';

  import type { BuildSettingSummary } from '$lib/api/client';
  import BuildProgressBar from '$lib/components/builds/BuildProgressBar.svelte';

  type Props = {
    title: string;
    description: string;
    items: BuildSettingSummary[];
    actionPending?: Record<string, boolean>;
    onRun?: (item: BuildSettingSummary) => Promise<void>;
    onCancel?: (item: BuildSettingSummary) => Promise<void>;
    onDelete?: (item: BuildSettingSummary) => Promise<void>;
    onCreateErrorReport?: (item: BuildSettingSummary) => Promise<void>;
  };

  let {
    title,
    description,
    items,
    actionPending = {},
    onRun,
    onCancel,
    onDelete,
    onCreateErrorReport
  }: Props = $props();

  const stateLabel = (state: BuildSettingSummary['state']) => {
    if (state === 'unbuilt') return '未構築';
    if (state === 'building') return '構築中';
    if (state === 'success') return '成功';
    return '失敗';
  };

  const stateClass = (state: BuildSettingSummary['state']) => {
    if (state === 'success') return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    if (state === 'failed') return 'border-rose-200 bg-rose-50 text-rose-700';
    if (state === 'building') return 'border-amber-200 bg-amber-50 text-amber-700';
    return 'border-slate-200 bg-slate-100 text-slate-600';
  };

  const handleRun = async (item: BuildSettingSummary) => {
    if (!onRun || actionPending[item.setting_id]) return;
    await onRun(item);
  };

  const handleCancel = async (item: BuildSettingSummary) => {
    if (!onCancel || actionPending[item.setting_id]) return;
    await onCancel(item);
  };

  const handleDelete = async (item: BuildSettingSummary) => {
    if (!onDelete || actionPending[item.setting_id]) return;
    await onDelete(item);
  };

  const handleCreateErrorReport = async (item: BuildSettingSummary) => {
    if (!onCreateErrorReport || actionPending[item.setting_id]) return;
    await onCreateErrorReport(item);
  };

  const primaryLabel = (item: BuildSettingSummary) => {
    if (item.state === 'building') return '中止';
    if (item.state === 'success') return '削除';
    if (item.state === 'failed') return '削除';
    return '構築';
  };

  const primaryClass = (item: BuildSettingSummary) => {
    if (item.state === 'success' || item.state === 'failed') {
      return 'btn-ghost border-rose-200/70 text-rose-600 hover:border-rose-300/80 hover:text-rose-700';
    }
    return 'btn-primary';
  };

  const secondaryLabel = (item: BuildSettingSummary) => {
    if (item.state === 'failed') return '報告';
    return '';
  };

  const titleText = (item: BuildSettingSummary) => {
    if (item.kind === 'shared') return item.package ?? item.display_name;
    return item.display_name;
  };

  const subtitleText = (item: BuildSettingSummary) => {
    if (item.kind === 'shared') {
      return item.description ?? item.variant ?? item.setting_id;
    }
    return item.description ?? item.env_name ?? item.setting_id;
  };

  const detailText = (item: BuildSettingSummary) => {
    if (item.state === 'building') return item.current_step_name ?? '構築中';
    if (item.state === 'failed') return item.latest_error_summary ?? '構築に失敗しました。';
    if (item.latest_build_id) return `最新 build: ${item.latest_build_id}`;
    return 'まだ構築されていません。';
  };

  const handleSecondary = async (item: BuildSettingSummary) => {
    if (item.state === 'failed' && item.actions.create_error_report) {
      await handleCreateErrorReport(item);
    }
  };

  const handlePrimary = async (item: BuildSettingSummary) => {
    if (item.state === 'building') {
      await handleCancel(item);
      return;
    }
    if (item.state === 'success' || item.state === 'failed') {
      await handleDelete(item);
      return;
    }
    await handleRun(item);
  };
</script>

<section class="card p-6">
  <div class="nested-block-header">
    <div>
      <p class="section-title">{title}</p>
      <p class="mt-1 text-sm text-slate-600">{description}</p>
    </div>
  </div>

  <div class="mt-4 space-y-3">
    {#each items as item}
      <article class={`rounded-2xl border px-4 py-4 ${item.state === 'failed' ? 'border-rose-200 bg-rose-50/40' : 'border-slate-200 bg-white'}`}>
        <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_10rem] xl:items-stretch">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-base font-semibold text-slate-900">{titleText(item)}</h3>
              <span class={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${stateClass(item.state)}`}>
                {stateLabel(item.state)}
              </span>
            </div>

            <p class="mt-1 text-xs text-slate-500">{subtitleText(item)}</p>

            <div class="mt-3 min-w-0 space-y-2">
              <p class={`text-sm ${item.state === 'failed' ? 'font-medium text-rose-700' : 'text-slate-600'}`}>
                {detailText(item)}
              </p>
              {#if item.state === 'building'}
                <BuildProgressBar
                  currentPercent={item.progress_percent ?? 0}
                  currentStepIndex={item.current_step_index ?? 0}
                  totalSteps={item.total_steps ?? 0}
                  running={true}
                />
              {/if}
            </div>
          </div>

          <div class="flex min-w-24 flex-col items-stretch xl:justify-self-end">
            {#if secondaryLabel(item)}
              <Button.Root class="btn-ghost w-full" type="button" disabled={actionPending[item.setting_id]} onclick={() => handleSecondary(item)}>
                {actionPending[item.setting_id] ? '発行中...' : secondaryLabel(item)}
              </Button.Root>
            {/if}

            <Button.Root class={`${primaryClass(item)} mt-auto w-full`} type="button" disabled={actionPending[item.setting_id]} onclick={() => handlePrimary(item)}>
              {actionPending[item.setting_id]
                ? item.state === 'building'
                  ? '中止中...'
                  : item.state === 'success'
                    ? '削除中...'
                    : '処理中...'
                : primaryLabel(item)}
            </Button.Root>
          </div>
        </div>
      </article>
    {/each}
  </div>
</section>

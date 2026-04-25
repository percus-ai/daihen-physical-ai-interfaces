<script lang="ts">
  import { Button } from 'bits-ui';

  import type { BuildSettingSummary } from '$lib/api/client';
  import BuildProgressBar from '$lib/components/builds/BuildProgressBar.svelte';

  type Props = {
    title: string;
    description: string;
    currentPlatform?: string;
    currentSm?: string;
    items: BuildSettingSummary[];
    actionPending?: Record<string, boolean>;
    onRun?: (item: BuildSettingSummary) => Promise<void>;
    onCancel?: (item: BuildSettingSummary) => Promise<void>;
    onDelete?: (item: BuildSettingSummary) => Promise<void>;
    onCreateErrorReport?: (item: BuildSettingSummary) => Promise<void>;
  };

  type PrimaryAction = 'run' | 'cancel' | 'delete';

  let {
    title,
    description,
    currentPlatform = '',
    currentSm = '',
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
    if (!onRun || !item.actions.run || actionPending[item.setting_id]) return;
    await onRun(item);
  };

  const handleCancel = async (item: BuildSettingSummary) => {
    if (!onCancel || !item.actions.cancel || actionPending[item.setting_id]) return;
    await onCancel(item);
  };

  const handleDelete = async (item: BuildSettingSummary) => {
    if (!onDelete || !item.actions.delete || actionPending[item.setting_id]) return;
    await onDelete(item);
  };

  const handleCreateErrorReport = async (item: BuildSettingSummary) => {
    if (!onCreateErrorReport || !item.actions.create_error_report || actionPending[item.setting_id]) return;
    await onCreateErrorReport(item);
  };

  const primaryAction = (item: BuildSettingSummary): PrimaryAction | null => {
    if (item.state === 'building' && item.actions.cancel) return 'cancel';
    if ((item.state === 'success' || item.state === 'failed') && item.actions.delete) return 'delete';
    if (item.actions.run) return 'run';
    return null;
  };

  const primaryLabel = (action: PrimaryAction) => {
    if (action === 'cancel') return '中止';
    if (action === 'delete') return '削除';
    return '構築';
  };

  const primaryPendingLabel = (action: PrimaryAction) => {
    if (action === 'cancel') return '中止中...';
    if (action === 'delete') return '削除中...';
    return '処理中...';
  };

  const primaryClass = (action: PrimaryAction) => {
    if (action === 'delete') {
      return 'btn-ghost border-rose-200/70 text-rose-600 hover:border-rose-300/80 hover:text-rose-700';
    }
    return 'btn-primary';
  };

  const primaryButtonClass = (item: BuildSettingSummary) => {
    const action = primaryAction(item);
    return action ? primaryClass(action) : '';
  };

  const primaryButtonLabel = (item: BuildSettingSummary) => {
    const action = primaryAction(item);
    return action ? primaryLabel(action) : '';
  };

  const primaryButtonPendingLabel = (item: BuildSettingSummary) => {
    const action = primaryAction(item);
    return action ? primaryPendingLabel(action) : '';
  };

  const secondaryLabel = (item: BuildSettingSummary) => {
    if (item.state === 'failed' && item.actions.create_error_report) return '報告';
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

  const environmentSupported = (item: BuildSettingSummary) => {
    if (item.platform_supported === false) return false;
    if (item.sm_supported === false) return false;
    if (item.platform_supported === true || item.sm_supported === true) return true;
    return null;
  };

  const environmentBadgeClass = (item: BuildSettingSummary) => {
    const supported = environmentSupported(item);
    if (supported === true) return 'border-sky-200 bg-sky-50 text-sky-700';
    if (supported === false) return 'border-slate-200 bg-slate-100 text-slate-500';
    return 'border-slate-200 bg-slate-100 text-slate-500';
  };

  const environmentBadgeText = (item: BuildSettingSummary) => {
    if (!currentPlatform && !currentSm) return '';
    const supported = environmentSupported(item);
    if (supported === true) return 'この環境に対応';
    if (supported === false) return 'この環境に非対応';
    return 'この環境は未判定';
  };

  const handleSecondary = async (item: BuildSettingSummary) => {
    if (secondaryLabel(item)) {
      await handleCreateErrorReport(item);
    }
  };

  const handlePrimary = async (item: BuildSettingSummary) => {
    const action = primaryAction(item);
    if (action === 'cancel') {
      await handleCancel(item);
      return;
    }
    if (action === 'delete') {
      await handleDelete(item);
      return;
    }
    if (action === 'run') {
      await handleRun(item);
    }
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
      <article class={`overflow-hidden rounded-2xl border px-4 py-4 ${item.state === 'failed' ? 'border-rose-200 bg-rose-50/40' : 'border-slate-200 bg-white'}`}>
        <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_10rem] xl:items-stretch">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-base font-semibold text-slate-900">{titleText(item)}</h3>
              <span class={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${stateClass(item.state)}`}>
                {stateLabel(item.state)}
              </span>
              {#if currentPlatform || currentSm}
                <span class={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold ${environmentBadgeClass(item)}`}>
                  {environmentBadgeText(item)}
                </span>
              {/if}
            </div>

            <p class="mt-1 truncate text-xs text-slate-500">{subtitleText(item)}</p>

            <div class="mt-3 min-w-0 space-y-2">
              <p class={`min-w-0 truncate text-sm ${item.state === 'failed' ? 'font-medium text-rose-700' : 'text-slate-600'}`}>
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

            {#if primaryAction(item)}
              <Button.Root class={`${primaryButtonClass(item)} mt-auto w-full`} type="button" disabled={actionPending[item.setting_id]} onclick={() => handlePrimary(item)}>
                {actionPending[item.setting_id] ? primaryButtonPendingLabel(item) : primaryButtonLabel(item)}
              </Button.Root>
            {/if}
          </div>
        </div>
      </article>
    {/each}
  </div>
</section>

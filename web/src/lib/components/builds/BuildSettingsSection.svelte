<script lang="ts">
  import { Button } from 'bits-ui';

  import type { BuildSettingSummary } from '$lib/api/client';
  import BuildProgressBar from '$lib/components/builds/BuildProgressBar.svelte';
  import { formatDate } from '$lib/format';

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

  const stateTone = (state: BuildSettingSummary['state']) => {
    if (state === 'success') {
      return {
        badge: 'border-emerald-200 bg-emerald-50 text-emerald-700',
        card: 'border-emerald-200/80 bg-[linear-gradient(140deg,rgba(236,253,245,0.96),rgba(255,255,255,0.98))]',
        accent: 'bg-emerald-500'
      };
    }
    if (state === 'failed') {
      return {
        badge: 'border-rose-200 bg-rose-50 text-rose-700',
        card: 'border-rose-200/80 bg-[linear-gradient(140deg,rgba(255,241,242,0.98),rgba(255,255,255,0.98))]',
        accent: 'bg-rose-500'
      };
    }
    if (state === 'building') {
      return {
        badge: 'border-amber-200 bg-amber-50 text-amber-700',
        card: 'border-amber-200/80 bg-[linear-gradient(140deg,rgba(255,251,235,0.98),rgba(255,255,255,0.98))]',
        accent: 'bg-amber-500'
      };
    }
    return {
      badge: 'border-slate-200 bg-slate-100 text-slate-600',
      card: 'border-slate-200/80 bg-[linear-gradient(140deg,rgba(248,250,252,0.98),rgba(255,255,255,0.98))]',
      accent: 'bg-slate-400'
    };
  };

  const settingKindLabel = (item: BuildSettingSummary) => (item.kind === 'env' ? '環境構築' : '共有パッケージ');

  const secondaryLabel = (item: BuildSettingSummary) => {
    if (item.kind === 'env') {
      return item.env_name?.trim() || item.setting_id;
    }
    return item.variant?.trim() || item.setting_id;
  };

  const latestTimeLabel = (item: BuildSettingSummary) => {
    if (item.latest_finished_at) return `更新 ${formatDate(item.latest_finished_at)}`;
    if (item.latest_started_at) return `開始 ${formatDate(item.latest_started_at)}`;
    return 'まだ履歴がありません';
  };

  const buildIdLabel = (item: BuildSettingSummary) => item.current_build_id ?? item.latest_build_id ?? '未作成';

  const summaryText = (item: BuildSettingSummary) => {
    if (item.state === 'building') return item.current_step_name?.trim() || '構築を進めています。';
    if (item.state === 'failed') return item.latest_error_summary?.trim() || '構築に失敗しました。';
    if (item.state === 'success') return 'この設定の build は利用可能です。';
    return 'まだ構築されていません。';
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
</script>

<section class="card p-6">
  <div class="nested-block-header">
    <div>
      <p class="section-title">{title}</p>
      <p class="mt-2 max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
    </div>
    <div class="chip shrink-0">{items.length} 件</div>
  </div>

  <div class="grid gap-4 xl:grid-cols-2">
    {#each items as item}
      {@const tone = stateTone(item.state)}
      <article class={`relative overflow-hidden rounded-2xl border p-5 shadow-sm ${tone.card}`}>
        <div class={`absolute inset-x-0 top-0 h-1.5 ${tone.accent}`}></div>

        <div class="flex flex-col gap-4">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="space-y-2">
              <div class="flex flex-wrap items-center gap-2">
                <span class="rounded-full border border-slate-200/80 bg-white/80 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  {settingKindLabel(item)}
                </span>
                <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${tone.badge}`}>
                  {stateLabel(item.state)}
                </span>
                {#if item.selected}
                  <span class="rounded-full border border-brand/30 bg-brand/10 px-2.5 py-1 text-[11px] font-semibold text-brand-ink">
                    選択中
                  </span>
                {/if}
              </div>

              <div>
                <h3 class="text-xl font-semibold text-slate-900">{item.display_name}</h3>
                <p class="mt-1 text-sm font-medium text-slate-500">{secondaryLabel(item)}</p>
              </div>
            </div>

            <div class="rounded-2xl border border-white/70 bg-white/75 px-3 py-2 text-right shadow-sm">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">build id</p>
              <p class="mt-1 text-sm font-semibold text-slate-700">{buildIdLabel(item)}</p>
            </div>
          </div>

          <div class="grid gap-3 md:grid-cols-3">
            <div class="nested-block-pane p-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">設定ID</p>
              <p class="mt-2 break-all text-sm font-medium text-slate-700">{item.setting_id}</p>
            </div>
            <div class="nested-block-pane p-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">更新</p>
              <p class="mt-2 text-sm font-medium text-slate-700">{latestTimeLabel(item)}</p>
            </div>
            <div class="nested-block-pane p-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">概要</p>
              <p class="mt-2 text-sm font-medium text-slate-700">{summaryText(item)}</p>
            </div>
          </div>

          {#if item.state === 'building'}
            <div class="rounded-2xl border border-amber-200/80 bg-white/80 p-4 shadow-sm">
              <div class="flex items-center justify-between gap-3 text-sm font-semibold text-slate-600">
                <span>{item.current_step_name ?? '構築中'}</span>
                <span>{Number(item.progress_percent ?? 0).toFixed(1)}%</span>
              </div>
              <div class="mt-3">
                <BuildProgressBar
                  currentPercent={item.progress_percent ?? 0}
                  currentStepIndex={item.current_step_index ?? 0}
                  totalSteps={item.total_steps ?? 0}
                  running={true}
                />
              </div>
            </div>
          {:else if item.state === 'failed'}
            <div class="rounded-2xl border border-rose-200/80 bg-white/80 p-4 shadow-sm">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-rose-400">Failure</p>
              <p class="mt-2 text-sm font-medium leading-6 text-rose-700">
                {item.latest_error_summary ?? '構築に失敗しました。ログとレポートで原因を確認してください。'}
              </p>
            </div>
          {:else if item.state === 'success'}
            <div class="rounded-2xl border border-emerald-200/80 bg-white/80 p-4 shadow-sm">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-500">Ready</p>
              <p class="mt-2 text-sm font-medium leading-6 text-emerald-700">
                最新 build は利用可能です。必要なら再構築または明示削除を行えます。
              </p>
            </div>
          {:else}
            <div class="rounded-2xl border border-slate-200/80 bg-white/80 p-4 shadow-sm">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Pending</p>
              <p class="mt-2 text-sm font-medium leading-6 text-slate-600">
                まだ build 実体はありません。構築を開始するとここに状態が反映されます。
              </p>
            </div>
          {/if}

          <div class="flex flex-wrap gap-2 border-t border-white/70 pt-1">
            {#if item.state === 'building'}
              <Button.Root class="btn-ghost" type="button" disabled={true}>構築中</Button.Root>
              <Button.Root class="btn-primary" type="button" disabled={actionPending[item.setting_id]} onclick={() => handleCancel(item)}>
                {actionPending[item.setting_id] ? '中止中...' : '中止'}
              </Button.Root>
            {:else}
              <Button.Root class="btn-primary" type="button" disabled={actionPending[item.setting_id]} onclick={() => handleRun(item)}>
                {item.state === 'success' ? '再構築' : '構築'}
              </Button.Root>
              {#if item.actions.create_error_report}
                <Button.Root class="btn-ghost" type="button" disabled={actionPending[item.setting_id]} onclick={() => handleCreateErrorReport(item)}>
                  {actionPending[item.setting_id] ? '作成中...' : 'レポート作成'}
                </Button.Root>
              {/if}
              {#if item.actions.delete}
                <Button.Root class="btn-ghost" type="button" disabled={actionPending[item.setting_id]} onclick={() => handleDelete(item)}>
                  {actionPending[item.setting_id] ? '削除中...' : '削除'}
                </Button.Root>
              {/if}
            {/if}
          </div>
        </div>
      </article>
    {/each}
  </div>
</section>

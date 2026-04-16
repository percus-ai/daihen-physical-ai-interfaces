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
</script>

<section class="card p-6">
  <div class="nested-block-header">
    <div>
      <p class="section-title">{title}</p>
      <p class="mt-2 text-sm text-slate-600">{description}</p>
    </div>
  </div>

  <div class="overflow-x-auto">
    <table class="min-w-full border-separate border-spacing-y-3">
      <thead>
        <tr class="text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
          <th class="px-3">設定</th>
          <th class="px-3">状態</th>
          <th class="px-3">詳細</th>
          <th class="px-3">操作</th>
        </tr>
      </thead>
      <tbody>
        {#each items as item}
          <tr class="nested-block-pane align-top">
            <td class="px-3 py-4">
              <div class="space-y-1">
                <div class="flex flex-wrap items-center gap-2">
                  <p class="font-semibold text-slate-900">{item.display_name}</p>
                  {#if item.selected}
                    <span class="rounded-full border border-brand/30 bg-brand/10 px-2 py-0.5 text-[11px] font-semibold text-brand-ink">
                      選択中
                    </span>
                  {/if}
                </div>
                <p class="text-xs text-slate-500">{item.setting_id}</p>
              </div>
            </td>

            <td class="px-3 py-4">
              <div class={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold ${stateClass(item.state)}`}>
                {stateLabel(item.state)}
              </div>
            </td>

            <td class="px-3 py-4">
              <div class="space-y-2 text-sm text-slate-600">
                {#if item.state === 'building'}
                  <p>{item.current_step_name ?? '構築中'}</p>
                  <BuildProgressBar
                    currentPercent={item.progress_percent ?? 0}
                    currentStepIndex={item.current_step_index ?? 0}
                    totalSteps={item.total_steps ?? 0}
                    running={true}
                  />
                {:else if item.state === 'failed'}
                  <p>{item.latest_error_summary ?? '構築に失敗しました。'}</p>
                {:else if item.latest_build_id}
                  <p>最新 build: {item.latest_build_id}</p>
                {:else}
                  <p>まだ構築されていません。</p>
                {/if}
              </div>
            </td>

            <td class="px-3 py-4">
              <div class="flex flex-wrap gap-2">
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
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

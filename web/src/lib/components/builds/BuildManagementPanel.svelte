<script lang="ts">
  import toast from 'svelte-french-toast';
  import FunnelSimple from 'phosphor-svelte/lib/FunnelSimple';
  import { DropdownMenu } from 'bits-ui';

  import {
    api,
    type BuildErrorReportResponse,
    type BuildJobSummary,
    type BuildLogEvent,
    type BuildSettingSummary,
  } from '$lib/api/client';
  import BuildErrorReportDialog from '$lib/components/builds/BuildErrorReportDialog.svelte';
  import BuildRunningCard from '$lib/components/builds/BuildRunningCard.svelte';
  import BuildSettingsSection from '$lib/components/builds/BuildSettingsSection.svelte';

  type Props = {
    currentSm?: string;
    envItems?: BuildSettingSummary[];
    sharedItems?: BuildSettingSummary[];
    runningJobs?: BuildJobSummary[];
    loading?: boolean;
    loadError?: string;
    actionPending?: Record<string, boolean>;
    logLinesByJobId?: Record<string, string[]>;
    onRun?: (item: BuildSettingSummary) => Promise<void>;
    onCancelByJobId?: (jobId: string, settingId?: string) => Promise<void>;
    onDelete?: (item: BuildSettingSummary) => Promise<void>;
  };

  let {
    currentSm = '',
    envItems = [],
    sharedItems = [],
    runningJobs = [],
    loading = false,
    loadError = '',
    actionPending = {},
    logLinesByJobId = {},
    onRun,
    onCancelByJobId,
    onDelete
  }: Props = $props();

  let hiddenSettingIds = $state<string[]>([]);

  const allItems = $derived([...envItems, ...sharedItems]);
  const allSettingIds = $derived(allItems.map((item) => item.setting_id));
  const visibleSettingCount = $derived(allItems.length - hiddenSettingIds.length);

  $effect(() => {
    const validIds = new Set(allSettingIds);
    hiddenSettingIds = hiddenSettingIds.filter((settingId) => validIds.has(settingId));
  });

  const envVisibleItems = $derived(envItems.filter((item) => !hiddenSettingIds.includes(item.setting_id)));
  const sharedVisibleItems = $derived(sharedItems.filter((item) => !hiddenSettingIds.includes(item.setting_id)));

  const isVisible = (settingId: string) => !hiddenSettingIds.includes(settingId);
  const toggleVisible = (settingId: string, nextVisible: boolean) => {
    hiddenSettingIds = nextVisible
      ? hiddenSettingIds.filter((value) => value !== settingId)
      : [...hiddenSettingIds, settingId];
  };
  const showAll = () => {
    hiddenSettingIds = [];
  };

  let errorReportDialogOpen = $state(false);
  let latestErrorReport = $state<BuildErrorReportResponse | null>(null);
  let errorReportMessage = $state('');

  const settingInfoById = $derived(
    new Map(
      [...envItems, ...sharedItems].map((item) => [
        item.setting_id,
        {
          title: item.kind === 'shared' ? (item.package ?? item.display_name) : item.display_name,
          description:
            item.kind === 'shared'
              ? (item.description ?? item.variant ?? item.setting_id)
              : (item.description ?? item.env_name ?? item.setting_id)
        }
      ])
    )
  );

  const handleCancel = async (item: BuildSettingSummary) => {
    if (!item.current_job_id || !onCancelByJobId) return;
    await onCancelByJobId(item.current_job_id, item.setting_id);
  };

  const handleCreateErrorReport = async (item: BuildSettingSummary) => {
    const buildId = item.latest_build_id;
    if (!buildId) return;
    errorReportMessage = '';
    latestErrorReport = null;
    try {
      let response: BuildErrorReportResponse;
      if (item.kind === 'env' && item.config_id && item.env_name) {
        response = await api.builds.createEnvErrorReport(item.config_id, item.env_name, buildId);
      } else if (item.kind === 'shared' && item.package && item.variant) {
        response = await api.builds.createSharedErrorReport(item.package, item.variant, buildId);
      } else {
        throw new Error('レポート対象を特定できません。');
      }
      latestErrorReport = response;
      errorReportDialogOpen = true;
      toast.success('エラーレポートを作成しました。');
    } catch (error) {
      errorReportMessage = error instanceof Error ? error.message : 'レポート作成に失敗しました。';
      toast.error(errorReportMessage);
    }
  };

  const handleCopyReportId = async (reportId: string) => {
    await navigator.clipboard.writeText(reportId);
    toast.success('レポートIDをコピーしました。');
  };
</script>

{#if loadError}
  <section class="card p-6">
    <p class="text-sm text-rose-600">{loadError}</p>
  </section>
{:else if loading}
  <section class="card p-6">
    <p class="text-sm text-slate-500">構築状態を読み込み中...</p>
  </section>
{/if}

{#if runningJobs.length > 0}
  <section class="card p-6">
    <div class="nested-block-header">
      <div>
        <p class="section-title">構築中</p>
        <p class="mt-2 text-sm leading-6 text-slate-600">
          実行中の ビルドジョブ を追跡します。
        </p>
      </div>
      <div class="chip whitespace-nowrap">{runningJobs.length} 件 実行中</div>
    </div>

    <div class="space-y-4">
      {#each runningJobs as job}
        <BuildRunningCard
          {job}
          title={settingInfoById.get(job.setting_id)?.title ?? ''}
          description={settingInfoById.get(job.setting_id)?.description ?? ''}
          logLines={logLinesByJobId[job.job_id] ?? []}
          cancelling={Boolean(actionPending[job.setting_id] ?? actionPending[job.job_id])}
          onCancel={(jobId) => onCancelByJobId?.(jobId, job.setting_id)}
        />
      {/each}
    </div>
  </section>
{/if}

{#if allItems.length > 0}
  <div class="flex items-center justify-end gap-3">
    {#if currentSm}
      <span class="chip">現在のSM: {currentSm}</span>
    {/if}
    <DropdownMenu.Root>
      <DropdownMenu.Trigger class="btn-ghost inline-flex items-center gap-2">
        <FunnelSimple size={16} />
        フィルタ
        <span class="text-xs text-slate-500">{visibleSettingCount}/{allItems.length}</span>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          class="z-50 w-[min(92vw,24rem)] rounded-2xl border border-slate-200 bg-white p-3 shadow-xl outline-none"
          sideOffset={8}
          align="end"
        >
          <div class="flex items-center justify-between gap-3 border-b border-slate-200 pb-2">
            <div>
              <p class="text-sm font-semibold text-slate-900">表示フィルタ</p>
              <p class="mt-1 text-xs text-slate-500">表示したい設定だけを選びます。</p>
            </div>
            <button class="text-xs font-semibold text-brand transition hover:text-brand-ink" type="button" onclick={showAll}>
              全件表示
            </button>
          </div>

          <div class="mt-3 space-y-4">
            <section>
              <h4 class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">環境構築</h4>
              <div class="mt-2 space-y-2">
                {#each envItems as item (item.setting_id)}
                  <label class="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2 transition hover:bg-slate-50">
                    <input
                      class="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
                      type="checkbox"
                      checked={isVisible(item.setting_id)}
                      onchange={(event) => toggleVisible(item.setting_id, event.currentTarget.checked)}
                    />
                    <div class="min-w-0 flex-1">
                      <p class="truncate text-sm font-medium text-slate-900">{item.display_name}</p>
                      <p class="truncate text-xs text-slate-500">{item.description ?? item.env_name ?? item.setting_id}</p>
                    </div>
                  </label>
                {/each}
              </div>
            </section>

            <section>
              <h4 class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">共有パッケージ</h4>
              <div class="mt-2 space-y-2">
                {#each sharedItems as item (item.setting_id)}
                  <label class="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2 transition hover:bg-slate-50">
                    <input
                      class="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
                      type="checkbox"
                      checked={isVisible(item.setting_id)}
                      onchange={(event) => toggleVisible(item.setting_id, event.currentTarget.checked)}
                    />
                    <div class="min-w-0 flex-1">
                      <p class="truncate text-sm font-medium text-slate-900">{item.package ?? item.display_name}</p>
                      <p class="truncate text-xs text-slate-500">{item.description ?? item.variant ?? item.setting_id}</p>
                    </div>
                  </label>
                {/each}
              </div>
            </section>
          </div>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  </div>
{/if}

<BuildSettingsSection
  title="環境構築"
  description="PC 設定から選ばれる環境定義と、その最新のビルド結果を一覧します。"
  items={envVisibleItems}
  currentSm={currentSm}
  {actionPending}
  onRun={onRun}
  onCancel={handleCancel}
  onDelete={onDelete}
  onCreateErrorReport={handleCreateErrorReport}
/>

<BuildSettingsSection
  title="共有パッケージ"
  description="共有パッケージ定義ごとの variant を一覧し、個別にビルド結果を一覧します。"
  items={sharedVisibleItems}
  currentSm={currentSm}
  {actionPending}
  onRun={onRun}
  onCancel={handleCancel}
  onDelete={onDelete}
  onCreateErrorReport={handleCreateErrorReport}
/>

<BuildErrorReportDialog
  bind:open={errorReportDialogOpen}
  reportId={latestErrorReport?.report_id ?? ''}
  settingId={latestErrorReport?.setting_id ?? ''}
  errorMessage={errorReportMessage}
  onCopy={handleCopyReportId}
/>

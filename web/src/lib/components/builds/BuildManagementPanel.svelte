<script lang="ts">
  import toast from 'svelte-french-toast';

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
  const runtimeEnvItems = $derived(envItems.filter((item) => (item.usage ?? 'runtime') === 'runtime'));
  const trainingEnvItems = $derived(envItems.filter((item) => item.usage === 'training'));

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

{#if runtimeEnvItems.length > 0}
  <BuildSettingsSection
    title="実行環境"
    description="推論や実行に使う環境定義と、その最新のビルド結果を一覧します。"
    items={runtimeEnvItems}
    currentSm={currentSm}
    {actionPending}
    onRun={onRun}
    onCancel={handleCancel}
    onDelete={onDelete}
    onCreateErrorReport={handleCreateErrorReport}
  />
{/if}

{#if trainingEnvItems.length > 0}
  <BuildSettingsSection
    title="学習環境"
    description="学習ジョブに使う環境定義と、その最新のビルド結果を一覧します。"
    items={trainingEnvItems}
    currentSm={currentSm}
    {actionPending}
    onRun={onRun}
    onCancel={handleCancel}
    onDelete={onDelete}
    onCreateErrorReport={handleCreateErrorReport}
  />
{/if}

<BuildSettingsSection
  title="共有パッケージ"
  description="共有パッケージ定義ごとの variant を一覧し、個別にビルド結果を一覧します。"
  items={sharedItems}
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

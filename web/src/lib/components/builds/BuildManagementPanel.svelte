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
    envItems?: BuildSettingSummary[];
    sharedItems?: BuildSettingSummary[];
    runningJobs?: BuildJobSummary[];
    selectedConfigId?: string;
    loading?: boolean;
    loadError?: string;
    actionPending?: Record<string, boolean>;
    logLinesByJobId?: Record<string, string[]>;
    onRun?: (item: BuildSettingSummary) => Promise<void>;
    onCancelByJobId?: (jobId: string, settingId?: string) => Promise<void>;
    onDelete?: (item: BuildSettingSummary) => Promise<void>;
  };

  let {
    envItems = [],
    sharedItems = [],
    runningJobs = [],
    selectedConfigId = '',
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

<section class="card-strong p-8">
  <p class="section-title">Builds</p>
  <div class="mt-3 grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.8fr)]">
    <div>
      <h2 class="text-3xl font-semibold text-slate-900">構築管理</h2>
      <p class="mt-3 max-w-3xl text-sm leading-7 text-slate-600">
        作成済み設定を起点に、環境構築と共有パッケージ構築の状態をまとめて管理します。進行中の build は上段で追跡し、
        下段では設定ごとに再構築・削除・レポート作成を行えます。
      </p>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
      <div class="nested-block-pane border-sky-200/80 bg-[linear-gradient(145deg,rgba(239,246,255,0.96),rgba(255,255,255,0.98))] p-4">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-500">選択中設定</p>
        <p class="mt-2 text-lg font-semibold text-slate-900">{selectedConfigId || '未選択'}</p>
        <p class="mt-1 text-sm text-slate-600">system settings で選ばれている env 設定を基準に表示します。</p>
      </div>
      <div class="nested-block-pane border-violet-200/80 bg-[linear-gradient(145deg,rgba(245,243,255,0.96),rgba(255,255,255,0.98))] p-4">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-violet-500">画面の見方</p>
        <p class="mt-2 text-sm leading-6 text-slate-600">
          上段は追跡、下段は管理です。構築中は進捗とログを追い、失敗時はその場でレポートIDを作成できます。
        </p>
      </div>
    </div>
  </div>
</section>

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
          実行中の build を追跡します。進捗バーは step 間を補間して表示し、直近ログから今どこで時間が掛かっているかを見やすくしています。
        </p>
      </div>
      <div class="chip">{runningJobs.length} 件 実行中</div>
    </div>

    <div class="grid gap-4 xl:grid-cols-2">
      {#each runningJobs as job}
        <BuildRunningCard
          {job}
          logLines={logLinesByJobId[job.job_id] ?? []}
          cancelling={Boolean(actionPending[job.setting_id] ?? actionPending[job.job_id])}
          onCancel={(jobId) => onCancelByJobId?.(jobId, job.setting_id)}
        />
      {/each}
    </div>
  </section>
{/if}

<BuildSettingsSection
  title="環境構築"
  description="PC 設定から選ばれる環境定義と、その最新 build 状態を一覧します。"
  items={envItems}
  {actionPending}
  onRun={onRun}
  onCancel={handleCancel}
  onDelete={onDelete}
  onCreateErrorReport={handleCreateErrorReport}
/>

<BuildSettingsSection
  title="共有パッケージ"
  description="shared package 定義ごとの variant を一覧し、個別に構築と削除を行います。"
  items={sharedItems}
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

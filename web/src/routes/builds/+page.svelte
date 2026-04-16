<script lang="ts">
  import { browser } from '$app/environment';
  import { onDestroy } from 'svelte';
  import toast from 'svelte-french-toast';

  import {
    api,
    type BuildErrorReportResponse,
    type BuildJobSummary,
    type BuildLogEvent,
    type BuildSettingSummary,
    type BuildsStatusSnapshot,
    type TabSessionSubscription
  } from '$lib/api/client';
  import BuildErrorReportDialog from '$lib/components/builds/BuildErrorReportDialog.svelte';
  import BuildRunningCard from '$lib/components/builds/BuildRunningCard.svelte';
  import BuildSettingsSection from '$lib/components/builds/BuildSettingsSection.svelte';
  import {
    registerTabRealtimeContributor,
    type TabRealtimeContributorHandle,
    type TabRealtimeEvent
  } from '$lib/realtime/tabSessionClient';

  let envItems = $state<BuildSettingSummary[]>([]);
  let sharedItems = $state<BuildSettingSummary[]>([]);
  let runningJobs = $state<BuildJobSummary[]>([]);
  let selectedConfigId = $state('');
  let loading = $state(true);
  let loadError = $state('');
  let actionPending = $state<Record<string, boolean>>({});
  let logLinesByJobId = $state<Record<string, string[]>>({});
  let errorReportDialogOpen = $state(false);
  let latestErrorReport = $state<BuildErrorReportResponse | null>(null);
  let errorReportMessage = $state('');
  let realtimeContributor: TabRealtimeContributorHandle | null = null;

  const loadSnapshot = async () => {
    loading = true;
    loadError = '';
    try {
      const [envs, shared] = await Promise.all([api.builds.envs(), api.builds.shared()]);
      envItems = envs.items;
      sharedItems = shared.items;
      selectedConfigId = envs.selected_config_id ?? '';
      runningJobs = [...envs.items, ...shared.items]
        .filter((item) => item.state === 'building' && item.current_job_id)
        .map((item) => ({
          job_id: item.current_job_id ?? '',
          build_id: item.latest_build_id ?? '',
          kind: item.kind,
          setting_id: item.setting_id,
          state: 'running',
          current_step_name: item.current_step_name ?? null,
          current_step_index: item.current_step_index ?? 0,
          total_steps: item.total_steps ?? 0,
          progress_percent: item.progress_percent ?? 0,
          created_at: item.latest_started_at ?? new Date().toISOString(),
          updated_at: item.latest_started_at ?? new Date().toISOString()
        }));
    } catch (error) {
      loadError = error instanceof Error ? error.message : '構築状態の取得に失敗しました。';
    } finally {
      loading = false;
    }
  };

  const applySnapshot = (snapshot: BuildsStatusSnapshot) => {
    selectedConfigId = snapshot.envs.selected_config_id ?? '';
    envItems = snapshot.envs.items;
    sharedItems = snapshot.shared.items;
    runningJobs = snapshot.running_jobs;
    const activeJobIds = new Set(snapshot.running_jobs.map((job) => job.job_id));
    logLinesByJobId = Object.fromEntries(
      Object.entries(logLinesByJobId).filter(([jobId]) => activeJobIds.has(jobId))
    );
  };

  const appendLogEvents = (events: BuildLogEvent[]) => {
    const next = { ...logLinesByJobId };
    for (const event of events) {
      const line = `${event.stream === 'stderr' ? '[stderr] ' : ''}${event.line.trim()}`.trim();
      const current = next[event.job_id] ?? [];
      next[event.job_id] = [...current, line].slice(-8);
    }
    logLinesByJobId = next;
  };

  const setPending = (key: string, value: boolean) => {
    actionPending = {
      ...actionPending,
      [key]: value
    };
  };

  const handleRealtimeEvent = (event: TabRealtimeEvent) => {
    if (event.source?.kind === 'builds.status' && event.op === 'snapshot') {
      applySnapshot(event.payload as unknown as BuildsStatusSnapshot);
      return;
    }
    if (event.source?.kind === 'builds.logs' && event.op === 'append') {
      const events = ((event.payload as { events?: BuildLogEvent[] }).events ?? []) as BuildLogEvent[];
      appendLogEvents(events);
    }
  };

  const ensureRealtime = () => {
    if (!browser || realtimeContributor) return;
    const subscriptions: TabSessionSubscription[] = [
      { subscription_id: 'builds.status', kind: 'builds.status', params: {} },
      { subscription_id: 'builds.logs', kind: 'builds.logs', params: {} }
    ];
    realtimeContributor = registerTabRealtimeContributor({
      contributorId: 'builds.page',
      subscriptions,
      onEvent: handleRealtimeEvent
    });
  };

  const handleRun = async (item: BuildSettingSummary) => {
    setPending(item.setting_id, true);
    try {
      if (item.kind === 'env' && item.config_id && item.env_name) {
        await api.builds.runEnv(item.config_id, item.env_name);
      } else if (item.kind === 'shared' && item.package && item.variant) {
        await api.builds.runShared(item.package, item.variant);
      }
      toast.success('構築を開始しました。');
      await loadSnapshot();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '構築の開始に失敗しました。');
    } finally {
      setPending(item.setting_id, false);
    }
  };

  const handleCancelByJobId = async (jobId: string, settingId?: string) => {
    setPending(settingId ?? jobId, true);
    try {
      await api.builds.cancelJob(jobId);
      toast.success('中止を要求しました。');
      await loadSnapshot();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '中止に失敗しました。');
    } finally {
      setPending(settingId ?? jobId, false);
    }
  };

  const handleCancel = async (item: BuildSettingSummary) => {
    if (!item.current_job_id) return;
    await handleCancelByJobId(item.current_job_id, item.setting_id);
  };

  const handleDelete = async (item: BuildSettingSummary) => {
    const buildId = item.current_build_id ?? item.latest_build_id;
    if (!buildId) return;
    setPending(item.setting_id, true);
    try {
      if (item.kind === 'env' && item.config_id && item.env_name) {
        await api.builds.deleteEnvArtifact(item.config_id, item.env_name, buildId);
      } else if (item.kind === 'shared' && item.package && item.variant) {
        await api.builds.deleteSharedArtifact(item.package, item.variant, buildId);
      }
      toast.success('構築成果物を削除しました。');
      await loadSnapshot();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '削除に失敗しました。');
    } finally {
      setPending(item.setting_id, false);
    }
  };

  const handleCreateErrorReport = async (item: BuildSettingSummary) => {
    const buildId = item.latest_build_id;
    if (!buildId) return;
    setPending(item.setting_id, true);
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
    } finally {
      setPending(item.setting_id, false);
    }
  };

  const handleCopyReportId = async (reportId: string) => {
    await navigator.clipboard.writeText(reportId);
    toast.success('レポートIDをコピーしました。');
  };

  $effect(() => {
    if (!browser) return;
    ensureRealtime();
    void loadSnapshot();
    return () => {
      realtimeContributor?.dispose();
      realtimeContributor = null;
    };
  });

  onDestroy(() => {
    realtimeContributor?.dispose();
    realtimeContributor = null;
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Builds</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">構築管理</h1>
      <p class="mt-2 text-sm text-slate-600">
        作成済み設定を起点に、環境構築と共有パッケージ構築の状態をまとめて管理します。
      </p>
      {#if selectedConfigId}
        <p class="mt-3 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">選択中設定: {selectedConfigId}</p>
      {/if}
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
        <p class="mt-2 text-sm text-slate-600">実行中の build を追跡します。進捗バーは step 間を補間して表示します。</p>
      </div>
    </div>

    <div class="grid gap-4 xl:grid-cols-2">
      {#each runningJobs as job}
        <BuildRunningCard
          {job}
          logLines={logLinesByJobId[job.job_id] ?? []}
          cancelling={Boolean(actionPending[job.setting_id] ?? actionPending[job.job_id])}
          onCancel={(jobId) => handleCancelByJobId(jobId, job.setting_id)}
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
  onRun={handleRun}
  onCancel={handleCancel}
  onDelete={handleDelete}
  onCreateErrorReport={handleCreateErrorReport}
/>

<BuildSettingsSection
  title="共有パッケージ"
  description="shared package 定義ごとの variant を一覧し、個別に構築と削除を行います。"
  items={sharedItems}
  {actionPending}
  onRun={handleRun}
  onCancel={handleCancel}
  onDelete={handleDelete}
  onCreateErrorReport={handleCreateErrorReport}
/>

<BuildErrorReportDialog
  bind:open={errorReportDialogOpen}
  reportId={latestErrorReport?.report_id ?? ''}
  settingId={latestErrorReport?.setting_id ?? ''}
  errorMessage={errorReportMessage}
  onCopy={handleCopyReportId}
/>

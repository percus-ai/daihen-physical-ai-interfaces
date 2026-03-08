<script lang="ts">
  import { onDestroy } from 'svelte';
  import { toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { AxisX, AxisY, GridY, Line, Plot } from 'svelteplot';
  import {
    api,
    type RemoteCheckpointUploadProgressMessage,
    type RemoteCheckpointUploadResult,
    type TrainingProvisionOperationStatusResponse,
    type TrainingReviveProgressMessage,
    type TrainingReviveResult
  } from '$lib/api/client';
  import { formatDate } from '$lib/format';
  import { getGpuModelLabel } from '$lib/policies';
  import { connectStream } from '$lib/realtime/stream';
  import { queryClient } from '$lib/queryClient';

  type JobInfo = {
    job_id?: string;
    job_name?: string;
    status?: string;
    dataset_id?: string;
    profile_instance_id?: string;
    profile_name?: string;
    policy_type?: string;
    ip?: string;
    ssh_user?: string;
    ssh_private_key?: string;
    ssh_port?: number;
    gpu_model?: string;
    gpus_per_instance?: number;
    created_at?: string;
    started_at?: string;
    completed_at?: string;
  };

  type TrainingConfig = {
    dataset?: { id?: string; video_backend?: string };
    policy?: { type?: string; pretrained_path?: string };
    cloud?: {
      provider?: string;
      gpu_model?: string;
      gpus_per_instance?: number;
      storage_size?: number;
      location?: string;
      ssh_port?: number;
      selected_mode?: 'spot' | 'ondemand';
      selected_instance_type?: string;
      selected_offer_id?: number;
      max_price?: number;
    };
    training?: {
      steps?: number;
      batch_size?: number;
      save_freq?: number;
      log_freq?: number;
    };
    validation?: { enable?: boolean };
    early_stopping?: { enable?: boolean };
  };

  type JobDetailResponse = {
    job?: JobInfo;
    provision_operation?: TrainingProvisionOperationStatusResponse | null;
    training_config?: TrainingConfig;
    summary?: Record<string, unknown> | null;
  };

  const jobId = $derived(page.params.job_id ?? '');

  const jobQuery = createQuery<JobDetailResponse>(
    toStore(() => ({
      queryKey: ['training', 'job', jobId],
      queryFn: () => api.training.job(jobId) as Promise<JobDetailResponse>,
      enabled: Boolean(jobId)
    }))
  );

  let logsType: 'training' | 'setup' = $state('training');
  let logLines = $state(30);
  let logs = $state('');
  let logsSource = $state('');
  let logsLoading = $state(false);
  let logsError = $state('');

  let metrics: { train?: Array<{ step?: number; loss?: number; ts?: string }>; val?: Array<{ step?: number; loss?: number; ts?: string }> } | null =
    $state(null);
  let metricsLoading = $state(false);
  let metricsError = $state('');

  let copied = $state(false);
  let provisionStreamError = $state('');
  type TrainingJobStreamPayload = {
    job_detail?: JobDetailResponse;
    metrics?: { train?: MetricPoint[]; val?: MetricPoint[] };
  };

  let streamStatus = $state('idle');
  let streamError = $state('');
  let streamLines: string[] = $state([]);
  let logStreamActive = $state(false);
  let reviveInProgress = $state(false);
  let reviveStage = $state('');
  let reviveMessage = $state('');
  let reviveError = $state('');
  let reviveElapsed: number | null = $state(null);
  let reviveTimeout: number | null = $state(null);
  let reviveEvents: string[] = $state([]);
  let reviveResult: TrainingReviveResult | null = $state(null);
  let reviveCopied = $state(false);
  let remoteCheckpointRoot = $state('');
  let remoteCheckpointNames: string[] = $state([]);
  let selectedRemoteCheckpoint = $state('');
  let remoteCheckpointLoading = $state(false);
  let remoteCheckpointError = $state('');
  let checkpointUploadInProgress = $state(false);
  let checkpointUploadStage = $state('');
  let checkpointUploadMessage = $state('');
  let checkpointUploadError = $state('');
  let checkpointUploadEvents: string[] = $state([]);
  let checkpointUploadResult: RemoteCheckpointUploadResult | null = $state(null);

  type MetricPoint = { step?: number; loss?: number; ts?: string };

  const jobInfo = $derived($jobQuery.data?.job);
  const provisionOperation = $derived($jobQuery.data?.provision_operation ?? null);
  const trainingConfig = $derived($jobQuery.data?.training_config ?? {});
  const summary = $derived($jobQuery.data?.summary ?? {});
  const status = $derived(jobInfo?.status ?? '');
  const provider = $derived(
    String(trainingConfig?.cloud?.provider ?? 'verda').trim().toLowerCase()
  );
  const effectiveSshPort = $derived(
    Number(trainingConfig?.cloud?.ssh_port ?? jobInfo?.ssh_port ?? 22)
  );
  const datasetId = $derived(trainingConfig?.dataset?.id ?? '');
  const profileId = $derived(jobInfo?.profile_name ?? jobInfo?.profile_instance_id ?? '');
  const trainSeries = $derived(
    (metrics?.train ?? [])
      .filter((point: MetricPoint) => typeof point.step === 'number' && typeof point.loss === 'number')
      .map((point: MetricPoint) => ({ step: point.step as number, loss: point.loss as number })) ?? []
  );
  const valSeries = $derived(
    (metrics?.val ?? [])
      .filter((point: MetricPoint) => typeof point.step === 'number' && typeof point.loss === 'number')
      .map((point: MetricPoint) => ({ step: point.step as number, loss: point.loss as number })) ?? []
  );

  const isRunning = $derived(['running', 'starting', 'deploying'].includes(status));
  const canDelete = $derived(['completed', 'failed', 'stopped', 'terminated'].includes(status));
  const canRevive = $derived(
    provider === 'verda' && ['completed', 'failed', 'stopped', 'terminated'].includes(status)
  );
  const provisionStepLabels: Record<string, string> = {
    queued: '開始待ち',
    validate: '設定検証',
    select_candidate: '候補確認',
    create_instance: 'インスタンス作成',
    job_created: 'ジョブ作成',
    wait_ip: 'IP割り当て待機',
    connect_ssh: 'SSH接続',
    deploy_files: 'ファイル転送',
    setup_env: '環境構築',
    start_training: '学習開始',
    completed: '完了',
    failed: 'エラー'
  };
  const provisionStepPercent: Record<string, number> = {
    queued: 4,
    validate: 12,
    select_candidate: 24,
    create_instance: 38,
    job_created: 48,
    wait_ip: 58,
    connect_ssh: 70,
    deploy_files: 82,
    setup_env: 92,
    start_training: 97,
    completed: 100,
    failed: 100
  };
  const provisionStep = $derived(provisionOperation?.step ?? '');
  const provisionStepLabel = $derived(
    provisionStep ? (provisionStepLabels[provisionStep] ?? provisionStep) : ''
  );
  const provisionTips: Record<string, string> = {
    queued: '作成要求を受け付けました。インスタンスの確保をこれから開始します。',
    validate: '設定内容を確認しています。通常はすぐに完了します。',
    select_candidate: '利用可能なインスタンス候補を確認しています。',
    create_instance: 'クラウド上でインスタンスを作成しています。数分かかることがあります。',
    job_created: 'ジョブは作成済みです。これ以降の準備はこの画面で追跡できます。',
    wait_ip: 'インスタンスの起動完了とネットワーク割り当てを待っています。',
    connect_ssh: 'インスタンスへの接続確認をしています。完了まで少し待ってください。',
    deploy_files: '学習に必要なファイルをインスタンスへ転送しています。',
    setup_env: '学習環境をセットアップしています。これには数分から10分程度かかる場合があります。',
    start_training: 'まもなく学習が始まります。開始後はログや loss が更新されます。',
    completed: '学習開始までの準備は完了しました。以後はジョブ本体の状態を追跡します。',
    failed: '作成が止まっています。更新時刻とエラーメッセージを確認してください。'
  };
  const provisionProgressPercent = $derived(
    provisionStep ? (provisionStepPercent[provisionStep] ?? 0) : 0
  );
  const provisionTip = $derived(
    provisionTips[provisionStep] ??
      'この画面を離れても作成は継続します。更新が長時間止まる場合は異常の可能性があります。'
  );
  const showProvisionCard = $derived(
    Boolean(provisionOperation) && (status === 'starting' || provisionOperation?.state === 'failed')
  );

  const sshTargetDisplay = $derived(
    (() => {
      if (!jobInfo?.ip) return '';
      const port = effectiveSshPort;
      return port > 0 && port !== 22 ? `${jobInfo.ip}:${port}` : jobInfo.ip;
    })()
  );

  const sshCommand = $derived(
    (() => {
      if (!jobInfo?.ip) return '';
      const keyPath = jobInfo?.ssh_private_key ?? '~/.ssh/id_rsa';
      const user = jobInfo?.ssh_user ?? 'root';
      const port = effectiveSshPort;
      const portOpt = port > 0 && port !== 22 ? ` -p ${port}` : '';
      return `ssh -i ${keyPath}${portOpt} ${user}@${jobInfo.ip}`;
    })()
  );
  const displayedLogs = $derived(
    streamLines.length
      ? `${logs}${logs ? '\n' : ''}${streamLines.join('\n')}`
      : logs
  );
  const reviveSshCommand = $derived(
    (() => {
      if (!reviveResult?.ip) return '';
      const keyPath = reviveResult?.ssh_private_key ?? '~/.ssh/id_rsa';
      const user = reviveResult?.ssh_user ?? 'root';
      const port = Number(reviveResult?.ssh_port ?? 22);
      const portOpt = port > 0 && port !== 22 ? ` -p ${port}` : '';
      return `ssh -i ${keyPath}${portOpt} ${user}@${reviveResult.ip}`;
    })()
  );

  const setProvisionOperationSnapshot = (
    snapshot: TrainingProvisionOperationStatusResponse | null
  ) => {
    if (!jobId) return;
    queryClient.setQueryData<JobDetailResponse>(['training', 'job', jobId], (current) => {
      if (!current) return current;
      return {
        ...current,
        provision_operation: snapshot
      };
    });
  };

  const refresh = async () => {
    const refetch = $jobQuery?.refetch;
    if (typeof refetch === 'function') {
      await refetch();
    }
  };

  const stopJob = async () => {
    if (!jobId || !isRunning) return;
    if (!confirm('このジョブを停止しますか?')) return;
    await api.training.stopJob(jobId);
    await refresh();
  };

  const deleteJob = async () => {
    if (!jobId || !canDelete) return;
    if (!confirm('このジョブを削除しますか？（リモートインスタンスも終了します）')) return;
    await api.training.deleteJob(jobId);
    await goto('/train');
  };

  const reviveJob = async () => {
    if (!jobId || !canRevive || reviveInProgress) return;
    if (!confirm('このジョブのインスタンスをCPUで蘇生しますか？')) return;

    reviveInProgress = true;
    reviveStage = '';
    reviveMessage = '';
    reviveError = '';
    reviveElapsed = null;
    reviveTimeout = null;
    reviveEvents = [];
    reviveResult = null;
    reviveCopied = false;

    try {
      const result = await api.training.reviveJobWs(
        jobId,
        (payload: TrainingReviveProgressMessage) => {
          if (payload.type) reviveStage = payload.type;
          if (payload.message) reviveMessage = payload.message;
          if (payload.error) reviveError = payload.error;
          if (typeof payload.elapsed === 'number') reviveElapsed = payload.elapsed;
          if (typeof payload.timeout === 'number') reviveTimeout = payload.timeout;

          const eventLabel = payload.type ?? 'event';
          const eventMessage = payload.error || payload.message || '';
          const line = eventMessage ? `${eventLabel}: ${eventMessage}` : eventLabel;
          reviveEvents = [...reviveEvents, line].slice(-30);
        }
      );
      reviveResult = result;
      reviveMessage = result.message;
      await refresh();
      await fetchRemoteCheckpoints();
    } catch (error) {
      reviveError = error instanceof Error ? error.message : 'インスタンス蘇生に失敗しました。';
    } finally {
      reviveInProgress = false;
    }
  };

  const fetchRemoteCheckpoints = async () => {
    if (!jobId) return;
    remoteCheckpointLoading = true;
    remoteCheckpointError = '';
    try {
      const result = await api.training.remoteCheckpoints(jobId);
      remoteCheckpointRoot = result.checkpoint_root || '';
      remoteCheckpointNames = result.checkpoint_names ?? [];
      if (remoteCheckpointNames.length === 0) {
        selectedRemoteCheckpoint = '';
      } else if (!remoteCheckpointNames.includes(selectedRemoteCheckpoint)) {
        selectedRemoteCheckpoint = remoteCheckpointNames[0];
      }
    } catch (error) {
      remoteCheckpointError =
        error instanceof Error ? error.message : 'リモートcheckpoint一覧の取得に失敗しました。';
      remoteCheckpointNames = [];
      selectedRemoteCheckpoint = '';
    } finally {
      remoteCheckpointLoading = false;
    }
  };

  const uploadSelectedCheckpoint = async () => {
    if (!jobId || !selectedRemoteCheckpoint || checkpointUploadInProgress) return;
    if (!confirm(`checkpoint ${selectedRemoteCheckpoint} をR2へ登録しますか？`)) return;

    checkpointUploadInProgress = true;
    checkpointUploadStage = '';
    checkpointUploadMessage = '';
    checkpointUploadError = '';
    checkpointUploadEvents = [];
    checkpointUploadResult = null;

    try {
      const result = await api.training.uploadCheckpointWs(
        jobId,
        selectedRemoteCheckpoint,
        (payload: RemoteCheckpointUploadProgressMessage) => {
          if (payload.type) checkpointUploadStage = payload.type;
          if (payload.message) checkpointUploadMessage = payload.message;
          if (payload.error) checkpointUploadError = payload.error;
          const eventType = payload.type ?? 'event';
          const eventMessage = payload.error || payload.message || '';
          const line = eventMessage ? `${eventType}: ${eventMessage}` : eventType;
          checkpointUploadEvents = [...checkpointUploadEvents, line].slice(-30);
        }
      );
      checkpointUploadResult = result;
      checkpointUploadMessage = result.message;
    } catch (error) {
      checkpointUploadError =
        error instanceof Error ? error.message : 'チェックポイントのR2登録に失敗しました。';
    } finally {
      checkpointUploadInProgress = false;
    }
  };

  const fetchLogs = async () => {
    logsError = '';
    if (!jobId) {
      logsError = 'ジョブIDが取得できません。';
      return;
    }
    logsLoading = true;
    try {
      const result = await api.training.logs(jobId, logsType, logLines);
      logs = (result as { logs?: string }).logs ?? '';
      logsSource = (result as { source?: string }).source ?? '';
    } catch (error) {
      logsError = error instanceof Error ? error.message : 'ログ取得に失敗しました。';
    } finally {
      logsLoading = false;
    }
  };

  const fetchMetrics = async () => {
    metricsError = '';
    if (!jobId) {
      metricsError = 'ジョブIDが取得できません。';
      return;
    }
    metricsLoading = true;
    try {
      const result = await api.training.metrics(jobId, 2000);
      metrics = result as typeof metrics;
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'メトリクス取得に失敗しました。';
    } finally {
      metricsLoading = false;
    }
  };

  const copySshCommand = async () => {
    if (!sshCommand) return;
    try {
      await navigator.clipboard.writeText(sshCommand);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      copied = false;
    }
  };

  const copyReviveSshCommand = async () => {
    if (!reviveSshCommand) return;
    try {
      await navigator.clipboard.writeText(reviveSshCommand);
      reviveCopied = true;
      setTimeout(() => (reviveCopied = false), 1500);
    } catch {
      reviveCopied = false;
    }
  };

  const downloadLogs = async () => {
    logsError = '';
    if (!jobId) {
      logsError = 'ジョブIDが取得できません。';
      return;
    }
    try {
      const content = await api.training.downloadLogs(jobId, logsType);
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${jobId}_${logsType}.log`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      logsError = error instanceof Error ? error.message : 'ログのダウンロードに失敗しました。';
    }
  };

  let stopLogStreamHandle = () => {};

  const closeLogStream = () => {
    stopLogStreamHandle();
    stopLogStreamHandle = () => {};
    logStreamActive = false;
  };

  const startLogStream = async () => {
    if (!jobId || logStreamActive) return;
    streamError = '';
    logsError = '';

    // Load full logs first so the user can see the full history before tailing.
    try {
      logsLoading = true;
      const content = await api.training.downloadLogs(jobId, logsType);
      logs = content ?? '';
      logsSource = 'remote';
    } catch (error) {
      logsError = error instanceof Error ? error.message : 'ログ取得に失敗しました。';
    } finally {
      logsLoading = false;
    }

    streamLines = [];
    streamStatus = 'connecting';
    logStreamActive = true;
    const stop = connectStream<{
      type?: string;
      line?: string;
      status?: string;
      message?: string;
      error?: string;
    }>({
      path: `/api/stream/training/jobs/${encodeURIComponent(jobId)}/logs?log_type=${logsType}`,
      onMessage: (data) => {
        if (data.type === 'connected') {
          streamStatus = 'connected';
          return;
        }
        if (data.type === 'log' && data.line) {
          streamLines = [...streamLines, data.line].slice(-200);
          return;
        }
        if (data.type === 'status') {
          streamStatus = data.status || 'status';
          closeLogStream();
          return;
        }
        if (data.type === 'error') {
          streamError = data.error || 'ログストリーミングに失敗しました。';
          streamStatus = 'error';
          closeLogStream();
        }
      },
      onError: () => {
        streamError = 'SSE接続に失敗しました。';
        streamStatus = 'error';
        closeLogStream();
      }
    });
    stopLogStreamHandle = () => {
      stop();
    };
  };

  const stopLogStream = () => {
    closeLogStream();
    streamStatus = 'stopped';
  };

  $effect(() => {
    if (!isRunning && logStreamActive) {
      stopLogStream();
    }
  });

  let lastJobId = '';
  $effect(() => {
    if (jobId && jobId !== lastJobId) {
      lastJobId = jobId;
      closeLogStream();
      streamLines = [];
      streamStatus = 'idle';
      streamError = '';
      logs = '';
      logsSource = '';
      logsError = '';
      metrics = null;
      metricsError = '';
      reviveInProgress = false;
      reviveStage = '';
      reviveMessage = '';
      reviveError = '';
      reviveElapsed = null;
      reviveTimeout = null;
      reviveEvents = [];
      reviveResult = null;
      reviveCopied = false;
      remoteCheckpointRoot = '';
      remoteCheckpointNames = [];
      selectedRemoteCheckpoint = '';
      remoteCheckpointLoading = false;
      remoteCheckpointError = '';
      checkpointUploadInProgress = false;
      checkpointUploadStage = '';
      checkpointUploadMessage = '';
      checkpointUploadError = '';
      checkpointUploadEvents = [];
      checkpointUploadResult = null;
      provisionStreamError = '';
    }
  });

  let stopTrainingStream = () => {};
  let lastStreamJobId = '';
  let stopProvisionStream = () => {};

  $effect(() => {
    if (jobId && jobId !== lastStreamJobId) {
      stopTrainingStream();
      lastStreamJobId = jobId;
      stopTrainingStream = connectStream<TrainingJobStreamPayload>({
        path: `/api/stream/training/jobs/${encodeURIComponent(jobId)}`,
        onMessage: (payload) => {
          if (payload.job_detail) {
            queryClient.setQueryData(['training', 'job', jobId], payload.job_detail);
          }
          if (payload.metrics) {
            metrics = payload.metrics;
            metricsLoading = false;
            metricsError = '';
          }
        }
      });
    }
  });

  $effect(() => {
    if (!jobId || status !== 'starting') {
      stopProvisionStream();
      provisionStreamError = '';
      return;
    }

    stopProvisionStream();
    provisionStreamError = '';
    stopProvisionStream = connectStream<TrainingProvisionOperationStatusResponse>({
      path: `/api/stream/training/jobs/${encodeURIComponent(jobId)}/provision-operation`,
      onMessage: (payload) => {
        provisionStreamError = '';
        setProvisionOperationSnapshot(payload);
      },
      onError: () => {
        provisionStreamError = '作成進行ストリームの接続に失敗しました。';
      }
    });

    return () => {
      stopProvisionStream();
    };
  });

  onDestroy(() => {
    stopProvisionStream();
    stopTrainingStream();
    closeLogStream();
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Train</p>
  <div class="mt-2 flex flex-wrap items-start justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">学習ジョブ詳細</h1>
      <p class="mt-2 text-sm text-slate-600">
        {jobInfo?.job_name ?? 'ジョブ名取得中...'}
      </p>
      <div class="mt-3 flex flex-wrap gap-2">
        <span class="chip">{status || 'unknown'}</span>
        {#if jobInfo?.gpu_model}
          <span class="chip">{getGpuModelLabel(jobInfo.gpu_model)} x {jobInfo.gpus_per_instance ?? 1}</span>
        {/if}
        {#if jobInfo?.dataset_id}
          <span class="chip">{jobInfo.dataset_id}</span>
        {/if}
      </div>
    </div>
    <div class="flex flex-wrap gap-3">
      <Button.Root class="btn-ghost" href="/train">一覧へ戻る</Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={refresh}>更新</Button.Root>
    </div>
  </div>
</section>

{#if showProvisionCard}
  <section class="card p-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="section-title">Creation Progress</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-900">作成進行カード</h2>
        <p class="mt-2 text-sm text-slate-600">
          {provisionTip}
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <span class="chip">job: {status || 'starting'}</span>
        <span class="chip">step: {provisionStepLabel || provisionStep || '-'}</span>
        {#if provisionOperation?.provider}
          <span class="chip">provider: {provisionOperation.provider}</span>
        {/if}
      </div>
    </div>
    <div class="mt-4 h-3 overflow-hidden rounded-full bg-slate-200/80">
      <div
        class={`h-full transition-all ${provisionOperation?.state === 'failed' ? 'bg-rose-500' : 'bg-brand'}`}
        style={`width: ${provisionProgressPercent}%`}
      ></div>
    </div>
    <div class="mt-4 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
      <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
        <p class="label">現在の状態</p>
        <div class="mt-2 space-y-1 text-xs text-slate-500">
          <p>job.status: <span class="font-semibold text-slate-800">{status || '-'}</span></p>
          <p>provision.state: <span class="font-semibold text-slate-800">{provisionOperation?.state ?? '-'}</span></p>
          <p>provision.step: <span class="font-semibold text-slate-800">{provisionStep || '-'}</span></p>
        </div>
      </div>
      <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
        <p class="label">補足</p>
        <div class="mt-2 space-y-1 text-xs text-slate-500">
          <p class="font-semibold text-slate-800">{provisionOperation?.message ?? provisionStepLabel ?? '状態取得中'}</p>
          <p class="break-all">instance: {provisionOperation?.instance_id ?? '-'}</p>
          <p>updated: {formatDate(provisionOperation?.updated_at)}</p>
        </div>
        {#if provisionOperation?.failure_reason}
          <p class="mt-3 text-sm text-rose-600 break-words">{provisionOperation.failure_reason}</p>
        {/if}
        {#if provisionStreamError}
          <p class="mt-3 text-sm text-rose-600">{provisionStreamError}</p>
        {/if}
      </div>
    </div>
  </section>
{/if}

<section class="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
  <div class="space-y-6 min-w-0">
    <section class="card p-6">
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-semibold text-slate-900">基本情報</h2>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">ジョブID</p>
          <p class="mt-2 font-semibold text-slate-800">{jobInfo?.job_id ?? '-'}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">ポリシー</p>
          <p class="mt-2 font-semibold text-slate-800">{jobInfo?.policy_type ?? '-'}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">作成日時</p>
          <p class="mt-2 font-semibold text-slate-800">{formatDate(jobInfo?.created_at)}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">開始日時</p>
          <p class="mt-2 font-semibold text-slate-800">{formatDate(jobInfo?.started_at)}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">完了日時</p>
          <p class="mt-2 font-semibold text-slate-800">{formatDate(jobInfo?.completed_at)}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">IP</p>
          <p class="mt-2 font-semibold text-slate-800">{sshTargetDisplay || '-'}</p>
        </div>
      </div>
    </section>

    <section class="card p-6">
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-semibold text-slate-900">loss推移</h2>
        <Button.Root class="btn-ghost" type="button" onclick={fetchMetrics} disabled={metricsLoading}>
          {metricsLoading ? '取得中...' : '更新'}
        </Button.Root>
      </div>
      {#if metricsError}
        <p class="mt-3 text-sm text-rose-600">{metricsError}</p>
      {:else if metrics}
        {#if trainSeries.length || valSeries.length}
          <div class="mt-4 space-y-4 text-sm text-slate-600">
            <div class="flex flex-wrap items-center gap-4 text-xs text-slate-500">
              <span class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-brand"></span>
                Train loss
              </span>
              <span class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-orange-400"></span>
                Val loss
              </span>
            </div>
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <Plot height={240} grid>
                <GridY />
                <AxisX tickCount={6} />
                <AxisY tickCount={6} />
                {#if trainSeries.length}
                  <Line data={trainSeries} x="step" y="loss" stroke="#5b7cfa" strokeWidth={2} />
                {/if}
                {#if valSeries.length}
                  <Line data={valSeries} x="step" y="loss" stroke="#fb923c" strokeWidth={2} />
                {/if}
              </Plot>
            </div>
          </div>
        {:else}
          <p class="mt-3 text-sm text-slate-500">まだデータがありません。</p>
        {/if}
      {:else}
        <p class="mt-3 text-sm text-slate-500">まだデータがありません。</p>
      {/if}
    </section>

    <section class="card p-6">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-xl font-semibold text-slate-900">ログ内容</h2>
        <span class="text-xs text-slate-500">
          表示: {logsType === 'training' ? '学習ログ' : 'セットアップログ'}{#if logsSource === 'r2'} (R2){/if}
        </span>
      </div>
      <div class="mt-4 space-y-4 text-sm text-slate-600">
        {#if logsError}
          <p class="text-sm text-rose-600">{logsError}</p>
        {/if}
        {#if streamError}
          <p class="text-sm text-rose-600">{streamError}</p>
        {/if}
        {#if isRunning}
          {#if displayedLogs}
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-600">
              <pre class="min-w-0 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs text-slate-700">{displayedLogs}</pre>
            </div>
          {:else}
            <p class="text-sm text-slate-500">ログは未取得です。</p>
          {/if}
        {:else}
          <p class="text-sm text-slate-500">実行中ではないため、ログはダウンロードのみ対応しています。</p>
        {/if}
      </div>
    </section>

    <section class="card p-6">
      <div class="flex items-center justify-between">
        <h2 class="text-xl font-semibold text-slate-900">設定</h2>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-2 text-sm text-slate-600">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
          <p class="label">データセット</p>
          <div class="mt-2 space-y-2 text-sm text-slate-600">
            <div>
              <p class="text-xs text-slate-500">データセットID</p>
              <p class="font-semibold text-slate-800 break-words">
                {datasetId || '-'}
              </p>
            </div>
            <div>
              <p class="text-xs text-slate-500">プロファイル</p>
              <p class="font-semibold text-slate-800 break-words">
                {profileId || '-'}
              </p>
            </div>
          </div>
          <p class="mt-2 text-xs text-slate-500">
            video_backend: {trainingConfig?.dataset?.video_backend ?? 'auto'}
          </p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
          <p class="label">ポリシー</p>
          <p class="mt-2 font-semibold text-slate-800">{trainingConfig?.policy?.type ?? '-'}</p>
          <p class="mt-1 text-xs text-slate-500">pretrained: {trainingConfig?.policy?.pretrained_path ?? '-'}</p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
          <p class="label">学習</p>
          <p class="mt-2 font-semibold text-slate-800">
            steps: {trainingConfig?.training?.steps ?? '-'} / batch: {trainingConfig?.training?.batch_size ?? '-'}
          </p>
          <p class="mt-1 text-xs text-slate-500">
            save_freq: {trainingConfig?.training?.save_freq ?? '-'} / log_freq: {trainingConfig?.training?.log_freq ?? '-'}
          </p>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
          <p class="label">検証 / Early</p>
          <p class="mt-2 font-semibold text-slate-800">
            validation: {trainingConfig?.validation?.enable ? '有効' : '無効'}
          </p>
          <p class="mt-1 text-xs text-slate-500">
            early_stopping: {trainingConfig?.early_stopping?.enable ? '有効' : '無効'}
          </p>
        </div>
      </div>
      {#if Object.keys(summary).length}
        <div class="mt-4 rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
          <p class="label">Summary</p>
          <div class="mt-2 grid gap-2">
            {#each Object.entries(summary) as [key, value]}
              <p class="text-xs text-slate-500">{key}: <span class="text-slate-800">{value}</span></p>
            {/each}
          </div>
        </div>
      {/if}
    </section>
  </div>

  <div class="space-y-6 min-w-0">
    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">操作</h2>
      <div class="mt-4 grid gap-3">
        <Button.Root class="btn-primary" type="button" onclick={stopJob} disabled={!isRunning}>
          {isRunning ? 'ジョブを停止' : '停止不可'}
        </Button.Root>
        {#if canRevive}
          <Button.Root class="btn-ghost" type="button" onclick={reviveJob} disabled={reviveInProgress}>
            {reviveInProgress ? 'インスタンス蘇生中...' : 'インスタンスを蘇生'}
          </Button.Root>
        {/if}
      </div>
      <p class="mt-3 text-xs text-slate-500">
        停止・蘇生はジョブステータスに応じて有効化されます。
      </p>
      {#if isRunning}
        <div class="mt-3 flex items-center gap-2 text-xs text-slate-500">
          <span class="chip">ストリーミング更新</span>
          <span>進捗とステータスはストリーミングで更新します。</span>
        </div>
      {/if}
    </section>

    {#if canRevive || reviveInProgress || reviveResult || reviveError || reviveEvents.length}
      <section class="card p-6">
        <h2 class="text-xl font-semibold text-slate-900">インスタンス蘇生</h2>
        <p class="mt-2 text-sm text-slate-600">
          終了済みジョブに対して、OSストレージからCPUインスタンスを再作成します。
        </p>
        <div class="mt-4 space-y-3 text-sm text-slate-600">
          <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
            <p class="label">救済チェックポイント登録</p>
            <p class="mt-2 text-xs text-slate-500">
              リモート上の checkpoint ディレクトリから保存対象を選択して R2 に登録します。
            </p>
            <div class="mt-3 flex flex-wrap gap-2">
              <Button.Root class="btn-ghost" type="button" onclick={fetchRemoteCheckpoints} disabled={remoteCheckpointLoading || checkpointUploadInProgress}>
                {remoteCheckpointLoading ? '候補取得中...' : '候補を取得'}
              </Button.Root>
            </div>
            {#if remoteCheckpointRoot}
              <p class="mt-3 text-xs text-slate-500 break-all">root: {remoteCheckpointRoot}</p>
            {/if}
            {#if remoteCheckpointError}
              <p class="mt-3 text-sm text-rose-600">{remoteCheckpointError}</p>
            {/if}
            {#if remoteCheckpointNames.length}
              <label class="mt-3 block text-sm font-semibold text-slate-700">
                <span class="label">保存するcheckpoint</span>
                <select class="input mt-2" bind:value={selectedRemoteCheckpoint} disabled={checkpointUploadInProgress}>
                  {#each remoteCheckpointNames as checkpointName}
                    <option value={checkpointName}>{checkpointName}</option>
                  {/each}
                </select>
              </label>
              <div class="mt-3 flex flex-wrap gap-2">
                <Button.Root class="btn-primary" type="button" onclick={uploadSelectedCheckpoint} disabled={!selectedRemoteCheckpoint || checkpointUploadInProgress}>
                  {checkpointUploadInProgress ? 'R2登録中...' : '選択したcheckpointをR2登録'}
                </Button.Root>
              </div>
            {:else if !remoteCheckpointLoading}
              <p class="mt-3 text-xs text-slate-500">候補はまだ取得されていません。</p>
            {/if}
          </div>

          {#if reviveStage}
            <span class="chip">フェーズ: {reviveStage}</span>
          {/if}
          {#if reviveElapsed !== null}
            <p class="text-xs text-slate-500">
              経過: {reviveElapsed}s{#if reviveTimeout !== null} / {reviveTimeout}s{/if}
            </p>
          {/if}
          {#if reviveMessage}
            <p class="text-sm text-slate-700">{reviveMessage}</p>
          {/if}
          {#if reviveError}
            <p class="text-sm text-rose-600">{reviveError}</p>
          {/if}
          {#if checkpointUploadStage}
            <span class="chip">登録フェーズ: {checkpointUploadStage}</span>
          {/if}
          {#if checkpointUploadMessage}
            <p class="text-sm text-slate-700">{checkpointUploadMessage}</p>
          {/if}
          {#if checkpointUploadError}
            <p class="text-sm text-rose-600">{checkpointUploadError}</p>
          {/if}
          {#if reviveEvents.length}
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <p class="label">進捗ログ</p>
              <div class="mt-2 max-h-72 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
                <pre class="min-w-0 whitespace-pre-wrap break-all text-xs text-slate-700">{reviveEvents.join('\n')}</pre>
              </div>
            </div>
          {/if}
          {#if checkpointUploadEvents.length}
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <p class="label">checkpoint登録ログ</p>
              <div class="mt-2 max-h-72 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
                <pre class="min-w-0 whitespace-pre-wrap break-all text-xs text-slate-700">{checkpointUploadEvents.join('\n')}</pre>
              </div>
            </div>
          {/if}
          {#if checkpointUploadResult}
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <p class="label">checkpoint登録結果</p>
              <div class="mt-2 space-y-1 text-xs text-slate-600">
                <p>checkpoint: <span class="font-semibold text-slate-800">{checkpointUploadResult.checkpoint_name}</span></p>
                <p>step: <span class="font-semibold text-slate-800">{checkpointUploadResult.step}</span></p>
                <p>R2 path: <span class="font-semibold text-slate-800 break-all">{checkpointUploadResult.r2_step_path}</span></p>
                <p>model_id: <span class="font-semibold text-slate-800 break-all">{checkpointUploadResult.model_id}</span></p>
                <p>
                  DB登録:
                  <span class="font-semibold text-slate-800">
                    {checkpointUploadResult.db_registered ? '完了' : '未完了'}
                  </span>
                </p>
              </div>
            </div>
          {/if}
          {#if reviveResult}
            <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4">
              <p class="label">蘇生結果</p>
              <div class="mt-2 space-y-1 text-xs text-slate-600">
                <p>旧インスタンスID: <span class="font-semibold text-slate-800 break-all">{reviveResult.old_instance_id}</span></p>
                <p>新インスタンスID: <span class="font-semibold text-slate-800 break-all">{reviveResult.instance_id}</span></p>
                <p>ストレージID: <span class="font-semibold text-slate-800 break-all">{reviveResult.volume_id}</span></p>
                <p>インスタンスタイプ: <span class="font-semibold text-slate-800">{reviveResult.instance_type}</span></p>
                <p>ロケーション: <span class="font-semibold text-slate-800">{reviveResult.location}</span></p>
                <p>
                  SSH接続先:
                  <span class="font-semibold text-slate-800">
                    {#if reviveResult.ssh_port && reviveResult.ssh_port !== 22}
                      {reviveResult.ip}:{reviveResult.ssh_port}
                    {:else}
                      {reviveResult.ip}
                    {/if}
                  </span>
                </p>
                <p>SSHユーザー: <span class="font-semibold text-slate-800">{reviveResult.ssh_user}</span></p>
                <p>SSH鍵: <span class="font-semibold text-slate-800 break-all">{reviveResult.ssh_private_key}</span></p>
              </div>
              <div class="mt-3 rounded-xl border border-slate-200/60 bg-slate-50/80 p-3 text-xs text-slate-600">
                <p class="label">SSHコマンド</p>
                <p class="mt-2 font-semibold text-slate-800 break-all">{reviveSshCommand || '-'}</p>
              </div>
              <div class="mt-3 flex flex-wrap gap-2">
                <Button.Root class="btn-ghost" type="button" onclick={copyReviveSshCommand} disabled={!reviveSshCommand}>
                  SSHコマンドをコピー
                </Button.Root>
                {#if reviveCopied}
                  <span class="chip">コピーしました</span>
                {/if}
              </div>
            </div>
          {/if}
        </div>
      </section>
    {/if}

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">ログ</h2>
      <div class="mt-4 grid gap-3 text-sm text-slate-600">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ログ種別</span>
          <select class="input mt-2" bind:value={logsType} disabled={logStreamActive}>
            <option value="training">学習ログ</option>
            <option value="setup">セットアップログ</option>
          </select>
        </label>
        {#if isRunning}
          <Button.Root class="btn-ghost" type="button" onclick={downloadLogs}>
            ログをダウンロード
          </Button.Root>
          <label class="text-sm font-semibold text-slate-700">
            <span class="label">取得行数</span>
            <input class="input mt-2" type="number" min="1" bind:value={logLines} />
          </label>
          <Button.Root class="btn-ghost" type="button" onclick={fetchLogs} disabled={logsLoading}>
            {logsLoading ? '取得中...' : 'ログを取得'}
          </Button.Root>
          <div class="flex flex-wrap gap-2">
            <Button.Root class="btn-primary" type="button" onclick={startLogStream} disabled={logStreamActive}>
              ストリーミング開始
            </Button.Root>
            <Button.Root class="btn-ghost" type="button" onclick={stopLogStream} disabled={!logStreamActive}>
              ストリーミング停止
            </Button.Root>
            <span class="chip">状態: {streamStatus}</span>
          </div>
        {:else}
          <Button.Root class="btn-primary" type="button" onclick={downloadLogs}>
            ログをダウンロード
          </Button.Root>
        {/if}
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">SSH接続</h2>
      <p class="mt-2 text-sm text-slate-600">ジョブ詳細のIP情報を使って接続します。</p>
      <div class="mt-4 rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-600">
        <p class="label">コマンド</p>
        <p class="mt-2 font-semibold text-slate-800">{sshCommand || 'IPが取得できていません'}</p>
      </div>
      <div class="mt-4 flex flex-wrap gap-3">
        <Button.Root class="btn-ghost" type="button" onclick={copySshCommand} disabled={!sshCommand}>
          コピー
        </Button.Root>
        {#if copied}
          <span class="chip">コピーしました</span>
        {/if}
      </div>
    </section>
  </div>
</section>

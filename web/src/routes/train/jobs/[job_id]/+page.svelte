<script lang="ts">
  import { browser } from '$app/environment';
  import { toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { AxisX, AxisY, GridY, Line, Plot } from 'svelteplot';
  import {
    api,
    type RemoteCheckpointUploadResult,
    type RescueCPUResult,
    type TabSessionSubscription,
    type TrainingJobCoreSubscription,
    type TrainingJobLogsSubscription,
    type TrainingJobMetricsSubscription,
    type TrainingJobOperationStatusResponse,
    type TrainingJobOperationsSubscription,
    type TrainingJobProvisionSubscription,
    type TrainingProvisionOperationStatusResponse
  } from '$lib/api/client';
  import { formatDate } from '$lib/format';
  import { getGpuModelLabel } from '$lib/policies';
  import { registerTabRealtimeContributor, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';
  import { queryClient } from '$lib/queryClient';

  type JobInfo = {
    job_id?: string;
    job_name?: string;
    instance_id?: string;
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
    policy?: { type?: string; pretrained_path?: string; base_model_path?: string };
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

  type InstanceStatusResponse = {
    instance_status?: string | null;
    job_status?: string;
    remote_process_status?: string | null;
    message?: string;
  };

  const jobId = $derived(page.params.job_id ?? '');

  const jobQuery = createQuery<JobDetailResponse>(
    toStore(() => ({
      queryKey: ['training', 'job', jobId],
      queryFn: () => api.training.job(jobId) as Promise<JobDetailResponse>,
      enabled: Boolean(jobId)
    }))
  );

  const instanceStatusQuery = createQuery<InstanceStatusResponse>(
    toStore(() => ({
      queryKey: ['training', 'job', jobId, 'instance-status'],
      queryFn: () => api.training.instanceStatus(jobId) as Promise<InstanceStatusResponse>,
      enabled: Boolean(
        jobId &&
          $jobQuery.data?.job?.instance_id &&
          ['running', 'starting', 'deploying'].includes(String($jobQuery.data?.job?.status ?? ''))
      )
    }))
  );

  type MetricsResponse = {
    train?: Array<{ step?: number; loss?: number; ts?: string }>;
    val?: Array<{ step?: number; loss?: number; ts?: string }>;
  };

  const metricsQuery = createQuery<MetricsResponse>(
    toStore(() => ({
      queryKey: ['training', 'job', jobId, 'metrics'],
      queryFn: () => api.training.metrics(jobId, 2000) as Promise<MetricsResponse>,
      enabled: Boolean(jobId)
    }))
  );

  let logsType: 'training' | 'setup' = $state('training');
  let logLines = $state(30);
  let logs = $state('');
  let logsSource = $state('');
  let logsLoading = $state(false);
  let logsError = $state('');

  let copied = $state(false);
  let streamStatus = $state('idle');
  let streamError = $state('');
  let streamLines: string[] = $state([]);
  let logStreamActive = $state(false);
  let rescueCpuInProgress = $state(false);
  let rescueCpuPhase = $state('');
  let rescueCpuMessage = $state('');
  let rescueCpuError = $state('');
  let rescueCpuProgressPercent = $state(0);
  let rescueCpuElapsed: number | null = $state(null);
  let rescueCpuTimeout: number | null = $state(null);
  let rescueCpuResult: RescueCPUResult | null = $state(null);
  const selectedPolicyModelPath = $derived(
    $jobQuery.data?.training_config?.policy?.base_model_path ??
      $jobQuery.data?.training_config?.policy?.pretrained_path ??
      null
  );
  let rescueCpuCopied = $state(false);
  let rescueCpuOperationSnapshot: TrainingJobOperationStatusResponse | null = $state(null);
  let remoteCheckpointRoot = $state('');
  let remoteCheckpointNames: string[] = $state([]);
  let selectedRemoteCheckpoint = $state('');
  let remoteCheckpointLoading = $state(false);
  let remoteCheckpointError = $state('');
  let remoteCheckpointMessage = $state('');
  let remoteCheckpointSshAvailable = $state(true);
  let remoteCheckpointRequiresRescueCpu = $state(false);
  let checkpointUploadInProgress = $state(false);
  let checkpointUploadPhase = $state('');
  let checkpointUploadProgressPercent = $state(0);
  let checkpointUploadMessage = $state('');
  let checkpointUploadError = $state('');
  let checkpointUploadResult: RemoteCheckpointUploadResult | null = $state(null);
  let checkpointUploadOperationSnapshot: TrainingJobOperationStatusResponse | null = $state(null);
  let trainingJobOperations: TrainingJobOperationStatusResponse[] = $state([]);

  type MetricPoint = { step?: number; loss?: number; ts?: string };
  let activeLogSnapshotKey = $state('');
  let loadedLogSnapshotKey = $state('');

  const jobInfo = $derived($jobQuery.data?.job);
  const provisionOperation = $derived($jobQuery.data?.provision_operation ?? null);
  const trainingConfig = $derived($jobQuery.data?.training_config ?? {});
  const summary = $derived($jobQuery.data?.summary ?? {});
  const metrics = $derived($metricsQuery.data ?? null);
  const metricsLoading = $derived(Boolean($metricsQuery.isFetching));
  const metricsError = $derived(
    $metricsQuery.error instanceof Error ? $metricsQuery.error.message : ''
  );
  const status = $derived(jobInfo?.status ?? '');
  const instanceStatus = $derived(
    String($instanceStatusQuery.data?.instance_status ?? '')
      .trim()
      .toLowerCase()
  );
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
  const shouldQueryInstanceStatus = $derived(
    Boolean(jobId && jobInfo?.instance_id && ['running', 'starting', 'deploying'].includes(status))
  );
  const hasLiveInstance = $derived(
    Boolean(jobInfo?.instance_id) &&
      Boolean(instanceStatus) &&
      !['offline', 'error', 'discontinued', 'deleted', 'terminated', 'stopped', 'exited', 'dead', 'unavailable'].includes(
        instanceStatus
      )
  );
  const canStop = $derived(isRunning || hasLiveInstance);
  const stopActionLabel = $derived(
    isRunning ? 'ジョブを停止' : hasLiveInstance ? 'インスタンスを停止' : '停止不可'
  );
  const canDelete = $derived(['completed', 'failed', 'stopped', 'terminated'].includes(status));
  const canRescueCpu = $derived(
    provider === 'verda' && ['completed', 'failed', 'stopped', 'terminated'].includes(status)
  );
  const shouldSubscribeLogStream = $derived(isRunning);
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
    connect_ssh: 'インスタンスへの接続確認をしています。これには数十秒から数分程度かかる場合があります。',
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
  const rescueCpuSshCommand = $derived(
    (() => {
      if (!rescueCpuResult?.ip) return '';
      const keyPath = rescueCpuResult?.ssh_private_key ?? '~/.ssh/id_rsa';
      const user = rescueCpuResult?.ssh_user ?? 'root';
      const port = Number(rescueCpuResult?.ssh_port ?? 22);
      const portOpt = port > 0 && port !== 22 ? ` -p ${port}` : '';
      return `ssh -i ${keyPath}${portOpt} ${user}@${rescueCpuResult.ip}`;
    })()
  );

  const getLatestOperationByKind = (
    operations: TrainingJobOperationStatusResponse[] | undefined,
    kind: 'checkpoint_upload' | 'rescue_cpu'
  ): TrainingJobOperationStatusResponse | null => {
    return (
      (operations ?? [])
        .filter((item) => item.kind === kind)
        .sort((left, right) => String(right.updated_at ?? '').localeCompare(String(left.updated_at ?? '')))[0] ??
      null
    );
  };

  const activeCheckpointOperation = $derived(
    getLatestOperationByKind(trainingJobOperations, 'checkpoint_upload')
  );
  const activeRescueOperation = $derived(
    getLatestOperationByKind(trainingJobOperations, 'rescue_cpu')
  );

  const hasSameOperationSnapshot = (
    left: TrainingJobOperationStatusResponse | null,
    right: TrainingJobOperationStatusResponse | null
  ): boolean => {
    if (!left || !right) return false;
    return (
      left.operation_id === right.operation_id &&
      String(left.updated_at ?? '') === String(right.updated_at ?? '')
    );
  };

  $effect(() => {
    if (!activeCheckpointOperation) {
      return;
    }
    if (!hasSameOperationSnapshot(checkpointUploadOperationSnapshot, activeCheckpointOperation)) {
      applyCheckpointUploadOperationSnapshot(activeCheckpointOperation, { fromRealtime: true });
    }
  });

  $effect(() => {
    if (!activeRescueOperation) {
      return;
    }
    if (!hasSameOperationSnapshot(rescueCpuOperationSnapshot, activeRescueOperation)) {
      applyRescueCpuOperationSnapshot(activeRescueOperation, { fromRealtime: true });
    }
  });

  const setProvisionOperationSnapshot = (
    targetJobId: string,
    snapshot: TrainingProvisionOperationStatusResponse | null
  ) => {
    if (!targetJobId) return;
    queryClient.setQueryData<JobDetailResponse>(['training', 'job', targetJobId], (current) => {
      return {
        ...current,
        provision_operation: snapshot
      };
    });
  };

  const setJobDetailSnapshot = (targetJobId: string, snapshot: JobDetailResponse) => {
    if (!targetJobId) return;
    queryClient.setQueryData<JobDetailResponse>(['training', 'job', targetJobId], snapshot);
  };

  const setMetricsSnapshot = (targetJobId: string, snapshot: MetricsResponse) => {
    if (!targetJobId) return;
    queryClient.setQueryData<MetricsResponse>(['training', 'job', targetJobId, 'metrics'], snapshot);
  };

  const isOperationActive = (snapshot: TrainingJobOperationStatusResponse | null): boolean => {
    if (!snapshot) return false;
    return snapshot.state === 'queued' || snapshot.state === 'running';
  };

  const getDetailNumber = (snapshot: TrainingJobOperationStatusResponse | null, key: string): number | null => {
    const value = snapshot?.detail?.[key];
    return typeof value === 'number' ? value : null;
  };

  const asCheckpointUploadResult = (
    snapshot: TrainingJobOperationStatusResponse | null
  ): RemoteCheckpointUploadResult | null => {
    if (!snapshot?.result || typeof snapshot.result !== 'object') return null;
    return snapshot.result as RemoteCheckpointUploadResult;
  };

  const asRescueCpuResult = (
    snapshot: TrainingJobOperationStatusResponse | null
  ): RescueCPUResult | null => {
    if (!snapshot?.result || typeof snapshot.result !== 'object') return null;
    return snapshot.result as RescueCPUResult;
  };

  const applyCheckpointUploadOperationSnapshot = (
    snapshot: TrainingJobOperationStatusResponse | null,
    options: { fromRealtime?: boolean } = {}
  ) => {
    const previousState = options.fromRealtime
      ? checkpointUploadOperationSnapshot?.state ?? null
      : null;
    checkpointUploadOperationSnapshot = snapshot;
    checkpointUploadInProgress = isOperationActive(snapshot);
    checkpointUploadPhase = snapshot?.phase ?? '';
    checkpointUploadProgressPercent = Number(snapshot?.progress_percent ?? 0);
    checkpointUploadMessage = snapshot?.message ?? '';
    checkpointUploadError = snapshot?.error ?? '';
    checkpointUploadResult = asCheckpointUploadResult(snapshot);

    if (
      options.fromRealtime &&
      previousState &&
      ['queued', 'running'].includes(previousState) &&
      snapshot &&
      ['completed', 'failed', 'cancelled'].includes(snapshot.state)
    ) {
      void refresh();
      void fetchRemoteCheckpoints();
    }

  };

  const applyRescueCpuOperationSnapshot = (
    snapshot: TrainingJobOperationStatusResponse | null,
    options: { fromRealtime?: boolean } = {}
  ) => {
    const previousState = options.fromRealtime
      ? rescueCpuOperationSnapshot?.state ?? null
      : null;
    rescueCpuOperationSnapshot = snapshot;
    rescueCpuInProgress = isOperationActive(snapshot);
    rescueCpuPhase = snapshot?.phase ?? '';
    rescueCpuMessage = snapshot?.message ?? '';
    rescueCpuError = snapshot?.error ?? '';
    rescueCpuProgressPercent = Number(snapshot?.progress_percent ?? 0);
    rescueCpuElapsed = getDetailNumber(snapshot, 'elapsed');
    rescueCpuTimeout = getDetailNumber(snapshot, 'timeout');
    rescueCpuResult = asRescueCpuResult(snapshot);

    if (
      options.fromRealtime &&
      previousState &&
      ['queued', 'running'].includes(previousState) &&
      snapshot &&
      ['completed', 'failed', 'cancelled'].includes(snapshot.state)
    ) {
      void refresh();
      void fetchRemoteCheckpoints();
    }

  };

  const buildRealtimeSubscriptions = (
    targetJobId: string,
    nextLogsType: 'training' | 'setup',
    nextLogLines: number
  ): TabSessionSubscription[] => {
    const coreSubscription: TrainingJobCoreSubscription = {
      subscription_id: `train.job.${targetJobId}.core`,
      kind: 'training.job.core',
      params: { job_id: targetJobId }
    };
    const provisionSubscription: TrainingJobProvisionSubscription = {
      subscription_id: `train.job.${targetJobId}.provision`,
      kind: 'training.job.provision',
      params: { job_id: targetJobId }
    };
    const metricsSubscription: TrainingJobMetricsSubscription = {
      subscription_id: `train.job.${targetJobId}.metrics`,
      kind: 'training.job.metrics',
      params: { job_id: targetJobId, limit: 2000 }
    };
    const subscriptions: TabSessionSubscription[] = [
      coreSubscription,
      provisionSubscription,
      metricsSubscription
    ];
    if (shouldSubscribeLogStream) {
      const logsSubscription: TrainingJobLogsSubscription = {
        subscription_id: `train.job.${targetJobId}.logs`,
        kind: 'training.job.logs',
        params: {
          job_id: targetJobId,
          log_type: nextLogsType,
          tail_lines: nextLogLines
        }
      };
      subscriptions.push(logsSubscription);
    }
    const operationsSubscription: TrainingJobOperationsSubscription = {
      subscription_id: `train.job.${targetJobId}.operations`,
      kind: 'training.job.operations',
      params: { job_id: targetJobId }
    };
    subscriptions.push(operationsSubscription);
    return subscriptions;
  };

  const appendLogLines = (lines: string[]) => {
    if (!lines.length) return;
    streamLines = [...streamLines, ...lines].slice(-200);
  };

  const handleLogControlPayload = (payload: Record<string, unknown>) => {
    const type = String(payload.type ?? '').trim();
    if (!type) return;
    if (type === 'connected') {
      logStreamActive = true;
      streamStatus = 'connected';
      streamError = '';
      return;
    }
    if (type === 'stream_ended') {
      logStreamActive = false;
      streamStatus = 'ended';
      return;
    }
    if (type === 'job_status') {
      logStreamActive = false;
      streamStatus = String(payload.status ?? 'stopped');
      return;
    }
    if (type === 'job_deleted' || type === 'job_missing' || type === 'ip_missing') {
      logStreamActive = false;
      streamStatus = type;
      streamError = `ログストリームが終了しました: ${type}`;
    }
  };

  const handleRealtimeEvent = (
    targetJobId: string,
    registrationKey: string,
    event: TabRealtimeEvent
  ) => {
    const activeKey = `${jobId}:${logsType}`;
    if (registrationKey !== activeKey) {
      return;
    }

    switch (event.source?.kind) {
      case 'training.job.core':
        if (event.op === 'snapshot') {
          setJobDetailSnapshot(targetJobId, event.payload as JobDetailResponse);
        }
        return;
      case 'training.job.provision':
        if (event.op === 'snapshot') {
          const payload = event.payload as { provision_operation?: TrainingProvisionOperationStatusResponse | null };
          setProvisionOperationSnapshot(targetJobId, payload.provision_operation ?? null);
        }
        return;
      case 'training.job.metrics':
        if (event.op === 'snapshot') {
          setMetricsSnapshot(targetJobId, event.payload as MetricsResponse);
        }
        return;
      case 'training.job.operations':
        if (event.op === 'snapshot') {
          const payload = event.payload as { operations?: TrainingJobOperationStatusResponse[] };
          trainingJobOperations = payload.operations ?? [];
        }
        return;
      case 'training.job.logs':
        if (event.op === 'append') {
          const payload = event.payload as { lines?: string[] };
          appendLogLines(payload.lines ?? []);
          logStreamActive = true;
          if (streamStatus === 'connecting' || streamStatus === 'idle') {
            streamStatus = 'connected';
          }
          streamError = '';
          return;
        }
        if (event.op === 'control') {
          handleLogControlPayload(event.payload);
          return;
        }
        if (event.op === 'error') {
          logStreamActive = false;
          streamStatus = 'error';
          streamError = String(event.payload.message ?? 'ログストリーミングに失敗しました。');
        }
        return;
    }
  };

  const refresh = async () => {
    const refetches: Promise<unknown>[] = [];
    const refetchJob = $jobQuery?.refetch;
    if (typeof refetchJob === 'function') {
      refetches.push(refetchJob());
    }
    const refetchInstanceStatus = $instanceStatusQuery?.refetch;
    if (shouldQueryInstanceStatus && typeof refetchInstanceStatus === 'function') {
      refetches.push(refetchInstanceStatus());
    }
    if (refetches.length > 0) {
      await Promise.all(refetches);
    }
  };

  const stopJob = async () => {
    if (!jobId || !canStop) return;
    const confirmMessage = isRunning ? 'このジョブを停止しますか?' : 'このインスタンスを停止しますか?';
    if (!confirm(confirmMessage)) return;
    await api.training.stopJob(jobId);
    await refresh();
  };

  const deleteJob = async () => {
    if (!jobId || !canDelete) return;
    if (!confirm('このジョブを削除しますか？（リモートインスタンスも終了します）')) return;
    await api.training.deleteJob(jobId);
    await goto('/train');
  };

  const rescueCpuJob = async () => {
    if (!jobId || !canRescueCpu || rescueCpuInProgress) return;
    if (!confirm('このジョブの checkpoint 抽出のために CPU rescue を開始しますか？')) return;

    rescueCpuInProgress = true;
    rescueCpuPhase = '';
    rescueCpuMessage = '';
    rescueCpuError = '';
    rescueCpuProgressPercent = 0;
    rescueCpuElapsed = null;
    rescueCpuTimeout = null;
    rescueCpuResult = null;
    rescueCpuCopied = false;

    try {
      await api.training.startRescueCpuOperation(jobId);
      rescueCpuPhase = 'queued';
      rescueCpuMessage = 'CPU rescue の開始を受け付けました。';
      await refresh();
    } catch (error) {
      rescueCpuError = error instanceof Error ? error.message : 'CPU rescue に失敗しました。';
    }
  };

  const fetchRemoteCheckpoints = async () => {
    if (!jobId) return;
    remoteCheckpointLoading = true;
    remoteCheckpointError = '';
    remoteCheckpointMessage = '';
    try {
      const result = await api.training.remoteCheckpoints(jobId);
      remoteCheckpointRoot = result.checkpoint_root || '';
      remoteCheckpointNames = result.checkpoint_names ?? [];
      remoteCheckpointSshAvailable = result.ssh_available;
      remoteCheckpointRequiresRescueCpu = result.requires_rescue_cpu;
      remoteCheckpointMessage = result.message || '';
      if (remoteCheckpointNames.length === 0) {
        selectedRemoteCheckpoint = '';
      } else if (!remoteCheckpointNames.includes(selectedRemoteCheckpoint)) {
        selectedRemoteCheckpoint = remoteCheckpointNames[0];
      }
    } catch (error) {
      remoteCheckpointError =
        error instanceof Error ? error.message : 'リモートcheckpoint一覧の取得に失敗しました。';
      remoteCheckpointRoot = '';
      remoteCheckpointNames = [];
      selectedRemoteCheckpoint = '';
      remoteCheckpointSshAvailable = false;
      remoteCheckpointRequiresRescueCpu = false;
      remoteCheckpointMessage = '';
    } finally {
      remoteCheckpointLoading = false;
    }
  };

  const uploadSelectedCheckpoint = async () => {
    if (!jobId || !selectedRemoteCheckpoint || checkpointUploadInProgress || rescueCpuInProgress) return;
    if (!confirm(`checkpoint ${selectedRemoteCheckpoint} をR2へ登録しますか？`)) return;

    checkpointUploadInProgress = true;
    checkpointUploadPhase = '';
    checkpointUploadProgressPercent = 0;
    checkpointUploadMessage = '';
    checkpointUploadError = '';
    checkpointUploadResult = null;

    try {
      await api.training.startCheckpointUploadOperation(jobId, selectedRemoteCheckpoint);
      checkpointUploadPhase = 'queued';
      checkpointUploadMessage = 'チェックポイント登録の開始を受け付けました。';
      await refresh();
    } catch (error) {
      checkpointUploadError =
        error instanceof Error ? error.message : 'チェックポイントのR2登録に失敗しました。';
    }
  };

  const fetchLogs = async () => {
    await loadLogsSnapshot(jobId, logsType, logLines);
  };

  const fetchMetrics = async () => {
    if (!jobId) {
      return;
    }
    const refetch = $metricsQuery?.refetch;
    if (typeof refetch === 'function') {
      await refetch();
    }
  };

  const loadLogsSnapshot = async (
    nextJobId: string,
    nextLogsType: 'training' | 'setup',
    nextLogLines: number
  ) => {
    const requestKey = `${nextJobId}:${nextLogsType}`;
    logsError = '';
    if (!nextJobId) {
      logsError = 'ジョブIDが取得できません。';
      return;
    }
    logsLoading = true;
    try {
      const result = await api.training.logs(nextJobId, nextLogsType, nextLogLines);
      if (requestKey !== activeLogSnapshotKey) {
        return;
      }
      logs = (result as { logs?: string }).logs ?? '';
      logsSource = (result as { source?: string }).source ?? '';
    } catch (error) {
      if (requestKey !== activeLogSnapshotKey) {
        return;
      }
      logsError = error instanceof Error ? error.message : 'ログ取得に失敗しました。';
    } finally {
      if (requestKey === activeLogSnapshotKey) {
        logsLoading = false;
      }
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

  const copyRescueCpuSshCommand = async () => {
    if (!rescueCpuSshCommand) return;
    try {
      await navigator.clipboard.writeText(rescueCpuSshCommand);
      rescueCpuCopied = true;
      setTimeout(() => (rescueCpuCopied = false), 1500);
    } catch {
      rescueCpuCopied = false;
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

  const resetLogAppendState = () => {
    logStreamActive = false;
    streamError = '';
    streamLines = [];
    streamStatus = 'idle';
  };

  $effect(() => {
    if (!isRunning && logStreamActive) {
      logStreamActive = false;
      if (streamStatus === 'connected' || streamStatus === 'connecting') {
        streamStatus = 'stopped';
      }
    }
  });

  let lastJobId = '';
  $effect(() => {
    if (jobId && jobId !== lastJobId) {
      lastJobId = jobId;
      resetLogAppendState();
      logs = '';
      logsSource = '';
      logsError = '';
      rescueCpuInProgress = false;
      rescueCpuPhase = '';
      rescueCpuMessage = '';
      rescueCpuError = '';
      rescueCpuProgressPercent = 0;
      rescueCpuElapsed = null;
      rescueCpuTimeout = null;
      rescueCpuResult = null;
      rescueCpuCopied = false;
      rescueCpuOperationSnapshot = null;
      remoteCheckpointRoot = '';
      remoteCheckpointNames = [];
      selectedRemoteCheckpoint = '';
      remoteCheckpointLoading = false;
      remoteCheckpointError = '';
      remoteCheckpointMessage = '';
      remoteCheckpointSshAvailable = true;
      remoteCheckpointRequiresRescueCpu = false;
      checkpointUploadInProgress = false;
      checkpointUploadPhase = '';
      checkpointUploadProgressPercent = 0;
      checkpointUploadMessage = '';
      checkpointUploadError = '';
      checkpointUploadResult = null;
      checkpointUploadOperationSnapshot = null;
      trainingJobOperations = [];
    }
  });

  let realtimeContributor: TabRealtimeContributorHandle | null = null;

  $effect(() => {
    if (!browser || !jobId) {
      realtimeContributor?.dispose();
      realtimeContributor = null;
      resetLogAppendState();
      return;
    }

    const currentJobId = jobId;
    const currentLogsType = logsType;
    const registrationKey = `${currentJobId}:${currentLogsType}`;

    realtimeContributor?.dispose();
    realtimeContributor = null;
    resetLogAppendState();
    activeLogSnapshotKey = registrationKey;
    loadedLogSnapshotKey = '';

    streamStatus = shouldSubscribeLogStream ? 'connecting' : 'idle';
    realtimeContributor = registerTabRealtimeContributor({
      subscriptions: buildRealtimeSubscriptions(currentJobId, currentLogsType, logLines),
      onEvent: (event) => handleRealtimeEvent(currentJobId, registrationKey, event)
    });
    if (!realtimeContributor) {
      return;
    }

    return () => {
      realtimeContributor?.dispose();
      realtimeContributor = null;
      activeLogSnapshotKey = '';
      loadedLogSnapshotKey = '';
      logStreamActive = false;
    };
  });

  $effect(() => {
    if (!realtimeContributor || !jobId) {
      return;
    }
    realtimeContributor.setSubscriptions(buildRealtimeSubscriptions(jobId, logsType, logLines));
  });

  $effect(() => {
    const currentJobId = jobId;
    const currentJob = jobInfo;
    const currentStatus = status;
    const currentLogsType = logsType;
    if (!currentJobId || !currentJob) {
      return;
    }

    const shouldLoadSnapshot =
      !currentJob.ip || !['running', 'starting', 'deploying'].includes(currentStatus);
    if (!shouldLoadSnapshot) {
      return;
    }

    const snapshotKey = `${currentJobId}:${currentLogsType}`;
    if (loadedLogSnapshotKey === snapshotKey) {
      return;
    }
    loadedLogSnapshotKey = snapshotKey;
    activeLogSnapshotKey = snapshotKey;
    void loadLogsSnapshot(currentJobId, currentLogsType, logLines);
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
      <div class="nested-block p-4 text-sm text-slate-600">
        <p class="label">現在の状態</p>
        <div class="mt-2 space-y-1 text-xs text-slate-500">
          <p>job.status: <span class="font-semibold text-slate-800">{status || '-'}</span></p>
          <p>provision.state: <span class="font-semibold text-slate-800">{provisionOperation?.state ?? '-'}</span></p>
          <p>provision.step: <span class="font-semibold text-slate-800">{provisionStep || '-'}</span></p>
        </div>
      </div>
      <div class="nested-block p-4 text-sm text-slate-600">
        <p class="label">補足</p>
        <div class="mt-2 space-y-1 text-xs text-slate-500">
          <p class="font-semibold text-slate-800">{provisionOperation?.message ?? provisionStepLabel ?? '状態取得中'}</p>
          <p class="break-all">instance: {provisionOperation?.instance_id ?? '-'}</p>
          <p>updated: {formatDate(provisionOperation?.updated_at)}</p>
        </div>
        {#if provisionOperation?.failure_reason}
          <p class="mt-3 text-sm text-rose-600 break-words">{provisionOperation.failure_reason}</p>
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
        <div class="nested-block p-4 text-sm text-slate-600">
          <p class="label">ジョブID</p>
          <p class="mt-2 font-semibold text-slate-800">{jobInfo?.job_id ?? '-'}</p>
        </div>
        <div class="nested-block p-4 text-sm text-slate-600">
          <p class="label">ポリシー</p>
          <p class="mt-2 font-semibold text-slate-800">{jobInfo?.policy_type ?? '-'}</p>
        </div>
        <div class="nested-block p-4 text-sm text-slate-600">
          <p class="label">作成日時</p>
          <p class="mt-2 font-semibold text-slate-800">{formatDate(jobInfo?.created_at)}</p>
        </div>
        <div class="nested-block p-4 text-sm text-slate-600">
          <p class="label">開始日時</p>
          <p class="mt-2 font-semibold text-slate-800">{formatDate(jobInfo?.started_at)}</p>
        </div>
        <div class="nested-block p-4 text-sm text-slate-600">
          <p class="label">完了日時</p>
          <p class="mt-2 font-semibold text-slate-800">{formatDate(jobInfo?.completed_at)}</p>
        </div>
        <div class="nested-block p-4 text-sm text-slate-600">
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
            <div class="nested-block p-4">
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
            <div class="nested-block p-4 text-xs text-slate-600">
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
        <div class="nested-block p-4">
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
        <div class="nested-block p-4">
          <p class="label">ポリシー</p>
          <p class="mt-2 font-semibold text-slate-800">{trainingConfig?.policy?.type ?? '-'}</p>
          <p class="mt-1 text-xs text-slate-500">model: {selectedPolicyModelPath ?? '-'}</p>
        </div>
        <div class="nested-block p-4">
          <p class="label">学習</p>
          <p class="mt-2 font-semibold text-slate-800">
            steps: {trainingConfig?.training?.steps ?? '-'} / batch: {trainingConfig?.training?.batch_size ?? '-'}
          </p>
          <p class="mt-1 text-xs text-slate-500">
            save_freq: {trainingConfig?.training?.save_freq ?? '-'} / log_freq: {trainingConfig?.training?.log_freq ?? '-'}
          </p>
        </div>
        <div class="nested-block p-4">
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
        <div class="mt-4 nested-block p-4 text-sm text-slate-600">
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
        <Button.Root class="btn-primary" type="button" onclick={stopJob} disabled={!canStop}>
          {stopActionLabel}
        </Button.Root>
        {#if canRescueCpu}
          <Button.Root class="btn-ghost" type="button" onclick={rescueCpuJob} disabled={rescueCpuInProgress}>
            {rescueCpuInProgress ? 'CPU rescue 実行中...' : 'CPU rescue を開始'}
          </Button.Root>
        {/if}
      </div>
      <p class="mt-3 text-xs text-slate-500">
        停止はジョブまたは稼働中インスタンス、CPU rescue は終端ジョブの checkpoint 抽出用に有効化されます。
      </p>
      {#if isRunning}
        <div class="mt-3 flex items-center gap-2 text-xs text-slate-500">
          <span class="chip">ストリーミング更新</span>
          <span>進捗とステータスはストリーミングで更新します。</span>
        </div>
      {/if}
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">Checkpoint</h2>
      <p class="mt-2 text-sm text-slate-600">
        remote checkpoint を確認し、選択した step を R2 / DB に登録します。SSH 不可の終端ジョブでは CPU rescue を使います。
      </p>
      <div class="mt-4 nested-block-stack text-sm text-slate-600">
        <div class="nested-block p-4">
          <p class="label">checkpoint 候補</p>
          <p class="mt-2 text-xs text-slate-500">
            対象ジョブの remote checkpoint を取得して、保存する step を選択します。
          </p>
          <div class="mt-3 flex flex-wrap gap-2">
            <Button.Root class="btn-ghost" type="button" onclick={fetchRemoteCheckpoints} disabled={remoteCheckpointLoading || checkpointUploadInProgress || rescueCpuInProgress}>
              {remoteCheckpointLoading ? '候補取得中...' : '候補を取得'}
            </Button.Root>
            {#if remoteCheckpointRequiresRescueCpu}
              <Button.Root class="btn-ghost" type="button" onclick={rescueCpuJob} disabled={!canRescueCpu || rescueCpuInProgress || checkpointUploadInProgress}>
                {rescueCpuInProgress ? 'CPU rescue 実行中...' : 'CPU rescue を開始'}
              </Button.Root>
            {/if}
          </div>
          {#if remoteCheckpointRoot}
            <p class="mt-3 text-xs text-slate-500 break-all">root: {remoteCheckpointRoot}</p>
          {/if}
          {#if remoteCheckpointMessage}
            <p class="mt-3 text-sm text-slate-700">{remoteCheckpointMessage}</p>
          {/if}
          {#if remoteCheckpointError}
            <p class="mt-3 text-sm text-rose-600">{remoteCheckpointError}</p>
          {/if}
          {#if !remoteCheckpointLoading && !remoteCheckpointSshAvailable && remoteCheckpointRequiresRescueCpu}
            <p class="mt-3 text-xs text-slate-500">
              live SSH では取得できないため、CPU rescue で接続先を確保してから同じカードで登録します。
            </p>
          {/if}
          {#if remoteCheckpointNames.length}
            <label class="mt-3 block text-sm font-semibold text-slate-700">
              <span class="label">保存する checkpoint</span>
              <select class="input mt-2" bind:value={selectedRemoteCheckpoint} disabled={checkpointUploadInProgress || rescueCpuInProgress}>
                {#each remoteCheckpointNames as checkpointName}
                  <option value={checkpointName}>{checkpointName}</option>
                {/each}
              </select>
            </label>
            <div class="mt-3 flex flex-wrap gap-2">
              <Button.Root class="btn-primary" type="button" onclick={uploadSelectedCheckpoint} disabled={!selectedRemoteCheckpoint || checkpointUploadInProgress || rescueCpuInProgress}>
                {checkpointUploadInProgress ? 'R2 / DB 登録中...' : '選択した checkpoint を登録'}
              </Button.Root>
            </div>
          {:else if !remoteCheckpointLoading}
            <p class="mt-3 text-xs text-slate-500">候補はまだ取得されていません。</p>
          {/if}
        </div>

        {#if rescueCpuInProgress || rescueCpuPhase || rescueCpuResult || rescueCpuError}
          <div class="nested-block p-4">
            <div class="flex items-center justify-between gap-3">
              <p class="label">CPU rescue</p>
              <span class="chip">{Math.round(rescueCpuProgressPercent)}%</span>
            </div>
            <div class="mt-3 h-2 overflow-hidden rounded-full bg-slate-200/80">
              <div class="h-full bg-brand transition-all" style={`width: ${rescueCpuProgressPercent}%`}></div>
            </div>
            {#if rescueCpuPhase}
              <p class="mt-3 text-xs text-slate-500">phase: {rescueCpuPhase}</p>
            {/if}
            {#if rescueCpuElapsed !== null}
              <p class="mt-1 text-xs text-slate-500">
                経過: {rescueCpuElapsed}s{#if rescueCpuTimeout !== null} / {rescueCpuTimeout}s{/if}
              </p>
            {/if}
            {#if rescueCpuMessage}
              <p class="mt-2 text-sm text-slate-700">{rescueCpuMessage}</p>
            {/if}
            {#if rescueCpuError}
              <p class="mt-2 text-sm text-rose-600">{rescueCpuError}</p>
            {/if}
          </div>
        {/if}

        {#if checkpointUploadInProgress || checkpointUploadPhase || checkpointUploadResult || checkpointUploadError}
          <div class="nested-block p-4">
            <div class="flex items-center justify-between gap-3">
              <p class="label">checkpoint upload</p>
              <span class="chip">{Math.round(checkpointUploadProgressPercent)}%</span>
            </div>
            <div class="mt-3 h-2 overflow-hidden rounded-full bg-slate-200/80">
              <div class="h-full bg-brand transition-all" style={`width: ${checkpointUploadProgressPercent}%`}></div>
            </div>
            {#if checkpointUploadPhase}
              <p class="mt-3 text-xs text-slate-500">phase: {checkpointUploadPhase}</p>
            {/if}
            {#if checkpointUploadMessage}
              <p class="mt-2 text-sm text-slate-700">{checkpointUploadMessage}</p>
            {/if}
            {#if checkpointUploadError}
              <p class="mt-2 text-sm text-rose-600">{checkpointUploadError}</p>
            {/if}
          </div>
        {/if}

        {#if checkpointUploadResult}
          <div class="nested-block p-4">
            <p class="label">checkpoint 登録結果</p>
            <div class="mt-2 space-y-1 text-xs text-slate-600">
              <p>message: <span class="font-semibold text-slate-800">{checkpointUploadResult.message}</span></p>
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

        {#if rescueCpuResult}
          <div class="nested-block p-4">
            <p class="label">CPU rescue 結果</p>
            <div class="mt-2 space-y-1 text-xs text-slate-600">
              <p>message: <span class="font-semibold text-slate-800">{rescueCpuResult.message}</span></p>
              <p>旧インスタンスID: <span class="font-semibold text-slate-800 break-all">{rescueCpuResult.old_instance_id}</span></p>
              <p>新インスタンスID: <span class="font-semibold text-slate-800 break-all">{rescueCpuResult.instance_id}</span></p>
              <p>ストレージID: <span class="font-semibold text-slate-800 break-all">{rescueCpuResult.volume_id}</span></p>
              <p>インスタンスタイプ: <span class="font-semibold text-slate-800">{rescueCpuResult.instance_type}</span></p>
              <p>ロケーション: <span class="font-semibold text-slate-800">{rescueCpuResult.location}</span></p>
              <p>
                SSH接続先:
                <span class="font-semibold text-slate-800">
                  {#if rescueCpuResult.ssh_port && rescueCpuResult.ssh_port !== 22}
                    {rescueCpuResult.ip}:{rescueCpuResult.ssh_port}
                  {:else}
                    {rescueCpuResult.ip}
                  {/if}
                </span>
              </p>
              <p>SSHユーザー: <span class="font-semibold text-slate-800">{rescueCpuResult.ssh_user}</span></p>
              <p>SSH鍵: <span class="font-semibold text-slate-800 break-all">{rescueCpuResult.ssh_private_key}</span></p>
            </div>
            <div class="mt-3 nested-block-pane p-3 text-xs text-slate-600">
              <p class="label">SSHコマンド</p>
              <p class="mt-2 font-semibold text-slate-800 break-all">{rescueCpuSshCommand || '-'}</p>
            </div>
            <div class="mt-3 flex flex-wrap gap-2">
              <Button.Root class="btn-ghost" type="button" onclick={copyRescueCpuSshCommand} disabled={!rescueCpuSshCommand}>
                SSHコマンドをコピー
              </Button.Root>
              {#if rescueCpuCopied}
                <span class="chip">コピーしました</span>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">ログ</h2>
      <div class="mt-4 grid gap-3 text-sm text-slate-600">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ログ種別</span>
          <select class="input mt-2" bind:value={logsType}>
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
            <span class="chip">状態: {streamStatus}</span>
            <span class="chip">{logStreamActive ? 'live' : 'idle'}</span>
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
      <div class="mt-4 nested-block p-4 text-xs text-slate-600">
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

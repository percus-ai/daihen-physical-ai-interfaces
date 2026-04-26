<script lang="ts">
  import { browser } from '$app/environment';
  import { toStore } from 'svelte/store';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import CopyableDetailField from '$lib/components/training/CopyableDetailField.svelte';
  import LossChart from '$lib/components/training/LossChart.svelte';
  import {
    api,
    type CheckpointDetailResponse,
    type RemoteCheckpointListResponse,
    type RemoteCheckpointUploadResult,
    type RescueCPUResult,
    type TrainingJobOperationStatusResponse,
    type TrainingProvisionOperationStatusResponse
  } from '$lib/api/client';
  import { formatDate, formatDurationMs, formatElapsedDuration, formatUuidPreview } from '$lib/format';
  import { getGpuModelLabel } from '$lib/policies';
  import {
    registerRealtimeTrackConsumer,
    type RealtimeTrackConsumerHandle,
    type RealtimeTrackEvent,
    type RealtimeTrackSelector
  } from '$lib/realtime/trackClient';
  import { queryClient } from '$lib/queryClient';
  import { formatStepValue, type CheckpointMarker, type CheckpointMarkerStatus } from '$lib/training/lossChart';
  import { estimateTrainingEta } from '$lib/training/trainingEta';

  type JobInfo = {
    job_id?: string;
    job_name?: string;
    instance_id?: string;
    status?: string;
    dataset_id?: string;
    dataset_name?: string;
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
      save_checkpoint?: boolean;
      drop_last?: boolean;
      persistent_workers?: boolean;
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
      enabled: false
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
  let rescueCpuOperationSnapshot: TrainingJobOperationStatusResponse | null = $state(null);
  let remoteCheckpointRoot = $state('');
  let remoteCheckpointNames: string[] = $state([]);
  let selectedRemoteCheckpoint = $state('');
  let remoteCheckpointLoading = $state(false);
  let remoteCheckpointError = $state('');
  let remoteCheckpointMessage = $state('');
  let remoteCheckpointSshAvailable = $state(true);
  let remoteCheckpointRequiresRescueCpu = $state(false);
  let remoteCheckpointRequested = $state(false);
  let remoteCheckpointRequestActive = false;
  let remoteCheckpointSummaryKey = $state('');
  let checkpointUploadInProgress = $state(false);
  let checkpointUploadPhase = $state('');
  let checkpointUploadProgressPercent = $state(0);
  let checkpointUploadMessage = $state('');
  let checkpointUploadError = $state('');
  let checkpointUploadResult: RemoteCheckpointUploadResult | null = $state(null);
  let checkpointUploadOperationSnapshot: TrainingJobOperationStatusResponse | null = $state(null);
  let trainingJobOperations: TrainingJobOperationStatusResponse[] = $state([]);
  let nowMs = $state(Date.now());

  type MetricPoint = { step?: number; loss?: number; ts?: string };
  let activeLogSnapshotKey = $state('');
  let loadedLogSnapshotKey = $state('');
  let lastAutoLogStatus = $state('');

  const parseCheckpointStep = (value: unknown): number | null => {
    if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
      return Math.floor(value);
    }
    const parsed = Number(String(value ?? '').trim());
    if (!Number.isFinite(parsed) || parsed <= 0) return null;
    return Math.floor(parsed);
  };

  const buildPlannedCheckpointSteps = (saveFreq: number | null, totalSteps: number | null): number[] => {
    if (!saveFreq || !totalSteps || saveFreq <= 0 || totalSteps <= 0) return [];
    const steps: number[] = [];
    for (let step = saveFreq; step <= totalSteps; step += saveFreq) {
      steps.push(step);
    }
    return steps;
  };

  const jobInfo = $derived($jobQuery.data?.job);
  const provisionOperation = $derived($jobQuery.data?.provision_operation ?? null);
  const trainingConfig = $derived($jobQuery.data?.training_config ?? {});
  const checkpointDetailQuery = createQuery<CheckpointDetailResponse | null>(
    toStore(() => {
      const checkpointJobName = String(jobInfo?.job_name ?? '').trim();
      return {
        queryKey: ['training', 'checkpoint-detail', checkpointJobName],
        queryFn: async () => {
          if (!checkpointJobName) return null;
          try {
            return await api.training.checkpointDetail(checkpointJobName);
          } catch {
            return null;
          }
        },
        enabled: Boolean(checkpointJobName),
        retry: false
      };
    })
  );
  const summary = $derived($jobQuery.data?.summary ?? {});
  const metrics = $derived($metricsQuery.data ?? null);
  const checkpointDetail = $derived($checkpointDetailQuery.data ?? null);
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
  const datasetName = $derived(jobInfo?.dataset_name ?? '');
  const datasetId = $derived(trainingConfig?.dataset?.id ?? jobInfo?.dataset_id ?? '');
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
  const totalTrainingSteps = $derived(
    typeof trainingConfig?.training?.steps === 'number' && trainingConfig.training.steps > 0
      ? trainingConfig.training.steps
      : null
  );
  const latestTrainPoint = $derived(trainSeries.length ? trainSeries[trainSeries.length - 1] : null);
  const currentStepLabel = $derived(
    latestTrainPoint
      ? `${formatStepValue(latestTrainPoint.step)} / ${totalTrainingSteps ? formatStepValue(totalTrainingSteps) : '-'}`
      : '-'
  );
  const remainingTrainingSteps = $derived(
    totalTrainingSteps && latestTrainPoint
      ? Math.max(0, Math.ceil(totalTrainingSteps - latestTrainPoint.step))
      : null
  );
  const remainingTrainingStepsLabel = $derived(
    remainingTrainingSteps === null ? '-' : `${formatStepValue(remainingTrainingSteps)} step`
  );
  const checkpointSaveEnabled = $derived(trainingConfig?.training?.save_checkpoint !== false);
  const checkpointSaveFrequency = $derived(
    typeof trainingConfig?.training?.save_freq === 'number' && trainingConfig.training.save_freq > 0
      ? trainingConfig.training.save_freq
      : null
  );
  const remoteSavedCheckpointSteps = $derived.by<Set<number>>(() => {
    return new Set(
      remoteCheckpointNames
        .map((name) => parseCheckpointStep(name))
        .filter((step): step is number => step !== null)
    );
  });
  const uploadedCheckpointSteps = $derived.by<Set<number>>(() => {
    const steps = new Set<number>();
    for (const step of checkpointDetail?.available_steps ?? []) {
      const parsed = parseCheckpointStep(step);
      if (parsed !== null) steps.add(parsed);
    }
    const resultStep = parseCheckpointStep(checkpointUploadResult?.step);
    if (resultStep !== null) steps.add(resultStep);
    return steps;
  });
  const activeCheckpointUploadStep = $derived.by<number | null>(() => {
    if (!checkpointUploadInProgress) return null;
    return (
      parseCheckpointStep(checkpointUploadOperationSnapshot?.detail?.step) ??
      parseCheckpointStep(checkpointUploadOperationSnapshot?.detail?.checkpoint_name) ??
      parseCheckpointStep(selectedRemoteCheckpoint)
    );
  });
  const checkpointMarkers = $derived.by<CheckpointMarker[]>(() => {
    if (!checkpointSaveEnabled) return [];
    return buildPlannedCheckpointSteps(checkpointSaveFrequency, totalTrainingSteps).map((step) => {
      let markerStatus: CheckpointMarkerStatus = 'pending';
      if (remoteSavedCheckpointSteps.has(step) || (latestTrainPoint?.step ?? 0) >= step) {
        markerStatus = 'saved';
      }
      if (uploadedCheckpointSteps.has(step)) {
        markerStatus = 'uploaded';
      }
      if (activeCheckpointUploadStep === step) {
        markerStatus = 'uploading';
      }
      return { step, status: markerStatus };
    });
  });
  const trainingEta = $derived(estimateTrainingEta(metrics?.train ?? [], totalTrainingSteps, nowMs));
  const estimatedRemainingTimeLabel = $derived(
    trainingEta ? formatDurationMs(trainingEta.estimatedRemainingMs) : '-'
  );
  const estimatedCompletionAtLabel = $derived(
    trainingEta ? formatDate(new Date(trainingEta.estimatedEndMs).toISOString()) : '-'
  );
  const trainingProgressPercent = $derived(
    totalTrainingSteps && latestTrainPoint
      ? Math.min(100, Math.max(0, (latestTrainPoint.step / totalTrainingSteps) * 100))
      : null
  );

  const liveJobStatuses = ['queued', 'starting', 'deploying', 'running'];
  const terminalJobStatuses = ['completed', 'failed', 'stopped', 'terminated', 'cancelled', 'deleted'];
  const isTerminal = $derived(terminalJobStatuses.includes(status));
  const isRunning = $derived(['running', 'starting', 'deploying'].includes(status));
  const jobRuntime = $derived(
    formatElapsedDuration(jobInfo?.started_at, jobInfo?.completed_at, isRunning ? nowMs : undefined)
  );
  const completionTimeBlockLabel = $derived(isTerminal ? '完了日時 (JST)' : '予測完了 (JST)');
  const completionTimeBlockValue = $derived(
    isTerminal ? formatDate(jobInfo?.completed_at) : estimatedCompletionAtLabel
  );
  const policyType = $derived(trainingConfig?.policy?.type ?? jobInfo?.policy_type ?? '');
  const effectiveGpuModel = $derived(trainingConfig?.cloud?.gpu_model ?? jobInfo?.gpu_model ?? '');
  const effectiveGpuCount = $derived(
    trainingConfig?.cloud?.gpus_per_instance ?? jobInfo?.gpus_per_instance ?? null
  );
  const gpuDisplay = $derived(
    effectiveGpuModel ? `${getGpuModelLabel(effectiveGpuModel)} x ${effectiveGpuCount ?? 1}` : '-'
  );
  const gpuModelDisplay = $derived(effectiveGpuModel ? getGpuModelLabel(effectiveGpuModel) : '-');
  const cloudProviderDisplay = $derived(
    provider === 'vast' ? 'Vast.ai' : provider === 'verda' ? 'Verda' : provider || '-'
  );
  const cloudModeDisplay = $derived(
    trainingConfig?.cloud?.selected_mode === 'spot'
      ? 'スポット'
      : trainingConfig?.cloud?.selected_mode === 'ondemand'
        ? 'オンデマンド'
        : '-'
  );
  const cloudStorageDisplay = $derived(
    trainingConfig?.cloud?.storage_size ? `${trainingConfig.cloud.storage_size} GB` : '-'
  );
  const selectedInstanceDisplay = $derived(
    trainingConfig?.cloud?.selected_instance_type ??
      (trainingConfig?.cloud?.selected_offer_id
        ? `オファー ${trainingConfig.cloud.selected_offer_id}`
        : '-')
  );
  const videoBackendDisplay = $derived(
    !trainingConfig?.dataset?.video_backend || trainingConfig.dataset.video_backend === 'auto'
      ? '自動'
      : trainingConfig.dataset.video_backend
  );
  const jobStatusLabels: Record<string, string> = {
    queued: '待機中',
    starting: '開始中',
    deploying: '準備中',
    running: '実行中',
    completed: '完了',
    failed: '失敗',
    stopped: '停止',
    terminated: '終了',
    cancelled: 'キャンセル',
    deleted: '削除済み'
  };
  const jobStatusDisplay = $derived(status ? (jobStatusLabels[status] ?? status) : '-');
  const streamStatusLabels: Record<string, string> = {
    idle: '待機中',
    connecting: '接続中',
    connected: '接続済み',
    ended: '終了',
    stopped: '停止',
    running: '実行中',
    job_deleted: 'ジョブ削除済み',
    job_missing: 'ジョブなし',
    ip_missing: 'IP未取得',
    stream_ended: '終了'
  };
  const streamStatusDisplay = $derived(streamStatusLabels[streamStatus] ?? streamStatus);
  const compactInstanceId = $derived(formatUuidPreview(jobInfo?.instance_id));
  const compactProfileId = $derived(formatUuidPreview(profileId));
  const shouldSubscribeJobRealtime = $derived(
    Boolean(jobId) && (!status || liveJobStatuses.includes(status) || !terminalJobStatuses.includes(status))
  );
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
    isRunning ? 'ジョブとインスタンスを停止' : hasLiveInstance ? 'インスタンスを停止' : '停止不可'
  );
  const canDelete = $derived(['completed', 'failed', 'stopped', 'terminated'].includes(status));
  const canRescueCpu = $derived(
    provider === 'verda' && ['completed', 'failed', 'stopped', 'terminated'].includes(status)
  );
  const shouldSubscribeLogStream = $derived(isRunning);
  const shouldLoadLogSnapshot = $derived(isTerminal);
  const provisionStepLabels: Record<string, string> = {
    queued: '開始待ち',
    validate: '設定検証',
    select_candidate: '候補確認',
    create_instance: 'インスタンス作成',
    job_created: 'ジョブ作成',
    wait_ip: 'IP割り当て待機',
    connect_ssh: '接続確認',
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

  $effect(() => {
    if (!browser || !isRunning) {
      return;
    }

    nowMs = Date.now();
    const timer = window.setInterval(() => {
      nowMs = Date.now();
    }, 30_000);

    return () => {
      window.clearInterval(timer);
    };
  });

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

  const applyRemoteCheckpointCandidates = (result: RemoteCheckpointListResponse) => {
    remoteCheckpointRoot = result.checkpoint_root || '';
    remoteCheckpointNames = result.checkpoint_names ?? [];
    remoteCheckpointSshAvailable = result.ssh_available;
    remoteCheckpointRequiresRescueCpu = result.requires_rescue_cpu;
    remoteCheckpointMessage = result.message || '';
    remoteCheckpointRequested = true;
    if (remoteCheckpointNames.length === 0) {
      selectedRemoteCheckpoint = '';
    } else if (!remoteCheckpointNames.includes(selectedRemoteCheckpoint)) {
      selectedRemoteCheckpoint = remoteCheckpointNames[0];
    }
  };

  const remoteCheckpointCandidatesFromSummary = (
    value: Record<string, unknown> | null | undefined
  ): RemoteCheckpointListResponse | null => {
    const state = value?.remote_checkpoint_candidates;
    if (!state || typeof state !== 'object' || Array.isArray(state)) return null;
    const record = state as Record<string, unknown>;
    const rawNames = Array.isArray(record.checkpoint_names) ? record.checkpoint_names : [];
    const checkpointNames = rawNames
      .map((name) => String(name ?? '').trim())
      .filter((name) => /^\d+$/.test(name))
      .sort((left, right) => Number(left) - Number(right));
    return {
      job_id: String(record.job_id ?? jobId),
      checkpoint_names: checkpointNames,
      checkpoint_root: String(record.checkpoint_root ?? ''),
      ssh_available: record.ssh_available !== false,
      requires_rescue_cpu: Boolean(record.requires_rescue_cpu),
      message: String(record.message ?? '')
    };
  };

  $effect(() => {
    const candidates = remoteCheckpointCandidatesFromSummary(summary);
    if (!candidates) return;
    const nextKey = JSON.stringify(candidates);
    if (remoteCheckpointSummaryKey === nextKey) return;
    remoteCheckpointSummaryKey = nextKey;
    applyRemoteCheckpointCandidates(candidates);
  });

  const setJobDetailSnapshot = (targetJobId: string, snapshot: JobDetailResponse) => {
    if (!targetJobId) return;
    queryClient.setQueryData<JobDetailResponse>(['training', 'job', targetJobId], snapshot);
    const candidates = remoteCheckpointCandidatesFromSummary(snapshot.summary);
    if (candidates) {
      remoteCheckpointSummaryKey = JSON.stringify(candidates);
      applyRemoteCheckpointCandidates(candidates);
    }
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
      void fetchRemoteCheckpoints({ silent: true });
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
      void fetchRemoteCheckpoints({ silent: true });
    }

  };

  const buildRealtimeTracks = (
    targetJobId: string,
    nextLogsType: 'training' | 'setup'
  ): RealtimeTrackSelector[] => {
    const coreTrack: RealtimeTrackSelector = {
      kind: 'training.job.core',
      params: { job_id: targetJobId }
    };
    const provisionTrack: RealtimeTrackSelector = {
      kind: 'training.job.provision',
      params: { job_id: targetJobId }
    };
    const metricsTrack: RealtimeTrackSelector = {
      kind: 'training.job.metrics',
      params: { job_id: targetJobId, limit: 2000 }
    };
    const tracks: RealtimeTrackSelector[] = shouldSubscribeJobRealtime
      ? [
          coreTrack,
          provisionTrack,
          metricsTrack
        ]
      : [];
    if (shouldSubscribeLogStream) {
      const logsTrack: RealtimeTrackSelector = {
        kind: 'training.job.logs',
        params: {
          job_id: targetJobId,
          log_type: nextLogsType
        }
      };
      tracks.push(logsTrack);
    }
    const operationsTrack: RealtimeTrackSelector = {
      kind: 'training.job.operations',
      params: { job_id: targetJobId }
    };
    tracks.push(operationsTrack);
    return tracks;
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
    if (type === 'job_deleted' || type === 'job_missing' || type === 'ip_missing') {
      logStreamActive = false;
      streamStatus = type;
      streamError = `ログストリームが終了しました: ${type}`;
    }
  };

  const handleRealtimeEvent = (
    targetJobId: string,
    registrationKey: string,
    event: RealtimeTrackEvent
  ) => {
    switch (event.kind) {
      case 'training.job.core':
        setJobDetailSnapshot(targetJobId, event.detail as JobDetailResponse);
        return;
      case 'training.job.provision':
        {
          const payload = event.detail as { provision_operation?: TrainingProvisionOperationStatusResponse | null };
          setProvisionOperationSnapshot(targetJobId, payload.provision_operation ?? null);
        }
        return;
      case 'training.job.metrics':
        setMetricsSnapshot(targetJobId, event.detail as MetricsResponse);
        return;
      case 'training.job.operations':
        {
          const payload = event.detail as { operations?: TrainingJobOperationStatusResponse[] };
          trainingJobOperations = payload.operations ?? [];
        }
        return;
      case 'training.job.logs':
        if (event.key !== registrationKey || registrationKey !== `${jobId}:${logsType}`) {
          return;
        }
        if (Array.isArray(event.detail.lines)) {
          const payload = event.detail as { lines?: string[] };
          logs = '';
          logsSource = '';
          streamLines = [...(payload.lines ?? [])].slice(-200);
          logStreamActive = true;
          if (streamStatus === 'connecting' || streamStatus === 'idle') {
            streamStatus = 'connected';
          }
          streamError = '';
          return;
        }
        if (event.detail.error || event.detail.failure_reason) {
          logStreamActive = false;
          streamStatus = 'error';
          streamError = String(event.detail.message ?? 'ログストリーミングに失敗しました。');
          return;
        }
        handleLogControlPayload(event.detail);
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
    const refetchCheckpointDetail = $checkpointDetailQuery?.refetch;
    if (typeof refetchCheckpointDetail === 'function') {
      refetches.push(refetchCheckpointDetail());
    }
    if (refetches.length > 0) {
      await Promise.all(refetches);
    }
  };

  const stopJob = async () => {
    if (!jobId || !canStop) return;
    const confirmMessage = isRunning ? 'このジョブとインスタンスを停止しますか?' : 'このインスタンスを停止しますか?';
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
    if (!confirm('このジョブのチェックポイント抽出のためにCPUレスキューを開始しますか？')) return;

    rescueCpuInProgress = true;
    rescueCpuPhase = '';
    rescueCpuMessage = '';
    rescueCpuError = '';
    rescueCpuProgressPercent = 0;
    rescueCpuElapsed = null;
    rescueCpuTimeout = null;
    rescueCpuResult = null;

    try {
      await api.training.startRescueCpuOperation(jobId);
      rescueCpuPhase = 'queued';
      rescueCpuMessage = 'CPUレスキューの開始を受け付けました。';
      await refresh();
    } catch (error) {
      rescueCpuError = error instanceof Error ? error.message : 'CPUレスキューに失敗しました。';
    }
  };

  const fetchRemoteCheckpoints = async (options: { silent?: boolean; rescan?: boolean } = {}) => {
    if (!jobId) return;
    if (remoteCheckpointLoading || remoteCheckpointRequestActive) return;
    remoteCheckpointRequestActive = true;
    const shouldShowLoading =
      !options.silent || (!remoteCheckpointNames.length && !remoteCheckpointMessage && !remoteCheckpointError);
    if (shouldShowLoading) {
      remoteCheckpointLoading = true;
    }
    remoteCheckpointError = '';
    remoteCheckpointMessage = '';
    remoteCheckpointRequested = true;
    try {
      const result = options.rescan
        ? await api.training.rescanRemoteCheckpoints(jobId)
        : await api.training.remoteCheckpoints(jobId);
      applyRemoteCheckpointCandidates(result);
    } catch (error) {
      remoteCheckpointError =
        error instanceof Error ? error.message : 'リモートチェックポイント一覧の取得に失敗しました。';
      remoteCheckpointRoot = '';
      remoteCheckpointNames = [];
      selectedRemoteCheckpoint = '';
      remoteCheckpointSshAvailable = false;
      remoteCheckpointRequiresRescueCpu = false;
      remoteCheckpointMessage = '';
    } finally {
      if (shouldShowLoading) {
        remoteCheckpointLoading = false;
      }
      remoteCheckpointRequestActive = false;
    }
  };

  const uploadSelectedCheckpoint = async () => {
    if (!jobId || !selectedRemoteCheckpoint || checkpointUploadInProgress || rescueCpuInProgress) return;
    if (!confirm(`チェックポイント ${selectedRemoteCheckpoint} をR2へ登録しますか？`)) return;

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

  const startRealtimeLogStream = async (
    targetJobId: string,
    targetLogsType: 'training' | 'setup',
    registrationKey: string
  ) => {
    try {
      await api.training.startLogStream(targetJobId, targetLogsType);
    } catch (error) {
      if (registrationKey !== activeLogSnapshotKey) {
        return;
      }
      logStreamActive = false;
      streamStatus = 'error';
      streamError = error instanceof Error ? error.message : 'ログストリームの開始に失敗しました。';
    }
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
      lastAutoLogStatus = '';
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
      rescueCpuOperationSnapshot = null;
      remoteCheckpointRoot = '';
      remoteCheckpointNames = [];
      selectedRemoteCheckpoint = '';
      remoteCheckpointLoading = false;
      remoteCheckpointError = '';
      remoteCheckpointMessage = '';
      remoteCheckpointSshAvailable = true;
      remoteCheckpointRequiresRescueCpu = false;
      remoteCheckpointRequested = false;
      remoteCheckpointRequestActive = false;
      remoteCheckpointSummaryKey = '';
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

  $effect(() => {
    if (!status || status === lastAutoLogStatus) {
      return;
    }
    lastAutoLogStatus = status;
    if (status === 'starting') {
      logsType = 'setup';
      return;
    }
    if (status === 'running') {
      logsType = 'training';
    }
  });

  let realtimeContributor: RealtimeTrackConsumerHandle | null = null;

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
    logs = '';
    logsSource = '';
    logsError = '';
    activeLogSnapshotKey = registrationKey;
    loadedLogSnapshotKey = '';

    streamStatus = shouldSubscribeLogStream ? 'connecting' : 'idle';
    realtimeContributor = registerRealtimeTrackConsumer({
      tracks: buildRealtimeTracks(currentJobId, currentLogsType),
      onEvent: (event) => handleRealtimeEvent(currentJobId, registrationKey, event)
    });
    if (!realtimeContributor) {
      return;
    }
    if (shouldSubscribeLogStream) {
      void startRealtimeLogStream(currentJobId, currentLogsType, registrationKey);
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
    realtimeContributor.setTracks(buildRealtimeTracks(jobId, logsType));
  });

  $effect(() => {
    const currentJobId = jobId;
    const currentJob = jobInfo;
    const currentLogsType = logsType;
    if (!currentJobId || !currentJob) {
      return;
    }

    const snapshotKey = `${currentJobId}:${currentLogsType}`;
    if (!shouldLoadLogSnapshot) {
      return;
    }
    if (loadedLogSnapshotKey === snapshotKey) {
      return;
    }
    loadedLogSnapshotKey = snapshotKey;
    activeLogSnapshotKey = snapshotKey;
    void loadLogsSnapshot(currentJobId, currentLogsType, logLines);
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">学習</p>
  <div class="mt-2 flex flex-wrap items-start justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">学習ジョブ詳細</h1>
      <p class="mt-2 text-sm text-slate-600">
        {jobInfo?.job_name ?? 'ジョブ名取得中...'}
      </p>
      <div class="mt-3 flex flex-wrap gap-2">
        <span class="chip">{jobStatusDisplay}</span>
        {#if effectiveGpuModel}
          <span class="chip">{gpuDisplay}</span>
        {/if}
        {#if datasetId}
          <span class="chip">{datasetId}</span>
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
  <section class="card min-w-0 p-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="section-title">作成進行</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-900">作成進行カード</h2>
        <p class="mt-2 text-sm text-slate-600">
          {provisionTip}
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <span class="chip">ジョブ: {jobStatusDisplay}</span>
        <span class="chip">手順: {provisionStepLabel || provisionStep || '-'}</span>
        {#if provisionOperation?.provider}
          <span class="chip">クラウド: {provisionOperation.provider}</span>
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
          <p class="break-all" title={provisionOperation?.instance_id ?? ''}>
            instance: {formatUuidPreview(provisionOperation?.instance_id)}
          </p>
          <p>updated: {formatDate(provisionOperation?.updated_at)}</p>
        </div>
        {#if provisionOperation?.failure_reason}
          <p class="mt-3 text-sm text-rose-600 break-words">{provisionOperation.failure_reason}</p>
        {/if}
      </div>
    </div>
  </section>
{/if}

<section class="min-w-0 space-y-6">
  <section class="card min-w-0 p-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="section-title">監視</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-900">実行状況</h2>
      </div>
      <div class="flex flex-wrap gap-2">
        <span class="chip">{jobStatusDisplay}</span>
        <span class="chip">{gpuDisplay}</span>
      </div>
    </div>

    <div class="mt-5 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      <div class="nested-block p-4 text-sm text-slate-600">
        <p class="label">現在ステップ</p>
        <p class="mt-2 text-lg font-semibold text-slate-900">{currentStepLabel}</p>
      </div>
      <div class="nested-block p-4 text-sm text-slate-600">
        <p class="label">残りステップ</p>
        <p class="mt-2 text-lg font-semibold text-slate-900">{remainingTrainingStepsLabel}</p>
      </div>
      <div class="nested-block p-4 text-sm text-slate-600">
        <p class="label">実行時間</p>
        <p class="mt-2 text-lg font-semibold text-slate-900">{jobRuntime}</p>
      </div>
      <div class="nested-block p-4 text-sm text-slate-600">
        <p class="label">残り時間（推定）</p>
        <p class="mt-2 text-lg font-semibold text-slate-900">{estimatedRemainingTimeLabel}</p>
      </div>
      <div class="nested-block p-4 text-sm text-slate-600">
        <p class="label">開始日時 (JST)</p>
        <p class="mt-2 font-semibold text-slate-900">{formatDate(jobInfo?.started_at)}</p>
      </div>
      <div class="nested-block p-4 text-sm text-slate-600">
        <p class="label">{completionTimeBlockLabel}</p>
        <p class="mt-2 font-semibold text-slate-900">{completionTimeBlockValue}</p>
      </div>
    </div>

    {#if trainingProgressPercent !== null}
      <div class="mt-4">
        <div class="flex items-center justify-between text-xs font-semibold text-slate-500">
          <span>進捗</span>
          <span>{trainingProgressPercent.toFixed(1)}%</span>
        </div>
        <div class="mt-2 h-2 overflow-hidden rounded-full bg-slate-200/80">
          <div class="h-full bg-brand transition-all" style={`width: ${trainingProgressPercent}%`}></div>
        </div>
      </div>
    {/if}
  </section>

  <section class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-xl font-semibold text-slate-900">loss推移</h2>
      </div>
      <div class="flex flex-wrap items-center gap-4">
        <div class="flex flex-wrap items-center gap-4 text-xs text-slate-500">
          <span class="flex items-center gap-2">
            <span class="h-2 w-2 rounded-full bg-brand"></span>
            学習 loss
          </span>
          <span class="flex items-center gap-2">
            <span class="h-2 w-2 rounded-full bg-orange-400"></span>
            検証 loss
          </span>
          <span class="flex items-center gap-2">
            <span class="h-4 border-l-2 border-dashed border-slate-300"></span>
            未保存
          </span>
          <span class="flex items-center gap-2">
            <span class="h-4 border-l-2 border-dashed border-orange-400"></span>
            保存済み
          </span>
          <span class="flex items-center gap-2">
            <span class="h-4 border-l-2 border-dashed border-sky-500"></span>
            アップロード中
          </span>
          <span class="flex items-center gap-2">
            <span class="h-4 border-l-2 border-dashed border-emerald-500"></span>
            アップロード済み
          </span>
        </div>
        <Button.Root class="btn-ghost" type="button" onclick={fetchMetrics} disabled={metricsLoading}>
          {metricsLoading ? '取得中...' : '更新'}
        </Button.Root>
      </div>
    </div>
    {#if metricsError}
      <p class="mt-3 text-sm text-rose-600">{metricsError}</p>
    {:else}
      <div class="mt-4 nested-block p-3">
        <LossChart
          trainSeries={trainSeries}
          valSeries={valSeries}
          totalSteps={totalTrainingSteps}
          checkpointMarkers={checkpointMarkers}
        />
      </div>
    {/if}
  </section>

  <section class="card p-6">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-xl font-semibold text-slate-900">ログ内容</h2>
        <p class="mt-1 text-sm text-slate-500">
          {logsType === 'training' ? '学習ログ' : 'セットアップログ'}{#if logsSource === 'r2'} / R2{/if}
        </p>
      </div>
      <div class="flex flex-wrap items-end gap-3 text-sm text-slate-600">
        <label class="min-w-[160px] text-sm font-semibold text-slate-700">
          <span class="label">ログ種別</span>
          <select class="input mt-2" bind:value={logsType}>
            <option value="training">学習ログ</option>
            <option value="setup">セットアップログ</option>
          </select>
        </label>
        <label class="w-28 text-sm font-semibold text-slate-700">
          <span class="label">取得行数</span>
          <input class="input mt-2" type="number" min="1" bind:value={logLines} />
        </label>
        <Button.Root class="btn-ghost" type="button" onclick={fetchLogs} disabled={logsLoading}>
          {logsLoading ? '取得中...' : 'ログを取得'}
        </Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={downloadLogs}>
          ダウンロード
        </Button.Root>
        <div class="flex flex-wrap gap-2 pb-1">
          <span class="chip">状態: {streamStatusDisplay}</span>
          <span class="chip">{logStreamActive ? 'ライブ' : '待機中'}</span>
        </div>
      </div>
    </div>
    <div class="mt-4 min-w-0 max-w-full space-y-4 text-sm text-slate-600">
      {#if logsError}
        <p class="text-sm text-rose-600">{logsError}</p>
      {/if}
      {#if streamError}
        <p class="text-sm text-rose-600">{streamError}</p>
      {/if}
      {#if displayedLogs}
        <div class="nested-block min-w-0 max-w-full overflow-hidden p-0 text-xs text-slate-600">
          <pre class="block max-h-[560px] w-full min-w-0 overflow-y-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-relaxed text-slate-700">{displayedLogs}</pre>
        </div>
      {:else if logsLoading}
        <p class="text-sm text-slate-500">ログを取得しています。</p>
      {:else}
        <p class="text-sm text-slate-500">ログは未取得です。</p>
      {/if}
    </div>
  </section>

  <section class="card p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-xl font-semibold text-slate-900">操作</h2>
      </div>
      <div class="flex flex-wrap gap-2">
        <span class="chip">{remoteCheckpointLoading ? '候補更新中' : `候補 ${remoteCheckpointNames.length}件`}</span>
        {#if checkpointUploadInProgress}
          <span class="chip">登録 {Math.round(checkpointUploadProgressPercent)}%</span>
        {/if}
      </div>
    </div>

    <div class="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.125fr)_minmax(320px,0.75fr)]">
      <section class="nested-block p-4 text-sm text-slate-600">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h3 class="text-base font-semibold text-slate-900">チェックポイント</h3>
          <Button.Root class="btn-ghost" type="button" onclick={() => fetchRemoteCheckpoints({ rescan: true })} disabled={remoteCheckpointLoading || checkpointUploadInProgress || rescueCpuInProgress}>
            {remoteCheckpointLoading ? '更新中' : '再取得'}
          </Button.Root>
        </div>

        {#if remoteCheckpointError}
          <p class="mt-3 text-sm text-rose-600">{remoteCheckpointError}</p>
        {:else if remoteCheckpointMessage}
          <p class="mt-3 text-sm text-slate-600">{remoteCheckpointMessage}</p>
        {/if}

        {#if !remoteCheckpointLoading && !remoteCheckpointSshAvailable && remoteCheckpointRequiresRescueCpu}
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <span class="chip">CPUレスキューが必要</span>
            <Button.Root class="btn-ghost" type="button" onclick={rescueCpuJob} disabled={!canRescueCpu || rescueCpuInProgress || checkpointUploadInProgress}>
              {rescueCpuInProgress ? '起動中' : 'CPUレスキュー'}
            </Button.Root>
          </div>
        {/if}

        {#if remoteCheckpointNames.length}
          <div class="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
            <label class="min-w-0 text-sm font-semibold text-slate-700">
              <span class="label">候補</span>
              <select class="input mt-2" bind:value={selectedRemoteCheckpoint} disabled={checkpointUploadInProgress || rescueCpuInProgress}>
                {#each remoteCheckpointNames as checkpointName}
                  <option value={checkpointName}>ステップ {checkpointName}</option>
                {/each}
              </select>
            </label>
            <Button.Root class="btn-primary" type="button" onclick={uploadSelectedCheckpoint} disabled={!selectedRemoteCheckpoint || checkpointUploadInProgress || rescueCpuInProgress}>
              {checkpointUploadInProgress ? '登録中' : 'R2に登録'}
            </Button.Root>
          </div>
        {:else if remoteCheckpointLoading}
          <p class="mt-4 text-sm text-slate-500">候補を確認中です。</p>
        {:else if !remoteCheckpointRequested}
          <p class="mt-4 text-sm text-slate-500">候補は未取得です。</p>
        {:else}
          <p class="mt-4 text-sm text-slate-500">候補はありません。</p>
        {/if}

        {#if checkpointUploadInProgress || checkpointUploadPhase || checkpointUploadResult || checkpointUploadError}
          <div class="mt-4 nested-block-pane p-3 text-xs text-slate-600">
            <div class="flex items-center justify-between gap-3">
              <span class="label">登録状況</span>
              <span class="chip">{Math.round(checkpointUploadProgressPercent)}%</span>
            </div>
            <div class="mt-2 h-2 overflow-hidden rounded-full bg-slate-200/80">
              <div class="h-full bg-brand transition-all" style={`width: ${checkpointUploadProgressPercent}%`}></div>
            </div>
            {#if checkpointUploadError}
              <p class="mt-2 text-rose-600">{checkpointUploadError}</p>
            {:else if checkpointUploadResult}
              <p class="mt-2 text-slate-700">
                ステップ {checkpointUploadResult.step} / DB登録 {checkpointUploadResult.db_registered ? '完了' : '未完了'}
              </p>
            {:else if checkpointUploadMessage}
              <p class="mt-2 text-slate-700">{checkpointUploadMessage}</p>
            {/if}
          </div>
        {/if}
      </section>

      <div class="space-y-4">
        <section class="nested-block p-4 text-sm text-slate-600">
          <h3 class="text-base font-semibold text-slate-900">実行制御</h3>
          <div class="mt-4 flex flex-wrap gap-3">
            <Button.Root class="btn-ghost border-rose-200/70 text-rose-600 hover:border-rose-300/80" type="button" onclick={stopJob} disabled={!canStop}>
              {stopActionLabel}
            </Button.Root>
            {#if canRescueCpu}
              <Button.Root class="btn-ghost" type="button" onclick={rescueCpuJob} disabled={rescueCpuInProgress}>
                {rescueCpuInProgress ? 'CPUレスキュー中' : 'CPUレスキュー'}
              </Button.Root>
            {/if}
          </div>

          {#if rescueCpuInProgress || rescueCpuPhase || rescueCpuResult || rescueCpuError}
            <div class="mt-4 nested-block-pane p-3 text-xs text-slate-600">
              <div class="flex items-center justify-between gap-3">
                <span class="label">CPUレスキュー</span>
                <span class="chip">{Math.round(rescueCpuProgressPercent)}%</span>
              </div>
              <div class="mt-2 h-2 overflow-hidden rounded-full bg-slate-200/80">
                <div class="h-full bg-brand transition-all" style={`width: ${rescueCpuProgressPercent}%`}></div>
              </div>
              {#if rescueCpuError}
                <p class="mt-2 text-rose-600">{rescueCpuError}</p>
              {:else if rescueCpuResult}
                <p class="mt-2 text-slate-700">{rescueCpuResult.ip}:{rescueCpuResult.ssh_port ?? 22}</p>
              {:else if rescueCpuMessage}
                <p class="mt-2 text-slate-700">{rescueCpuMessage}</p>
              {/if}
            </div>
          {/if}
        </section>

        <section class="nested-block p-4 text-sm text-slate-600">
          <h3 class="text-base font-semibold text-slate-900">接続情報</h3>
          <dl class="mt-3">
            <CopyableDetailField label="接続コマンド" value={sshCommand || 'IP未取得'} copyText={sshCommand} copyable={Boolean(sshCommand)} breakAll />
          </dl>
          {#if rescueCpuSshCommand}
            <dl class="mt-3">
              <CopyableDetailField label="CPUレスキュー" value={rescueCpuSshCommand} copyable breakAll />
            </dl>
          {/if}
        </section>
      </div>
    </div>
  </section>

  <section class="card p-6">
    <div class="flex items-center justify-between">
      <h2 class="text-xl font-semibold text-slate-900">詳細情報</h2>
    </div>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      <section class="nested-block p-4">
        <h3 class="text-base font-semibold text-slate-900">ジョブ情報</h3>
        <dl class="mt-3 grid gap-4">
          <div class="grid gap-3 lg:grid-cols-2">
            <CopyableDetailField label="ジョブ名" value={jobInfo?.job_name} copyable />
            <CopyableDetailField label="ジョブID" value={jobInfo?.job_id} copyable mono breakAll />
          </div>
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div>
              <dt class="text-xs font-semibold text-slate-500">ステータス</dt>
              <dd class="mt-1 font-semibold text-slate-800">{jobStatusDisplay}</dd>
            </div>
            <div>
              <dt class="text-xs font-semibold text-slate-500">作成日時 (JST)</dt>
              <dd class="mt-1 font-semibold text-slate-800">{formatDate(jobInfo?.created_at)}</dd>
            </div>
            <div>
              <dt class="text-xs font-semibold text-slate-500">開始日時 (JST)</dt>
              <dd class="mt-1 font-semibold text-slate-800">{formatDate(jobInfo?.started_at)}</dd>
            </div>
            <div>
              <dt class="text-xs font-semibold text-slate-500">完了日時 (JST)</dt>
              <dd class="mt-1 font-semibold text-slate-800">{formatDate(jobInfo?.completed_at)}</dd>
            </div>
            <div>
              <dt class="text-xs font-semibold text-slate-500">実行時間</dt>
              <dd class="mt-1 font-semibold text-slate-800">{jobRuntime}</dd>
            </div>
          </div>
        </dl>
      </section>

      <section class="nested-block p-4">
        <h3 class="text-base font-semibold text-slate-900">学習設定</h3>
        <div class="mt-4 space-y-5">
          <div>
            <dl class="mt-2 grid gap-3 lg:grid-cols-2">
              <CopyableDetailField label="データセット" value={datasetName || null} copyable />
              <CopyableDetailField label="データセットID" value={datasetId || null} copyable mono breakAll />
            </dl>
          </div>

          <div>
            <dl class="mt-2 grid gap-3 lg:grid-cols-2">
              <CopyableDetailField label="ポリシータイプ" value={policyType || null} copyable />
              <CopyableDetailField
                label="事前学習済みモデル"
                value={selectedPolicyModelPath}
                copyable
                breakAll
              />
            </dl>
          </div>

          <div>
            <dl class="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <CopyableDetailField label="プロファイル" value={compactProfileId} copyText={profileId} copyable title={profileId} />
              <CopyableDetailField label="VIDEO BACKEND" value={videoBackendDisplay} />
              <CopyableDetailField label="検証 (Validation)" value={trainingConfig?.validation?.enable ? '有効' : '無効'} />
              <CopyableDetailField label="早期停止 (Early Stopping)" value={trainingConfig?.early_stopping?.enable ? '有効' : '無効'} />
              <CopyableDetailField label="ステップ数" value={trainingConfig?.training?.steps ?? null} />
              <CopyableDetailField label="バッチサイズ" value={trainingConfig?.training?.batch_size ?? null} />
              <CopyableDetailField label="保存頻度" value={trainingConfig?.training?.save_freq ?? null} />
              <CopyableDetailField label="ログ頻度" value={trainingConfig?.training?.log_freq ?? null} />
              <CopyableDetailField label="drop_last" value={trainingConfig?.training?.drop_last ? '有効' : '無効'} />
              <CopyableDetailField
                label="Persistent workers"
                value={trainingConfig?.training?.persistent_workers ? '有効' : '無効'}
              />
            </dl>
          </div>
        </div>
      </section>

      <div class="grid gap-4 lg:grid-cols-2">
        <section class="nested-block p-4">
          <h3 class="text-base font-semibold text-slate-900">実行環境</h3>
          <dl class="mt-3 grid gap-3 sm:grid-cols-2">
            <CopyableDetailField label="クラウド" value={cloudProviderDisplay} />
            <CopyableDetailField label="利用方式" value={cloudModeDisplay} />
            <CopyableDetailField label="GPUモデル" value={gpuModelDisplay} />
            <CopyableDetailField label="GPU数" value={effectiveGpuCount ?? null} />
            <CopyableDetailField label="ストレージ容量" value={cloudStorageDisplay} />
            <CopyableDetailField label="インスタンスタイプ" value={selectedInstanceDisplay} copyable breakAll />
          </dl>
        </section>

        <section class="nested-block p-4">
          <h3 class="text-base font-semibold text-slate-900">接続情報</h3>
          <dl class="mt-3 grid gap-3">
            <CopyableDetailField label="インスタンスID" value={compactInstanceId} copyText={jobInfo?.instance_id} copyable mono breakAll title={jobInfo?.instance_id ?? ''} />
            <div class="grid gap-3 sm:grid-cols-2">
              <CopyableDetailField label="IP / ポート" value={sshTargetDisplay || null} copyable />
              <CopyableDetailField label="SSHユーザー" value={jobInfo?.ssh_user ?? 'root'} copyable />
            </div>
            <CopyableDetailField label="SSH鍵" value={jobInfo?.ssh_private_key} copyable breakAll />
          </dl>
        </section>
      </div>
    </div>
    {#if Object.keys(summary).length}
      <div class="mt-4 nested-block p-4 text-sm text-slate-600">
        <p class="label">概要</p>
        <div class="mt-2 grid gap-2">
          {#each Object.entries(summary) as [key, value]}
            <p class="text-xs text-slate-500">{key}: <span class="text-slate-800">{value}</span></p>
          {/each}
        </div>
      </div>
    {/if}
  </section>
</section>

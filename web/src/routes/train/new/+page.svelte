<script lang="ts">
  import { browser } from '$app/environment';
  import { onDestroy } from 'svelte';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import {
    api,
    type TrainingProvisionOperationStatusResponse
  } from '$lib/api/client';
  import HelpLabel from '$lib/components/HelpLabel.svelte';
  import CloudInstanceSelector from '$lib/components/training/CloudInstanceSelector.svelte';
  import { formatBytes, formatDate } from '$lib/format';
  import { GPU_COUNTS, POLICY_TYPES } from '$lib/policies';
  import { registerTabRealtimeContributor, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';
  import type { TrainingProviderCapabilityResponse } from '$lib/types/training';

  type DatasetSummary = {
    id: string;
    name?: string;
    profile_name?: string;
    dataset_type?: string;
    status?: string;
    created_at?: string;
    size_bytes?: number;
  };

  type DatasetListResponse = {
    datasets?: DatasetSummary[];
    total?: number;
  };

  const datasetsQuery = createQuery<DatasetListResponse>({
    queryKey: ['datasets', 'train'],
    queryFn: () => api.storage.datasets()
  });

  let cloudProvider = $state<'verda' | 'vast'>('verda');
  let vastMaxPrice = $state<number | null>(null);

	  const providerCapabilitiesQuery = createQuery<TrainingProviderCapabilityResponse>({
	    queryKey: ['training', 'provider-capabilities'],
	    queryFn: api.training.providerCapabilities
	  });

	  const isVerdaProviderEnabled = $derived($providerCapabilitiesQuery.data?.verda_enabled ?? true);
	  const isVastProviderEnabled = $derived($providerCapabilitiesQuery.data?.vast_enabled ?? false);

	  $effect(() => {
	    if (cloudProvider === 'verda' && !isVerdaProviderEnabled && isVastProviderEnabled) {
	      cloudProvider = 'vast';
	      return;
	    }
	    if (cloudProvider === 'vast' && !isVastProviderEnabled) {
	      cloudProvider = 'verda';
	    }
	  });

  const defaultPolicy = POLICY_TYPES[0];
  let policyType = $state(defaultPolicy?.id ?? '');

  let steps = $state(defaultPolicy?.defaultSteps ?? 100000);
  let batchSize = $state(defaultPolicy?.defaultBatchSize ?? 32);
  let saveFreq = $state(defaultPolicy?.defaultSaveFreq ?? 5000);
  let logFreq = $state(200);
  let numWorkers = $state(4);
  let saveCheckpoint = $state(true);

  let validationEnable = $state(true);
  let validationTrainRatioPercent = $state(70);
  let validationSplitSeed = $state(42);
  let validationEvalFreq = $state(100);
  let validationMaxBatches = $state(0);
  let validationBatchSize = $state(0);

  let earlyStoppingEnable = $state(true);
  let earlyStoppingPatience = $state(5);
  let earlyStoppingMinDelta = $state(0.002);
  let earlyStoppingMode = $state<'min' | 'max'>('min');

  let datasetVideoBackend = $state<'auto' | 'torchcodec' | 'pyav'>('torchcodec');
  let selectedPretrainedId = $state('');

  let policyDtype = $state<'auto' | 'float32' | 'bfloat16' | 'float16'>('auto');
  let policyUseAmp = $state<'auto' | 'true' | 'false'>('auto');
  let policyGradientCheckpointing = $state<'auto' | 'true' | 'false'>('auto');
  let policyCompileModel = $state<'auto' | 'true' | 'false'>('auto');

  let gpuModel = $state('H100');
  let gpuCount = $state(GPU_COUNTS[0] ?? 1);
  let storageSize = $state(200);
  let selectedMode = $state<'spot' | 'ondemand'>('spot');
  let selectedInstanceType = $state<string | null>(null);
  let selectedOfferId = $state<number | null>(null);
  let selectedLocation = $state('auto');
  let selectedCandidateTitle = $state('');
  let selectedCandidateDetail = $state('');
  let selectedCandidateRoute = $state('');
  let selectedCandidatePricePerHour = $state<number | null>(null);

  let jobName = $state('');

  let submitting = $state(false);
  let submitError = $state('');
  let createStage = $state('待機中');
  let createMessage = $state('');
  let createStatus = $state<'idle' | 'running' | 'complete' | 'error'>('idle');
  let createEvents = $state<Array<{ type: string; message: string; timestamp: string }>>([]);
  let createProgressPercent = $state(0);
  let provisionOperationId = $state('');
  let createOperationContributor: TabRealtimeContributorHandle | null = null;
  let lastCreateEventKey = '';

  let selectedDataset = $state('');

  const PARAMETER_HELP = {
    video_backend:
      'auto:\n自動選択です。まず torchcodec を試し、使えない場合は pyav を使います。\n\ntorchcodec:\nPyTorch系の動画デコード実装です。環境が合えば高速で安定しやすい選択です。\n\npyav:\nFFmpegベースの実装です。互換性が広く、torchcodec で問題が出る場合の代替になります。',
    steps: '学習を何回更新するかです。大きいほど学習は進みますが、時間も増えます。',
    batch_size: '1回の更新で使うデータ量です。大きいほどメモリ使用量が増えます。',
    save_freq: '何ステップごとにチェックポイントを保存するかです。',
    log_freq: '何ステップごとに学習ログを記録するかです。',
    num_workers: 'データ読み込みを並列処理する数です。増やすと前処理が速くなる場合があります。',
    save_checkpoint: '有効にすると途中状態を保存します。再開やEarly Stopping運用には有効化が推奨です。',
    validation_enable:
      '有効にすると train/val 分割を作って検証を実行します。Early Stopping を使う場合は有効化が必要です。',
    validation_train_ratio:
      '残り割合（100 - 学習データ割合）が検証に使われます。\n（例: 70% なら train:val = 7:3）',
    validation_split_seed:
      'train/val の振り分けを決める乱数の種です。\n同じseedなら同じ分割、seedを変えると分割内容が変わります。',
    validation_eval_freq: '検証が走る間隔です（ステップ単位）。',
    validation_batch_size: '検証時だけ使うバッチサイズです。\n（例: 0 なら学習バッチサイズを使用）',
    validation_max_batches: '1回の検証で見る最大バッチ数です。\n（例: 0 なら全件）',
    early_stopping_enable: '有効にすると、改善しない状態が続いたとき学習を途中で停止します。',
    early_stopping_mode:
      'min は小さいほど良い（通常は val_loss）、max は大きいほど良い指標向けです。',
    early_stopping_patience: '改善しない検証が何回続いたら止めるかの回数です。',
    early_stopping_min_delta: '改善とみなす最小変化量です。差がこれ未満なら「改善なし」と判定します。',
    dtype: '重みや計算の精度です。auto はモデル既定値を使います。',
    amp: '混合精度で学習を高速化します。dtype=bfloat16 選択時は無効化されます。',
    gradient_checkpointing: 'メモリ使用量を下げる代わりに計算時間が増える設定です。',
    torch_compile: 'モデル実行を最適化して高速化を狙う設定です。環境によって効果は変わります。'
  } as const;

  const SCRATCH_PRETRAINED_ID = '__scratch__';

  const applyPolicyDefaults = (policyId: string) => {
    const info = POLICY_TYPES.find((policy) => policy.id === policyId);
    if (!info) return;
    steps = info.defaultSteps;
    batchSize = info.defaultBatchSize;
    saveFreq = info.defaultSaveFreq;
    logFreq = info.defaultLogFreq;
    numWorkers = info.defaultNumWorkers;
    saveCheckpoint = true;
    validationEnable = true;
    validationTrainRatioPercent = 70;
    validationSplitSeed = 42;
    validationEvalFreq = 100;
    validationMaxBatches = 0;
    validationBatchSize = 0;
    earlyStoppingEnable = true;
    earlyStoppingPatience = 5;
    earlyStoppingMinDelta = 0.002;
    earlyStoppingMode = 'min';

    policyDtype = info.dtype ? (info.dtype as typeof policyDtype) : 'auto';
    policyCompileModel = info.compileModel === undefined ? 'auto' : info.compileModel ? 'true' : 'false';
    policyGradientCheckpointing =
      info.gradientCheckpointing === undefined ? 'auto' : info.gradientCheckpointing ? 'true' : 'false';
    if (policyDtype === 'bfloat16') {
      policyUseAmp = 'false';
    } else {
      policyUseAmp = info.useAmp === undefined ? 'auto' : info.useAmp ? 'true' : 'false';
    }

    if (policyId === 'pi05') {
      validationEvalFreq = Math.min(500, steps);
      earlyStoppingMinDelta = 0.002;
    }
  };

  const handlePolicyChange = (event: Event) => {
    const value = (event.target as HTMLSelectElement).value;
    policyType = value;
    applyPolicyDefaults(value);
  };

  const isTrainingDataset = (dataset: DatasetSummary) => {
    const datasetId = dataset.id ?? '';
    const datasetType = dataset.dataset_type;
    if (datasetType === 'eval' || datasetId.includes('/eval_')) return false;
    if (dataset.status === 'archived') return false;
    return Boolean(datasetId);
  };

  const policyInfo = $derived(POLICY_TYPES.find((policy) => policy.id === policyType) ?? null);
  const pretrainedOptions = $derived.by(() => {
    const baseOptions = [...(policyInfo?.pretrainedModels ?? [])];
    if (policyInfo?.supportsScratchInitialization) {
      return [
        ...baseOptions,
        {
          id: SCRATCH_PRETRAINED_ID,
          path: '',
          name: 'フルスクラッチ',
          description: '事前学習済み重みを使わず、新規初期化で学習を開始'
        }
      ];
    }
    return baseOptions;
  });
  const supportsScratchInitialization = $derived(policyInfo?.supportsScratchInitialization ?? false);
  const usesScratchInitialization = $derived(selectedPretrainedId === SCRATCH_PRETRAINED_ID);

  $effect(() => {
    if (policyInfo?.skipPretrained || pretrainedOptions.length === 0) {
      if (selectedPretrainedId) {
        selectedPretrainedId = '';
      }
      return;
    }
    if (!pretrainedOptions.some((option) => option.id === selectedPretrainedId)) {
      selectedPretrainedId = pretrainedOptions[0]?.id ?? '';
    }
  });

  const selectedPretrained = $derived(
    pretrainedOptions.find((option) => option.id === selectedPretrainedId) ?? null
  );

  const datasets = $derived($datasetsQuery.data?.datasets?.filter(isTrainingDataset) ?? []);
  const datasetsSorted = $derived(
    datasets.slice().sort(
      (a, b) =>
        new Date((b.created_at as string | undefined) ?? 0).getTime() -
        new Date((a.created_at as string | undefined) ?? 0).getTime()
    )
  );

  $effect(() => {
    if (datasetsSorted.length && !selectedDataset) {
      selectedDataset = datasetsSorted[0].id as string;
      return;
    }
    if (selectedDataset && datasetsSorted.length && !datasetsSorted.some((s) => s.id === selectedDataset)) {
      selectedDataset = datasetsSorted[0].id as string;
    }
  });

  const selectedDatasetInfo = $derived(
    datasetsSorted.find((dataset) => dataset.id === selectedDataset) ?? null
  );
  const datasetShortId = $derived(selectedDatasetInfo?.id?.slice(0, 6) ?? '');

  $effect(() => {
    if (!validationEnable && earlyStoppingEnable) {
      earlyStoppingEnable = false;
    }
  });

  const useAmpDisabled = $derived(policyDtype === 'bfloat16');
  const isVast = $derived(cloudProvider === 'vast');
  const isVerda = $derived(cloudProvider === 'verda');

  const progressLabelMap: Record<string, string> = {
    queued: '開始待ち',
    validate: '設定検証',
    select_candidate: '候補確認',
    create_instance: 'インスタンス作成',
    wait_ip: 'IP割り当て待機',
    connect_ssh: 'SSH接続',
    deploy_files: 'ファイル転送',
    setup_env: '環境構築',
    start_training: '学習開始',
    job_created: 'ジョブ作成',
    completed: '完了',
    failed: 'エラー'
  };

  const progressPercentMap: Record<string, number> = {
    queued: 2,
    validate: 10,
    select_candidate: 20,
    create_instance: 35,
    wait_ip: 50,
    connect_ssh: 65,
    deploy_files: 78,
    setup_env: 90,
    start_training: 97,
    job_created: 100,
    completed: 100,
    failed: 100
  };

  const buildJobName = (policy: string, shortId: string) => {
    const now = new Date();
    const pad = (value: number) => value.toString().padStart(2, '0');
    const timestamp = `${pad(now.getFullYear() % 100)}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(
      now.getHours()
    )}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const parts = [] as string[];
    if (policy) parts.push(policy);
    if (shortId) parts.push(shortId);
    parts.push(timestamp);
    return parts.join('_');
  };

  const generatedJobName = $derived(buildJobName(policyType, datasetShortId));

  const toBool = (value: 'auto' | 'true' | 'false') => {
    if (value === 'auto') return null;
    return value === 'true';
  };

  const buildPayload = () => {
    if (!selectedDataset) return null;
    const name = jobName.trim() || generatedJobName;

    const payload: Record<string, unknown> = {
      job_name: name,
      dataset: {
        id: selectedDataset,
        source: 'r2'
      },
      policy: {
        type: policyType
      },
      training: {
        steps,
        batch_size: batchSize,
        save_freq: saveFreq,
        log_freq: logFreq,
        num_workers: numWorkers,
        save_checkpoint: saveCheckpoint
      },
      validation: {
        enable: validationEnable
      },
      early_stopping: {
        enable: earlyStoppingEnable,
        patience: earlyStoppingPatience,
        min_delta: earlyStoppingMinDelta,
        mode: earlyStoppingMode
      },
      cloud: {
        provider: cloudProvider,
        gpu_model: gpuModel,
        gpus_per_instance: gpuCount,
        selected_mode: selectedMode,
        selected_instance_type: cloudProvider === 'verda' ? selectedInstanceType : null,
        selected_offer_id: cloudProvider === 'vast' ? selectedOfferId : null,
        location: cloudProvider === 'verda' ? selectedLocation : 'auto',
        ...(isVerda
          ? {
              storage_size: storageSize,
              is_spot: selectedMode === 'spot'
            }
		          : {
		              storage_size: storageSize,
		              interruptible: selectedMode === 'spot',
		              max_price:
		                vastMaxPrice === null || Number.isNaN(vastMaxPrice)
		                  ? null
		                  : vastMaxPrice
		            })
		      },
      wandb_enable: false,
      sync_dataset: false
    };

    const policyPayload = payload.policy as Record<string, unknown>;
    if (supportsScratchInitialization) {
      policyPayload.initialization = usesScratchInitialization ? 'scratch' : 'pretrained';
    }
    if (selectedPretrained?.path && !usesScratchInitialization) {
      policyPayload.pretrained_path = selectedPretrained.path;
    }
    if (datasetVideoBackend !== 'auto') {
      (payload.dataset as Record<string, unknown>).video_backend = datasetVideoBackend;
    }
    const normalizedTrainRatio = Math.min(
      100,
      Math.max(1, Number(validationTrainRatioPercent) || 70)
    ) / 100;
    const normalizedSplitSeed = Math.max(0, Math.floor(Number(validationSplitSeed) || 42));
    (payload.dataset as Record<string, unknown>).split = {
      train_ratio: normalizedTrainRatio,
      seed: normalizedSplitSeed
    };

    if (validationEnable) {
      const validationPayload = payload.validation as Record<string, unknown>;
      validationPayload.eval_freq = validationEvalFreq;
      validationPayload.max_batches = validationMaxBatches > 0 ? validationMaxBatches : null;
      validationPayload.batch_size = validationBatchSize > 0 ? validationBatchSize : null;
    }

    if (policyDtype !== 'auto') policyPayload.dtype = policyDtype;

    const ampSetting = useAmpDisabled ? 'false' : policyUseAmp;
    const useAmpValue = toBool(ampSetting);
    const gradValue = toBool(policyGradientCheckpointing);
    const compileValue = toBool(policyCompileModel);

    if (useAmpValue !== null) policyPayload.use_amp = useAmpValue;
    if (gradValue !== null) policyPayload.gradient_checkpointing = gradValue;
    if (compileValue !== null) policyPayload.compile_model = compileValue;

    return payload;
  };

  const setProvisionOperationQuery = async (operationId: string | null) => {
    const nextUrl = new URL(page.url);
    if (operationId) {
      nextUrl.searchParams.set('operation_id', operationId);
    } else {
      nextUrl.searchParams.delete('operation_id');
    }
    await goto(`${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`, {
      replaceState: true,
      noScroll: true,
      keepFocus: true
    });
  };

  const closeCreateStream = () => {
    createOperationContributor?.dispose();
    createOperationContributor = null;
  };

  const appendCreateEvent = (type: string, message: string, eventKey: string) => {
    if (!message || eventKey === lastCreateEventKey) return;
    lastCreateEventKey = eventKey;
    createEvents = [
      ...createEvents,
      { type, message, timestamp: new Date().toLocaleTimeString('ja-JP') }
    ].slice(-12);
  };

  const applyProvisionSnapshot = async (snapshot: TrainingProvisionOperationStatusResponse) => {
    const step = snapshot.step || 'queued';
    const label = progressLabelMap[step] ?? step;
    const message = snapshot.message || label;
    createStage = label;
    createMessage = message;
    createProgressPercent = progressPercentMap[step] ?? 0;
    provisionOperationId = snapshot.operation_id;

    appendCreateEvent(step, message, `${snapshot.state}:${step}:${message}`);

    if (snapshot.job_id) {
      closeCreateStream();
      createStatus = 'complete';
      submitting = false;
      await goto(`/train/jobs/${snapshot.job_id}`);
      return;
    }

    if (snapshot.state === 'failed') {
      createStatus = 'error';
      submitError = snapshot.message || snapshot.failure_reason || '学習ジョブの作成に失敗しました。';
      submitting = false;
      return;
    }

    if (snapshot.state === 'completed') {
      createStatus = 'complete';
      submitting = false;
      return;
    }

    createStatus = 'running';
    submitting = true;
  };

  const submit = async () => {
    submitError = '';
    createStatus = 'idle';
    if (cloudProvider === 'vast' && !isVastProviderEnabled) {
      submitError = 'Vast.ai は現在選択できません。';
      return;
    }
    if (cloudProvider === 'verda' && !isVerdaProviderEnabled) {
      submitError = 'Verda認証情報が不足しています: DATACRUNCH_CLIENT_ID, DATACRUNCH_CLIENT_SECRET';
      return;
    }
    if (cloudProvider === 'verda' && !selectedInstanceType) {
      submitError = 'Verda のインスタンス候補を選択してください。';
      return;
    }
    if (cloudProvider === 'vast' && selectedOfferId == null) {
      submitError = 'Vast.ai のオファー候補を選択してください。';
      return;
    }
    const payload = buildPayload();
    if (!payload) {
      submitError = 'データセットを選択してください。';
      return;
    }
    submitting = true;
    createStatus = 'running';
    createStage = '開始';
    createMessage = '';
    createEvents = [];
    try {
      closeCreateStream();
      const accepted = await api.training.startProvisionOperation(payload);
      provisionOperationId = accepted.operation_id;
      createProgressPercent = progressPercentMap.queued;
      await setProvisionOperationQuery(accepted.operation_id);
    } catch (error) {
      createStatus = 'error';
      submitError = error instanceof Error ? error.message : '学習ジョブの作成に失敗しました。';
      submitting = false;
    }
  };

  $effect(() => {
    const operationId = page.url.searchParams.get('operation_id') ?? '';
    if (!operationId) {
      if (!submitting) {
        closeCreateStream();
        provisionOperationId = '';
      }
      return;
    }

    provisionOperationId = operationId;
    closeCreateStream();

    let cancelled = false;
    (async () => {
      try {
        const snapshot = await api.training.provisionOperation(operationId);
        if (cancelled) return;
        await applyProvisionSnapshot(snapshot);
        if (snapshot.job_id || snapshot.state === 'failed' || snapshot.state === 'completed') {
          return;
        }
        if (!browser) return;
        const currentOperationId = operationId;
        closeCreateStream();
        createOperationContributor = registerTabRealtimeContributor({
          subscriptions: [
            {
              subscription_id: `train.new.provision.${currentOperationId}`,
              kind: 'training.provision-operation',
              params: { operation_id: currentOperationId }
            }
          ],
          onEvent: (event: TabRealtimeEvent) => {
            if (event.op !== 'snapshot' || event.source?.kind !== 'training.provision-operation') return;
            if (provisionOperationId !== currentOperationId) return;
            void applyProvisionSnapshot(event.payload as TrainingProvisionOperationStatusResponse);
          }
        });
      } catch (error) {
        if (cancelled) return;
        createStatus = 'error';
        submitError = error instanceof Error ? error.message : '作成進行の取得に失敗しました。';
        submitting = false;
      }
    })();

    return () => {
      cancelled = true;
      closeCreateStream();
    };
  });

  onDestroy(() => {
    closeCreateStream();
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Train</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">新規学習</h1>
      <p class="mt-2 text-sm text-slate-600">1ページで学習ジョブを設定して開始します。</p>
    </div>
    <div class="flex gap-3">
      <Button.Root class="btn-ghost" href="/train">一覧へ戻る</Button.Root>
    </div>
  </div>
</section>

<section class="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
  <div class="space-y-6">
    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">ポリシー</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ポリシータイプ</span>
          <select class="input mt-2" bind:value={policyType} onchange={handlePolicyChange}>
            {#each POLICY_TYPES as policy}
              <option value={policy.id}>{policy.displayName}</option>
            {/each}
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">事前学習済みモデル</span>
          <select
            class="input mt-2"
            bind:value={selectedPretrainedId}
            disabled={policyInfo?.skipPretrained || pretrainedOptions.length === 0}
          >
            {#if policyInfo?.skipPretrained || pretrainedOptions.length === 0}
              <option value="">このポリシーは事前学習不要</option>
            {:else}
              {#each pretrainedOptions as model}
                <option value={model.id}>{model.name}</option>
              {/each}
            {/if}
          </select>
          {#if usesScratchInitialization}
            <p class="mt-2 text-xs text-slate-500">事前学習済み重みを使わず、新規初期化で学習を開始します。</p>
          {:else if selectedPretrained?.description}
            <p class="mt-2 text-xs text-slate-500">{selectedPretrained.description}</p>
          {/if}
        </label>
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">データセット</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">データセット</span>
          <select class="input mt-2" bind:value={selectedDataset}>
            {#if datasetsSorted.length}
              {#each datasetsSorted as dataset}
                <option value={dataset.id}>
                  {dataset.name ?? dataset.id} (profile: {dataset.profile_name ?? '-'})
                </option>
              {/each}
            {:else}
              <option value="">データセットがありません</option>
            {/if}
          </select>
        </label>
      </div>
      <div class="mt-4 rounded-xl border border-slate-200/60 bg-white/70 p-4 text-sm text-slate-600">
        <div class="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p class="label">選択中のデータセット</p>
            <p class="mt-2 font-semibold text-slate-800">
              {selectedDatasetInfo?.name ?? selectedDatasetInfo?.id ?? '-'}
            </p>
            <p class="text-xs text-slate-500">
              profile: {selectedDatasetInfo?.profile_name ?? '-'}
            </p>
          </div>
          <div>
            <p class="label">サイズ / 作成日時</p>
            <p class="mt-2 font-semibold text-slate-800">
              {formatBytes(selectedDatasetInfo?.size_bytes ?? 0)} / {formatDate(selectedDatasetInfo?.created_at)}
            </p>
          </div>
        </div>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="Video backend" help={PARAMETER_HELP.video_backend} />
          <select class="input mt-2" bind:value={datasetVideoBackend} title={PARAMETER_HELP.video_backend}>
            <option value="auto">自動 (torchcodec優先)</option>
            <option value="torchcodec">torchcodec</option>
            <option value="pyav">pyav</option>
          </select>
        </label>
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">学習パラメータ</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="ステップ数" help={PARAMETER_HELP.steps} />
          <input class="input mt-2" type="number" min="100" bind:value={steps} title={PARAMETER_HELP.steps} />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="バッチサイズ" help={PARAMETER_HELP.batch_size} />
          <input class="input mt-2" type="number" min="1" bind:value={batchSize} title={PARAMETER_HELP.batch_size} />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="保存頻度" help={PARAMETER_HELP.save_freq} />
          <input class="input mt-2" type="number" min="50" bind:value={saveFreq} title={PARAMETER_HELP.save_freq} />
        </label>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="ログ頻度" help={PARAMETER_HELP.log_freq} />
          <input class="input mt-2" type="number" min="1" bind:value={logFreq} title={PARAMETER_HELP.log_freq} />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="DataLoader workers" help={PARAMETER_HELP.num_workers} />
          <input class="input mt-2" type="number" min="0" bind:value={numWorkers} title={PARAMETER_HELP.num_workers} />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="チェックポイント保存" help={PARAMETER_HELP.save_checkpoint} />
          <div class="mt-3 flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" bind:checked={saveCheckpoint} title={PARAMETER_HELP.save_checkpoint} />
            <span>{saveCheckpoint ? '有効' : '無効'}</span>
          </div>
        </label>
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">検証 / Early Stopping</h2>
      <div class="mt-4 text-sm font-semibold text-slate-700">
        <HelpLabel text="検証を有効" help={PARAMETER_HELP.validation_enable} />
        <div class="mt-3 flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" bind:checked={validationEnable} title={PARAMETER_HELP.validation_enable} />
          <span>{validationEnable ? '有効' : '無効'}</span>
        </div>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="学習データ割合 (%)" help={PARAMETER_HELP.validation_train_ratio} />
          <input
            class="input mt-2"
            type="number"
            min="1"
            max="100"
            bind:value={validationTrainRatioPercent}
            disabled={!validationEnable}
            title={PARAMETER_HELP.validation_train_ratio}
          />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="分割seed" help={PARAMETER_HELP.validation_split_seed} />
          <input
            class="input mt-2"
            type="number"
            min="0"
            bind:value={validationSplitSeed}
            disabled={!validationEnable}
            title={PARAMETER_HELP.validation_split_seed}
          />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="検証頻度" help={PARAMETER_HELP.validation_eval_freq} />
          <input
            class="input mt-2"
            type="number"
            min="1"
            bind:value={validationEvalFreq}
            disabled={!validationEnable}
            title={PARAMETER_HELP.validation_eval_freq}
          />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="検証バッチサイズ" help={PARAMETER_HELP.validation_batch_size} />
          <input
            class="input mt-2"
            type="number"
            min="0"
            bind:value={validationBatchSize}
            disabled={!validationEnable}
            title={PARAMETER_HELP.validation_batch_size}
          />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="検証バッチ数上限" help={PARAMETER_HELP.validation_max_batches} />
          <input
            class="input mt-2"
            type="number"
            min="0"
            bind:value={validationMaxBatches}
            disabled={!validationEnable}
            title={PARAMETER_HELP.validation_max_batches}
          />
        </label>
      </div>

      <div class="divider my-6"></div>

      <div class="text-sm font-semibold text-slate-700">
        <HelpLabel text="Early Stopping" help={PARAMETER_HELP.early_stopping_enable} />
        <div class="mt-3 flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            bind:checked={earlyStoppingEnable}
            disabled={!validationEnable}
            title={PARAMETER_HELP.early_stopping_enable}
          />
          <span>{earlyStoppingEnable ? '有効' : '無効'}</span>
        </div>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="モード" help={PARAMETER_HELP.early_stopping_mode} />
          <select
            class="input mt-2"
            bind:value={earlyStoppingMode}
            disabled={!earlyStoppingEnable}
            title={PARAMETER_HELP.early_stopping_mode}
          >
            <option value="min">min</option>
            <option value="max">max</option>
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="Patience" help={PARAMETER_HELP.early_stopping_patience} />
          <input
            class="input mt-2"
            type="number"
            min="1"
            bind:value={earlyStoppingPatience}
            disabled={!earlyStoppingEnable}
            title={PARAMETER_HELP.early_stopping_patience}
          />
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="min_delta" help={PARAMETER_HELP.early_stopping_min_delta} />
          <input
            class="input mt-2"
            type="number"
            step="0.0001"
            bind:value={earlyStoppingMinDelta}
            disabled={!earlyStoppingEnable}
            title={PARAMETER_HELP.early_stopping_min_delta}
          />
        </label>
      </div>
    </section>

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">モデル設定</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="dtype" help={PARAMETER_HELP.dtype} />
          <select class="input mt-2" bind:value={policyDtype} title={PARAMETER_HELP.dtype}>
            <option value="auto">指定しない</option>
            <option value="float32">float32</option>
            <option value="bfloat16">bfloat16</option>
            <option value="float16">float16</option>
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="AMP" help={PARAMETER_HELP.amp} />
          <select class="input mt-2" bind:value={policyUseAmp} disabled={useAmpDisabled} title={PARAMETER_HELP.amp}>
            <option value="auto">指定しない</option>
            <option value="true">有効</option>
            <option value="false">無効</option>
          </select>
          {#if useAmpDisabled}
            <p class="mt-2 text-xs text-slate-500">bfloat16 選択時は AMP を無効化します。</p>
          {/if}
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="Gradient checkpointing" help={PARAMETER_HELP.gradient_checkpointing} />
          <select
            class="input mt-2"
            bind:value={policyGradientCheckpointing}
            title={PARAMETER_HELP.gradient_checkpointing}
          >
            <option value="auto">指定しない</option>
            <option value="true">有効</option>
            <option value="false">無効</option>
          </select>
        </label>
        <label class="text-sm font-semibold text-slate-700">
          <HelpLabel text="torch.compile" help={PARAMETER_HELP.torch_compile} />
          <select class="input mt-2" bind:value={policyCompileModel} title={PARAMETER_HELP.torch_compile}>
            <option value="auto">指定しない</option>
            <option value="true">有効</option>
            <option value="false">無効</option>
          </select>
        </label>
      </div>
    </section>
  </div>

  <div class="space-y-6">
    <CloudInstanceSelector
      {cloudProvider}
      {gpuModel}
      {gpuCount}
      {storageSize}
      {selectedMode}
      {selectedInstanceType}
      {selectedOfferId}
      {selectedLocation}
      {selectedCandidateTitle}
      {selectedCandidateDetail}
      {selectedCandidateRoute}
      {selectedCandidatePricePerHour}
      {vastMaxPrice}
      {isVerdaProviderEnabled}
      {isVastProviderEnabled}
      onApplySelection={({ cloudProvider: nextProvider, gpuModel: nextGpuModel, gpuCount: nextGpuCount, storageSize: nextStorageSize, selectedMode: nextSelectedMode, selectedInstanceType: nextSelectedInstanceType, selectedOfferId: nextSelectedOfferId, selectedLocation: nextSelectedLocation, vastMaxPrice: nextVastMaxPrice, candidateTitle: nextCandidateTitle, candidateDetail: nextCandidateDetail, candidateRoute: nextCandidateRoute, candidatePricePerHour: nextCandidatePricePerHour }) => {
        cloudProvider = nextProvider;
        gpuModel = nextGpuModel;
        gpuCount = nextGpuCount;
        storageSize = nextStorageSize;
        selectedMode = nextSelectedMode;
        selectedInstanceType = nextSelectedInstanceType;
        selectedOfferId = nextSelectedOfferId;
        selectedLocation = nextSelectedLocation;
        vastMaxPrice = nextVastMaxPrice;
        selectedCandidateTitle = nextCandidateTitle;
        selectedCandidateDetail = nextCandidateDetail;
        selectedCandidateRoute = nextCandidateRoute;
        selectedCandidatePricePerHour = nextCandidatePricePerHour;
      }}
    />

    <section class="card p-6">
      <h2 class="text-xl font-semibold text-slate-900">ジョブ名と実行</h2>
      <div class="mt-4 grid gap-4">
        <label class="text-sm font-semibold text-slate-700">
          <span class="label">ジョブ名 (空で自動生成)</span>
          <input class="input mt-2" bind:value={jobName} placeholder={generatedJobName} />
        </label>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-600">
          <p class="label">プレビュー</p>
          <p class="mt-2 font-semibold text-slate-800">{jobName.trim() || generatedJobName}</p>
        </div>
        {#if submitError}
          <p class="text-sm text-rose-600">{submitError}</p>
        {/if}
        <Button.Root class="btn-primary" type="button" onclick={submit} disabled={submitting}>
          {submitting ? '作成中...' : '学習を開始'}
        </Button.Root>
        {#if submitting || createEvents.length || provisionOperationId}
          <div class="rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-600">
            <div class="flex items-center justify-between">
              <p class="label">作成進行</p>
              <span class="chip">{createStage}</span>
            </div>
            <div class="mt-3 h-2 overflow-hidden rounded-full bg-slate-200/80">
              <div
                class={`h-full rounded-full transition-[width] duration-300 ${createStatus === 'error' ? 'bg-rose-500' : 'bg-[linear-gradient(90deg,#5c7cff,#5f7cff,#7a8cff)]'}`}
                style={`width: ${Math.max(0, Math.min(100, createProgressPercent))}%`}
              ></div>
            </div>
            <p class="mt-2 text-sm text-slate-700">{createMessage || '進行状況を取得中...'}</p>
            <div class="mt-3 space-y-1">
              {#each createEvents as event}
                <p class="text-xs text-slate-500">[{event.timestamp}] {event.message}</p>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </section>
  </div>
</section>

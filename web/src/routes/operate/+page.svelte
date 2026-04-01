<script lang="ts">
  import { browser } from '$app/environment';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { goto } from '$app/navigation';
  import {
    api,
    type TabSessionSubscription,
    type StartupOperationAcceptedResponse,
    type StartupOperationStatusResponse
  } from '$lib/api/client';
  import { registerTabRealtimeContributor, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';
  import { queryClient } from '$lib/queryClient';
  import OperateStatusCards from '$lib/components/OperateStatusCards.svelte';
  import ActiveSessionSection from '$lib/components/ActiveSessionSection.svelte';
  import ActiveSessionCard from '$lib/components/ActiveSessionCard.svelte';
  import InferenceModelSelector from '$lib/components/InferenceModelSelector.svelte';
  import TaskCandidateCombobox from '$lib/components/TaskCandidateCombobox.svelte';
  import { formatBytes } from '$lib/format';
  import { START_PHASE_LABELS } from '$lib/operate/startupPhases';
  import type {
    InferenceDeviceCompatibilityResponse,
    InferenceModel,
    InferenceModelsResponse,
    InferenceRunnerStatusResponse,
    OperateStatusResponse,
    RunnerStatus
  } from '$lib/types/inference';
  import type { SystemStatusSnapshot } from '$lib/types/systemStatus';

  const PI0_POLICY_TYPES = new Set(['pi0', 'pi05']);

  type OperateStatusStreamPayload = {
    vlabor_status?: Record<string, unknown>;
    inference_runner_status?: InferenceRunnerStatusResponse;
    operate_status?: OperateStatusResponse;
  };

  const inferenceModelsQuery = createQuery<InferenceModelsResponse>({
    queryKey: ['inference', 'models'],
    queryFn: api.inference.models
  });

  const inferenceDeviceQuery = createQuery<InferenceDeviceCompatibilityResponse>({
    queryKey: ['inference', 'device-compatibility'],
    queryFn: api.inference.deviceCompatibility
  });

  const inferenceRunnerStatusQuery = createQuery<InferenceRunnerStatusResponse>({
    queryKey: ['inference', 'runner', 'status'],
    queryFn: api.inference.runnerStatus
  });

  const operateStatusQuery = createQuery<OperateStatusResponse>({
    queryKey: ['operate', 'status'],
    queryFn: api.operate.status
  });

  const resolveModelId = (model: InferenceModel) => model.model_id ?? model.name ?? '';
  const formatDeviceMemory = (memoryMb?: number | null) =>
    typeof memoryMb === 'number' && Number.isFinite(memoryMb) && memoryMb > 0
      ? formatBytes(memoryMb * 1024 * 1024)
      : '-';

  const refetchQuery = async (snapshot?: { refetch?: () => Promise<unknown> }) => {
    if (snapshot && typeof snapshot.refetch === 'function') {
      await snapshot.refetch();
    }
  };

  let selectedModelId = $state('');
  let selectedDevice = $state('');
  let selectedTaskCandidate = $state('');
  let taskInput = $state('');
  let taskInputMode = $state<'auto' | 'manual'>('auto');
  let taskModelId = $state('');
  let numEpisodesInput = $state('20');
  let denoisingStepsInput = $state('10');
  let inferenceStartError = $state('');
  let inferenceStopError = $state('');
  let inferenceStartPending = $state(false);
  let inferenceStopPending = $state(false);
  let startupStatus = $state<StartupOperationStatusResponse | null>(null);
  let startupStreamError = $state('');
  let systemStatusSnapshot = $state<SystemStatusSnapshot | null>(null);
  let realtimeContributor: TabRealtimeContributorHandle | null = null;
  let startupContributor: TabRealtimeContributorHandle | null = null;
  let startupOperationId = $state('');

  const operateRealtimeSubscriptions: TabSessionSubscription[] = [
    { subscription_id: 'operate.page.status', kind: 'operate.status', params: {} },
    { subscription_id: 'operate.page.system-status', kind: 'system.status', params: {} }
  ];

  const emptyRunnerStatus: RunnerStatus = {};
  $effect(() => {
    if (!selectedModelId && $inferenceModelsQuery.data?.models?.length) {
      selectedModelId = resolveModelId($inferenceModelsQuery.data.models[0]);
    }
  });

  $effect(() => {
    const devices = ($inferenceDeviceQuery.data?.devices ?? []).filter((device) => Boolean(device.device));
    const availableDevices = devices.filter((device) => device.available);
    const recommendedAvailable = availableDevices.find((device) => device.device === $inferenceDeviceQuery.data?.recommended);
    const recommendedNonCpu = recommendedAvailable?.device && recommendedAvailable.device !== 'cpu' ? recommendedAvailable : null;
    const firstNonCpu = availableDevices.find((device) => device.device !== 'cpu');
    const preferredDevice =
      recommendedNonCpu?.device ??
      firstNonCpu?.device ??
      recommendedAvailable?.device ??
      availableDevices[0]?.device ??
      devices[0]?.device ??
      'cpu';
    const selectedAvailable = availableDevices.some((device) => device.device === selectedDevice);
    const shouldPromoteFromCpu =
      selectedDevice === 'cpu' &&
      Boolean(firstNonCpu?.device) &&
      firstNonCpu?.device !== selectedDevice;

    if (selectedAvailable && !shouldPromoteFromCpu) return;
    selectedDevice =
      preferredDevice;
  });

  const disposeStartupContributor = () => {
    startupContributor?.dispose();
    startupContributor = null;
  };

  const handleStartupStatusUpdate = async (status: StartupOperationStatusResponse) => {
    startupStatus = status;
    if (status.state === 'completed' && status.target_session_id) {
      disposeStartupContributor();
      startupOperationId = '';
      inferenceStartPending = false;
      await refetchQuery($inferenceRunnerStatusQuery);
      await goto(`/operate/sessions/${encodeURIComponent(status.target_session_id)}?kind=inference`);
      return;
    }
    if (status.state === 'failed') {
      disposeStartupContributor();
      startupOperationId = '';
      inferenceStartPending = false;
      inferenceStartError = status.error ?? status.message ?? '推論の開始に失敗しました。';
    }
  };

  const handleInferenceStart = async () => {
    if (!selectedModelId) {
      inferenceStartError = '推論モデルを選択してください。';
      return;
    }
    startupStatus = null;
    startupStreamError = '';
    inferenceStartPending = true;
    inferenceStartError = '';
    inferenceStopError = '';
    const rawNumEpisodes = numEpisodesInput.trim();
    let numEpisodes: number | undefined;
    if (rawNumEpisodes) {
      const parsed = Number.parseInt(rawNumEpisodes, 10);
      if (!Number.isInteger(parsed) || parsed < 1) {
        inferenceStartError = 'エピソード数は 1 以上の整数で入力してください。';
        inferenceStartPending = false;
        return;
      }
      numEpisodes = parsed;
    }
    let denoisingSteps: number | undefined;
    if (supportsDenoisingSteps) {
      const raw = denoisingStepsInput.trim();
      if (raw) {
        const parsed = Number.parseInt(raw, 10);
        if (!Number.isInteger(parsed) || parsed < 1) {
          inferenceStartError = 'denoising step は 1 以上の整数で入力してください。';
          inferenceStartPending = false;
          return;
        }
        denoisingSteps = parsed;
      }
    }
    const policyOptions =
      denoisingSteps === undefined
        ? undefined
        : selectedPolicyType === 'pi05'
          ? { pi05: { denoising_steps: denoisingSteps } }
          : { pi0: { denoising_steps: denoisingSteps } };
    try {
      const result = (await api.inference.runnerStart({
        model_id: selectedModelId,
        device: selectedDevice || $inferenceDeviceQuery.data?.recommended,
        task: taskInput.trim() || undefined,
        num_episodes: numEpisodes,
        policy_options: policyOptions
      })) as StartupOperationAcceptedResponse;
      if (!result?.operation_id) {
        throw new Error('開始オペレーションIDを取得できませんでした。');
      }
      disposeStartupContributor();
      startupOperationId = result.operation_id;
      const snapshot = await api.startup.operation(result.operation_id);
      await handleStartupStatusUpdate(snapshot);
    } catch (err) {
      inferenceStartError = err instanceof Error ? err.message : '推論の開始に失敗しました。';
      inferenceStartPending = false;
    }
  };

  const handleTaskCandidateSelect = (nextTask: string) => {
    taskInputMode = 'auto';
    selectedTaskCandidate = nextTask;
    taskInput = nextTask;
  };

  const handleTaskInput = (nextValue: string) => {
    taskInputMode = 'manual';
    taskInput = nextValue;
    selectedTaskCandidate = taskCandidates.includes(nextValue) ? nextValue : '';
  };

  const clearTaskInput = () => {
    taskInputMode = 'manual';
    taskInput = '';
    selectedTaskCandidate = '';
  };

  const handleInferenceStop = async () => {
    inferenceStopPending = true;
    inferenceStopError = '';
    try {
      const runnerStatus = $inferenceRunnerStatusQuery.data?.runner_status ?? emptyRunnerStatus;
      const sessionId = runnerStatus.session_id;
      await api.inference.runnerStop({ session_id: sessionId });
      await refetchQuery($inferenceRunnerStatusQuery);
    } catch (err) {
      inferenceStopError = err instanceof Error ? err.message : '推論の停止に失敗しました。';
    } finally {
      inferenceStopPending = false;
    }
  };

  const runnerStatus = $derived($inferenceRunnerStatusQuery.data?.runner_status ?? emptyRunnerStatus);
  const inferenceModels = $derived($inferenceModelsQuery.data?.models ?? []);
  const deviceOptions = $derived(($inferenceDeviceQuery.data?.devices ?? []).filter((device) => Boolean(device.device)));
  const recommendedDevice = $derived($inferenceDeviceQuery.data?.recommended ?? 'cpu');
  const selectedModel = $derived(
    inferenceModels.find((item) => resolveModelId(item) === selectedModelId)
  );
  const selectedDeviceInfo = $derived(deviceOptions.find((device) => device.device === selectedDevice) ?? null);
  const selectedPolicyType = $derived((selectedModel?.policy_type ?? '').toLowerCase());
  const taskCandidates = $derived(selectedModel?.task_candidates ?? []);
  const supportsDenoisingSteps = $derived(PI0_POLICY_TYPES.has(selectedPolicyType));
  const runnerActive = $derived(Boolean(runnerStatus.active));
  const startupProgressPercent = $derived(
    Math.min(100, Math.max(0, Number(startupStatus?.progress_percent ?? 0)))
  );
  const startupState = $derived(startupStatus?.state ?? '');
  const startupActive = $derived(startupState === 'queued' || startupState === 'running');
  const showStartupBlock = $derived(Boolean(startupStatus) && (startupActive || startupState === 'failed'));
  const startupPhaseLabel = $derived(START_PHASE_LABELS[startupStatus?.phase ?? ''] ?? (startupStatus?.phase ?? '-'));
  const startupDetail = $derived(startupStatus?.detail ?? {});
  const startupPanelClass = $derived(
    startupState === 'failed' ? 'border-rose-200 bg-rose-50/80' : 'border-emerald-200 bg-emerald-50/70'
  );
  const startupTextClass = $derived(startupState === 'failed' ? 'text-rose-800' : 'text-emerald-800');
  const startupSubtextClass = $derived(startupState === 'failed' ? 'text-rose-900/80' : 'text-emerald-900/80');
  const startupTrackClass = $derived(startupState === 'failed' ? 'bg-rose-100' : 'bg-emerald-100');
  const startupBarClass = $derived(startupState === 'failed' ? 'bg-rose-500' : 'bg-emerald-500');

  $effect(() => {
    const modelId = selectedModelId;
    const candidates = taskCandidates;
    const mode = taskInputMode;

    const modelChanged = modelId !== taskModelId;
    if (modelChanged) {
      taskModelId = modelId;
      if (mode === 'auto') {
        const nextCandidate = candidates[0] ?? '';
        selectedTaskCandidate = nextCandidate;
        taskInput = nextCandidate;
        return;
      }
      selectedTaskCandidate = candidates.includes(taskInput) ? taskInput : '';
      return;
    }

    if (mode === 'auto') {
      if (!candidates.length) {
        selectedTaskCandidate = '';
        taskInput = '';
        return;
      }
      if (!selectedTaskCandidate || !candidates.includes(selectedTaskCandidate)) {
        selectedTaskCandidate = candidates[0];
      }
      if (taskInput !== selectedTaskCandidate) {
        taskInput = selectedTaskCandidate;
      }
      return;
    }

    const nextSelectedCandidate = candidates.includes(taskInput) ? taskInput : '';
    if (selectedTaskCandidate !== nextSelectedCandidate) {
      selectedTaskCandidate = nextSelectedCandidate;
    }
  });

  $effect(() => {
    if (!browser) {
      return;
    }
    if (!startupOperationId) {
      disposeStartupContributor();
      return;
    }
    const currentOperationId = startupOperationId;
    disposeStartupContributor();
    startupContributor = registerTabRealtimeContributor({
      subscriptions: [
        {
          subscription_id: `operate.startup.${currentOperationId}`,
          kind: 'startup.operation',
          params: { operation_id: currentOperationId }
        }
      ],
      onEvent: (event: TabRealtimeEvent) => {
        if (event.op !== 'snapshot' || event.source?.kind !== 'startup.operation') return;
        if (startupOperationId !== currentOperationId) return;
        void handleStartupStatusUpdate(event.payload as StartupOperationStatusResponse);
      }
    });

    return () => {
      disposeStartupContributor();
    };
  });

  $effect(() => {
    if (!browser) {
      return;
    }
    if (realtimeContributor === null) {
      realtimeContributor = registerTabRealtimeContributor({
        subscriptions: operateRealtimeSubscriptions,
        onEvent: (event: TabRealtimeEvent) => {
          if (event.op !== 'snapshot') return;
          if (event.source?.kind === 'operate.status') {
            const payload = event.payload as OperateStatusStreamPayload;
            if (payload.inference_runner_status) {
              queryClient.setQueryData(['inference', 'runner', 'status'], payload.inference_runner_status);
            }
            if (payload.operate_status) {
              queryClient.setQueryData(['operate', 'status'], payload.operate_status);
            }
            return;
          }
          if (event.source?.kind === 'system.status') {
            systemStatusSnapshot = event.payload as SystemStatusSnapshot;
          }
        }
      });
      if (!realtimeContributor) {
        return;
      }
      return;
    }
    realtimeContributor.setSubscriptions(operateRealtimeSubscriptions);
  });

  $effect(() => {
    return () => {
      disposeStartupContributor();
      realtimeContributor?.dispose();
      realtimeContributor = null;
    };
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">Operate</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">推論</h1>
      <p class="mt-2 text-sm text-slate-600">推論セッションの確認と開始を行います。</p>
    </div>
  </div>
</section>

<ActiveSessionSection
  title="稼働中セッション"
  description="推論セッションの状況を表示します。"
  badges={[`推論: ${runnerActive ? '稼働中' : '停止'}`]}
>
  {#if $inferenceRunnerStatusQuery.isLoading}
    <ActiveSessionCard tone="muted">
      <p class="text-sm text-slate-600">推論セッションを読み込み中...</p>
    </ActiveSessionCard>
  {:else if runnerActive}
    <ActiveSessionCard>
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="label">セッション種別</p>
          <p class="text-base font-semibold text-slate-900">推論</p>
          <p class="mt-1 text-xs text-slate-500">モデル推論での実行セッション。</p>
        </div>
        <span class="chip">稼働中</span>
      </div>
      <div class="mt-3 space-y-1 text-xs text-slate-500">
        <p>session_id: {runnerStatus.session_id ?? '-'}</p>
        <p>task: {runnerStatus.task ?? '-'}</p>
        <p>queue: {runnerStatus.queue_length ?? 0}</p>
      </div>
      <div class="mt-4 flex flex-wrap gap-2">
        <Button.Root
          class="btn-primary"
          href={`/operate/sessions/${encodeURIComponent(runnerStatus.session_id ?? '')}?kind=inference`}
        >
          セッションを開く
        </Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={handleInferenceStop} disabled={inferenceStopPending}>
          停止
        </Button.Root>
      </div>
      {#if runnerStatus.last_error}
        <p class="mt-2 text-xs text-rose-600">{runnerStatus.last_error}</p>
      {/if}
      {#if inferenceStopError}
        <p class="mt-2 text-xs text-rose-600">{inferenceStopError}</p>
      {/if}
    </ActiveSessionCard>
  {:else}
    <ActiveSessionCard tone="muted">
      <p class="text-sm text-slate-600">稼働中のセッションはありません。</p>
    </ActiveSessionCard>
  {/if}
</ActiveSessionSection>

<section class="card overflow-hidden">
  <div class="border-b border-slate-200/80 bg-[linear-gradient(140deg,rgba(91,124,250,0.14),rgba(255,184,107,0.10),rgba(255,255,255,0.98))] px-6 py-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="label">Launch Pad</p>
        <h2 class="mt-2 text-2xl font-semibold tracking-tight text-slate-950">推論開始</h2>
        <p class="mt-2 text-sm leading-6 text-slate-600">
          モデル選択、実行デバイス、タスク指定を一つの面にまとめて起動まで進めます。
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <span class="chip">{runnerActive ? '稼働中' : '待機中'}</span>
        <span class="chip">device: {selectedDeviceInfo?.device ?? selectedDevice ?? recommendedDevice}</span>
        {#if selectedModel}
          <span class="chip">{selectedModel.policy_type ?? 'unknown'}</span>
        {/if}
      </div>
    </div>
  </div>

  <div class="grid gap-6 px-6 py-6 xl:grid-cols-[minmax(0,1fr)_360px]">
    <section class="nested-block flex h-full flex-col justify-start p-5">
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="label">実行設定</p>
          <h3 class="mt-2 text-xl font-semibold text-slate-950">ランタイム</h3>
        </div>
        <span class="chip bg-white">{selectedDeviceInfo?.device ?? selectedDevice ?? recommendedDevice}</span>
      </div>

      <div class="mt-5 space-y-5">
        <div>
          <div class="flex items-center justify-between gap-2">
            <span class="label">デバイス</span>
            <span class="text-xs text-slate-500">推奨: {recommendedDevice}</span>
          </div>
          <div class="mt-3 grid gap-2 sm:grid-cols-2">
            {#each deviceOptions as device}
              <button
                type="button"
                class={`rounded-2xl border px-4 py-3 text-left transition ${
                  selectedDevice === device.device
                    ? 'border-sky-300 bg-sky-50/40 shadow-[0_0_0_3px_rgba(14,165,233,0.08)]'
                    : device.available
                      ? 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                      : 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400'
                }`}
                onclick={() => device.available && (selectedDevice = device.device ?? 'cpu')}
                disabled={!device.available}
                aria-pressed={selectedDevice === device.device}
              >
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <p class="text-sm font-semibold text-slate-900">{device.device}</p>
                    <p class="mt-1 text-xs text-slate-500">{device.available ? '利用可能' : '利用不可'}</p>
                  </div>
                  {#if device.device === recommendedDevice}
                    <span class="chip bg-emerald-50 text-emerald-700">推奨</span>
                  {/if}
                </div>
                <p class="mt-3 text-xs text-slate-500">
                  free {formatDeviceMemory(device.memory_free_mb)} / total {formatDeviceMemory(device.memory_total_mb)}
                </p>
              </button>
            {/each}
            {#if deviceOptions.length === 0}
              <div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 px-4 py-5 text-sm text-slate-500 sm:col-span-2">
                デバイス情報を取得できないため、`cpu` を利用します。
              </div>
            {/if}
          </div>
        </div>

        <div>
          <div class="flex items-center justify-between gap-2">
            <span class="label">タスク説明</span>
            <button
              type="button"
              class="text-xs font-semibold text-slate-500 transition hover:text-slate-800 disabled:cursor-not-allowed disabled:text-slate-300"
              onclick={clearTaskInput}
              disabled={!taskInput.trim()}
              aria-label="タスク説明をクリア"
            >
              クリア
            </button>
          </div>
          <div class="mt-3">
            <TaskCandidateCombobox
              items={taskCandidates}
              value={selectedTaskCandidate}
              inputValue={taskInput}
              placeholder="候補からタスクを選択"
              emptyMessage="このモデルで利用可能なタスク候補はありません。"
              onSelect={handleTaskCandidateSelect}
              onInput={handleTaskInput}
            />
          </div>
          {#if taskCandidates.length}
            <p class="mt-2 text-xs text-slate-500">
              候補選択または直接入力のどちらでもタスクを指定できます。
            </p>
          {:else}
            <p class="mt-2 text-xs text-slate-500">
              このモデルに紐づく active データセットのタスク候補はありません。直接入力してください。
            </p>
          {/if}
        </div>
      </div>
    </section>

    <div class="space-y-4 self-start xl:sticky xl:top-6">
      <InferenceModelSelector
        models={inferenceModels}
        ownerOptions={$inferenceModelsQuery.data?.owner_options ?? []}
        profileOptions={$inferenceModelsQuery.data?.profile_options ?? []}
        trainingStepsOptions={$inferenceModelsQuery.data?.training_steps_options ?? []}
        batchSizeOptions={$inferenceModelsQuery.data?.batch_size_options ?? []}
        selectedModelId={selectedModelId}
        loading={$inferenceModelsQuery.isLoading}
        disabled={runnerActive || inferenceStartPending || startupActive}
        onSelect={(modelId) => {
          selectedModelId = modelId;
        }}
      />

      <section class="nested-block p-4">
        <p class="label">起動</p>
        <div class="mt-3 space-y-3">
          <div class="text-xs text-slate-500">
            {#if !selectedModel}
              推論モデルを選択してください。
            {:else if selectedModel.is_local}
              ローカルモデルから起動します。
            {:else}
              モデル未同期のため起動前に同期処理が入る可能性があります。
            {/if}
          </div>
          <Button.Root
            class="btn-primary w-full"
            type="button"
            onclick={handleInferenceStart}
            disabled={inferenceStartPending || startupActive || !selectedModelId || runnerActive}
            aria-busy={inferenceStartPending}
          >
            {startupActive ? '準備中...' : '推論を開始'}
          </Button.Root>
          {#if inferenceStartError}
            <p class="text-xs text-rose-600">{inferenceStartError}</p>
          {/if}
        </div>
      </section>
    </div>
  </div>

  <div class="border-t border-slate-200/80 px-6 py-6">
    <section class="nested-block p-4">
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p class="label">詳細設定</p>
        <p class="text-xs text-slate-500">必要な項目のみ指定</p>
      </div>
      <div class="mt-3 grid gap-4 md:grid-cols-[320px_320px]">
        <label class="block w-full max-w-[320px]">
          <span class="label">エピソード数</span>
          <input
            class="input mt-2"
            type="text"
            inputmode="numeric"
            bind:value={numEpisodesInput}
            placeholder="例: 20"
          />
        </label>
        {#if supportsDenoisingSteps}
          <label class="block w-full max-w-[320px]">
            <span class="label">Denoising Step</span>
            <input
              class="input mt-2"
              type="text"
              inputmode="numeric"
              bind:value={denoisingStepsInput}
              placeholder="例: 10"
            />
          </label>
        {/if}
      </div>
    </section>
  </div>

  {#if showStartupBlock}
    <div class="border-t border-slate-200/80 px-6 py-5">
      <div class={`rounded-2xl border p-4 ${startupPanelClass}`}>
        <div class={`flex items-center justify-between gap-3 text-xs ${startupTextClass}`}>
          <p>{startupStatus?.message ?? '推論セッションを準備中です...'}</p>
          <p class="font-semibold">{Math.round(startupProgressPercent)}%</p>
        </div>
        <p class={`mt-1 text-xs ${startupSubtextClass}`}>フェーズ: {startupPhaseLabel}</p>
        <div class={`mt-3 h-2 overflow-hidden rounded-full ${startupTrackClass}`}>
          <div
            class={`h-full rounded-full transition-[width] duration-300 ${startupBarClass}`}
            style={`width: ${startupProgressPercent}%;`}
          ></div>
        </div>
        {#if (startupDetail.total_files ?? 0) > 0 || (startupDetail.total_bytes ?? 0) > 0}
          <p class={`mt-3 text-xs ${startupSubtextClass}`}>
            {startupDetail.files_done ?? 0}/{startupDetail.total_files ?? 0} files
            · {formatBytes(startupDetail.transferred_bytes)} / {formatBytes(startupDetail.total_bytes)}
            {#if startupDetail.current_file}
              · {startupDetail.current_file}
            {/if}
          </p>
        {/if}
        {#if startupStreamError}
          <p class="mt-3 text-xs text-amber-700">{startupStreamError}</p>
        {/if}
      </div>
    </div>
  {/if}
</section>

<OperateStatusCards snapshot={systemStatusSnapshot} network={$operateStatusQuery.data?.network ?? null} />

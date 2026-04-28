<script lang="ts">
  import { browser } from '$app/environment';
  import { onDestroy, onMount } from 'svelte';
  import { page } from '$app/state';
  import { AlertDialog, Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';
  import { registerRealtimeTrackConsumer, type RealtimeTrackConsumerHandle, type RealtimeTrackEvent } from '$lib/realtime/trackClient';
  import { queryClient } from '$lib/queryClient';
  import { requestInferenceUploadProgress } from '$lib/recording/inferenceUploadProgressRequests';

  import SessionLayoutEditor from '$lib/components/recording/SessionLayoutEditor.svelte';
  import { scrollIntoViewSoon, speakSessionMessage } from '$lib/session/sessionUx';

  type RunnerStatus = {
    active?: boolean;
    session_id?: string;
    state?: string;
    task?: string;
    last_error?: string;
    paused?: boolean;
    recording_dataset_id?: string | null;
    recording_active?: boolean;
    recorder_state?: string | null;
    awaiting_continue_confirmation?: boolean;
    batch_size?: number;
    episode_count?: number;
    num_episodes?: number;
    denoising_steps?: number | null;
  };

  type InferenceRunnerStatusResponse = {
    runner_status?: RunnerStatus;
  };

  type VlaborStatus = {
    status?: string;
    service?: string;
    state?: string;
    status_detail?: string;
    running_for?: string;
    created_at?: string;
    container_id?: string;
  };

  type OperateStatusStreamPayload = {
    vlabor_status?: VlaborStatus;
    inference_runner_status?: InferenceRunnerStatusResponse;
    operate_status?: unknown;
  };

  const KIND_LABELS: Record<string, string> = {
    inference: '推論',
    teleop: 'テレオペ'
  };

  const sessionId = $derived(page.params.session_id ?? '');
  const sessionKindParam = $derived(page.url.searchParams.get('kind') ?? '');

  const inferenceRunnerStatusQuery = createQuery<InferenceRunnerStatusResponse>({
    queryKey: ['inference', 'runner', 'status'],
    queryFn: api.inference.runnerStatus
  });

  const vlaborStatusQuery = createQuery<VlaborStatus>({
    queryKey: ['profiles', 'vlabor', 'status'],
    queryFn: api.profiles.vlaborStatus
  });

  let mounted = $state(false);
  let editMode = $state(false);
  let continueModalOpen = $state(false);
  let continueDecisionPending = $state(false);
  let continueDecisionError = $state('');
  let editorAnchor = $state<HTMLElement | null>(null);
  let lastAnnouncedState = $state('');

  onMount(() => {
    mounted = true;
    const stopAutoScroll = scrollIntoViewSoon(editorAnchor, 180);
    return () => {
      stopAutoScroll();
    };
  });

  let realtimeContributor: RealtimeTrackConsumerHandle | null = null;

  onMount(() => {
    if (!browser) return;
    realtimeContributor = registerRealtimeTrackConsumer({
      tracks: [
        {
          kind: 'operate.status',
          params: {}
        }
      ],
      onEvent: (event: RealtimeTrackEvent) => {
        if (event.kind !== 'operate.status') return;
        const payload = event.detail as OperateStatusStreamPayload;
        queryClient.setQueryData(['profiles', 'vlabor', 'status'], payload.vlabor_status);
        queryClient.setQueryData(['inference', 'runner', 'status'], payload.inference_runner_status);
        queryClient.setQueryData(['operate', 'status'], payload.operate_status);
      }
    });
  });

  onDestroy(() => {
    realtimeContributor?.dispose();
    realtimeContributor = null;
  });

  const runnerStatus = $derived($inferenceRunnerStatusQuery.data?.runner_status ?? {});
  const vlaborStatus = $derived($vlaborStatusQuery.data ?? {});
  const inferenceMatches = $derived(runnerStatus.session_id === sessionId);
  const teleopMatches = $derived(sessionId === 'teleop');

  const resolvedKind = $derived(
    sessionKindParam || (inferenceMatches ? 'inference' : teleopMatches ? 'teleop' : '')
  );
  const blueprintKind = $derived(
    resolvedKind === 'inference' ? 'inference' : resolvedKind === 'teleop' ? 'teleop' : ''
  );

  const inferenceRecordingSessionId = $derived(
    typeof runnerStatus.recording_dataset_id === 'string' ? runnerStatus.recording_dataset_id : ''
  );

  const layoutSessionId = $derived(
    resolvedKind === 'inference' ? inferenceRecordingSessionId || '' : sessionId
  );

  const layoutMode = $derived(resolvedKind === 'inference' ? 'recording' : 'operate');

  const continueBatchSize = $derived.by(() => {
    const raw = runnerStatus.batch_size;
    if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) {
      return Math.floor(raw);
    }
    return 20;
  });

  const toggleEditMode = () => {
    editMode = !editMode;
  };

  const refreshStatus = () => {
    void $inferenceRunnerStatusQuery.refetch?.();
    void $vlaborStatusQuery.refetch?.();
  };

  const sessionLabel = $derived(KIND_LABELS[resolvedKind] ?? 'セッション');
  const sessionState = $derived(
    resolvedKind === 'inference'
      ? runnerStatus.state
        ? runnerStatus.state
        : runnerStatus.paused
          ? 'paused'
        : runnerStatus.active
          ? 'running'
          : runnerStatus.last_error
            ? 'failed'
            : vlaborStatus.state ?? 'idle'
      : vlaborStatus.state ?? 'idle'
  );
  const handleContinueDecision = async (continueRecording: boolean) => {
    if (continueDecisionPending) return;
    continueDecisionPending = true;
    continueDecisionError = '';
    const targetDatasetId = inferenceRecordingSessionId;
    try {
      await api.inference.decideRecording(
        continueRecording
          ? { continue_recording: true }
          : {
              continue_recording: false,
              stop_reason: 'batch_declined',
              recording_dataset_id: targetDatasetId || undefined
            }
      );
      if (!continueRecording && targetDatasetId) {
        requestInferenceUploadProgress({
          inferenceSessionId: sessionId,
          datasetId: targetDatasetId,
          stopReason: 'batch_declined'
        });
      }
      await $inferenceRunnerStatusQuery.refetch?.();
      continueModalOpen = false;
    } catch (error) {
      continueDecisionError =
        error instanceof Error ? error.message : '継続判定の適用に失敗しました。';
    } finally {
      continueDecisionPending = false;
    }
  };

  $effect(() => {
    if (!mounted) return;
    if (resolvedKind !== 'inference') {
      continueModalOpen = false;
      return;
    }
    continueModalOpen = Boolean(runnerStatus.awaiting_continue_confirmation);
  });

  $effect(() => {
    if (!mounted) return;
    const next = String(sessionState ?? '').trim();
    if (!next) return;
    if (!lastAnnouncedState) {
      lastAnnouncedState = next;
      return;
    }
    if (lastAnnouncedState === next) return;
    lastAnnouncedState = next;

    if (runnerStatus.awaiting_continue_confirmation) {
      speakSessionMessage('エピソード保存完了です。継続収録を確認してください。');
      return;
    }
    if (next === 'resetting' || next === 'resetting_paused') {
      speakSessionMessage('環境をリセットしてください。');
      return;
    }
    if (next === 'running') {
      speakSessionMessage('推論を開始しました。');
      return;
    }
    if (next === 'failed') {
      speakSessionMessage('推論でエラーが発生しました。');
      return;
    }
    if (next === 'stopped' || next === 'inactive') {
      speakSessionMessage('推論を停止しました。');
    }
  });
</script>

<section class="card-strong p-6">
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="section-title">Operate Session</p>
      <h1 class="text-3xl font-semibold text-slate-900">{sessionLabel} セッション</h1>
    </div>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <Button.Root class="btn-ghost" type="button" onclick={toggleEditMode}>
        {editMode ? '閲覧モード' : '編集モード'}
      </Button.Root>
      <Button.Root class="btn-ghost" href="/operate">テレオペ / 推論一覧</Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={refreshStatus}>更新</Button.Root>
    </div>
  </div>
</section>

<AlertDialog.Root bind:open={continueModalOpen}>
  <AlertDialog.Portal>
    <AlertDialog.Overlay class="fixed inset-0 z-40 bg-slate-900/50 backdrop-blur-[1px]" />
    <AlertDialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,32rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      <AlertDialog.Title class="text-base font-semibold text-slate-900">
        追加収録を開始しますか？
      </AlertDialog.Title>
      <AlertDialog.Description class="mt-2 text-sm text-slate-600">
        {continueBatchSize} エピソードの収録が完了しました。同じデータセットに追加で
        {continueBatchSize} エピソードを収録しますか？
      </AlertDialog.Description>
      {#if inferenceRecordingSessionId}
        <p class="mt-2 text-[11px] text-slate-500">dataset: {inferenceRecordingSessionId}</p>
      {/if}
      {#if continueDecisionError}
        <p class="mt-2 text-xs text-rose-600">{continueDecisionError}</p>
      {/if}
      <div class="mt-5 flex items-center justify-end gap-2">
        <Button.Root
          class="btn-ghost"
          type="button"
          disabled={continueDecisionPending}
          onclick={() => {
            void handleContinueDecision(false);
          }}
        >
          {continueDecisionPending ? '処理中...' : '終了'}
        </Button.Root>
        <Button.Root
          class="btn-primary"
          type="button"
          disabled={continueDecisionPending}
          onclick={() => {
            void handleContinueDecision(true);
          }}
        >
          {continueDecisionPending ? '処理中...' : '追加収録'}
        </Button.Root>
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>

<div class="mt-6" bind:this={editorAnchor}>
<SessionLayoutEditor
  blueprintSessionId={sessionId}
  blueprintSessionKind={blueprintKind}
  layoutSessionId={layoutSessionId}
  layoutSessionKind={blueprintKind}
  layoutMode={layoutMode}
  viewSource="ros"
  {editMode}
/>
</div>

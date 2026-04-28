<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { getContext } from 'svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import { AlertDialog, Button } from 'bits-ui';
  import { toStore } from 'svelte/store';
  import toast from 'svelte-french-toast';
  import { api } from '$lib/api/client';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';
  import { registerRealtimeTrackConsumer, type RealtimeTrackConsumerHandle, type RealtimeTrackEvent } from '$lib/realtime/trackClient';
  import { VIEWER_RUNTIME, type ViewerRuntimeStore } from '$lib/viewer/runtimeContext';
  import { sessionViewer } from '$lib/viewer/sessionViewerStore';
  import { hasEditableFocus, isEditableTarget } from '$lib/recording/keyboard';
  import {
    createPendingRecordingUploadStatus,
    shouldIgnoreIdleUploadSnapshot,
    type RecordingUploadStatus
  } from '$lib/recording/uploadStatus';
  import {
    subscribeRecorderStatus,
    type RecorderStatus,
    type RosbridgeStatus
  } from '$lib/recording/recorderStatus';
  import { subscribeInferenceUploadProgressRequests } from '$lib/recording/inferenceUploadProgressRequests';

  let {
    title = 'Controls',
  }: {
    title?: string;
  } = $props();

  const runtimeStore = getContext<ViewerRuntimeStore>(VIEWER_RUNTIME);
  const runtime = $derived($runtimeStore);
  const mode = $derived(runtime.mode);
  const sessionId = $derived(runtime.kind === 'ros' ? runtime.sessionId : '');
  const sessionKind = $derived(runtime.kind === 'ros' ? runtime.sessionKind : '');

  type InferenceRunnerStatus = {
    active?: boolean;
    session_id?: string | null;
    recording_dataset_id?: string | null;
    recording_active?: boolean;
    awaiting_continue_confirmation?: boolean;
  };

  type InferenceRunnerStatusResponse = {
    runner_status?: InferenceRunnerStatus;
  };

  const inferenceRunnerStatusQuery = createQuery<InferenceRunnerStatusResponse>(
    toStore(() => ({
      queryKey: ['inference', 'runner', 'status'],
      queryFn: api.inference.runnerStatus,
      enabled: sessionKind === 'inference'
    }))
  );

  let recorderStatus = $state<RecorderStatus | null>(null);
  let rosbridgeStatus = $state<RosbridgeStatus>('idle');
  let actionBusy = $state('');
  let confirmOpen = $state(false);
  let confirmTitle = $state('');
  let confirmDescription = $state('');
  let confirmActionLabel = $state('実行');
  let pendingConfirmAction = $state<(() => Promise<boolean>) | null>(null);
  let wasDisconnected = false;
  let wasFinalizing = false;
  let previousStatusState = '';
  let finalizingToastId: string | null = null;
  let uploadModalOpen = $state(false);
  let uploadDatasetId = $state('');
  let uploadStatus = $state<RecordingUploadStatus | null>(null);
  let uploadContributor: RealtimeTrackConsumerHandle | null = null;
  let dismissedUploadDatasetId = $state('');

  const runAction = async (
    label: string,
    action: () => Promise<unknown>,
    options: { successToast?: string } = {}
  ): Promise<boolean> => {
    actionBusy = label;
    try {
      await action();
      toast.success(options.successToast ?? `${label}リクエストを受け付けました。`);
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : `${label} に失敗しました。`;
      toast.error(message);
      return false;
    } finally {
      actionBusy = '';
    }
  };

  const handlePause = async () =>
    runAction(
      '中断',
      () => (sessionKind === 'inference' ? api.inference.pauseRunner() : api.recording.pauseSession()),
      {
        successToast:
          sessionKind === 'inference'
            ? '推論と録画の一時停止リクエストを受け付けました。'
            : '一時停止リクエストを受け付けました。'
      }
    ).then(async (success) => {
      if (success && sessionKind === 'inference') {
        await $inferenceRunnerStatusQuery.refetch?.();
      }
      return success;
    });
  const handleResume = async () =>
    runAction(
      '再開',
      () => (sessionKind === 'inference' ? api.inference.resumeRunner() : api.recording.resumeSession()),
      {
        successToast:
          sessionKind === 'inference'
            ? '推論と録画の再開リクエストを受け付けました。'
            : '再開リクエストを受け付けました。'
      }
    ).then(async (success) => {
      if (success && sessionKind === 'inference') {
        await $inferenceRunnerStatusQuery.refetch?.();
      }
      return success;
    });
  const openConfirm = (options: {
    title: string;
    description: string;
    actionLabel: string;
    action: () => Promise<boolean>;
  }) => {
    if (actionBusy) return;
    confirmTitle = options.title;
    confirmDescription = options.description;
    confirmActionLabel = options.actionLabel;
    pendingConfirmAction = options.action;
    confirmOpen = true;
  };
  const handleConfirmAction = async () => {
    if (!pendingConfirmAction) return;
    const action = pendingConfirmAction;
    pendingConfirmAction = null;
    confirmOpen = false;
    await action();
  };
  const handleConfirmCancel = () => {
    pendingConfirmAction = null;
  };
  const handleStart = async () => {
    if (sessionKind === 'inference') {
      const success = await runAction('開始', () => api.inference.resumeRunner(), {
        successToast: '推論と録画の開始リクエストを受け付けました。状態反映を待っています。'
      });
      if (success) {
        await $inferenceRunnerStatusQuery.refetch?.();
      }
      return;
    }
    if (!sessionId) return;
    await runAction('開始', () => api.recording.startSession({ dataset_id: sessionId }), {
      successToast: '開始リクエストを受け付けました。状態反映を待っています。'
    });
  };
  const handleRetakePrevious = async () => {
    openConfirm({
      title: '直前エピソードを取り直しますか？',
      description: '直前に保存したエピソードを取り消して、録画し直します。',
      actionLabel: '取り直す',
      action: () =>
        runAction('直前取り直し', () => api.recording.retakePreviousEpisode(), {
          successToast: '直前エピソードの取り直しを受け付けました。'
        })
    });
  };
  const handleRetakeCurrent = async () => {
    openConfirm({
      title: '現在のエピソードを取り直しますか？',
      description: '現在のエピソードは破棄され、最初から録画し直します。',
      actionLabel: '取り直す',
      action: () =>
        runAction('取り直し', () => api.recording.cancelEpisode(), {
          successToast: '現在エピソードの取り直しを受け付けました。'
        })
    });
  };
  const handleNext = async () => {
    await runAction('次へ', () => api.recording.nextEpisode(), {
      successToast: '次エピソードへの遷移を受け付けました。状態反映を待っています。'
    });
  };
  const handleStop = async () => {
    const targetDatasetId = String(
      sessionKind === 'inference'
        ? inferenceRecordingDatasetId || statusDatasetId || datasetId || ''
        : datasetId || sessionId || ''
    ).trim();
    openConfirm({
      title: sessionKind === 'inference' ? '推論セッションを終了しますか？' : 'データセット収録を終了しますか？',
      description:
        sessionKind === 'inference'
          ? '現在のエピソードを保存して、推論と収録を終了します。'
          : '現在のエピソードは保存された状態で終了します。',
      actionLabel: '終了する',
      action: async () => {
        if (targetDatasetId) {
          startUploadModal(targetDatasetId);
        }
        const success = await runAction(
          '終了',
          () =>
            sessionKind === 'inference'
              ? api.inference.decideRecording({
                  continue_recording: false,
                  stop_reason: 'manual_stop',
                  recording_dataset_id: targetDatasetId || undefined
                })
              : api.recording.stopSession({
                  dataset_id: datasetId,
                  save_current: true
                }),
          {
            successToast: '終了リクエストを受け付けました。状態反映を待っています。'
          }
        );
        if (!success) {
          disposeUploadContributor();
          uploadModalOpen = false;
          return false;
        }
        if (sessionKind === 'inference') {
          await $inferenceRunnerStatusQuery.refetch?.();
        }
        return true;
      }
    });
  };

  const isTerminalUploadStatus = (status: { status?: string; phase?: string } | null) => {
    if (!status) return false;
    const phase = String(status.phase ?? '').toLowerCase();
    const value = String(status.status ?? '').toLowerCase();
    return (
      phase === 'completed' ||
      phase === 'failed' ||
      phase === 'disabled' ||
      value === 'completed' ||
      value === 'failed' ||
      value === 'disabled'
    );
  };

  const uploadPhaseLabel = $derived.by(() => {
    const phase = String(uploadStatus?.phase ?? '').toLowerCase();
    if (actionBusy === '終了' && (!phase || phase === 'idle')) {
      return '収録終了処理中';
    }
    if (phase === 'starting') return 'アップロード準備中';
    if (phase === 'uploading') return 'アップロード中';
    if (phase === 'completed') return 'アップロード完了';
    if (phase === 'failed') return 'アップロード失敗';
    if (phase === 'disabled') return 'アップロード無効';
    return '待機中';
  });

  const uploadProgressPercent = $derived.by(() => {
    const raw = uploadStatus?.progress_percent;
    if (typeof raw === 'number' && Number.isFinite(raw)) {
      return Math.min(Math.max(raw, 0), 100);
    }
    return 0;
  });

  const uploadReturnHref = $derived(
    sessionKind === 'recording' ? '/record' : sessionKind === 'inference' ? '/operate' : '/'
  );
  const uploadReturnLabel = $derived(
    sessionKind === 'recording' ? '一覧へ戻る' : sessionKind === 'inference' ? '一覧へ戻る' : '一覧へ戻る'
  );

  const disposeUploadContributor = () => {
    uploadContributor?.dispose();
    uploadContributor = null;
  };

  const startUploadModal = (datasetIdForStatus: string) => {
    if (typeof window === 'undefined') return;
    dismissedUploadDatasetId = '';
    uploadDatasetId = datasetIdForStatus;
    uploadModalOpen = true;
    uploadStatus = createPendingRecordingUploadStatus(datasetIdForStatus);
  };

  const closeUploadModal = () => {
    const targetDatasetId = String(uploadDatasetId || uploadStatus?.dataset_id || '').trim();
    if (targetDatasetId) {
      dismissedUploadDatasetId = targetDatasetId;
    }
    disposeUploadContributor();
    uploadModalOpen = false;
    uploadDatasetId = '';
    uploadStatus = null;
  };

  const handleUploadStatusEvent = (event: RealtimeTrackEvent) => {
    if (event.kind !== 'recording.upload-status') return;
    const targetDatasetId = String(uploadDatasetId || '').trim();
    if (!targetDatasetId) return;

    const nextStatus = event.detail as RecordingUploadStatus;
    if (String(nextStatus.dataset_id || '').trim() !== targetDatasetId) return;
    if (shouldIgnoreIdleUploadSnapshot(uploadStatus, nextStatus, targetDatasetId)) return;
    uploadStatus = nextStatus;
  };

  const retryUpload = async () => {
    const targetDatasetId = String(uploadDatasetId || uploadStatus?.dataset_id || datasetId || sessionId || '').trim();
    if (!targetDatasetId) return;
    const success = await runAction('再送信', () => api.storage.reuploadDataset(targetDatasetId), {
      successToast: '再送信を受け付けました。'
    });
    if (!success) return;
    uploadDatasetId = targetDatasetId;
    uploadStatus = createPendingRecordingUploadStatus(targetDatasetId);
  };

  const openDatasetViewer = () => {
    const targetDatasetId = String(uploadDatasetId || uploadStatus?.dataset_id || datasetId || sessionId || '').trim();
    if (!targetDatasetId) return;
    sessionViewer.open({ datasetId: targetDatasetId });
  };

  $effect(() => {
    if (typeof window === 'undefined') return;
    return subscribeRecorderStatus({
      onStatus: (next) => {
        recorderStatus = next;
      },
      onConnectionChange: (next) => {
        rosbridgeStatus = next;
      }
    });
  });

  $effect(() => {
    if (typeof window === 'undefined') return;
    if (sessionKind !== 'inference') return;
    return subscribeInferenceUploadProgressRequests((request) => {
      if (request.datasetId !== sessionId) return;
      startUploadModal(request.datasetId);
    });
  });

  const status = $derived(recorderStatus ?? {});
  const asNumber = (value: unknown, fallback = 0) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const statusDatasetId = $derived.by(() => {
    const value = (status as Record<string, unknown>)?.dataset_id;
    return typeof value === 'string' ? value : '';
  });
  const inferenceRunnerStatus = $derived($inferenceRunnerStatusQuery.data?.runner_status ?? {});
  const inferenceRecordingDatasetId = $derived(String(inferenceRunnerStatus.recording_dataset_id ?? '').trim());
  const expectedStatusDatasetId = $derived(
    sessionKind === 'inference' ? inferenceRecordingDatasetId : sessionId
  );
  const statusState = $derived.by(() => {
    const state = (status as Record<string, unknown>)?.state ?? (status as Record<string, unknown>)?.status ?? '';
    if (sessionKind === 'inference') {
      if (!inferenceRunnerStatus.active && !inferenceRecordingDatasetId) return 'inactive';
      if (inferenceRunnerStatus.awaiting_continue_confirmation) return 'completed';
      if (inferenceRunnerStatus.recording_active) {
        if (!statusDatasetId || !expectedStatusDatasetId || statusDatasetId === expectedStatusDatasetId) {
          return String(state || 'recording');
        }
      }
    }
    if (!expectedStatusDatasetId) return String(state || 'inactive');
    if (!statusDatasetId || statusDatasetId !== expectedStatusDatasetId) return 'inactive';
    return String(state);
  });
  const datasetId = $derived.by(() => {
    if (sessionKind === 'inference' && !inferenceRunnerStatus.active && !inferenceRecordingDatasetId) {
      return '';
    }
    const value = (status as Record<string, unknown>)?.dataset_id;
    return typeof value === 'string' && value ? value : expectedStatusDatasetId || sessionId;
  });
  const completedEpisodeCount = $derived(
    asNumber((status as Record<string, unknown>)?.episode_count ?? 0, 0)
  );
  const statusPhase = $derived(String((status as Record<string, unknown>)?.phase ?? 'wait'));
  const isFinalizing = $derived(statusPhase === 'finalizing');
  const inferenceSessionMatches = $derived.by(() => {
    if (sessionKind !== 'inference') return false;
    if (!sessionId) return false;
    const activeInferenceSessionId = String(inferenceRunnerStatus.session_id ?? '').trim();
    const activeRecordingDatasetId = String(inferenceRunnerStatus.recording_dataset_id ?? '').trim();
    return sessionId === activeInferenceSessionId || sessionId === activeRecordingDatasetId;
  });
  const inferenceSessionStartable = $derived.by(() => {
    if (sessionKind !== 'inference') return false;
    if (!inferenceSessionMatches) return false;
    return Boolean(inferenceRunnerStatus.active);
  });

  const canPause = $derived(['recording', 'resetting'].includes(String(statusState)) && !isFinalizing);
  const canResume = $derived(['paused', 'resetting_paused'].includes(String(statusState)) && !isFinalizing);
  const canRetakePrevious = $derived.by(() => {
    if (isFinalizing) return false;
    const state = String(statusState);
    if (state === 'resetting') {
      return false;
    }
    if (state === 'paused') {
      return false;
    }
    return state === 'recording' && completedEpisodeCount > 0;
  });
  const canRetakeCurrent = $derived.by(() => {
    if (isFinalizing) return false;
    const state = String(statusState);
    if (state === 'resetting') {
      return false;
    }
    return state === 'recording' || state === 'paused';
  });
  const canNext = $derived(
    ['recording', 'paused', 'resetting', 'resetting_paused'].includes(String(statusState)) && !isFinalizing
  );
  const canStop = $derived(
    ['recording', 'paused', 'resetting', 'resetting_paused', 'warming'].includes(String(statusState)) && !isFinalizing
  );
  const canStart = $derived.by(() => {
    const startableState = ['idle', 'completed', 'inactive', ''].includes(String(statusState));
    if (!startableState) return false;
    if (sessionKind === 'inference') return inferenceSessionStartable;
    return Boolean(sessionId);
  });

  $effect(() => {
    if (typeof window === 'undefined') return;
    const handleKeydown = (event: KeyboardEvent) => {
      if (mode !== 'recording') return;
      if (confirmOpen || uploadModalOpen) return;
      if (event.defaultPrevented || event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      if (isEditableTarget(event.target) || hasEditableFocus()) return;

      if (event.key === 'ArrowRight') {
        if (!canNext || Boolean(actionBusy)) return;
        event.preventDefault();
        void handleNext();
        return;
      }

      if (event.key === 'ArrowLeft') {
        if (!canRetakeCurrent || Boolean(actionBusy)) return;
        event.preventDefault();
        void handleRetakeCurrent();
        return;
      }

      if (event.key === ' ' || event.key === 'Spacebar') {
        if ((!canResume && !canPause) || Boolean(actionBusy)) return;
        event.preventDefault();
        if (canResume) {
          void handleResume();
        } else {
          void handlePause();
        }
      }
    };

    window.addEventListener('keydown', handleKeydown);
    return () => {
      window.removeEventListener('keydown', handleKeydown);
    };
  });

  $effect(() => {
    if (typeof window === 'undefined') return;
    const disconnected = rosbridgeStatus !== 'connected';
    if (disconnected && !wasDisconnected) {
      toast.error('rosbridge が切断されています。状態は更新されません。');
    } else if (!disconnected && wasDisconnected) {
      toast.success('rosbridge 接続が復旧しました。');
    }
    wasDisconnected = disconnected;
  });

  $effect(() => {
    if (typeof window === 'undefined') return;
    if (uploadModalOpen) return;
    if (isFinalizing && !wasFinalizing) {
      finalizingToastId = String(toast.loading('エピソード保存中です...'));
    } else if (!isFinalizing && wasFinalizing) {
      if (finalizingToastId !== null) {
        toast.dismiss(finalizingToastId);
        finalizingToastId = null;
      }
      toast.success('エピソード保存が完了しました。');
    }
    wasFinalizing = isFinalizing;
  });

  $effect(() => {
    return () => {
      if (finalizingToastId !== null) {
        toast.dismiss(finalizingToastId);
        finalizingToastId = null;
      }
    };
  });

  $effect(() => {
    if (typeof window === 'undefined') return;
    if (sessionKind !== 'recording') return;
    const current = String(statusState);
    const previous = previousStatusState;
    const isCompletedNow = current === 'completed';
    const wasCompleted = previous === 'completed';
    const sameSession = statusDatasetId === sessionId;
    if (
      isCompletedNow &&
      !wasCompleted &&
      previous !== '' &&
      sameSession &&
      dismissedUploadDatasetId !== sessionId &&
      !uploadModalOpen
    ) {
      startUploadModal(sessionId);
      toast.success('録画が完了しました。アップロード進捗を表示します。');
    }
    previousStatusState = current;
  });

  $effect(() => {
    if (!browser) return;
    if (uploadContributor === null) {
      uploadContributor = registerRealtimeTrackConsumer({
        contributorId: 'recording.controls.upload-modal',
        tracks: [],
        onEvent: handleUploadStatusEvent
      });
    }
    uploadContributor?.setEventHandler(handleUploadStatusEvent);

    const targetDatasetId = String(uploadDatasetId || '').trim();
    if (!uploadModalOpen || !targetDatasetId) {
      uploadContributor?.setTracks([]);
      return;
    }
    uploadContributor?.setTracks([
      {
        kind: 'recording.upload-status',
        params: { session_id: targetDatasetId }
      }
    ]);
  });

  $effect(() => {
    return () => {
      disposeUploadContributor();
    };
  });

  $effect(() => {
    if (!uploadStatus) return;
    if (!isTerminalUploadStatus(uploadStatus)) return;
    if (actionBusy === '終了') return;
    disposeUploadContributor();
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{statusState || 'unknown'}</span>
  </div>

  {#if mode !== 'recording'}
    <div class="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3 text-xs text-amber-700">
      このビューはデータセット収録のみ対応しています。
    </div>
  {:else}
    <div class="grid gap-2 text-sm">
      <div class="grid grid-cols-[1fr_1fr_auto_1fr] items-center gap-2">
        <Button.Root
          class="btn-ghost"
          type="button"
          onclick={handleRetakePrevious}
          disabled={!canRetakePrevious || Boolean(actionBusy)}
        >
          {actionBusy === '直前取り直し' ? '前を取り直し中...' : '⇤'}
        </Button.Root>
        <Button.Root
          class="btn-ghost"
          type="button"
          onclick={handleRetakeCurrent}
          disabled={!canRetakeCurrent || Boolean(actionBusy)}
        >
          {actionBusy === '取り直し' ? '← 実行中...' : '←'}
        </Button.Root>
        <Button.Root
          class="btn-primary min-w-[120px]"
          type="button"
          onclick={canResume ? handleResume : handlePause}
          disabled={(!canResume && !canPause) || Boolean(actionBusy)}
        >
          {#if canResume}
            {actionBusy === '再開' ? '再開中...' : '再開'}
          {:else}
            {actionBusy === '中断' ? '一時停止中...' : '一時停止'}
          {/if}
        </Button.Root>
        <Button.Root class="btn-ghost" type="button" onclick={handleNext} disabled={!canNext || Boolean(actionBusy)}>
          {actionBusy === '次へ' ? '実行中... →' : '→'}
        </Button.Root>
      </div>

      <div class="grid gap-2">
        {#if canStart}
          <Button.Root class="btn-primary" type="button" onclick={handleStart} disabled={Boolean(actionBusy)}>
            {actionBusy === '開始' ? '開始中...' : '開始'}
          </Button.Root>
        {:else}
          <Button.Root class="btn-primary" type="button" onclick={handleStop} disabled={!canStop || Boolean(actionBusy)}>
            {actionBusy === '終了' ? '終了中...' : '終了'}
          </Button.Root>
        {/if}
      </div>

      <p class="text-[11px] text-slate-500">
        ⇤: 直前エピソードを取り直し / ←: 現在エピソードを取り直し / →: 現在エピソードを保存して次へ
      </p>
      <p class="text-[11px] text-slate-500">
        キーボード: ← 取り直し / → 次へ / Space 一時停止・再開
      </p>
    </div>
  {/if}
</div>

<AlertDialog.Root bind:open={confirmOpen}>
  <AlertDialog.Portal>
    <AlertDialog.Overlay class="fixed inset-0 z-40 bg-slate-900/50 backdrop-blur-[1px]" />
    <AlertDialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      <AlertDialog.Title class="text-base font-semibold text-slate-900">{confirmTitle}</AlertDialog.Title>
      <AlertDialog.Description class="mt-2 text-sm text-slate-600">{confirmDescription}</AlertDialog.Description>
      <div class="mt-5 flex items-center justify-end gap-2">
        <AlertDialog.Cancel
          class="btn-ghost"
          type="button"
          disabled={Boolean(actionBusy)}
          onclick={handleConfirmCancel}
        >
          キャンセル
        </AlertDialog.Cancel>
        <AlertDialog.Action
          class="btn-primary"
          type="button"
          disabled={!pendingConfirmAction || Boolean(actionBusy)}
          onclick={handleConfirmAction}
        >
          {confirmActionLabel}
        </AlertDialog.Action>
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>

<AlertDialog.Root bind:open={uploadModalOpen}>
  <AlertDialog.Portal>
    <AlertDialog.Overlay class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]" />
    <AlertDialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,32rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      <AlertDialog.Title class="text-base font-semibold text-slate-900">アップロード進捗</AlertDialog.Title>
      <AlertDialog.Description class="mt-2 text-sm text-slate-600">
        収録終了後のデータアップロード状況を表示しています。
      </AlertDialog.Description>
      <p class="mt-2 text-xs text-slate-500">一覧へ戻ってもアップロードはバックグラウンドで継続します。</p>

      <div class="mt-4 nested-block-pane nested-block-stack p-3">
        <div class="flex items-center justify-between text-xs text-slate-500">
          <span>{uploadPhaseLabel}</span>
          <span>{uploadProgressPercent.toFixed(1)}%</span>
        </div>
        <div class="h-2 w-full rounded-full bg-slate-200">
          <div class="h-2 rounded-full bg-brand transition-all" style={`width:${uploadProgressPercent}%`}></div>
        </div>
        <div class="grid gap-1 text-xs text-slate-600">
          <p>データセット: {uploadStatus?.dataset_id ?? sessionId}</p>
          <p>
            files: {uploadStatus?.files_done ?? 0}
            {#if (uploadStatus?.total_files ?? 0) > 0}
              / {uploadStatus?.total_files}
            {/if}
          </p>
          {#if uploadStatus?.current_file}
            <p class="truncate">current: {uploadStatus.current_file}</p>
          {/if}
          {#if uploadStatus?.error}
            <p class="text-rose-600">{uploadStatus.error}</p>
          {/if}
        </div>
      </div>

      <div class="mt-5 flex items-center justify-end gap-2">
        <Button.Root
          class="btn-ghost"
          type="button"
          onclick={() => {
            void goto(uploadReturnHref);
          }}
        >
          {uploadReturnLabel}
        </Button.Root>
        <AlertDialog.Cancel
          class="btn-ghost"
          type="button"
          onclick={closeUploadModal}
        >
          この画面に残る
        </AlertDialog.Cancel>
        {#if String(uploadStatus?.phase ?? uploadStatus?.status ?? '').toLowerCase() === 'completed'}
          <Button.Root class="btn-ghost" type="button" onclick={openDatasetViewer}>
            ビューアで開く
          </Button.Root>
        {/if}
        {#if String(uploadStatus?.phase ?? uploadStatus?.status ?? '').toLowerCase() === 'failed'}
          <Button.Root
            class="btn-primary"
            type="button"
            onclick={retryUpload}
            disabled={Boolean(actionBusy)}
          >
            {actionBusy === '再送信' ? '再送信中...' : '再送信'}
          </Button.Root>
        {/if}
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>

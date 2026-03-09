<script lang="ts">
  import { getContext } from 'svelte';
  import type { DatasetPlaybackController, DatasetPlaybackState } from '$lib/recording/datasetPlayback';
  import {
    getRecorderDisplayEpisodeNumber,
    subscribeRecorderStatus,
    type RecorderStatus,
    type RosbridgeStatus
  } from '$lib/recording/recorderStatus';
  import { resolveSessionRecorderStatus } from '$lib/recording/recorderStatusView';
  import { VIEWER_RUNTIME, type ViewerRuntimeStore } from '$lib/viewer/runtimeContext';

  let {
    title = 'Timeline',
  }: {
    title?: string;
  } = $props();

  const runtimeStore = getContext<ViewerRuntimeStore>(VIEWER_RUNTIME);
  const runtime = $derived($runtimeStore);
  const isDataset = $derived(runtime.kind === 'dataset');
  const mode = $derived(runtime.mode);
  const playbackController = $derived(
    runtime.kind === 'dataset' ? (runtime.playback as DatasetPlaybackController | null) : null
  );
  const datasetId = $derived(runtime.kind === 'dataset' ? runtime.datasetId : '');
  const datasetEpisodeIndex = $derived(runtime.kind === 'dataset' ? runtime.episodeIndex : 0);
  const sessionId = $derived(runtime.kind === 'ros' ? runtime.sessionId : '');
  const onPrevEpisode = $derived(runtime.kind === 'dataset' ? runtime.onPrevEpisode : undefined);
  const onNextEpisode = $derived(runtime.kind === 'dataset' ? runtime.onNextEpisode : undefined);

  let recorderStatus = $state<RecorderStatus | null>(null);
  let rosbridgeStatus = $state<RosbridgeStatus>('idle');
  let playbackState = $state<DatasetPlaybackState>({
    playing: false,
    currentTime: 0,
    duration: 0,
    rate: 1,
    ready: false
  });

  const asNumber = (value: unknown, fallback = 0) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  $effect(() => {
    if (typeof window === 'undefined') return;
    if (isDataset) return;
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
    if (!isDataset) return;
    if (!playbackController) return;
    playbackState = playbackController.getState();
    const unsubState = playbackController.subscribeState((next) => {
      playbackState = next;
    });
    const unsubTime = playbackController.subscribeTime((time) => {
      playbackState = { ...playbackState, currentTime: time };
    }, { maxFps: 30 });
    return () => {
      unsubState?.();
      unsubTime?.();
    };
  });

  const status = $derived(recorderStatus ?? {});
  const sessionStatus = $derived(resolveSessionRecorderStatus(status, sessionId));
  const statusPhase = $derived(sessionStatus.phase);
  const statusDetail = $derived(sessionStatus.lastError);
  const finalizeElapsed = $derived(asNumber((status as Record<string, unknown>)?.finalize_elapsed_s ?? 0));
  const displayEpisodeNumber = $derived(getRecorderDisplayEpisodeNumber(status));
  const episodeTotal = $derived(asNumber((status as Record<string, unknown>)?.num_episodes ?? 0));
  const episodeTime = $derived(asNumber((status as Record<string, unknown>)?.episode_time_s ?? 0));
  const episodeElapsed = $derived(asNumber((status as Record<string, unknown>)?.episode_elapsed_s ?? 0));
  const resetTime = $derived(asNumber((status as Record<string, unknown>)?.reset_time_s ?? 0));
  const resetElapsed = $derived(asNumber((status as Record<string, unknown>)?.reset_elapsed_s ?? 0));

  const timelineMode = $derived(
    statusPhase === 'finalizing'
      ? 'finalizing'
      : statusPhase === 'recording'
        ? 'recording'
        : statusPhase === 'reset'
          ? 'reset'
          : 'wait'
  );
  const timelineTotal = $derived(
    timelineMode === 'recording' ? episodeTime : timelineMode === 'reset' ? resetTime : 0
  );
  const timelineElapsed = $derived(
    timelineMode === 'recording'
      ? episodeElapsed
      : timelineMode === 'reset'
        ? resetElapsed
        : timelineMode === 'finalizing'
          ? finalizeElapsed
          : 0
  );
  const timelineProgress = $derived(
    timelineMode === 'finalizing'
      ? 1
      : timelineTotal > 0
        ? Math.min(Math.max(timelineElapsed / timelineTotal, 0), 1)
        : 0
  );
  const timelineLabel = $derived(
    timelineMode === 'recording'
      ? '録画中'
      : timelineMode === 'reset'
        ? 'リセット中'
        : timelineMode === 'finalizing'
          ? '保存中'
          : '待機中'
  );
  const connectionWarning = $derived(
    rosbridgeStatus !== 'connected' ? 'rosbridge が切断されています。状態は更新されません。' : ''
  );

  const formatSeconds = (value: number) => `${value.toFixed(1)}s`;

  const datasetCanSeek = $derived(
    isDataset &&
      Boolean(playbackController) &&
      playbackState.ready &&
      Number.isFinite(playbackState.duration) &&
      playbackState.duration > 0
  );

  const handleTogglePlay = () => {
    if (!playbackController) return;
    if (playbackState.playing) {
      playbackController.pause();
    } else {
      playbackController.play();
    }
  };

  const handleSeek = (event: Event) => {
    if (!playbackController) return;
    const value = Number((event.target as HTMLInputElement | null)?.value ?? 0);
    playbackController.seek(value);
  };

  let pendingRestartTimer: number | null = $state(null);

  const clearPendingRestart = () => {
    if (pendingRestartTimer != null && typeof window !== 'undefined') {
      window.clearTimeout(pendingRestartTimer);
    }
    pendingRestartTimer = null;
  };

  const scheduleRestartPlay = () => {
    if (!playbackController) return;
    if (typeof window === 'undefined') return;
    clearPendingRestart();
    pendingRestartTimer = window.setTimeout(() => {
      pendingRestartTimer = null;
      playbackController.play();
    }, 1000);
  };

  const handleRestartOrPrevEpisode = () => {
    if (!playbackController) return;
    if (pendingRestartTimer != null) {
      clearPendingRestart();
      // Second press during the 1s delay: jump to previous linked episode (if available).
      playbackController.pause();
      onPrevEpisode?.();
      return;
    }
    playbackController.pause();
    playbackController.seek(0);
    scheduleRestartPlay();
  };

  const handleNextEpisode = () => {
    if (!playbackController) return;
    playbackController.pause();
    onNextEpisode?.();
  };

  $effect(() => {
    if (typeof window === 'undefined') return;
    return () => {
      clearPendingRestart();
    };
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">
      {#if isDataset}
        {datasetId ? `${datasetId} / ep ${Number(datasetEpisodeIndex) + 1}` : 'dataset未選択'}
      {:else}
        {timelineLabel}
      {/if}
    </span>
  </div>

  {#if isDataset}
    {#if !playbackController}
      <div class="rounded-xl border border-slate-200 bg-white/70 p-3 text-xs text-slate-600">
        再生コントローラが見つかりません。
      </div>
    {:else}
      <div class="rounded-2xl border border-slate-200/60 bg-white/70 p-3">
        <div class="flex items-center gap-3">
          <div class="flex shrink-0 items-center gap-1">
            <button
              class="grid h-9 w-9 place-items-center rounded-full border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
              type="button"
              onclick={handleRestartOrPrevEpisode}
              disabled={!datasetCanSeek}
              aria-label="0秒に戻す / もう一度で前のエピソード"
              title="0秒に戻す / もう一度で前へ"
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" class="h-4 w-4">
                <path d="M11 15L6 10l5-5" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M17 15l-5-5 5-5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>

            <button
              class="grid h-9 w-9 place-items-center rounded-full bg-brand text-white shadow-glow transition hover:translate-y-[-1px] hover:shadow-lg disabled:opacity-50"
              type="button"
              onclick={handleTogglePlay}
              disabled={!datasetCanSeek}
              aria-label={playbackState.playing ? '一時停止' : '再生'}
              title={playbackState.playing ? '一時停止' : '再生'}
            >
              {#if playbackState.playing}
                <svg viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
                  <path d="M6 4h3v12H6V4zM11 4h3v12h-3V4z" />
                </svg>
              {:else}
                <svg viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
                  <path d="M7 5v10l9-5-9-5z" />
                </svg>
              {/if}
            </button>

            <button
              class="grid h-9 w-9 place-items-center rounded-full border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
              type="button"
              onclick={handleNextEpisode}
              disabled={!datasetCanSeek || !onNextEpisode}
              aria-label="次のエピソード"
              title="次へ"
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" class="h-4 w-4">
                <path d="M9 5l5 5-5 5" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M3 5l5 5-5 5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </div>

          <input
            class="h-2 w-full flex-1 accent-[rgb(91,124,250)] disabled:opacity-50"
            type="range"
            min="0"
            max={Math.max(0, playbackState.duration || 0)}
            step="0.05"
            value={Math.min(Math.max(playbackState.currentTime || 0, 0), Math.max(0, playbackState.duration || 0))}
            oninput={handleSeek}
            disabled={!datasetCanSeek}
          />

          <span class="shrink-0 text-right text-xs font-semibold text-slate-600 tabular-nums">
            {formatSeconds(playbackState.currentTime)} / {formatSeconds(playbackState.duration || 0)}
          </span>
        </div>

        {#if !playbackState.ready}
          <p class="mt-2 text-[10px] text-slate-400">動画メタデータ読込中…</p>
        {/if}
      </div>
    {/if}
  {:else if mode !== 'recording'}
    <div class="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3 text-xs text-amber-700">
      このビューはデータセット収録のみ対応しています。
    </div>
  {:else}
    {#if connectionWarning}
      <p class="text-xs text-amber-600">{connectionWarning}</p>
    {/if}

    <div class="rounded-2xl border border-slate-200/60 bg-white/70 p-3">
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>録画タイムライン</span>
        <span>
          {#if displayEpisodeNumber != null}
            エピソード {displayEpisodeNumber}{episodeTotal ? ` / ${episodeTotal}` : ''}
          {:else}
            エピソード待機中
          {/if}
        </span>
      </div>
      <div class="mt-3 h-3 w-full overflow-hidden rounded-full bg-slate-200/70">
        <div
          class={`h-full rounded-full transition ${
            timelineMode === 'reset'
              ? 'bg-amber-400'
              : timelineMode === 'finalizing'
                ? 'bg-sky-400 animate-pulse'
                : 'bg-brand'
          }`}
          style={`width: ${(timelineProgress * 100).toFixed(1)}%`}
        ></div>
      </div>
      <div class="mt-2 flex justify-between text-[10px] text-slate-500">
        <span>
          {#if timelineMode === 'finalizing'}
            {formatSeconds(timelineElapsed)}
          {:else}
            {formatSeconds(timelineElapsed)}
          {/if}
        </span>
        <span>
          {#if timelineMode === 'finalizing'}
            エピソード保存中
          {:else}
            {formatSeconds(timelineTotal)}
          {/if}
        </span>
      </div>
    </div>

    {#if statusDetail}
      <p class="text-xs text-slate-500">{statusDetail}</p>
    {/if}
  {/if}
</div>

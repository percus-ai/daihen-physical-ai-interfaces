<script lang="ts">
  import type { DatasetPlaybackController, DatasetPlaybackState } from '$lib/recording/datasetPlayback';
  import {
    subscribeRecorderStatus,
    type RecorderStatus,
    type RosbridgeStatus
  } from '$lib/recording/recorderStatus';

  let {
    sessionId = '',
    title = 'Timeline',
    mode = 'recording',
    viewSource = 'ros',
    datasetId = '',
    datasetEpisodeIndex = 0,
    playbackController = null
  }: {
    sessionId?: string;
    title?: string;
    mode?: 'recording' | 'operate';
    viewSource?: 'ros' | 'dataset';
    datasetId?: string;
    datasetEpisodeIndex?: number;
    playbackController?: DatasetPlaybackController | null;
  } = $props();

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
    if (viewSource === 'dataset') return;
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
    if (viewSource !== 'dataset') return;
    if (!playbackController) return;
    return playbackController.subscribe((next) => {
      playbackState = next;
    });
  });

  const status = $derived(recorderStatus ?? {});
  const statusDatasetId = $derived.by(() => {
    const value = (status as Record<string, unknown>)?.dataset_id;
    return typeof value === 'string' ? value : '';
  });
  const rawStatusPhase = $derived(String((status as Record<string, unknown>)?.phase ?? 'wait'));
  const statusPhase = $derived.by(() => {
    if (!sessionId) return rawStatusPhase;
    if (!statusDatasetId || statusDatasetId !== sessionId) return 'wait';
    return rawStatusPhase;
  });
  const statusDetail = $derived(String((status as Record<string, unknown>)?.last_error ?? ''));
  const finalizeElapsed = $derived(asNumber((status as Record<string, unknown>)?.finalize_elapsed_s ?? 0));
  const episodeIndex = $derived((status as Record<string, unknown>)?.episode_index ?? null);
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
    viewSource === 'dataset' &&
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

  const handleStop = () => {
    playbackController?.stop();
  };

  const handleSeek = (event: Event) => {
    if (!playbackController) return;
    const value = Number((event.target as HTMLInputElement | null)?.value ?? 0);
    playbackController.seek(value);
  };
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">
      {#if viewSource === 'dataset'}
        {datasetId ? `${datasetId} / ep ${Number(datasetEpisodeIndex) + 1}` : 'dataset未選択'}
      {:else}
        {timelineLabel}
      {/if}
    </span>
  </div>

  {#if viewSource === 'dataset'}
    {#if !playbackController}
      <div class="rounded-xl border border-slate-200 bg-white/70 p-3 text-xs text-slate-600">
        再生コントローラが見つかりません。
      </div>
    {:else}
      <div class="rounded-2xl border border-slate-200/60 bg-white/70 p-3">
        <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600">
          <span>データセット再生</span>
          <span class="tabular-nums">
            {formatSeconds(playbackState.currentTime)} / {formatSeconds(playbackState.duration || 0)}
          </span>
        </div>

        <div class="mt-3 flex items-center gap-2">
          <button
            class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
            onclick={handleTogglePlay}
            disabled={!datasetCanSeek}
          >
            {playbackState.playing ? '一時停止' : '再生'}
          </button>
          <button
            class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
            onclick={handleStop}
            disabled={!datasetCanSeek}
          >
            停止
          </button>
          <div class="flex-1"></div>
          <span class="text-[10px] text-slate-400">
            {#if !playbackState.ready}
              動画メタデータ読込中…
            {:else if !datasetCanSeek}
              再生不可
            {:else}
              シーク可能
            {/if}
          </span>
        </div>

        <div class="mt-3">
          <input
            class="h-2 w-full accent-[rgb(91,124,250)] disabled:opacity-50"
            type="range"
            min="0"
            max={Math.max(0, playbackState.duration || 0)}
            step="0.05"
            value={Math.min(Math.max(playbackState.currentTime || 0, 0), Math.max(0, playbackState.duration || 0))}
            oninput={handleSeek}
            disabled={!datasetCanSeek}
          />
        </div>
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
          {#if episodeIndex != null}
            エピソード {Number(episodeIndex) + 1}{episodeTotal ? ` / ${episodeTotal}` : ''}
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

<script lang="ts">
  import { getRosbridgeClient } from '$lib/recording/rosbridge';
  import { api } from '$lib/api/client';
  import type { DatasetPlaybackController } from '$lib/recording/datasetPlayback';

  let {
    topic = '',
    title = 'Camera',
    source = 'ros',
    datasetId = '',
    episodeIndex = 0,
    playbackController = null
  }: {
    topic?: string;
    title?: string;
    source?: 'ros' | 'dataset';
    datasetId?: string;
    episodeIndex?: number;
    playbackController?: DatasetPlaybackController | null;
  } = $props();

  let imageSrc = $state('');
  let error = $state('');
  let status = $state('idle');
  let lastFrameAt = 0;
  let unsubscribe: (() => void) | null = null;
  let videoError = $state(false);
  let videoEl = $state<HTMLVideoElement | null>(null);
  let unregisterPlayback: (() => void) | null = null;

  const handleMessage = (msg: Record<string, unknown>) => {
    const data = msg.data as string | undefined;
    if (!data) return;
    const now = Date.now();
    if (now - lastFrameAt < 80) return;
    lastFrameAt = now;
    const format = String(msg.format ?? 'jpeg').toLowerCase();
    const mime = format.includes('png') ? 'image/png' : 'image/jpeg';
    imageSrc = `data:${mime};base64,${data}`;
  };

  const subscribe = () => {
    if (!topic) return;
    const client = getRosbridgeClient();
    status = 'connecting';
    error = '';
    unsubscribe?.();
    unsubscribe = client.subscribe(topic, handleMessage, {
      type: 'sensor_msgs/CompressedImage',
      throttle_rate: 120,
      queue_length: 1
    });
    status = client.getStatus();
  };

  const requiresCompressed = $derived(Boolean(topic) && !topic.endsWith('/compressed'));
  const datasetVideoUrl = $derived.by(() => {
    if (source !== 'dataset') return '';
    if (!datasetId || !topic) return '';
    return api.storage.datasetViewerVideoUrl(datasetId, topic, Math.max(0, Math.floor(Number(episodeIndex) || 0)));
  });

  let lastDatasetVideoUrl = '';
  $effect(() => {
    if (source !== 'dataset') return;
    if (datasetVideoUrl === lastDatasetVideoUrl) return;
    lastDatasetVideoUrl = datasetVideoUrl;
    videoError = false;
  });

  $effect(() => {
    if (source === 'dataset') {
      unsubscribe?.();
      unsubscribe = null;
      imageSrc = '';
      error = '';
      status = 'idle';
      videoError = false;
      return;
    }
    if (!topic) {
      unsubscribe?.();
      unsubscribe = null;
      imageSrc = '';
      error = '';
      return;
    }
    if (requiresCompressed) {
      error = 'compressed 形式のみ対応しています。';
      unsubscribe?.();
      unsubscribe = null;
      imageSrc = '';
      return;
    }
    error = '';
    imageSrc = '';
    subscribe();
    return () => {
      unsubscribe?.();
      unsubscribe = null;
    };
  });

  $effect(() => {
    if (source !== 'dataset') return;
    if (!playbackController) return;
    if (!videoEl) return;
    unregisterPlayback = playbackController.register(videoEl);
    return () => {
      unregisterPlayback?.();
      unregisterPlayback = null;
    };
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{source === 'dataset' ? topic || 'no camera' : topic || 'no topic'}</span>
  </div>
  {#if error}
    <p class="text-xs text-rose-500">{error}</p>
  {/if}
  <div class="flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-slate-950/5">
    {#if source === 'dataset'}
      {#if datasetVideoUrl}
        {#if videoError}
          <div class="flex h-full min-h-[160px] items-center justify-center text-xs text-slate-400">
            動画の読み込みに失敗しました。
          </div>
        {:else}
          <!-- svelte-ignore a11y_media_has_caption -->
          {#key datasetVideoUrl}
            <video
              class="block h-full w-full bg-black/5 object-contain"
              bind:this={videoEl}
              src={datasetVideoUrl}
              crossorigin="use-credentials"
              playsinline
              preload="metadata"
              onerror={() => {
                videoError = true;
              }}
            ></video>
          {/key}
        {/if}
      {:else}
        <div class="flex h-full min-h-[160px] items-center justify-center text-xs text-slate-400">
          カメラが未選択です。
        </div>
      {/if}
    {:else if imageSrc}
      <img src={imageSrc} alt="camera" class="block h-full w-full object-contain" />
    {:else}
      <div class="flex h-full min-h-[160px] items-center justify-center text-xs text-slate-400">
        映像を待機中… ({status})
      </div>
    {/if}
  </div>
</div>

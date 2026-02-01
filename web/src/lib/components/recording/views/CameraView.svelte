<script lang="ts">
  import { onDestroy } from 'svelte';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';

  export let topic = '';
  export let title = 'Camera';

  let imageSrc = '';
  let error = '';
  let status = 'idle';
  let lastFrameAt = 0;
  let unsubscribe: (() => void) | null = null;
  let requiresCompressed = false;

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

  $: requiresCompressed = Boolean(topic) && !topic.endsWith('/compressed');

  $: if (topic) {
    if (requiresCompressed) {
      error = 'compressed 形式のみ対応しています。';
      unsubscribe?.();
      unsubscribe = null;
      imageSrc = '';
    } else {
      error = '';
      subscribe();
    }
  } else {
    unsubscribe?.();
    unsubscribe = null;
    imageSrc = '';
  }

  onDestroy(() => {
    unsubscribe?.();
  });
</script>

<div class="flex h-full flex-col gap-3">
  <div class="flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</p>
    <span class="text-[10px] text-slate-400">{topic || 'no topic'}</span>
  </div>
  {#if error}
    <p class="text-xs text-rose-500">{error}</p>
  {/if}
  <div class="flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-slate-950/5">
    {#if imageSrc}
      <img src={imageSrc} alt="camera" class="block h-full w-full object-contain" />
    {:else}
      <div class="flex h-full min-h-[160px] items-center justify-center text-xs text-slate-400">
        映像を待機中… ({status})
      </div>
    {/if}
  </div>
</div>

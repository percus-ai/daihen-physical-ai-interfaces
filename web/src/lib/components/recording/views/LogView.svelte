<script lang="ts">
  import { onDestroy } from 'svelte';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';

  export let topic = '';
  export let title = 'Logs';
  export let maxLines = 120;

  let lines: string[] = [];
  let status = 'idle';
  let unsubscribe: (() => void) | null = null;

  const handleMessage = (msg: Record<string, unknown>) => {
    let line = '';
    if (typeof msg.msg === 'string') {
      line = msg.msg;
    } else if (typeof msg.message === 'string') {
      line = msg.message;
    } else if (typeof msg.data === 'string') {
      line = msg.data;
    } else {
      line = JSON.stringify(msg);
    }
    const next = [...lines, line];
    lines = next.slice(-maxLines);
  };

  const subscribe = () => {
    if (!topic) return;
    const client = getRosbridgeClient();
    unsubscribe?.();
    unsubscribe = client.subscribe(topic, handleMessage, {
      throttle_rate: 200
    });
    status = client.getStatus();
  };

  $: if (topic) {
    subscribe();
  } else {
    unsubscribe?.();
    unsubscribe = null;
    lines = [];
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
  <div class="flex-1 rounded-2xl border border-slate-200/60 bg-white/70 p-3">
    {#if lines.length}
      <pre class="whitespace-pre-wrap text-xs text-slate-700">{lines.join('\n')}</pre>
    {:else}
      <p class="text-xs text-slate-400">ログを待機中… ({status})</p>
    {/if}
  </div>
</div>

<script lang="ts">
  let { src = '', label = '' }: { src?: string; label?: string } = $props();

  let rootEl = $state<HTMLDivElement | null>(null);
  let videoEl = $state<HTMLVideoElement | null>(null);
  let error = $state(false);
  let ready = $state(false);
  let activated = $state(false);
  let activeSrc = $state('');

  const handleLoadedMetadata = () => {
    if (!videoEl) return;
    ready = true;
    try {
      const dur = Number(videoEl.duration) || 0;
      // Nudge forward to force a decoded frame to display.
      const t = dur > 0 ? Math.min(0.2, Math.max(0, dur - 0.001)) : 0;
      videoEl.currentTime = t;
      videoEl.pause();
    } catch {
      // ignore; some browsers block programmatic seek before user gesture
    }
  };

  $effect(() => {
    if (!activated) return;
    if (activeSrc === src) return;
    // Once activated, keep the last successful src to avoid reloading while scrolling.
    if (src) {
      activeSrc = src;
      error = false;
      ready = false;
    }
  });

  $effect(() => {
    if (typeof window === 'undefined') return;
    if (!rootEl) return;
    if (activated) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          activated = true;
          observer.disconnect();
          break;
        }
      },
      { root: null, rootMargin: '120px', threshold: 0.15 }
    );
    observer.observe(rootEl);
    return () => {
      observer.disconnect();
    };
  });
</script>

<div class="relative h-full w-full overflow-hidden rounded-lg bg-slate-900/5" bind:this={rootEl}>
  {#if !src}
    <div class="flex h-full w-full items-center justify-center text-[10px] text-slate-400">no preview</div>
  {:else if !activated}
    <div class="absolute inset-0 animate-pulse bg-slate-200/50"></div>
  {:else if error}
    <div class="flex h-full w-full items-center justify-center text-[10px] text-slate-400">preview failed</div>
  {:else}
    <!-- svelte-ignore a11y_media_has_caption -->
    <video
      class={`block h-full w-full object-cover ${ready ? 'opacity-100' : 'opacity-0'}`}
      bind:this={videoEl}
      src={activeSrc}
      muted
      playsinline
      preload="metadata"
      crossorigin="use-credentials"
      onloadedmetadata={handleLoadedMetadata}
      onerror={() => {
        error = true;
      }}
    ></video>
    {#if !ready}
      <div class="absolute inset-0 animate-pulse bg-slate-200/50"></div>
    {/if}
  {/if}
  {#if label}
    <div class="pointer-events-none absolute bottom-1 left-1 rounded bg-white/80 px-1.5 py-0.5 text-[9px] font-semibold text-slate-700">
      {label}
    </div>
  {/if}
</div>

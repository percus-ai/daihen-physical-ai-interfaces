<script lang="ts">
  import type { Snippet } from 'svelte';

  let { tone = 'default', children }: { tone?: 'default' | 'muted'; children?: Snippet } = $props();
</script>

<div class={`nested-block p-4 ${tone === 'muted' ? 'text-slate-500' : ''}`}>
  {@render children?.()}
</div>

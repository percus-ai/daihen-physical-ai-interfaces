<script lang="ts">
  let { tone = 'default' }: { tone?: 'default' | 'muted' } = $props();
</script>

<div class={`rounded-xl border border-slate-200/60 bg-white/70 p-4 ${tone === 'muted' ? 'text-slate-500' : ''}`}>
  <slot />
</div>

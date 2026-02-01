<script lang="ts">
  import type { BlueprintNode } from '$lib/recording/blueprint';

  export let node: BlueprintNode;
  export let selectedId = '';
  export let depth = 0;
  export let onSelect: (id: string) => void;

  const labelForNode = (value: BlueprintNode) => {
    if (value.type === 'split') return `Split (${value.direction})`;
    if (value.type === 'tabs') return 'Tabs';
    return `View: ${value.viewType}`;
  };
</script>

<div class="space-y-2">
  <button
    type="button"
    class={`flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-xs font-semibold transition ${
      node.id === selectedId ? 'border-brand bg-white text-slate-900' : 'border-transparent text-slate-600'
    }`}
    style={`padding-left: ${depth * 12 + 12}px`}
    on:click={() => onSelect?.(node.id)}
  >
    <span class="text-[10px] uppercase tracking-widest text-slate-400">{node.type}</span>
    <span>{labelForNode(node)}</span>
  </button>

  {#if node.type === 'split'}
    <div class="space-y-2">
      <svelte:self node={node.children[0]} {selectedId} depth={depth + 1} {onSelect} />
      <svelte:self node={node.children[1]} {selectedId} depth={depth + 1} {onSelect} />
    </div>
  {:else if node.type === 'tabs'}
    <div class="space-y-2">
      {#each node.tabs as tab}
        <svelte:self node={tab.child} {selectedId} depth={depth + 1} {onSelect} />
      {/each}
    </div>
  {/if}
</div>

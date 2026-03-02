<script lang="ts">
  import { Tabs } from 'bits-ui';
  import type { Snippet } from 'svelte';

  let {
    value = $bindable<'blueprint' | 'selection' | 'search'>('blueprint'),
    showSearchTab = false,
    children,
    blueprintPanel,
    selectionPanel,
    searchPanel
  }: {
    value?: 'blueprint' | 'selection' | 'search';
    showSearchTab?: boolean;
    // Svelte 5 passes component children via this prop; declare it to keep typings happy even when using named snippets.
    children?: Snippet;
    blueprintPanel?: Snippet;
    selectionPanel?: Snippet;
    searchPanel?: Snippet;
  } = $props();
</script>

<Tabs.Root bind:value={value}>
  <Tabs.List
    class={`inline-grid ${showSearchTab ? 'grid-cols-3' : 'grid-cols-2'} gap-1 rounded-full border border-slate-200/70 bg-slate-100/80 p-1`}
  >
    <Tabs.Trigger
      value="blueprint"
      class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
    >
      Blueprint
    </Tabs.Trigger>
    <Tabs.Trigger
      value="selection"
      class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
    >
      Selection
    </Tabs.Trigger>
    {#if showSearchTab}
      <Tabs.Trigger
        value="search"
        class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
      >
        Search
      </Tabs.Trigger>
    {/if}
  </Tabs.List>

  <Tabs.Content value="blueprint" class="mt-3">
    {@render blueprintPanel?.()}
  </Tabs.Content>

  <Tabs.Content value="selection" class="mt-3">
    {@render selectionPanel?.()}
  </Tabs.Content>

  {#if showSearchTab}
    <Tabs.Content value="search" class="mt-3">
      {@render searchPanel?.()}
    </Tabs.Content>
  {/if}
</Tabs.Root>

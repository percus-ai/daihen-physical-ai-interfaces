<script lang="ts">
  import { Tabs } from 'bits-ui';
  import type { Snippet } from 'svelte';

  let {
    value = $bindable<string>('blueprint'),
    children,
    blueprintPanel,
    selectionPanel,
    extraTabs = []
  }: {
    value?: string;
    // Svelte 5 passes component children via this prop; declare it to keep typings happy even when using named snippets.
    children?: Snippet;
    blueprintPanel?: Snippet;
    selectionPanel?: Snippet;
    extraTabs?: { id: string; label: string; panel?: Snippet }[];
  } = $props();

  const resolvedExtraTabs = $derived.by(() =>
    (extraTabs ?? []).filter((tab) => Boolean(tab?.id) && tab.id !== 'blueprint' && tab.id !== 'selection')
  );
</script>

<Tabs.Root bind:value={value} class="flex min-h-0 flex-1 flex-col">
  <Tabs.List
    class="inline-grid shrink-0 gap-1 rounded-full border border-slate-200/70 bg-slate-100/80 p-1"
    style={`grid-template-columns: repeat(${2 + resolvedExtraTabs.length}, minmax(0, 1fr));`}
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
    {#each resolvedExtraTabs as tab (tab.id)}
      <Tabs.Trigger
        value={tab.id}
        class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
      >
        {tab.label}
      </Tabs.Trigger>
    {/each}
  </Tabs.List>

  <Tabs.Content value="blueprint" class="mt-3 min-h-0 flex-1 overflow-y-auto">
    {@render blueprintPanel?.()}
  </Tabs.Content>

  <Tabs.Content value="selection" class="mt-3 min-h-0 flex-1 overflow-y-auto">
    {@render selectionPanel?.()}
  </Tabs.Content>

  {#each resolvedExtraTabs as tab (tab.id)}
    <Tabs.Content value={tab.id} class="mt-3 min-h-0 flex-1 overflow-y-auto">
      {@render tab.panel?.()}
    </Tabs.Content>
  {/each}
</Tabs.Root>

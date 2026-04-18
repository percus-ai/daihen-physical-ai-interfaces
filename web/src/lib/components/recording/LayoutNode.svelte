<script lang="ts">
  import { getContext } from 'svelte';
  import SplitPane from '$lib/components/recording/SplitPane.svelte';
  import TabsView from '$lib/components/recording/TabsView.svelte';
  import LayoutNode from '$lib/components/recording/LayoutNode.svelte';
  import type { BlueprintNode } from '$lib/recording/blueprint';
  import { getViewDefinition } from '$lib/recording/viewRegistry';
  import { hasEditableFocus, isEditableTarget } from '$lib/recording/keyboard';
  import PlaceholderView from '$lib/components/recording/views/PlaceholderView.svelte';
  import { VIEWER_RUNTIME, type ViewerRuntimeStore } from '$lib/viewer/runtimeContext';

		  let {
		    node,
		    selectedId = '',
		    editMode = true,
		    onSelect,
		    onResize,
		    onTabChange
	  }: {
	    node: BlueprintNode;
	    selectedId?: string;
		    editMode?: boolean;
		    onSelect: (id: string) => void;
		    onResize: (id: string, sizes: [number, number]) => void;
		    onTabChange: (id: string, activeId: string) => void;
	  } = $props();

  const runtimeStore = getContext<ViewerRuntimeStore>(VIEWER_RUNTIME);
  const runtime = $derived($runtimeStore);
  const viewSource = $derived(runtime.kind === 'dataset' ? 'dataset' : 'ros');
  const mode = $derived(runtime.mode);

  const handleSelect = (event: Event) => {
    event.stopPropagation();
    if (editMode) {
      onSelect?.(node.id);
    }
  };

  const handleKeydown = (event: KeyboardEvent) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    if (isEditableTarget(event.target) || hasEditableFocus()) return;
    event.preventDefault();
    handleSelect(event);
  };

  const renderComponent = (viewType: string) => {
    const definition = getViewDefinition(viewType);
    if (viewSource === 'dataset' && definition?.sources && !definition.sources.includes('dataset')) {
      return PlaceholderView;
    }
    return definition?.component ?? PlaceholderView;
  };

	  const buildProps = (viewType: string) => {
		    const definition = getViewDefinition(viewType);
		    const datasetUnsupported =
		      viewSource === 'dataset' && definition?.sources && !definition.sources.includes('dataset');
		    const baseProps = {
		      ...(node.type === 'view' ? node.config : {}),
		      title: datasetUnsupported ? `${definition?.label ?? viewType} (dataset未対応)` : definition?.label ?? viewType,
		      mode
		    } as Record<string, unknown>;
    return baseProps;
  };

  const viewType = $derived(node.type === 'view' ? node.viewType : 'placeholder');
  const ViewComponent = $derived(renderComponent(viewType));
</script>

<div
  class={`layout-node ${editMode && selectedId === node.id ? 'selected' : ''}`}
  role="button"
  tabindex="0"
  onclick={handleSelect}
  onkeydown={handleKeydown}
>
  {#if node.type === 'split'}
    <SplitPane
      direction={node.direction}
      sizes={node.sizes}
      editable={editMode}
      on:resize={(event) => onResize?.(node.id, event.detail.sizes)}
    >
      {#snippet first()}
        <div class="h-full">
		          <LayoutNode
		            node={node.children[0]}
		            {selectedId}
		            {editMode}
		            {onSelect}
		            {onResize}
	            {onTabChange}
	          />
        </div>
      {/snippet}
      {#snippet second()}
        <div class="h-full">
		          <LayoutNode
		            node={node.children[1]}
		            {selectedId}
		            {editMode}
		            {onSelect}
		            {onResize}
	            {onTabChange}
	          />
        </div>
      {/snippet}
    </SplitPane>
  {:else if node.type === 'tabs'}
    <TabsView tabs={node.tabs} activeId={node.activeId} on:change={(event) => onTabChange?.(node.id, event.detail.activeId)}>
      {#each node.tabs as tab (tab.id)}
        {#if tab.id === node.activeId}
		          <LayoutNode
		            node={tab.child}
		            {selectedId}
		            {editMode}
		            {onSelect}
		            {onResize}
	            {onTabChange}
	          />
        {/if}
      {/each}
    </TabsView>
  {:else}
    <div class="h-full rounded-2xl border border-slate-200/60 bg-white/80 p-3 shadow-sm">
      <ViewComponent {...buildProps(viewType)} />
    </div>
  {/if}
</div>

<style>
  .layout-node {
    position: relative;
    height: 100%;
    width: 100%;
    min-height: 120px;
  }
  .layout-node.selected > div {
    outline: 2px solid rgba(91, 124, 250, 0.5);
    outline-offset: 2px;
  }
</style>

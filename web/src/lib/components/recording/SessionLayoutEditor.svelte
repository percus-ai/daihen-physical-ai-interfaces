<script lang="ts">
  import { onMount } from 'svelte';
  import { toStore } from 'svelte/store';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api, type ExperimentEpisodeLink } from '$lib/api/client';

  import LayoutNode from '$lib/components/recording/LayoutNode.svelte';
  import BlueprintTree from '$lib/components/recording/BlueprintTree.svelte';
  import BlueprintWorkspace from '$lib/components/recording/BlueprintWorkspace.svelte';
  import InspectorTabs from '$lib/components/recording/InspectorTabs.svelte';
  import DatasetEpisodeSearchTab from '$lib/components/recording/DatasetEpisodeSearchTab.svelte';
  import {
    createDatasetPlaybackController,
    type DatasetPlaybackController
  } from '$lib/recording/datasetPlayback';

  import {
    addTab,
    createDefaultBlueprint,
    deleteNode,
    ensureValidSelection,
    findNode,
    removeTab,
    renameTab,
    updateSplitDirection,
    updateSplitSizes,
    updateTabsActive,
    updateViewConfig,
    updateViewType,
    wrapInSplit,
    wrapInTabs,
    type BlueprintNode
  } from '$lib/recording/blueprint';
  import {
    getTopicFieldOptions,
    getViewDefinition,
    getViewOptionsBySource,
    isFieldSupported,
    type ViewConfigSource
  } from '$lib/recording/viewRegistry';
  import { type BlueprintSessionKind } from '$lib/blueprints/draftStorage';

  type ProfileStatusResponse = {
    topics?: string[];
  };

			  let {
			    blueprintSessionId = '',
			    blueprintSessionKind = '' as BlueprintSessionKind | '',
			    layoutSessionId = '',
			    layoutSessionKind = '' as BlueprintSessionKind | '',
			    layoutMode = 'recording',
			    viewSource = 'ros',
			    editMode = true,
			    initialInspectorTab = 'blueprint',
			    persistBlueprintDraft = true,
			    embedded = false,
			    datasetId = '',
			    datasetEpisodeIndex = 0,
			    datasetCameraKeys = [],
			    datasetSignalKeys = [],
			    datasetAutoplayNonce = 0,
			    searchDatasets = [],
			    searchRecommendedDatasetId = '',
			    searchEpisodeLinks = [],
			    onPreviewEpisode = undefined,
		    onAddEpisodeLink = undefined,
		    onRemoveEpisodeLink = undefined
		  }: {
    blueprintSessionId?: string;
    blueprintSessionKind?: BlueprintSessionKind | '';
    layoutSessionId?: string;
    layoutSessionKind?: BlueprintSessionKind | '';
    layoutMode?: 'recording' | 'operate';
    viewSource?: ViewConfigSource;
    editMode?: boolean;
    initialInspectorTab?: 'blueprint' | 'selection' | 'search';
    persistBlueprintDraft?: boolean;
			    embedded?: boolean;
			    datasetId?: string;
			    datasetEpisodeIndex?: number;
			    datasetCameraKeys?: string[];
			    datasetSignalKeys?: string[];
			    datasetAutoplayNonce?: number;
			    searchDatasets?: { id: string; name?: string; status?: string }[];
			    searchRecommendedDatasetId?: string;
			    searchEpisodeLinks?: ExperimentEpisodeLink[];
			    onPreviewEpisode?: (datasetId: string, episodeIndex: number) => void;
			    onAddEpisodeLink?: (datasetId: string, episodeIndex: number) => void;
    onRemoveEpisodeLink?: (datasetId: string, episodeIndex: number) => void;
  } = $props();

  const resolvedLayoutSessionId = $derived(layoutSessionId || blueprintSessionId);
  const resolvedLayoutSessionKind = $derived(layoutSessionKind || blueprintSessionKind);
  const viewOptions = $derived(getViewOptionsBySource(viewSource));
  const showSearchTab = $derived(
    viewSource === 'dataset' && Boolean(onPreviewEpisode) && Boolean(onAddEpisodeLink) && Boolean(onRemoveEpisodeLink)
  );

	  const topicsQuery = createQuery<ProfileStatusResponse>(
	    toStore(() => ({
	      queryKey: ['profiles', 'active', 'status'],
	      queryFn: api.profiles.activeStatus,
	      enabled: viewSource === 'ros'
	    }))
	  );
	  const topics = $derived(
	    (viewSource === 'dataset' ? datasetCameraKeys : viewSource === 'ros' ? ($topicsQuery.data?.topics ?? []) : []) as string[]
	  );
	  const inspectorTopics = $derived.by(() => {
	    if (viewSource === 'dataset') {
	      if (selectedViewNode?.viewType === 'joint_state') {
	        return datasetSignalKeys;
	      }
	      return datasetCameraKeys;
	    }
	    if (viewSource === 'ros') return $topicsQuery.data?.topics ?? [];
	    return [];
	  });

		  const datasetPlayback: DatasetPlaybackController = createDatasetPlaybackController();
		  let lastDatasetPlaybackSignature = $state('');
		  let lastDatasetAutoplayNonce = $state(0);
		  let pendingAutoplayOnDatasetChange = $state(false);

		  const linkedEpisodeLinks = $derived.by(() => {
		    if (!showSearchTab) return [] as ExperimentEpisodeLink[];
		    return [...(searchEpisodeLinks ?? [])]
		      .filter((link) => Boolean(link.dataset_id) && Number.isFinite(Number(link.episode_index)))
		      .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
		      .map((link, idx) => ({
		        dataset_id: String(link.dataset_id),
		        episode_index: Math.max(0, Math.floor(Number(link.episode_index) || 0)),
		        sort_order: idx
		      }));
		  });

		  const linkedEpisodeIndex = $derived.by(() => {
		    if (!linkedEpisodeLinks.length) return -1;
		    const key = `${datasetId}:${Math.max(0, Math.floor(Number(datasetEpisodeIndex) || 0))}`;
		    return linkedEpisodeLinks.findIndex((link) => `${link.dataset_id}:${link.episode_index}` === key);
		  });

		  const prevLinkedEpisode = $derived.by(() => {
		    if (!linkedEpisodeLinks.length) return null;
		    if (linkedEpisodeIndex > 0) return linkedEpisodeLinks[linkedEpisodeIndex - 1] ?? null;
		    return null;
		  });

		  const nextLinkedEpisode = $derived.by(() => {
		    if (!linkedEpisodeLinks.length) return null;
		    if (linkedEpisodeIndex >= 0) return linkedEpisodeLinks[linkedEpisodeIndex + 1] ?? null;
		    return linkedEpisodeLinks[0] ?? null;
		  });

		  const navigateToLinkedEpisode = (link: ExperimentEpisodeLink | null) => {
		    if (!link) return;
		    if (!onPreviewEpisode) return;
		    pendingAutoplayOnDatasetChange = true;
		    onPreviewEpisode(link.dataset_id, link.episode_index);
		  };

		  const onPrevLinkedEpisode = $derived.by(() =>
		    prevLinkedEpisode ? () => navigateToLinkedEpisode(prevLinkedEpisode) : undefined
		  );
		  const onNextLinkedEpisode = $derived.by(() =>
		    nextLinkedEpisode ? () => navigateToLinkedEpisode(nextLinkedEpisode) : undefined
		  );

  let blueprint: BlueprintNode = $state(createDefaultBlueprint());
  let selectedId = $state('');
  let mounted = $state(false);
  let filledDefaults = $state(false);
  let lastDatasetCameraKeysSignature = $state('');
  let lastDatasetSignalKeysSignature = $state('');
  let editInspectorTab = $state<'blueprint' | 'selection' | 'search'>('blueprint');
  let inspectorInitialized = $state(false);
  let editorShellEl = $state<HTMLDivElement | null>(null);
  let editorToolbarEl = $state<HTMLDivElement | null>(null);
  let editorContentEl = $state<HTMLDivElement | null>(null);
  let editorRightPaneWidth = $state(420);
  let editorViewScale = $state(1);

  $effect(() => {
    if (!selectedId && blueprint?.id) {
      selectedId = blueprint.id;
    }
  });

  const fillDefaultConfig = (node: BlueprintNode, topics: string[]): BlueprintNode => {
    if (node.type === 'view') {
      const definition = getViewDefinition(node.viewType);
      if (!definition?.defaultConfig) return node;
      const defaults = definition.defaultConfig(topics, viewSource);
      return {
        ...node,
        config: {
          ...defaults,
          ...node.config
        }
      };
    }
    if (node.type === 'split') {
      return {
        ...node,
        children: [fillDefaultConfig(node.children[0], topics), fillDefaultConfig(node.children[1], topics)]
      };
    }
    return {
      ...node,
      tabs: node.tabs.map((tab) => ({
        ...tab,
        child: fillDefaultConfig(tab.child, topics)
      }))
    };
  };

  onMount(() => {
    mounted = true;
  });

	  const ensureDatasetCameraTopics = (node: BlueprintNode, keys: string[], used = new Set<string>()): BlueprintNode => {
	    if (!keys.length) return node;
	    if (node.type === 'view' && node.viewType === 'camera') {
	      const topic = typeof node.config?.topic === 'string' ? node.config.topic.trim() : '';
	      if (topic && keys.includes(topic)) {
	        used.add(topic);
	        return node;
	      }

	      const fallback = keys.find((key) => !used.has(key)) ?? keys[0] ?? '';
	      if (!fallback) return node;

	      used.add(fallback);
	      return {
	        ...node,
	        config: {
	          ...node.config,
	          topic: fallback
	        }
	      };
	    }
	    if (node.type === 'split') {
	      const left = ensureDatasetCameraTopics(node.children[0], keys, used);
	      const right = ensureDatasetCameraTopics(node.children[1], keys, used);
	      if (left === node.children[0] && right === node.children[1]) return node;
	      return { ...node, children: [left, right] };
	    }
	    if (node.type !== 'tabs') return node;
	    const nextTabs = node.tabs.map((tab) => {
	      const child = ensureDatasetCameraTopics(tab.child, keys, used);
	      return child === tab.child ? tab : { ...tab, child };
	    });
	    const changed = nextTabs.some((tab, idx) => tab !== node.tabs[idx]);
	    return changed ? { ...node, tabs: nextTabs } : node;
	  };

		  const ensureDatasetJointTopics = (node: BlueprintNode, keys: string[]): BlueprintNode => {
		    if (!keys.length) return node;
		    const resolvedFallback = keys.includes('observation.state') ? 'observation.state' : keys[0] ?? '';
		    if (!resolvedFallback) return node;
		    if (node.type === 'view' && node.viewType === 'joint_state') {
		      const topic = typeof node.config?.topic === 'string' ? node.config.topic.trim() : '';
		      if (topic && keys.includes(topic)) return node;
	      return {
	        ...node,
	        config: {
	          ...node.config,
	          topic: resolvedFallback
	        }
	      };
		    }
		    if (node.type === 'split') {
		      const left = ensureDatasetJointTopics(node.children[0], keys);
		      const right = ensureDatasetJointTopics(node.children[1], keys);
		      if (left === node.children[0] && right === node.children[1]) return node;
		      return { ...node, children: [left, right] };
		    }
		    if (node.type !== 'tabs') return node;
		    const nextTabs = node.tabs.map((tab) => {
		      const child = ensureDatasetJointTopics(tab.child, keys);
		      return child === tab.child ? tab : { ...tab, child };
		    });
	    const changed = nextTabs.some((tab, idx) => tab !== node.tabs[idx]);
	    return changed ? { ...node, tabs: nextTabs } : node;
	  };

		  $effect(() => {
		    if (!mounted) return;
		    if (viewSource !== 'dataset') {
		      lastDatasetCameraKeysSignature = '';
		      return;
		    }
		    if (!datasetId) return;
		    const signature = `${datasetId}:${datasetCameraKeys.join('|')}`;
		    if (signature === lastDatasetCameraKeysSignature) return;
		    lastDatasetCameraKeysSignature = signature;
		    if (!datasetCameraKeys.length) return;
		    const next = ensureDatasetCameraTopics(blueprint, datasetCameraKeys);
		    if (next !== blueprint) {
		      blueprint = next;
		      selectedId = ensureValidSelection(next, selectedId);
		    }
		  });

		  $effect(() => {
		    if (!mounted) return;
		    if (viewSource !== 'dataset') {
		      lastDatasetSignalKeysSignature = '';
		      return;
		    }
		    if (!datasetId) return;
		    const signature = `${datasetId}:${datasetSignalKeys.join('|')}`;
		    if (signature === lastDatasetSignalKeysSignature) return;
		    lastDatasetSignalKeysSignature = signature;
		    if (!datasetSignalKeys.length) return;
		    const next = ensureDatasetJointTopics(blueprint, datasetSignalKeys);
		    if (next !== blueprint) {
		      blueprint = next;
		      selectedId = ensureValidSelection(next, selectedId);
		    }
		  });

  $effect(() => {
    if (!mounted) return;
    if (inspectorInitialized) return;
    if (!editMode) return;

    const desired =
      showSearchTab && initialInspectorTab === 'search'
        ? 'search'
        : initialInspectorTab === 'search'
          ? 'selection'
          : initialInspectorTab;

    editInspectorTab = desired;
    inspectorInitialized = true;
  });

  const applyBlueprintFromWorkspace = (detail: { id: string; name: string; blueprint: BlueprintNode }) => {
    blueprint = detail.blueprint;
    selectedId = ensureValidSelection(blueprint, selectedId);
    filledDefaults = false;
  };

  $effect(() => {
    if (filledDefaults) return;
    if ((viewSource === 'ros' || viewSource === 'dataset') && topics.length === 0) return;
    blueprint = fillDefaultConfig(blueprint, topics);
    filledDefaults = true;
    selectedId = ensureValidSelection(blueprint, selectedId);
  });

	  $effect(() => {
	    if (!mounted) return;
	    if (viewSource !== 'dataset') return;
	    const signature = `${datasetId}:${datasetEpisodeIndex}`;
	    if (signature === lastDatasetPlaybackSignature) return;
	    lastDatasetPlaybackSignature = signature;
	    datasetPlayback.reset();
	    if (pendingAutoplayOnDatasetChange) {
	      pendingAutoplayOnDatasetChange = false;
	      datasetPlayback.play();
	    }
	  });

	  $effect(() => {
	    if (!mounted) return;
	    if (viewSource !== 'dataset') return;
	    if (!datasetAutoplayNonce) return;
	    if (datasetAutoplayNonce === lastDatasetAutoplayNonce) return;
	    lastDatasetAutoplayNonce = datasetAutoplayNonce;
	    datasetPlayback.play();
	  });

  const selectedNode = $derived(selectedId ? findNode(blueprint, selectedId) : null);
  const selectedViewNode = $derived(selectedNode?.type === 'view' ? selectedNode : null);
  const selectedSplitNode = $derived(selectedNode?.type === 'split' ? selectedNode : null);
  const selectedTabsNode = $derived(selectedNode?.type === 'tabs' ? selectedNode : null);

  const updateSelection = (id: string) => {
    selectedId = id;
  };

  const handleResize = (id: string, sizes: [number, number]) => {
    blueprint = updateSplitSizes(blueprint, id, sizes);
  };

  const handleTabChange = (id: string, activeId: string) => {
    blueprint = updateTabsActive(blueprint, id, activeId);
  };

  const handleSplit = (direction: 'row' | 'column') => {
    if (!selectedNode) return;
    blueprint = wrapInSplit(blueprint, selectedNode.id, direction);
  };

  const handleTabs = () => {
    if (!selectedNode) return;
    blueprint = wrapInTabs(blueprint, selectedNode.id);
  };

  const handleViewTypeChange = (nextType: string) => {
    if (!selectedViewNode) return;
    const definition = getViewDefinition(nextType);
    const defaults = definition?.defaultConfig?.(topics, viewSource) ?? {};
    blueprint = updateViewType(blueprint, selectedViewNode.id, nextType);
    blueprint = updateViewConfig(blueprint, selectedViewNode.id, defaults);
  };

  const handleConfigChange = (key: string, value: unknown) => {
    if (!selectedViewNode) return;
    blueprint = updateViewConfig(blueprint, selectedViewNode.id, {
      ...selectedViewNode.config,
      [key]: value
    });
  };

  const handleAddTab = () => {
    if (!selectedTabsNode) return;
    blueprint = addTab(blueprint, selectedTabsNode.id);
  };

  const handleRenameTab = (tabId: string, title: string) => {
    if (!selectedTabsNode) return;
    blueprint = renameTab(blueprint, selectedTabsNode.id, tabId, title);
  };

  const handleRemoveTab = (tabId: string) => {
    if (!selectedTabsNode) return;
    blueprint = removeTab(blueprint, selectedTabsNode.id, tabId);
    selectedId = ensureValidSelection(blueprint, selectedId);
  };

  const handleDeleteSelected = (mode: 'view' | 'split' | 'tabs') => {
    if (!selectedNode) return;
    const message =
      mode === 'view'
        ? 'このビューを削除しますか？'
        : mode === 'split'
          ? 'この分割を解除しますか？（片側のみ残ります）'
          : 'タブセットを解除しますか？（アクティブなタブのみ残ります）';
    if (!confirm(message)) return;
    blueprint = deleteNode(blueprint, selectedNode.id);
    selectedId = ensureValidSelection(blueprint, selectedId);
  };

  const recomputeEditorPaneWidth = () => {
    if (typeof window === 'undefined') return;
    if (!editorShellEl || !editorToolbarEl || !editorContentEl) return;
    if (!window.matchMedia('(min-width: 1024px)').matches) {
      editorRightPaneWidth = 420;
      editorViewScale = 1;
      return;
    }

    const shellWidth = editorShellEl.clientWidth;
    const shellHeight = editorShellEl.clientHeight;
    const toolbarHeight = editorToolbarEl.getBoundingClientRect().height;
    const rowGap = Number.parseFloat(window.getComputedStyle(editorShellEl).rowGap || '0') || 0;
    const columnGap = Number.parseFloat(window.getComputedStyle(editorContentEl).columnGap || '0') || 0;
    const contentWidth = editorContentEl.clientWidth;

    if (shellWidth <= 0 || shellHeight <= 0 || contentWidth <= 0) return;

    const viewAspectRatio = shellWidth / shellHeight;
    const editableViewHeight = Math.max(shellHeight - toolbarHeight - rowGap, 1);
    const targetViewWidth = viewAspectRatio * editableViewHeight;
    const computedRightWidth = contentWidth - columnGap - targetViewWidth;
    // Search tab needs extra width; keep the right pane usable in the modal.
    const nextRightWidth = Math.max(420, computedRightWidth);
    const actualLeftWidth = Math.max(contentWidth - columnGap - nextRightWidth, 1);
    editorRightPaneWidth = nextRightWidth;
    editorViewScale = Math.min(actualLeftWidth / shellWidth, editableViewHeight / shellHeight);
  };

  $effect(() => {
    if (typeof window === 'undefined' || !editMode) return;
    if (!editorShellEl || !editorToolbarEl || !editorContentEl) return;

    const observer = new ResizeObserver(() => {
      recomputeEditorPaneWidth();
    });
    observer.observe(editorShellEl);
    observer.observe(editorToolbarEl);
    observer.observe(editorContentEl);
    const onResize = () => {
      recomputeEditorPaneWidth();
    };
    window.addEventListener('resize', onResize);
    recomputeEditorPaneWidth();

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', onResize);
    };
  });
</script>

<section class={embedded ? 'grid h-full min-h-0 gap-6' : 'grid gap-6'}>
  {#if editMode}
    <div class={embedded ? 'card p-4 h-full min-h-0' : 'card p-4 min-h-[640px] lg:h-[var(--app-shell-height)]'}>
      <div class="grid h-full grid-rows-[auto_minmax(0,1fr)] gap-4" bind:this={editorShellEl}>
        <div bind:this={editorToolbarEl}>
          <BlueprintWorkspace
            sessionId={blueprintSessionId}
            sessionKind={blueprintSessionKind}
            {blueprint}
            persistDraft={persistBlueprintDraft}
            disabled={!mounted}
            onApplyBlueprintDetail={applyBlueprintFromWorkspace}
          />
        </div>

        <div
          class="min-h-0 grid gap-4 lg:grid-cols-[minmax(0,1fr)_var(--editor-right-pane-width)]"
          style={`--editor-right-pane-width:${Math.round(editorRightPaneWidth)}px;`}
          bind:this={editorContentEl}
        >
		          <div class="min-h-0 rounded-xl border border-slate-200/60 bg-white/70 p-2">
			            <LayoutNode
			              node={blueprint}
			              selectedId={selectedId}
		              sessionId={resolvedLayoutSessionId}
		              sessionKind={resolvedLayoutSessionKind}
		              mode={layoutMode}
			              viewSource={viewSource}
			              datasetId={datasetId}
			              datasetEpisodeIndex={datasetEpisodeIndex}
			              datasetPlayback={viewSource === 'dataset' ? datasetPlayback : null}
			              onPrevLinkedEpisode={onPrevLinkedEpisode}
			              onNextLinkedEpisode={onNextLinkedEpisode}
			              editMode={editMode}
			              viewScale={editorViewScale}
			              onSelect={updateSelection}
			              onResize={handleResize}
		              onTabChange={handleTabChange}
            />
          </div>

          <aside class="min-h-0 rounded-xl border border-slate-200/60 bg-white/70 p-3 lg:overflow-y-auto">
            <InspectorTabs bind:value={editInspectorTab} {showSearchTab}>
              {#snippet blueprintPanel()}
                <BlueprintTree node={blueprint} selectedId={selectedId} onSelect={updateSelection} />
              {/snippet}

              {#snippet selectionPanel()}
                {#if !selectedNode}
                  <p class="text-xs text-slate-500">選択されていません。</p>
                {:else if selectedNode.type === 'view'}
                  <div class="space-y-4 text-sm text-slate-700">
                    <div>
                      <p class="label">View Type</p>
                      <select
                        class="input mt-2"
                        value={selectedViewNode?.viewType}
                        onchange={(event) => handleViewTypeChange((event.target as HTMLSelectElement).value)}
                      >
                        <option value="placeholder">Empty</option>
                        {#each viewOptions as option}
                          <option value={option.type}>{option.label}</option>
                        {/each}
                      </select>
                    </div>

                    {#if selectedViewNode}
                      {#each getViewDefinition(selectedViewNode.viewType)?.fields ?? [] as field}
                        {#if isFieldSupported(field, viewSource)}
	                          {#if field.type === 'topic'}
	                            <div>
	                              <p class="label">{field.label}</p>
	                              <select
	                                class="input mt-2"
	                                value={(selectedViewNode.config?.[field.key] as string) ?? ''}
	                                onchange={(event) =>
	                                  handleConfigChange(field.key, (event.target as HTMLSelectElement).value)}
	                                disabled={viewSource === 'dataset' && selectedViewNode.viewType === 'joint_state' && !inspectorTopics.length}
	                              >
	                                {#if viewSource === 'dataset' && selectedViewNode.viewType === 'joint_state' && !inspectorTopics.length}
	                                  <option value="">signals loading...</option>
	                                {:else}
	                                  <option value="">未選択</option>
	                                  {#each getTopicFieldOptions(field, inspectorTopics, viewSource) as topic}
	                                    <option value={topic}>{topic}</option>
	                                  {/each}
	                                {/if}
	                              </select>
	                              {#if viewSource === 'dataset' && selectedViewNode.viewType === 'joint_state' && !inspectorTopics.length}
	                                <p class="mt-2 text-xs text-slate-500">
	                                  Signal一覧を取得中です。少し待ってから再度開いてください。
	                                </p>
	                              {/if}
	                            </div>
                          {:else if field.type === 'boolean'}
                            <label class="flex items-center gap-2 text-xs text-slate-600">
                              <input
                                type="checkbox"
                                class="h-4 w-4 rounded border-slate-300"
                                checked={Boolean(selectedViewNode.config?.[field.key])}
                                onchange={(event) =>
                                  handleConfigChange(field.key, (event.target as HTMLInputElement).checked)}
                              />
                              {field.label}
                            </label>
                          {:else if field.type === 'number'}
                            <div>
                              <p class="label">{field.label}</p>
                              <input
                                class="input mt-2"
                                type="number"
                                min="10"
                                value={Number(selectedViewNode.config?.[field.key] ?? 160)}
                                onchange={(event) =>
                                  handleConfigChange(field.key, Number((event.target as HTMLInputElement).value))}
                              />
                            </div>
                          {/if}
                        {/if}
                      {/each}
                    {/if}

                    <div class="divider"></div>
                    <div class="space-y-2">
                      <Button.Root class="btn-ghost w-full" type="button" onclick={() => handleSplit('row')}>
                        横分割
                      </Button.Root>
                      <Button.Root class="btn-ghost w-full" type="button" onclick={() => handleSplit('column')}>
                        縦分割
                      </Button.Root>
                      <Button.Root class="btn-ghost w-full" type="button" onclick={handleTabs}>タブ化</Button.Root>
                      <Button.Root
                        class="btn-ghost w-full border-rose-200/70 text-rose-600 hover:border-rose-300/80"
                        type="button"
                        onclick={() => handleDeleteSelected('view')}
                      >
                        このビューを削除
                      </Button.Root>
                    </div>
                  </div>
                {:else if selectedNode.type === 'split'}
                  <div class="space-y-4 text-sm text-slate-700">
                    <div>
                      <p class="label">Direction</p>
                      <select
                        class="input mt-2"
                        value={selectedSplitNode?.direction}
                        onchange={(event) => {
                          const nextDirection = (event.target as HTMLSelectElement).value as 'row' | 'column';
                          if (selectedSplitNode) {
                            blueprint = updateSplitDirection(blueprint, selectedSplitNode.id, nextDirection);
                          }
                        }}
                      >
                        <option value="row">横</option>
                        <option value="column">縦</option>
                      </select>
                    </div>
                    <p class="text-xs text-slate-500">ドラッグで比率を変更できます。</p>
                    <Button.Root
                      class="btn-ghost w-full border-rose-200/70 text-rose-600 hover:border-rose-300/80"
                      type="button"
                      onclick={() => handleDeleteSelected('split')}
                    >
                      分割を解除
                    </Button.Root>
                  </div>
                {:else if selectedNode.type === 'tabs'}
                  <div class="space-y-4 text-sm text-slate-700">
                    <div class="flex items-center justify-between">
                      <p class="label">Tabs</p>
                      <Button.Root class="btn-ghost" type="button" onclick={handleAddTab}>タブ追加</Button.Root>
                    </div>
                    <div class="space-y-2">
                      {#each selectedTabsNode?.tabs ?? [] as tab}
                        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-2">
                          <input
                            class="input"
                            type="text"
                            value={tab.title}
                            onchange={(event) => handleRenameTab(tab.id, (event.target as HTMLInputElement).value)}
                          />
                          <Button.Root
                            class="btn-ghost mt-2 w-full"
                            type="button"
                            onclick={() => handleRemoveTab(tab.id)}
                          >
                            このタブを削除
                          </Button.Root>
                        </div>
                      {/each}
                    </div>
                    <Button.Root
                      class="btn-ghost w-full border-rose-200/70 text-rose-600 hover:border-rose-300/80"
                      type="button"
                      onclick={() => handleDeleteSelected('tabs')}
                    >
                      タブセットを解除
                    </Button.Root>
                  </div>
                {/if}
              {/snippet}

              {#if showSearchTab}
                {#snippet searchPanel()}
                  <DatasetEpisodeSearchTab
                    datasets={searchDatasets}
                    recommendedDatasetId={searchRecommendedDatasetId}
                    previewDatasetId={datasetId}
                    previewEpisodeIndex={datasetEpisodeIndex}
                    episodeLinks={searchEpisodeLinks}
                    onPreview={onPreviewEpisode}
                    onAdd={onAddEpisodeLink}
                    onRemove={onRemoveEpisodeLink}
                  />
                {/snippet}
              {/if}
            </InspectorTabs>
          </aside>
        </div>
      </div>
    </div>
  {:else}
		    <div class={embedded ? 'card p-4 h-full min-h-0' : 'card p-4 min-h-[640px] lg:h-[var(--app-shell-height)]'}>
			      <LayoutNode
			        node={blueprint}
			        selectedId={selectedId}
		        sessionId={resolvedLayoutSessionId}
		        sessionKind={resolvedLayoutSessionKind}
		        mode={layoutMode}
			        viewSource={viewSource}
			        datasetId={datasetId}
			        datasetEpisodeIndex={datasetEpisodeIndex}
			        datasetPlayback={viewSource === 'dataset' ? datasetPlayback : null}
			        onPrevLinkedEpisode={onPrevLinkedEpisode}
			        onNextLinkedEpisode={onNextLinkedEpisode}
			        editMode={editMode}
			        viewScale={1}
			        onSelect={updateSelection}
			        onResize={handleResize}
		        onTabChange={handleTabChange}
	      />
	    </div>
  {/if}
</section>

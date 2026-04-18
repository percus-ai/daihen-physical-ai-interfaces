<script lang="ts">
  import { onMount, setContext, tick } from 'svelte';
  import type { Snippet } from 'svelte';
  import { toStore } from 'svelte/store';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import toast from 'svelte-french-toast';
  import { api } from '$lib/api/client';
  import { resolveBlueprintForSession } from '$lib/blueprints/blueprintManager';
  import { getBlueprintSessionSignature, materializeSessionBlueprintState } from '$lib/blueprints/sessionBlueprintState';
  import { VIEWER_RUNTIME, type ViewerRuntime, type ViewerRuntimeStore } from '$lib/viewer/runtimeContext';

  import LayoutNode from '$lib/components/recording/LayoutNode.svelte';
  import BlueprintTree from '$lib/components/recording/BlueprintTree.svelte';
  import BlueprintWorkspace from '$lib/components/recording/BlueprintWorkspace.svelte';
  import InspectorTabs from '$lib/components/recording/InspectorTabs.svelte';
  import {
    createDatasetPlaybackController,
    type DatasetPlaybackController
  } from '$lib/recording/datasetPlayback';

  import {
    addTab,
    createDefaultBlueprint,
    DEFAULT_BLUEPRINT_CANVAS_HEIGHT,
    DEFAULT_BLUEPRINT_CANVAS_WIDTH,
    deleteNode,
    ensureValidSelection,
    findNode,
    normalizeBlueprintDocument,
    removeTab,
    renameTab,
    updateSplitDirection,
    updateSplitSizes,
    updateTabsActive,
    updateViewConfig,
    updateViewType,
    wrapInSplit,
    wrapInTabs,
    type BlueprintDocument
  } from '$lib/recording/blueprint';
  import {
    getTopicFieldOptions,
    getViewDefinition,
    getViewOptionsBySource,
    isFieldSupported,
    type ViewConfigSource
  } from '$lib/recording/viewRegistry';
  import {
    ensureDatasetCameraTopics,
    ensureDatasetJointTopics,
    fillDefaultConfig
  } from '$lib/recording/blueprintNormalization';
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
				    datasetVideoWindows = {},
				    datasetAutoplayNonce = 0,
			    inspectorExtraTabs = [],
			    onPrevEpisode = undefined,
			    onNextEpisode = undefined
		  }: {
    blueprintSessionId?: string;
    blueprintSessionKind?: BlueprintSessionKind | '';
    layoutSessionId?: string;
    layoutSessionKind?: BlueprintSessionKind | '';
    layoutMode?: 'recording' | 'operate';
    viewSource?: ViewConfigSource;
    editMode?: boolean;
    initialInspectorTab?: string;
    persistBlueprintDraft?: boolean;
			    embedded?: boolean;
			    datasetId?: string;
			    datasetEpisodeIndex?: number;
				    datasetCameraKeys?: string[];
				    datasetSignalKeys?: string[];
				    datasetVideoWindows?: Record<string, { from_s: number; to_s: number }>;
				    datasetAutoplayNonce?: number;
			    inspectorExtraTabs?: { id: string; label: string; panel?: Snippet }[];
			    onPrevEpisode?: () => void;
			    onNextEpisode?: () => void;
  } = $props();

  const datasetPlayback: DatasetPlaybackController = createDatasetPlaybackController();

  const resolvedLayoutSessionId = $derived(layoutSessionId || blueprintSessionId);
  const resolvedLayoutSessionKind = $derived(layoutSessionKind || blueprintSessionKind);
  const viewOptions = $derived(getViewOptionsBySource(viewSource));
  const effectiveInspectorExtraTabs = $derived.by(() =>
    editMode ? (inspectorExtraTabs ?? []).filter((tab) => Boolean(tab?.id) && Boolean(tab?.label)) : []
  );

  const runtimeStore: ViewerRuntimeStore = toStore(() => {
    const mode = layoutMode;
	    if (viewSource === 'dataset') {
	      return {
	        kind: 'dataset',
	        mode,
	        datasetId,
	        episodeIndex: Math.max(0, Math.floor(Number(datasetEpisodeIndex) || 0)),
	        videoWindows: datasetVideoWindows,
	        playback: datasetPlayback,
	        onPrevEpisode,
	        onNextEpisode
	      } satisfies ViewerRuntime;
	    }
    return {
      kind: 'ros',
      mode,
      sessionId: resolvedLayoutSessionId,
      sessionKind: resolvedLayoutSessionKind
    } satisfies ViewerRuntime;
  });

  setContext(VIEWER_RUNTIME, runtimeStore);

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

  let lastDatasetPlaybackSignature = '';
  let lastDatasetAutoplayNonce = 0;

  let blueprint: BlueprintDocument = $state(createDefaultBlueprint());
  let selectedId = $state('');
  let activeBlueprintId = $state('');
  let activeBlueprintName = $state('');
  let mounted = $state(false);
  let filledDefaults = $state(false);
  let editInspectorTab = $state<string>('blueprint');
  let inspectorInitialized = $state(false);
  let lastResolvedBlueprintSignature = '';
  let activeBlueprintResolveRequestId = 0;

  $effect(() => {
    if (!selectedId && blueprint?.root?.id) {
      selectedId = blueprint.root.id;
    }
  });

  onMount(() => {
    mounted = true;
  });

  $effect(() => {
    if (!mounted) return;
    if (viewSource !== 'dataset') return;
    if (!datasetId) return;
    if (!datasetCameraKeys.length) return;
    // Blueprint can change after the dataset keys are loaded (e.g. workspace load),
    // so normalize on both key changes and blueprint changes.
    const nextRoot = ensureDatasetCameraTopics(blueprint.root, datasetCameraKeys);
    if (nextRoot === blueprint.root) return;
    blueprint = { ...blueprint, root: nextRoot };
    selectedId = ensureValidSelection(nextRoot, selectedId);
  });

  $effect(() => {
    if (!mounted) return;
    if (viewSource !== 'dataset') return;
    if (!datasetId) return;
    if (!datasetSignalKeys.length) return;
    const nextRoot = ensureDatasetJointTopics(blueprint.root, datasetSignalKeys);
    if (nextRoot === blueprint.root) return;
    blueprint = { ...blueprint, root: nextRoot };
    selectedId = ensureValidSelection(nextRoot, selectedId);
  });

  $effect(() => {
    if (!mounted) return;
    if (inspectorInitialized) return;
    if (!editMode) return;

    const desired = String(initialInspectorTab || 'blueprint');
    const available = ['blueprint', 'selection', ...effectiveInspectorExtraTabs.map((tab) => tab.id)];
    editInspectorTab = available.includes(desired) ? desired : 'selection';
    inspectorInitialized = true;
  });

  const applyBlueprintFromWorkspace = (detail: { id: string; name: string; blueprint: BlueprintDocument }) => {
    activeBlueprintId = detail.id;
    activeBlueprintName = detail.name;
    blueprint = normalizeBlueprintDocument(detail.blueprint);
    selectedId = ensureValidSelection(blueprint.root, selectedId);
    filledDefaults = false;
  };

  $effect(() => {
    if (!mounted) return;
    const currentSessionKind = blueprintSessionKind;
    const currentSessionId = blueprintSessionId;
    const signature = getBlueprintSessionSignature(currentSessionKind, currentSessionId);
    if (!signature || signature === lastResolvedBlueprintSignature) return;
    lastResolvedBlueprintSignature = signature;
    if (!currentSessionKind || !currentSessionId) return;

    const requestId = activeBlueprintResolveRequestId + 1;
    activeBlueprintResolveRequestId = requestId;

    void resolveBlueprintForSession(currentSessionKind, currentSessionId)
      .then((resolved) => {
        if (requestId !== activeBlueprintResolveRequestId) return;
        const nextState = materializeSessionBlueprintState({
          detail: resolved.blueprint,
          persistDraft: persistBlueprintDraft,
          sessionKind: currentSessionKind,
          sessionId: currentSessionId
        });
        applyBlueprintFromWorkspace(nextState);
      })
      .catch((error) => {
        if (requestId !== activeBlueprintResolveRequestId) return;
        const message = error instanceof Error ? error.message : 'ブループリントの読み込みに失敗しました。';
        if (typeof window !== 'undefined') {
          toast.error(message);
        }
      });
  });

  $effect(() => {
    if (filledDefaults) return;
    if ((viewSource === 'ros' || viewSource === 'dataset') && topics.length === 0) return;
    blueprint = {
      ...blueprint,
      root: fillDefaultConfig(blueprint.root, topics, viewSource)
    };
    filledDefaults = true;
    selectedId = ensureValidSelection(blueprint.root, selectedId);
  });

	  $effect(() => {
	    if (!mounted) return;
	    if (viewSource !== 'dataset') return;
	    const normalizedDatasetId = String(datasetId || '').trim();
	    const normalizedEpisode = Math.max(0, Math.floor(Number(datasetEpisodeIndex) || 0));
	    const signature = `${normalizedDatasetId}:${normalizedEpisode}`;
	    if (signature === lastDatasetPlaybackSignature) return;
	    lastDatasetPlaybackSignature = signature;

	    const prev = datasetPlayback.getState();
	    datasetPlayback.reset();
	    if (prev.rate !== 1) datasetPlayback.setRate(prev.rate);

	    // Keep playback going when users navigate episodes while playing.
	    if (prev.playing) {
	      void tick().then(() => {
	        datasetPlayback.play();
	      });
	    }
	  });

  $effect(() => {
    if (!mounted) return;
    if (viewSource !== 'dataset') return;
    if (!datasetAutoplayNonce) return;
    if (datasetAutoplayNonce === lastDatasetAutoplayNonce) return;
    lastDatasetAutoplayNonce = datasetAutoplayNonce;
    // Defer one microtask so dataset switches can reset first, then autoplay.
    if (typeof queueMicrotask === 'function') {
      queueMicrotask(() => datasetPlayback.play());
    } else {
      datasetPlayback.play();
    }
  });

  const selectedNode = $derived(selectedId ? findNode(blueprint.root, selectedId) : null);
  const selectedViewNode = $derived(selectedNode?.type === 'view' ? selectedNode : null);
  const selectedSplitNode = $derived(selectedNode?.type === 'split' ? selectedNode : null);
  const selectedTabsNode = $derived(selectedNode?.type === 'tabs' ? selectedNode : null);

  const updateSelection = (id: string) => {
    selectedId = id;
  };

  const handleResize = (id: string, sizes: [number, number]) => {
    blueprint = { ...blueprint, root: updateSplitSizes(blueprint.root, id, sizes) };
  };

  const handleTabChange = (id: string, activeId: string) => {
    blueprint = { ...blueprint, root: updateTabsActive(blueprint.root, id, activeId) };
  };

  const handleSplit = (direction: 'row' | 'column') => {
    if (!selectedNode) return;
    blueprint = { ...blueprint, root: wrapInSplit(blueprint.root, selectedNode.id, direction) };
  };

  const handleTabs = () => {
    if (!selectedNode) return;
    blueprint = { ...blueprint, root: wrapInTabs(blueprint.root, selectedNode.id) };
  };

  const handleViewTypeChange = (nextType: string) => {
    if (!selectedViewNode) return;
    const definition = getViewDefinition(nextType);
    const defaults = definition?.defaultConfig?.(topics, viewSource) ?? {};
    const nextRoot = updateViewConfig(
      updateViewType(blueprint.root, selectedViewNode.id, nextType),
      selectedViewNode.id,
      defaults
    );
    blueprint = { ...blueprint, root: nextRoot };
  };

  const handleConfigChange = (key: string, value: unknown) => {
    if (!selectedViewNode) return;
    blueprint = {
      ...blueprint,
      root: updateViewConfig(blueprint.root, selectedViewNode.id, {
        ...selectedViewNode.config,
        [key]: value
      })
    };
  };

  const handleAddTab = () => {
    if (!selectedTabsNode) return;
    blueprint = { ...blueprint, root: addTab(blueprint.root, selectedTabsNode.id) };
  };

  const handleRenameTab = (tabId: string, title: string) => {
    if (!selectedTabsNode) return;
    blueprint = { ...blueprint, root: renameTab(blueprint.root, selectedTabsNode.id, tabId, title) };
  };

  const handleRemoveTab = (tabId: string) => {
    if (!selectedTabsNode) return;
    const nextRoot = removeTab(blueprint.root, selectedTabsNode.id, tabId);
    blueprint = { ...blueprint, root: nextRoot };
    selectedId = ensureValidSelection(nextRoot, selectedId);
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
    const nextRoot = deleteNode(blueprint.root, selectedNode.id);
    blueprint = { ...blueprint, root: nextRoot };
    selectedId = ensureValidSelection(nextRoot, selectedId);
  };

  const updateCanvasWidth = (value: string) => {
    const next = Math.max(320, Math.min(4096, Math.round(Number(value) || DEFAULT_BLUEPRINT_CANVAS_WIDTH)));
    blueprint = { ...blueprint, canvasWidth: next };
  };

  const updateCanvasHeight = (value: string) => {
    const next = Math.max(320, Math.min(4096, Math.round(Number(value) || DEFAULT_BLUEPRINT_CANVAS_HEIGHT)));
    blueprint = { ...blueprint, canvasHeight: next };
  };

  const resetCanvasSize = () => {
    blueprint = {
      ...blueprint,
      canvasWidth: DEFAULT_BLUEPRINT_CANVAS_WIDTH,
      canvasHeight: DEFAULT_BLUEPRINT_CANVAS_HEIGHT
    };
  };

  const canvasRatioLabel = $derived.by(() => {
    const width = Math.max(1, Number(blueprint.canvasWidth) || DEFAULT_BLUEPRINT_CANVAS_WIDTH);
    const height = Math.max(1, Number(blueprint.canvasHeight) || DEFAULT_BLUEPRINT_CANVAS_HEIGHT);
    return `${(width / height).toFixed(2)}:1`;
  });

</script>

<section class={embedded ? 'grid h-full min-h-0 gap-6' : 'grid gap-6'}>
  {#if editMode}
    <div class={embedded ? 'card p-4 h-full min-h-0' : 'card p-4 min-h-[640px] lg:h-[var(--app-shell-height)]'}>
      <div class="grid h-full grid-rows-[auto_minmax(0,1fr)] gap-4">
        <div>
          <BlueprintWorkspace
            sessionId={blueprintSessionId}
            sessionKind={blueprintSessionKind}
            {blueprint}
            currentBlueprintId={activeBlueprintId}
            currentBlueprintName={activeBlueprintName}
            persistDraft={persistBlueprintDraft}
            disabled={!mounted}
            onApplyBlueprintDetail={applyBlueprintFromWorkspace}
          />
        </div>

        <div
          class="min-h-0 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(26rem,26rem)]"
        >
		          <div class="min-h-0 nested-block p-2">
                <div class="session-layout-stage">
                  <div
                    class="session-layout-canvas"
                    style={`--session-canvas-width:${blueprint.canvasWidth}px;--session-canvas-height:${blueprint.canvasHeight}px;`}
                  >
                    <div class="session-layout-root">
			                  <LayoutNode
			                    node={blueprint.root}
			                    selectedId={selectedId}
			                    editMode={editMode}
			                    onSelect={updateSelection}
			                    onResize={handleResize}
		                    onTabChange={handleTabChange}
                      />
                    </div>
                  </div>
                </div>
          </div>

          <aside class="flex min-h-0 flex-col overflow-hidden nested-block p-3">
            <InspectorTabs bind:value={editInspectorTab} extraTabs={effectiveInspectorExtraTabs}>
              {#snippet blueprintPanel()}
                <div class="space-y-4">
                  <BlueprintTree node={blueprint.root} selectedId={selectedId} onSelect={updateSelection} />
                  <div class="divider"></div>
                  <div class="space-y-3">
                    <div class="flex items-center justify-between">
                      <p class="label">Canvas</p>
                      <Button.Root class="btn-ghost px-3 py-1.5 text-xs" type="button" onclick={resetCanvasSize}>
                        リセット
                      </Button.Root>
                    </div>
                    <div class="grid gap-3 sm:grid-cols-2">
                      <label class="text-xs font-semibold text-slate-600">
                        <span>Width</span>
                        <input
                          class="input mt-2"
                          type="number"
                          min="320"
                          max="4096"
                          value={blueprint.canvasWidth}
                          onchange={(event) => updateCanvasWidth((event.target as HTMLInputElement).value)}
                        />
                      </label>
                      <label class="text-xs font-semibold text-slate-600">
                        <span>Height</span>
                        <input
                          class="input mt-2"
                          type="number"
                          min="320"
                          max="4096"
                          value={blueprint.canvasHeight}
                          onchange={(event) => updateCanvasHeight((event.target as HTMLInputElement).value)}
                        />
                      </label>
                    </div>
                    <div class="flex flex-wrap gap-2">
                      <Button.Root
                        class="btn-ghost px-3 py-1.5 text-xs"
                        type="button"
                        onclick={() => {
                          blueprint = { ...blueprint, canvasWidth: 2050, canvasHeight: 900 };
                        }}
                      >
                        2050 x 900
                      </Button.Root>
                      <Button.Root
                        class="btn-ghost px-3 py-1.5 text-xs"
                        type="button"
                        onclick={() => {
                          blueprint = { ...blueprint, canvasWidth: 1600, canvasHeight: 900 };
                        }}
                      >
                        1600 x 900
                      </Button.Root>
                      <Button.Root
                        class="btn-ghost px-3 py-1.5 text-xs"
                        type="button"
                        onclick={() => {
                          blueprint = { ...blueprint, canvasWidth: 1900, canvasHeight: 900 };
                        }}
                      >
                        1900 x 900
                      </Button.Root>
                    </div>
                    <p class="text-[11px] text-slate-500">ratio: {canvasRatioLabel}</p>
                  </div>
                </div>
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
                            blueprint = {
                              ...blueprint,
                              root: updateSplitDirection(blueprint.root, selectedSplitNode.id, nextDirection)
                            };
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
                        <div class="nested-block p-2">
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
            </InspectorTabs>
          </aside>
        </div>
      </div>
    </div>
  {:else}
		    <div class={embedded ? 'card p-4 h-full min-h-0' : 'card p-4 min-h-[640px] lg:h-[var(--app-shell-height)]'}>
          <div class="session-layout-stage">
            <div
              class="session-layout-canvas"
              style={`--session-canvas-width:${blueprint.canvasWidth}px;--session-canvas-height:${blueprint.canvasHeight}px;`}
            >
              <div class="session-layout-root">
			        <LayoutNode
			          node={blueprint.root}
			          selectedId={selectedId}
			          editMode={editMode}
			          onSelect={updateSelection}
			          onResize={handleResize}
		          onTabChange={handleTabChange}
	        />
              </div>
            </div>
          </div>
	    </div>
  {/if}
</section>

<style>
  .session-layout-stage {
    container-type: size;
    height: 100%;
    width: 100%;
    overflow: hidden;
    display: grid;
    place-items: center;
  }

  .session-layout-canvas {
    --session-layout-scale:
      min(calc(100cqw / var(--session-canvas-width)), calc(100cqh / var(--session-canvas-height)));
    width: calc(var(--session-canvas-width) * var(--session-layout-scale));
    height: calc(var(--session-canvas-height) * var(--session-layout-scale));
    max-width: 100%;
    max-height: 100%;
    overflow: hidden;
  }

  .session-layout-root {
    width: var(--session-canvas-width);
    height: var(--session-canvas-height);
    transform: scale(var(--session-layout-scale));
    transform-origin: top left;
  }
 </style>

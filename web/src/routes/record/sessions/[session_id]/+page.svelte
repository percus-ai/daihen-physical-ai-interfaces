<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { Button } from 'bits-ui';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { getRosbridgeClient } from '$lib/recording/rosbridge';

  import LayoutNode from '$lib/components/recording/LayoutNode.svelte';
  import BlueprintTree from '$lib/components/recording/BlueprintTree.svelte';
  import BlueprintCombobox from '$lib/components/blueprints/BlueprintCombobox.svelte';

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
  import { getViewDefinition, getViewOptions } from '$lib/recording/viewRegistry';
  import {
    loadBlueprintDraft,
    saveBlueprintDraft,
    type BlueprintSessionKind
  } from '$lib/blueprints/draftStorage';
  import {
    createBlueprintManager,
    type WebuiBlueprintDetail,
    type WebuiBlueprintSummary
  } from '$lib/blueprints/blueprintManager';

  type ProfileStatusResponse = {
    topics?: string[];
  };

  const STATUS_LABELS: Record<string, string> = {
    idle: '待機',
    warming: '準備中',
    recording: '録画中',
    paused: '一時停止',
    resetting: 'リセット中',
    inactive: '停止',
    completed: '完了'
  };

  const BLUEPRINT_KIND = 'recording' as const;

  const sessionId = $derived(page.params.session_id ?? '');

  const topicsQuery = createQuery<ProfileStatusResponse>({
    queryKey: ['profiles', 'instances', 'active', 'status'],
    queryFn: api.profiles.activeStatus
  });

  type RecorderStatus = Record<string, unknown> & {
    state?: string;
    status?: string;
    phase?: string;
    task?: string;
    dataset_id?: string;
    episode_index?: number | null;
    num_episodes?: number;
    episode_time_s?: number;
    reset_time_s?: number;
    episode_elapsed_s?: number;
    episode_remaining_s?: number;
    reset_elapsed_s?: number;
    reset_remaining_s?: number;
    last_error?: string;
  };

  const STATUS_TOPIC = '/lerobot_recorder/status';
  let recorderStatus = $state<RecorderStatus | null>(null);
  let rosbridgeStatus = $state<'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'>('idle');

  let blueprint: BlueprintNode = $state(createDefaultBlueprint());
  let selectedId = $state('');
  let mounted = $state(false);
  let lastSessionId = '';
  let filledDefaults = $state(false);
  let editMode = $state(true);

  let activeBlueprintId = $state('');
  let activeBlueprintName = $state('');
  let savedBlueprints = $state<WebuiBlueprintSummary[]>([]);
  let blueprintBusy = $state(false);
  let blueprintActionPending = $state(false);
  let blueprintError = $state('');
  let blueprintNotice = $state('');

  $effect(() => {
    if (!selectedId && blueprint?.id) {
      selectedId = blueprint.id;
    }
  });

  const fillDefaultConfig = (node: BlueprintNode, topics: string[]): BlueprintNode => {
    if (node.type === 'view') {
      const definition = getViewDefinition(node.viewType);
      if (!definition?.defaultConfig) return node;
      const defaults = definition.defaultConfig(topics);
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

  const parseRecorderPayload = (msg: Record<string, unknown>): RecorderStatus => {
    if (typeof msg.data === 'string') {
      try {
        return JSON.parse(msg.data) as RecorderStatus;
      } catch {
        return { state: 'unknown' };
      }
    }
    return msg as RecorderStatus;
  };

  const applyBlueprintDetail = (
    detail: WebuiBlueprintDetail,
    useDraft: boolean,
    kind: BlueprintSessionKind
  ) => {
    activeBlueprintId = detail.id;
    activeBlueprintName = detail.name;
    blueprint = detail.blueprint;

    if (useDraft && sessionId) {
      const draft = loadBlueprintDraft(kind, sessionId, detail.id);
      if (draft) {
        blueprint = draft;
      }
    }

    selectedId = ensureValidSelection(blueprint, selectedId);
    filledDefaults = false;
  };

  const blueprintManager = createBlueprintManager({
    getSessionId: () => sessionId,
    getSessionKind: () => BLUEPRINT_KIND,
    getActiveBlueprintId: () => activeBlueprintId,
    getActiveBlueprintName: () => activeBlueprintName,
    getBlueprint: () => blueprint,
    setSavedBlueprints: (items) => {
      savedBlueprints = items;
    },
    setBusy: (value) => {
      blueprintBusy = value;
    },
    setActionPending: (value) => {
      blueprintActionPending = value;
    },
    setError: (message) => {
      blueprintError = message;
    },
    setNotice: (message) => {
      blueprintNotice = message;
    },
    applyBlueprintDetail
  });

  const resolveSessionBlueprint = blueprintManager.resolveSessionBlueprint;
  const handleOpenBlueprint = blueprintManager.openBlueprint;
  const handleSaveBlueprint = blueprintManager.saveBlueprint;
  const handleDuplicateBlueprint = blueprintManager.duplicateBlueprint;
  const handleDeleteBlueprint = blueprintManager.deleteBlueprint;
  const handleResetBlueprint = blueprintManager.resetBlueprint;

  $effect(() => {
    if (typeof window === 'undefined') return;
    const client = getRosbridgeClient();
    const unsubscribe = client.subscribe(
      STATUS_TOPIC,
      (message) => {
        recorderStatus = parseRecorderPayload(message);
      },
      { throttle_rate: 100 }
    );
    const offStatus = client.onStatusChange((next) => {
      rosbridgeStatus = next;
    });
    rosbridgeStatus = client.getStatus();
    return () => {
      unsubscribe();
      offStatus();
    };
  });

  $effect(() => {
    if (mounted && sessionId && sessionId !== lastSessionId) {
      lastSessionId = sessionId;
      void resolveSessionBlueprint();
    }
  });

  $effect(() => {
    if (mounted && sessionId && activeBlueprintId) {
      saveBlueprintDraft(BLUEPRINT_KIND, sessionId, activeBlueprintId, blueprint);
    }
  });

  $effect(() => {
    if (!filledDefaults && ($topicsQuery.data?.topics ?? []).length > 0) {
      blueprint = fillDefaultConfig(blueprint, $topicsQuery.data?.topics ?? []);
      filledDefaults = true;
      selectedId = ensureValidSelection(blueprint, selectedId);
    }
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
    const defaults = definition?.defaultConfig?.($topicsQuery.data?.topics ?? []) ?? {};
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

  const toggleEditMode = () => {
    editMode = !editMode;
  };

  const status = $derived(recorderStatus ?? {});
  const datasetId = $derived((status as RecorderStatus)?.dataset_id ?? sessionId);
  const statusState = $derived((status as RecorderStatus)?.state ?? (status as RecorderStatus)?.status ?? '');
  const statusLabel = $derived(STATUS_LABELS[String(statusState)] ?? String(statusState || 'unknown'));
  const statusDetail = $derived((status as RecorderStatus)?.last_error ?? '');
  const taskLabel = $derived((status as RecorderStatus)?.task ?? '');
  const statusPhase = $derived(String((status as RecorderStatus)?.phase ?? 'wait'));

  const episodeIndex = $derived((status as RecorderStatus)?.episode_index ?? null);
  const episodeTotal = $derived(Number((status as RecorderStatus)?.num_episodes ?? 0));
  const episodeTime = $derived(Number((status as RecorderStatus)?.episode_time_s ?? 0));
  const episodeElapsed = $derived(Number((status as RecorderStatus)?.episode_elapsed_s ?? 0));
  const resetTime = $derived(Number((status as RecorderStatus)?.reset_time_s ?? 0));
  const resetElapsed = $derived(Number((status as RecorderStatus)?.reset_elapsed_s ?? 0));

  const timelineMode = $derived(
    statusPhase === 'recording' ? 'recording' : statusPhase === 'reset' ? 'reset' : 'wait'
  );
  const timelineTotal = $derived(timelineMode === 'recording' ? episodeTime : timelineMode === 'reset' ? resetTime : 0);
  const timelineElapsed = $derived(
    timelineMode === 'recording' ? episodeElapsed : timelineMode === 'reset' ? resetElapsed : 0
  );
  const timelineProgress = $derived(
    timelineTotal > 0 ? Math.min(Math.max(timelineElapsed / timelineTotal, 0), 1) : 0
  );
  const timelineLabel = $derived(
    timelineMode === 'recording' ? '録画中' : timelineMode === 'reset' ? 'リセット中' : '待機中'
  );
  const formatSeconds = (value: number) => `${value.toFixed(1)}s`;

  const connectionLabel = $derived(
    rosbridgeStatus === 'connected'
      ? '接続中'
      : rosbridgeStatus === 'connecting'
        ? '接続中...'
        : rosbridgeStatus === 'error'
          ? 'エラー'
          : '切断中'
  );

  const handleReconnect = () => {
    const client = getRosbridgeClient();
    client.connect().catch(() => {
      // ignore; connection status handles UI fallback
    });
  };
</script>

<section class="card-strong p-6">
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="section-title">Record Session</p>
      <h1 class="text-3xl font-semibold text-slate-900">録画セッション</h1>
      <p class="mt-2 text-sm text-slate-600">{taskLabel || 'タスク未設定 / 状態を同期中...'}</p>
      <div class="mt-3 flex flex-wrap gap-2">
        <span class="chip">状態: {statusLabel}</span>
        <span class="chip">接続: {connectionLabel}</span>
        {#if datasetId}
          <span class="chip">Dataset: {datasetId}</span>
        {/if}
      </div>
      {#if rosbridgeStatus !== 'connected'}
        <p class="mt-2 text-xs text-rose-600">rosbridge に接続できません。接続を確認してください。</p>
      {/if}
    </div>
    <div class="flex flex-wrap gap-3">
      <Button.Root class="btn-ghost" type="button" onclick={toggleEditMode}>
        {editMode ? '閲覧モード' : '編集モード'}
      </Button.Root>
      <Button.Root class="btn-ghost" href="/record">録画一覧</Button.Root>
      <Button.Root class="btn-ghost" href="/record/new">新規セッション</Button.Root>
      <Button.Root class="btn-ghost" type="button" onclick={handleReconnect}>再接続</Button.Root>
    </div>
  </div>
</section>

<section class={`grid gap-6 ${editMode ? 'lg:grid-cols-[260px_minmax(0,1fr)_320px]' : 'lg:grid-cols-[minmax(0,1fr)]'}`}>
  {#if editMode}
    <aside class="card p-4">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-semibold text-slate-700">Blueprint</h2>
        <span class="text-[10px] text-slate-400">{selectedNode?.type ?? 'none'}</span>
      </div>
      <div class="mt-3 space-y-3">
        <div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
          <p class="label">保存済みブループリント</p>
          <div class="mt-2">
            <BlueprintCombobox
              items={savedBlueprints}
              value={activeBlueprintId}
              disabled={blueprintBusy || blueprintActionPending}
              onSelect={handleOpenBlueprint}
            />
          </div>
          <p class="mt-2 text-[11px] text-slate-500">編集中の内容はローカルに自動保存されます。</p>

          <label class="mt-3 block text-xs font-semibold text-slate-600">
            <span>名前</span>
            <input class="input mt-1" type="text" bind:value={activeBlueprintName} />
          </label>

          <div class="mt-3 grid grid-cols-2 gap-2">
            <Button.Root
              class="btn-primary"
              type="button"
              disabled={blueprintBusy || blueprintActionPending || !activeBlueprintId}
              onclick={handleSaveBlueprint}
            >
              保存
            </Button.Root>
            <Button.Root
              class="btn-ghost"
              type="button"
              disabled={blueprintBusy || blueprintActionPending || !activeBlueprintId}
              onclick={handleDuplicateBlueprint}
            >
              複製
            </Button.Root>
            <Button.Root
              class="btn-ghost"
              type="button"
              disabled={blueprintBusy || blueprintActionPending || !activeBlueprintId}
              onclick={handleResetBlueprint}
            >
              リセット
            </Button.Root>
            <Button.Root
              class="btn-ghost border-rose-200/70 text-rose-600 hover:border-rose-300/80"
              type="button"
              disabled={blueprintBusy || blueprintActionPending || !activeBlueprintId}
              onclick={handleDeleteBlueprint}
            >
              削除
            </Button.Root>
          </div>

          {#if blueprintBusy || blueprintActionPending}
            <p class="mt-2 text-xs text-slate-500">ブループリント処理中...</p>
          {/if}
          {#if blueprintError}
            <p class="mt-2 text-xs text-rose-600">{blueprintError}</p>
          {/if}
          {#if blueprintNotice}
            <p class="mt-2 text-xs text-emerald-600">{blueprintNotice}</p>
          {/if}
        </div>

        <BlueprintTree node={blueprint} selectedId={selectedId} onSelect={updateSelection} />
      </div>
    </aside>
  {/if}

  <div class="card p-4 min-h-[640px]">
    <LayoutNode
      node={blueprint}
      selectedId={selectedId}
      sessionId={sessionId}
      recorderStatus={recorderStatus}
      rosbridgeStatus={rosbridgeStatus}
      mode="recording"
      editMode={editMode}
      onSelect={updateSelection}
      onResize={handleResize}
      onTabChange={handleTabChange}
    />
  </div>

  {#if editMode}
    <aside class="card p-4">
      <h2 class="text-sm font-semibold text-slate-700">Selection</h2>
      {#if !selectedNode}
        <p class="mt-3 text-xs text-slate-500">選択されていません。</p>
      {:else if selectedNode.type === 'view'}
        <div class="mt-3 space-y-4 text-sm text-slate-700">
          <div>
            <p class="label">View Type</p>
            <select
              class="input mt-2"
              value={selectedViewNode?.viewType}
              onchange={(event) => handleViewTypeChange((event.target as HTMLSelectElement).value)}
            >
              <option value="placeholder">Empty</option>
              {#each getViewOptions() as option}
                <option value={option.type}>{option.label}</option>
              {/each}
            </select>
          </div>

          {#if selectedViewNode}
            {#each getViewDefinition(selectedViewNode.viewType)?.fields ?? [] as field}
              {#if field.type === 'topic'}
                <div>
                  <p class="label">{field.label}</p>
                  <select
                    class="input mt-2"
                    value={(selectedViewNode.config?.[field.key] as string) ?? ''}
                    onchange={(event) => handleConfigChange(field.key, (event.target as HTMLSelectElement).value)}
                  >
                    <option value="">未選択</option>
                    {#each ($topicsQuery.data?.topics ?? []).filter((topic) => field.filter?.(topic) ?? true) as topic}
                      <option value={topic}>{topic}</option>
                    {/each}
                  </select>
                </div>
              {:else if field.type === 'boolean'}
                <label class="flex items-center gap-2 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    class="h-4 w-4 rounded border-slate-300"
                    checked={Boolean(selectedViewNode.config?.[field.key])}
                    onchange={(event) => handleConfigChange(field.key, (event.target as HTMLInputElement).checked)}
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
                    onchange={(event) => handleConfigChange(field.key, Number((event.target as HTMLInputElement).value))}
                  />
                </div>
              {/if}
            {/each}
          {/if}

          <div class="divider"></div>
          <div class="space-y-2">
            <Button.Root class="btn-ghost w-full" type="button" onclick={() => handleSplit('row')}>横分割</Button.Root>
            <Button.Root class="btn-ghost w-full" type="button" onclick={() => handleSplit('column')}>縦分割</Button.Root>
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
        <div class="mt-3 space-y-4 text-sm text-slate-700">
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
        <div class="mt-3 space-y-4 text-sm text-slate-700">
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
                <Button.Root class="btn-ghost mt-2 w-full" type="button" onclick={() => handleRemoveTab(tab.id)}>
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
    </aside>
  {/if}
</section>

<section class="card p-4">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <p class="label">Timeline</p>
      <p class="text-sm font-semibold text-slate-700">録画タイムライン</p>
      <p class="mt-1 text-xs text-slate-500">{timelineLabel}</p>
    </div>
    <div class="text-xs text-slate-500">
      {#if episodeIndex != null}
        エピソード {episodeIndex + 1}{episodeTotal ? ` / ${episodeTotal}` : ''}
      {:else}
        エピソード待機中
      {/if}
    </div>
  </div>
  <div class="mt-3">
    <div class="h-3 w-full overflow-hidden rounded-full bg-slate-200/70">
      <div
        class={`h-full rounded-full ${timelineMode === 'reset' ? 'bg-amber-400' : 'bg-brand'}`}
        style={`width:${(timelineProgress * 100).toFixed(1)}%`}
      ></div>
    </div>
    <div class="mt-2 flex justify-between text-[10px] text-slate-500">
      <span>{formatSeconds(timelineElapsed)}</span>
      <span>{formatSeconds(timelineTotal)}</span>
    </div>
  </div>
  {#if statusDetail}
    <p class="mt-2 text-xs text-slate-500">{statusDetail}</p>
  {/if}
</section>

<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { Dialog, Tabs } from 'bits-ui';
  import FunnelSimple from 'phosphor-svelte/lib/FunnelSimple';

  import { api, type TabSessionSubscription } from '$lib/api/client';
  import type {
    BuildJobSummary,
    BuildLogEvent,
    BuildSettingSummary,
    BuildsStatusSnapshot,
  } from '$lib/api/client';
  import ProfileTab from '$lib/components/system/ProfileTab.svelte';
  import RuntimeTab from '$lib/components/system/RuntimeTab.svelte';
  import SettingsTab from '$lib/components/system/SettingsTab.svelte';
  import SystemStatusTab from '$lib/components/system/SystemStatusTab.svelte';
  import { registerTabRealtimeContributor, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';
  import {
    buildSystemTabHref,
    normalizeSystemTab,
    reconcileSystemTabState,
    type SystemTab
  } from '$lib/system/systemTabRouting';
  import type { BundledTorchBuildSnapshot } from '$lib/types/bundledTorch';
  import type { FeaturesRepoSuggestions, SystemSettings, UserSettings } from '$lib/types/settings';
  import type { HealthLevel, SystemStatusSnapshot } from '$lib/types/systemStatus';

  type OperateNetworkStatus = {
    status?: string;
    message?: string;
    details?: {
      zmq?: { status?: string; message?: string; endpoint?: string };
      zenoh?: { status?: string; message?: string };
      rosbridge?: { status?: string; message?: string };
    };
  };

  type OperateStatusRealtimePayload = {
    operate_status?: {
      network?: OperateNetworkStatus;
    };
  };

  type OperateStatusResponse = {
    network?: OperateNetworkStatus;
  };

  const RUNTIME_BUILD_FILTER_STORAGE_KEY = 'runtime-build-filter:v1';

  type RuntimeBuildFilterStorage = {
    showUnsupported?: boolean;
    hiddenSettingIds?: string[];
  };

  const loadRuntimeBuildFilterStorage = (): RuntimeBuildFilterStorage | null => {
    if (!browser || typeof localStorage === 'undefined') return null;
    const raw = localStorage.getItem(RUNTIME_BUILD_FILTER_STORAGE_KEY);
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as RuntimeBuildFilterStorage;
      return {
        showUnsupported: Boolean(parsed.showUnsupported),
        hiddenSettingIds: Array.isArray(parsed.hiddenSettingIds)
          ? parsed.hiddenSettingIds.filter((value): value is string => typeof value === 'string')
          : []
      };
    } catch {
      localStorage.removeItem(RUNTIME_BUILD_FILTER_STORAGE_KEY);
      return null;
    }
  };

  const saveRuntimeBuildFilterStorage = (value: RuntimeBuildFilterStorage) => {
    if (!browser || typeof localStorage === 'undefined') return;
    localStorage.setItem(RUNTIME_BUILD_FILTER_STORAGE_KEY, JSON.stringify(value));
  };

  let activeTab = $state<SystemTab>(normalizeSystemTab(page.url.searchParams.get('tab')));
  let systemStatusSnapshot = $state<SystemStatusSnapshot | null>(null);
  let networkStatus = $state<OperateNetworkStatus | null>(null);
  let bundledTorchSnapshot = $state<BundledTorchBuildSnapshot | null>(null);
  let systemSettings = $state<SystemSettings | null>(null);
  let featuresRepoSuggestions = $state<FeaturesRepoSuggestions | null>(null);
  let featuresRepoSuggestionsPending = $state(false);
  let userSettings = $state<UserSettings | null>(null);
  let buildLoading = $state(false);
  let buildLoadError = $state('');
  let buildCurrentPlatform = $state('');
  let buildCurrentSm = $state('');
  let envBuildItems = $state<BuildSettingSummary[]>([]);
  let sharedBuildItems = $state<BuildSettingSummary[]>([]);
  let runningBuildJobs = $state<BuildJobSummary[]>([]);
  let selectedBuildConfigId = $state('');
  let buildActionPending = $state<Record<string, boolean>>({});
  let buildLogLinesByJobId = $state<Record<string, string[]>>({});
  let runtimeHiddenBuildSettingIds = $state<string[]>([]);
  let runtimeShowUnsupported = $state(false);
  let runtimeFilterOpen = $state(false);
  let runtimeFilterPrefsReady = $state(false);
  let runtimeBuildItemsReady = $state(false);
  let systemSettingsPending = $state(false);
  let systemSettingsError = $state('');
  let systemSettingsSuccess = $state('');
  let userSettingsPending = $state(false);
  let userSettingsError = $state('');
  let userSettingsSuccess = $state('');
  let featuresRepoSuggestionsAbort = $state<AbortController | null>(null);
  let pendingTabNavigation = $state<SystemTab | null>(null);

  $effect(() => {
    const nextState = reconcileSystemTabState({
      activeTab,
      urlTab: normalizeSystemTab(page.url.searchParams.get('tab')),
      pendingTabNavigation
    });

    if (nextState.pendingTabNavigation !== pendingTabNavigation) {
      pendingTabNavigation = nextState.pendingTabNavigation;
    }
    if (nextState.activeTab !== activeTab) {
      activeTab = nextState.activeTab;
    }
  });

  const handleTabChange = (nextValue: string) => {
    const nextTab = normalizeSystemTab(nextValue);
    if (nextTab === activeTab) {
      return;
    }

    activeTab = nextTab;
    pendingTabNavigation = nextTab;

    void goto(buildSystemTabHref(page.url, nextTab), {
      keepFocus: true,
      noScroll: true,
      invalidateAll: false
    }).catch(() => {
      pendingTabNavigation = null;
    });
  };

  const renderStatusLabel = (value?: string) => {
    switch (value) {
      case 'running':
      case 'healthy':
      case 'available':
      case 'completed':
        return '正常';
      case 'degraded':
      case 'partial':
      case 'cleaning':
      case 'building':
        return '注意';
      case 'stopped':
      case 'idle':
        return '停止';
      case 'error':
      case 'failed':
        return 'エラー';
      default:
        return '不明';
    }
  };

  const renderLevelClass = (level?: HealthLevel | string) => {
    switch (level) {
      case 'healthy':
      case 'completed':
      case 'running':
        return 'border-emerald-200 bg-emerald-50 text-emerald-700';
      case 'degraded':
      case 'building':
      case 'cleaning':
      case 'partial':
        return 'border-amber-200 bg-amber-50 text-amber-700';
      case 'error':
      case 'failed':
        return 'border-rose-200 bg-rose-50 text-rose-700';
      default:
        return 'border-slate-200 bg-slate-100 text-slate-600';
    }
  };

  const loadInitialState = async () => {
    buildLoading = true;
    buildLoadError = '';
    const [bundledResult, operateResult, systemSettingsResult, userSettingsResult, envBuildsResult, sharedBuildsResult] = await Promise.allSettled([
      api.system.bundledTorchStatus(),
      api.operate.status(),
      api.system.settings(),
      api.user.settings(),
      api.builds.envs(),
      api.builds.shared()
    ]);

    if (bundledResult.status === 'fulfilled') {
      bundledTorchSnapshot = bundledResult.value;
    }

    if (operateResult.status === 'fulfilled') {
      networkStatus = (operateResult.value as OperateStatusResponse | null)?.network ?? null;
    }

    if (systemSettingsResult.status === 'fulfilled') {
      systemSettings = systemSettingsResult.value;
    } else {
      systemSettingsError =
        systemSettingsResult.reason instanceof Error ? systemSettingsResult.reason.message : 'system settings の取得に失敗しました。';
    }

    if (userSettingsResult.status === 'fulfilled') {
      userSettings = userSettingsResult.value;
    } else {
      userSettingsError =
        userSettingsResult.reason instanceof Error ? userSettingsResult.reason.message : 'user settings の取得に失敗しました。';
    }

    if (envBuildsResult.status === 'fulfilled' && sharedBuildsResult.status === 'fulfilled') {
      selectedBuildConfigId = envBuildsResult.value.selected_config_id ?? '';
      buildCurrentPlatform =
        envBuildsResult.value.current_platform ?? sharedBuildsResult.value.current_platform ?? '';
      buildCurrentSm = envBuildsResult.value.current_sm ?? sharedBuildsResult.value.current_sm ?? '';
      envBuildItems = envBuildsResult.value.items;
      sharedBuildItems = sharedBuildsResult.value.items;
      runningBuildJobs = [...envBuildsResult.value.items, ...sharedBuildsResult.value.items]
        .filter((item) => item.state === 'building' && item.current_job_id)
        .map((item) => ({
          job_id: item.current_job_id ?? '',
          build_id: item.latest_build_id ?? '',
          kind: item.kind,
          setting_id: item.setting_id,
          state: 'running',
          current_step_name: item.current_step_name ?? null,
          current_step_index: item.current_step_index ?? 0,
          total_steps: item.total_steps ?? 0,
          progress_percent: item.progress_percent ?? 0,
          created_at: item.latest_started_at ?? new Date().toISOString(),
          updated_at: item.latest_started_at ?? new Date().toISOString()
        }));
    } else {
      buildLoadError =
        envBuildsResult.status === 'rejected'
          ? envBuildsResult.reason instanceof Error
            ? envBuildsResult.reason.message
            : '構築状態の取得に失敗しました。'
          : sharedBuildsResult.status === 'rejected'
            ? sharedBuildsResult.reason instanceof Error
              ? sharedBuildsResult.reason.message
              : '構築状態の取得に失敗しました。'
            : '';
    }

    buildLoading = false;
    runtimeBuildItemsReady = true;
  };

  const applyBuildsSnapshot = (snapshot: BuildsStatusSnapshot) => {
    buildCurrentPlatform =
      snapshot.current_platform ?? snapshot.envs.current_platform ?? snapshot.shared.current_platform ?? '';
    buildCurrentSm = snapshot.current_sm ?? snapshot.envs.current_sm ?? snapshot.shared.current_sm ?? '';
    selectedBuildConfigId = snapshot.envs.selected_config_id ?? '';
    envBuildItems = snapshot.envs.items;
    sharedBuildItems = snapshot.shared.items;
    runningBuildJobs = snapshot.running_jobs;
    runtimeBuildItemsReady = true;
    const activeJobIds = new Set(snapshot.running_jobs.map((job) => job.job_id));
    buildLogLinesByJobId = Object.fromEntries(
      Object.entries(buildLogLinesByJobId).filter(([jobId]) => activeJobIds.has(jobId))
    );
  };

  const allRuntimeBuildItems = $derived([...envBuildItems, ...sharedBuildItems]);
  const allRuntimeBuildSettingIds = $derived(allRuntimeBuildItems.map((item) => item.setting_id));
  const hasCurrentPlatformSpecificMatches = $derived(
    allRuntimeBuildItems.some(
      (item) => (item.supported_platforms?.length ?? 0) > 0 && item.platform_supported === true
    )
  );
  const isRuntimeSettingSupportedVisible = (item: BuildSettingSummary) => {
    if (runtimeShowUnsupported) {
      return true;
    }
    if (item.sm_supported === false) {
      return false;
    }
    if (hasCurrentPlatformSpecificMatches && (item.supported_platforms?.length ?? 0) > 0) {
      return item.platform_supported !== false;
    }
    return true;
  };
  const runtimeSmVisibleSettingIds = $derived(
    allRuntimeBuildItems.filter((item) => isRuntimeSettingSupportedVisible(item)).map((item) => item.setting_id)
  );
  const runtimeVisibleBuildItems = $derived(
    allRuntimeBuildItems.filter(
      (item) => isRuntimeSettingSupportedVisible(item) && !runtimeHiddenBuildSettingIds.includes(item.setting_id)
    )
  );
  const runtimeVisibleSettingCount = $derived(runtimeVisibleBuildItems.length);
  const runtimeAllVisible = $derived(
    runtimeSmVisibleSettingIds.every((settingId) => !runtimeHiddenBuildSettingIds.includes(settingId))
  );
  const filteredEnvBuildItems = $derived(
    envBuildItems.filter(
      (item) => isRuntimeSettingSupportedVisible(item) && !runtimeHiddenBuildSettingIds.includes(item.setting_id)
    )
  );
  const filteredSharedBuildItems = $derived(
    sharedBuildItems.filter(
      (item) => isRuntimeSettingSupportedVisible(item) && !runtimeHiddenBuildSettingIds.includes(item.setting_id)
    )
  );
  const runtimeEnvFilterItems = $derived(
    envBuildItems.filter((item) => item.usage !== 'training' && isRuntimeSettingSupportedVisible(item))
  );
  const trainingEnvFilterItems = $derived(
    envBuildItems.filter((item) => item.usage === 'training' && isRuntimeSettingSupportedVisible(item))
  );

  $effect(() => {
    if (!runtimeBuildItemsReady) {
      return;
    }
    const validIds = new Set(allRuntimeBuildSettingIds);
    const nextHiddenSettingIds = runtimeHiddenBuildSettingIds.filter((settingId) => validIds.has(settingId));
    if (
      nextHiddenSettingIds.length === runtimeHiddenBuildSettingIds.length &&
      nextHiddenSettingIds.every((settingId, index) => settingId === runtimeHiddenBuildSettingIds[index])
    ) {
      return;
    }
    runtimeHiddenBuildSettingIds = nextHiddenSettingIds;
  });

  $effect(() => {
    if (!browser || !runtimeFilterPrefsReady) {
      return;
    }
    saveRuntimeBuildFilterStorage({
      showUnsupported: runtimeShowUnsupported,
      hiddenSettingIds: runtimeHiddenBuildSettingIds
    });
  });

  const isRuntimeSettingVisible = (settingId: string) => !runtimeHiddenBuildSettingIds.includes(settingId);
  const toggleRuntimeSettingVisible = (settingId: string, nextVisible: boolean) => {
    runtimeHiddenBuildSettingIds = nextVisible
      ? runtimeHiddenBuildSettingIds.filter((value) => value !== settingId)
      : [...runtimeHiddenBuildSettingIds, settingId];
  };
  const toggleAllRuntimeSettings = () => {
    if (runtimeAllVisible) {
      const smVisibleIds = new Set(runtimeSmVisibleSettingIds);
      const nextHiddenSettingIds = new Set(runtimeHiddenBuildSettingIds);
      for (const settingId of smVisibleIds) {
        nextHiddenSettingIds.add(settingId);
      }
      runtimeHiddenBuildSettingIds = [...nextHiddenSettingIds];
      return;
    }

    const smVisibleIds = new Set(runtimeSmVisibleSettingIds);
    runtimeHiddenBuildSettingIds = runtimeHiddenBuildSettingIds.filter((settingId) => !smVisibleIds.has(settingId));
  };

  const appendBuildLogEvents = (events: BuildLogEvent[]) => {
    const next = { ...buildLogLinesByJobId };
    for (const event of events) {
      const line = `${event.stream === 'stderr' ? '[stderr] ' : ''}${event.line.trim()}`.trim();
      const current = next[event.job_id] ?? [];
      next[event.job_id] = [...current, line].slice(-100);
    }
    buildLogLinesByJobId = next;
  };

  const setBuildActionPending = (key: string, value: boolean) => {
    buildActionPending = {
      ...buildActionPending,
      [key]: value
    };
  };

  const triggerBuildRun = async (item: BuildSettingSummary) => {
    setBuildActionPending(item.setting_id, true);
    try {
      if (item.kind === 'env' && item.config_id && item.env_name) {
        await api.builds.runEnv(item.config_id, item.env_name);
      } else if (item.kind === 'shared' && item.package && item.variant) {
        await api.builds.runShared(item.package, item.variant);
      }
    } catch (error) {
      buildLoadError = error instanceof Error ? error.message : '構築の開始に失敗しました。';
    } finally {
      setBuildActionPending(item.setting_id, false);
    }
  };

  const triggerBuildCancelByJobId = async (jobId: string, settingId?: string) => {
    setBuildActionPending(settingId ?? jobId, true);
    try {
      await api.builds.cancelJob(jobId);
    } catch (error) {
      buildLoadError = error instanceof Error ? error.message : '中止に失敗しました。';
    } finally {
      setBuildActionPending(settingId ?? jobId, false);
    }
  };

  const triggerBuildDelete = async (item: BuildSettingSummary) => {
    const buildId = item.current_build_id ?? item.latest_build_id;
    if (!buildId) {
      return;
    }
    setBuildActionPending(item.setting_id, true);
    try {
      if (item.kind === 'env' && item.config_id && item.env_name) {
        await api.builds.deleteEnvArtifact(item.config_id, item.env_name, buildId);
      } else if (item.kind === 'shared' && item.package && item.variant) {
        await api.builds.deleteSharedArtifact(item.package, item.variant, buildId);
      }
    } catch (error) {
      buildLoadError = error instanceof Error ? error.message : '削除に失敗しました。';
    } finally {
      setBuildActionPending(item.setting_id, false);
    }
  };

  const saveSystemSettings = async (payload: {
    pytorchVersion: string;
    torchvisionVersion: string;
    repoUrl: string;
    repoRef: string;
    repoCommit?: string;
  }) => {
    systemSettingsPending = true;
    systemSettingsError = '';
    systemSettingsSuccess = '';
    try {
      systemSettings = await api.system.updateSettings({
        bundled_torch: {
          pytorch_version: payload.pytorchVersion.trim(),
          torchvision_version: payload.torchvisionVersion.trim()
        },
        features_repo: {
          repo_url: payload.repoUrl.trim(),
          repo_ref: payload.repoRef.trim(),
          repo_commit: payload.repoCommit?.trim() || null
        }
      });
      systemSettingsSuccess = 'system settings を更新しました。';
    } catch (error) {
      systemSettingsError =
        error instanceof Error ? error.message : 'system settings の更新に失敗しました。';
    } finally {
      systemSettingsPending = false;
    }
  };

  const refreshFeaturesRepoSuggestions = async (payload: { repoUrl: string; repoRef?: string }) => {
    const repoUrl = payload.repoUrl.trim();
    if (!repoUrl) {
      featuresRepoSuggestionsAbort?.abort();
      featuresRepoSuggestionsAbort = null;
      featuresRepoSuggestionsPending = false;
      featuresRepoSuggestions = null;
      return;
    }
    featuresRepoSuggestionsAbort?.abort();
    const controller = new AbortController();
    featuresRepoSuggestionsAbort = controller;
    featuresRepoSuggestionsPending = true;
    try {
      featuresRepoSuggestions = await api.system.featuresRepoSuggestions({
        repo_url: repoUrl,
        repo_ref: payload.repoRef?.trim() || undefined,
        signal: controller.signal
      });
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      systemSettingsError =
        error instanceof Error ? error.message : 'features repo 候補の取得に失敗しました。';
    } finally {
      if (featuresRepoSuggestionsAbort === controller) {
        featuresRepoSuggestionsAbort = null;
        featuresRepoSuggestionsPending = false;
      }
    }
  };

  $effect(() => {
    if (
      activeTab !== 'settings' ||
      !systemSettings?.features_repo?.repo_url ||
      featuresRepoSuggestionsPending ||
      featuresRepoSuggestions
    ) {
      return;
    }
    void refreshFeaturesRepoSuggestions({
      repoUrl: systemSettings.features_repo.repo_url,
      repoRef: systemSettings.features_repo.repo_ref
    });
  });

  const saveUserSettings = async (payload: {
    username?: string;
    firstName?: string;
    lastName?: string;
    huggingfaceToken?: string;
    clear?: boolean;
  }) => {
    userSettingsPending = true;
    userSettingsError = '';
    userSettingsSuccess = '';
    try {
      userSettings = await api.user.updateSettings({
        username: payload.username !== undefined ? payload.username.trim() : undefined,
        first_name: payload.firstName !== undefined ? payload.firstName.trim() : undefined,
        last_name: payload.lastName !== undefined ? payload.lastName.trim() : undefined,
        huggingface_token: payload.clear
          ? null
          : payload.huggingfaceToken !== undefined
            ? payload.huggingfaceToken.trim()
            : undefined,
        clear_huggingface_token: Boolean(payload.clear)
      });
      userSettingsSuccess = payload.clear
        ? 'HF token を削除しました。'
        : payload.huggingfaceToken !== undefined
          ? 'HF token を更新しました。'
          : 'ユーザープロフィールを更新しました。';
    } catch (error) {
      userSettingsError =
        error instanceof Error ? error.message : 'user settings の更新に失敗しました。';
    } finally {
      userSettingsPending = false;
    }
  };

  const buildRealtimeSubscriptions = (tab: SystemTab): TabSessionSubscription[] => {
    if (tab === 'status') {
      return [
        { subscription_id: 'system.page.status', kind: 'system.status', params: {} },
        { subscription_id: 'system.page.operate', kind: 'operate.status', params: {} }
      ];
    }
    if (tab === 'runtime') {
      return [
        { subscription_id: 'system.page.bundled-torch', kind: 'system.bundled-torch', params: {} },
        { subscription_id: 'system.page.builds-status', kind: 'builds.status', params: {} },
        { subscription_id: 'system.page.builds-logs', kind: 'builds.logs', params: {} }
      ];
    }
    return [];
  };

  const handleRealtimeEvent = (event: TabRealtimeEvent) => {
    if (event.source?.kind === 'builds.logs' && event.op === 'append') {
      appendBuildLogEvents(((event.payload as { events?: BuildLogEvent[] }).events ?? []) as BuildLogEvent[]);
      return;
    }
    if (event.op !== 'snapshot') return;
    switch (event.source?.kind) {
      case 'system.status':
        systemStatusSnapshot = event.payload as SystemStatusSnapshot;
        return;
      case 'operate.status': {
        const payload = event.payload as OperateStatusRealtimePayload;
        networkStatus = payload.operate_status?.network ?? null;
        return;
      }
      case 'system.bundled-torch':
        bundledTorchSnapshot = event.payload as BundledTorchBuildSnapshot;
        return;
      case 'builds.status':
        applyBuildsSnapshot(event.payload as BuildsStatusSnapshot);
        return;
    }
  };

  let realtimeContributor: TabRealtimeContributorHandle | null = null;

  onMount(() => {
    const persistedRuntimeFilter = loadRuntimeBuildFilterStorage();
    if (persistedRuntimeFilter) {
      runtimeShowUnsupported = Boolean(persistedRuntimeFilter.showUnsupported);
      runtimeHiddenBuildSettingIds = persistedRuntimeFilter.hiddenSettingIds ?? [];
    }
    runtimeFilterPrefsReady = true;
    void loadInitialState();

    return () => {
      realtimeContributor?.dispose();
      realtimeContributor = null;
      featuresRepoSuggestionsAbort?.abort();
      featuresRepoSuggestionsAbort = null;
      featuresRepoSuggestionsPending = false;
    };
  });

  $effect(() => {
    if (!browser) {
      return;
    }

    if (realtimeContributor === null) {
      realtimeContributor = registerTabRealtimeContributor({
        subscriptions: buildRealtimeSubscriptions(activeTab),
        onEvent: handleRealtimeEvent
      });
      if (!realtimeContributor) {
        return;
      }
      return;
    }

    realtimeContributor.setEventHandler(handleRealtimeEvent);
    realtimeContributor.setSubscriptions(buildRealtimeSubscriptions(activeTab));
  });
</script>

<section class="card-strong p-8">
  <p class="section-title">System</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">システム</h1>
      <p class="mt-2 text-sm text-slate-600">
        監視、プロファイル、bundled-torch、設定を一箇所で管理します。
      </p>
    </div>
    <div class="flex flex-wrap gap-2">
      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(systemStatusSnapshot?.overall?.level)}`}>
        {renderStatusLabel(systemStatusSnapshot?.overall?.level)}
      </span>
      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${renderLevelClass(bundledTorchSnapshot?.state)}`}>
        bundled-torch: {renderStatusLabel(bundledTorchSnapshot?.state)}
      </span>
    </div>
  </div>
</section>

<section class="card p-6">
  <Tabs.Root value={activeTab} onValueChange={handleTabChange}>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <Tabs.List class="inline-grid grid-cols-2 gap-1 rounded-full border border-slate-200/70 bg-slate-100/80 p-1 md:grid-cols-4">
        <Tabs.Trigger value="status" class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm">
          Status
        </Tabs.Trigger>
        <Tabs.Trigger value="profile" class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm">
          Profile
        </Tabs.Trigger>
        <Tabs.Trigger value="runtime" class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm">
          Runtime
        </Tabs.Trigger>
        <Tabs.Trigger value="settings" class="rounded-full px-4 py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm">
          Settings
        </Tabs.Trigger>
      </Tabs.List>

      {#if activeTab === 'runtime' && allRuntimeBuildItems.length > 0}
        <div class="flex flex-wrap items-center justify-end gap-3">
          {#if buildCurrentSm}
            <span class="chip">現在のSM: {buildCurrentSm}</span>
          {/if}
          <button
            class="btn-ghost inline-flex items-center gap-2"
            type="button"
            onclick={() => {
              runtimeFilterOpen = true;
            }}
          >
              <FunnelSimple size={16} />
              フィルタ
              <span class="text-xs text-slate-500">{runtimeVisibleSettingCount}/{allRuntimeBuildItems.length}</span>
          </button>
        </div>
      {/if}
    </div>

    <Tabs.Content value="status" class="mt-6 space-y-6">
      {#if activeTab === 'status'}
        <SystemStatusTab snapshot={systemStatusSnapshot} network={networkStatus} />
      {/if}
    </Tabs.Content>

    <Tabs.Content value="profile" class="mt-6 space-y-6">
      {#if activeTab === 'profile'}
        <ProfileTab />
      {/if}
    </Tabs.Content>

    <Tabs.Content value="runtime" class="mt-6 space-y-6">
      {#if activeTab === 'runtime'}
        <RuntimeTab
          buildLoading={buildLoading}
          buildLoadError={buildLoadError}
                    buildCurrentPlatform={buildCurrentPlatform}
                    buildCurrentSm={buildCurrentSm}
          envBuildItems={filteredEnvBuildItems}
          sharedBuildItems={filteredSharedBuildItems}
          runningBuildJobs={runningBuildJobs}
          buildActionPending={buildActionPending}
          buildLogLinesByJobId={buildLogLinesByJobId}
          onBuildRun={triggerBuildRun}
          onBuildCancelByJobId={triggerBuildCancelByJobId}
          onBuildDelete={triggerBuildDelete}
        />
      {/if}
    </Tabs.Content>

    <Tabs.Content value="settings" class="mt-6 space-y-6">
      {#if activeTab === 'settings'}
        <SettingsTab
          systemSettings={systemSettings}
          userSettings={userSettings}
          featuresRepoSuggestions={featuresRepoSuggestions}
          featuresRepoSuggestionsPending={featuresRepoSuggestionsPending}
          systemPending={systemSettingsPending}
          userPending={userSettingsPending}
          systemError={systemSettingsError}
          userError={userSettingsError}
          systemSuccess={systemSettingsSuccess}
          userSuccess={userSettingsSuccess}
          onSaveSystemSettings={saveSystemSettings}
          onSaveUserSettings={saveUserSettings}
          onRefreshFeaturesRepoSuggestions={refreshFeaturesRepoSuggestions}
        />
      {/if}
    </Tabs.Content>
  </Tabs.Root>
</section>

<Dialog.Root bind:open={runtimeFilterOpen}>
  <Dialog.Portal>
    <Dialog.Overlay class="fixed inset-0 z-40 bg-slate-900/30 backdrop-blur-[1px]" />
    <Dialog.Content
      class="fixed inset-y-0 right-0 z-50 flex w-[min(92vw,30rem)] flex-col border-l border-slate-200 bg-white shadow-2xl outline-none"
    >
      <div class="border-b border-slate-200 px-5 py-4">
        <div class="flex items-start justify-between gap-4">
          <div>
            <Dialog.Title class="text-base font-semibold text-slate-900">表示フィルタ</Dialog.Title>
            <Dialog.Description class="mt-1 text-sm text-slate-600">
              Runtime に表示する設定を絞り込みます。
            </Dialog.Description>
          </div>
          <button
            class="inline-flex h-10 items-center justify-center rounded-full border border-slate-200 px-4 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
            type="button"
            onclick={() => {
              runtimeFilterOpen = false;
            }}
          >
            閉じる
          </button>
        </div>
      </div>

      <div class="border-b border-slate-200 px-5 py-4">
        <label class="flex items-center justify-between gap-4 rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-3">
          <div class="min-w-0">
            <p class="text-sm font-semibold text-slate-900">現在の環境に対応のみ</p>
          </div>
          <button
            class={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition ${
              runtimeShowUnsupported ? 'bg-slate-300' : 'bg-brand'
            }`}
            type="button"
            role="switch"
            aria-checked={!runtimeShowUnsupported}
            aria-label="現在の環境に対応のみを切り替え"
            onclick={() => {
              runtimeShowUnsupported = !runtimeShowUnsupported;
            }}
          >
            <span
              class={`inline-block h-5 w-5 transform rounded-full bg-white shadow-sm transition ${
                runtimeShowUnsupported ? 'translate-x-1' : 'translate-x-6'
              }`}
            ></span>
          </button>
        </label>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        <div class="space-y-6">
          <section>
            <div class="flex items-center justify-between gap-3">
              <h4 class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">実行環境</h4>
              <div class="flex items-center gap-3">
                <button class="text-xs font-semibold text-brand transition hover:text-brand-ink" type="button" onclick={() => {
                  for (const item of runtimeEnvFilterItems) {
                    if (!isRuntimeSettingVisible(item.setting_id)) {
                      toggleRuntimeSettingVisible(item.setting_id, true);
                    }
                  }
                }}>
                  すべて選択
                </button>
                <button class="text-xs font-semibold text-slate-500 transition hover:text-slate-700" type="button" onclick={() => {
                  for (const item of runtimeEnvFilterItems) {
                    if (isRuntimeSettingVisible(item.setting_id)) {
                      toggleRuntimeSettingVisible(item.setting_id, false);
                    }
                  }
                }}>
                  すべて解除
                </button>
              </div>
            </div>
            <div class="mt-3 space-y-2">
              {#each runtimeEnvFilterItems as item (item.setting_id)}
                <label class="flex cursor-pointer items-start gap-3 rounded-2xl border border-slate-200/80 px-3 py-3 transition hover:border-slate-300 hover:bg-slate-50">
                  <input
                    class="mt-1 h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
                    type="checkbox"
                    checked={isRuntimeSettingVisible(item.setting_id)}
                    onchange={(event) => toggleRuntimeSettingVisible(item.setting_id, event.currentTarget.checked)}
                  />
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium text-slate-900">{item.display_name}</p>
                    <p class="mt-1 truncate text-xs leading-5 text-slate-500">{item.description ?? item.env_name ?? item.setting_id}</p>
                  </div>
                </label>
              {/each}
            </div>
          </section>

          <section>
            <div class="flex items-center justify-between gap-3">
              <h4 class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">学習環境</h4>
              <div class="flex items-center gap-3">
                <button class="text-xs font-semibold text-brand transition hover:text-brand-ink" type="button" onclick={() => {
                  for (const item of trainingEnvFilterItems) {
                    if (!isRuntimeSettingVisible(item.setting_id)) {
                      toggleRuntimeSettingVisible(item.setting_id, true);
                    }
                  }
                }}>
                  すべて選択
                </button>
                <button class="text-xs font-semibold text-slate-500 transition hover:text-slate-700" type="button" onclick={() => {
                  for (const item of trainingEnvFilterItems) {
                    if (isRuntimeSettingVisible(item.setting_id)) {
                      toggleRuntimeSettingVisible(item.setting_id, false);
                    }
                  }
                }}>
                  すべて解除
                </button>
              </div>
            </div>
            <div class="mt-3 space-y-2">
              {#each trainingEnvFilterItems as item (item.setting_id)}
                <label class="flex cursor-pointer items-start gap-3 rounded-2xl border border-slate-200/80 px-3 py-3 transition hover:border-slate-300 hover:bg-slate-50">
                  <input
                    class="mt-1 h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
                    type="checkbox"
                    checked={isRuntimeSettingVisible(item.setting_id)}
                    onchange={(event) => toggleRuntimeSettingVisible(item.setting_id, event.currentTarget.checked)}
                  />
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium text-slate-900">{item.display_name}</p>
                    <p class="mt-1 truncate text-xs leading-5 text-slate-500">{item.description ?? item.env_name ?? item.setting_id}</p>
                  </div>
                </label>
              {/each}
            </div>
          </section>

          <section>
            <div class="flex items-center justify-between gap-3">
              <h4 class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">共有パッケージ</h4>
              <div class="flex items-center gap-3">
                <button class="text-xs font-semibold text-brand transition hover:text-brand-ink" type="button" onclick={() => {
                  for (const item of sharedBuildItems.filter((entry) => isRuntimeSettingSupportedVisible(entry))) {
                    if (!isRuntimeSettingVisible(item.setting_id)) {
                      toggleRuntimeSettingVisible(item.setting_id, true);
                    }
                  }
                }}>
                  すべて選択
                </button>
                <button class="text-xs font-semibold text-slate-500 transition hover:text-slate-700" type="button" onclick={() => {
                  for (const item of sharedBuildItems.filter((entry) => isRuntimeSettingSupportedVisible(entry))) {
                    if (isRuntimeSettingVisible(item.setting_id)) {
                      toggleRuntimeSettingVisible(item.setting_id, false);
                    }
                  }
                }}>
                  すべて解除
                </button>
              </div>
            </div>
            <div class="mt-3 space-y-2">
              {#each sharedBuildItems.filter((item) => isRuntimeSettingSupportedVisible(item)) as item (item.setting_id)}
                <label class="flex cursor-pointer items-start gap-3 rounded-2xl border border-slate-200/80 px-3 py-3 transition hover:border-slate-300 hover:bg-slate-50">
                  <input
                    class="mt-1 h-4 w-4 rounded border-slate-300 text-brand focus:ring-brand"
                    type="checkbox"
                    checked={isRuntimeSettingVisible(item.setting_id)}
                    onchange={(event) => toggleRuntimeSettingVisible(item.setting_id, event.currentTarget.checked)}
                  />
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium text-slate-900">{item.package ?? item.display_name}</p>
                    <p class="mt-1 truncate text-xs leading-5 text-slate-500">{item.description ?? item.variant ?? item.setting_id}</p>
                  </div>
                </label>
              {/each}
            </div>
          </section>
        </div>
      </div>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

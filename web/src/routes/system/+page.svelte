<script lang="ts">
  import { browser } from '$app/environment';
  import { afterNavigate, goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { Tabs } from 'bits-ui';

  import { api, type TabSessionSubscription } from '$lib/api/client';
  import ProfileTab from '$lib/components/system/ProfileTab.svelte';
  import RuntimeTab from '$lib/components/system/RuntimeTab.svelte';
  import SettingsTab from '$lib/components/system/SettingsTab.svelte';
  import SystemStatusTab from '$lib/components/system/SystemStatusTab.svelte';
  import { registerTabRealtimeContributor, type TabRealtimeContributorHandle, type TabRealtimeEvent } from '$lib/realtime/tabSessionClient';
  import type { BundledTorchBuildSnapshot } from '$lib/types/bundledTorch';
  import type { RuntimeEnvSnapshot } from '$lib/types/runtimeEnv';
  import type { FeaturesRepoSuggestions, SystemSettings, UserSettings } from '$lib/types/settings';
  import type { HealthLevel, SystemStatusSnapshot } from '$lib/types/systemStatus';

  type SystemTab = 'status' | 'profile' | 'runtime' | 'settings';

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

  const TABS: SystemTab[] = ['status', 'profile', 'runtime', 'settings'];

  const normalizeTab = (value: string | null | undefined): SystemTab => {
    if (value && TABS.includes(value as SystemTab)) {
      return value as SystemTab;
    }
    return 'status';
  };

  let activeTab = $state<SystemTab>(normalizeTab(page.url.searchParams.get('tab')));
  let systemStatusSnapshot = $state<SystemStatusSnapshot | null>(null);
  let networkStatus = $state<OperateNetworkStatus | null>(null);
  let bundledTorchSnapshot = $state<BundledTorchBuildSnapshot | null>(null);
  let runtimeEnvSnapshot = $state<RuntimeEnvSnapshot | null>(null);
  let systemSettings = $state<SystemSettings | null>(null);
  let featuresRepoSuggestions = $state<FeaturesRepoSuggestions | null>(null);
  let featuresRepoSuggestionsPending = $state(false);
  let userSettings = $state<UserSettings | null>(null);
  let bundledTorchActionPending = $state(false);
  let bundledTorchActionError = $state('');
  let runtimeEnvActionPending = $state(false);
  let runtimeEnvActionError = $state('');
  let systemSettingsPending = $state(false);
  let systemSettingsError = $state('');
  let systemSettingsSuccess = $state('');
  let userSettingsPending = $state(false);
  let userSettingsError = $state('');
  let userSettingsSuccess = $state('');
  let featuresRepoSuggestionsAbort = $state<AbortController | null>(null);
  let pendingTabNavigation = $state<SystemTab | null>(null);

  afterNavigate(() => {
    const nextTab = normalizeTab(page.url.searchParams.get('tab'));
    if (pendingTabNavigation !== null && nextTab === pendingTabNavigation) {
      pendingTabNavigation = null;
    }
    if (nextTab !== activeTab) {
      activeTab = nextTab;
    }
  });

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
    const [bundledResult, runtimeEnvResult, operateResult, systemSettingsResult, userSettingsResult] = await Promise.allSettled([
      api.system.bundledTorchStatus(),
      api.system.runtimeEnvStatus(),
      api.operate.status(),
      api.system.settings(),
      api.user.settings()
    ]);

    if (bundledResult.status === 'fulfilled') {
      bundledTorchSnapshot = bundledResult.value;
    } else {
      bundledTorchActionError =
        bundledResult.reason instanceof Error ? bundledResult.reason.message : 'bundled-torch状態の取得に失敗しました。';
    }

    if (runtimeEnvResult.status === 'fulfilled') {
      runtimeEnvSnapshot = runtimeEnvResult.value;
    } else {
      runtimeEnvActionError =
        runtimeEnvResult.reason instanceof Error ? runtimeEnvResult.reason.message : 'runtime env 状態の取得に失敗しました。';
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
  };

  const triggerBuild = async (payload: {
    pytorchVersion: string;
    torchvisionVersion: string;
    force: boolean;
  }) => {
    bundledTorchActionPending = true;
    bundledTorchActionError = '';
    try {
      bundledTorchSnapshot = await api.system.buildBundledTorch({
        pytorch_version: payload.pytorchVersion.trim() || null,
        torchvision_version: payload.torchvisionVersion.trim() || null,
        force: payload.force
      });
    } catch (error) {
      bundledTorchActionError =
        error instanceof Error ? error.message : 'bundled-torch build の開始に失敗しました。';
    } finally {
      bundledTorchActionPending = false;
    }
  };

  const triggerClean = async () => {
    bundledTorchActionPending = true;
    bundledTorchActionError = '';
    try {
      bundledTorchSnapshot = await api.system.cleanBundledTorch();
    } catch (error) {
      bundledTorchActionError =
        error instanceof Error ? error.message : 'bundled-torch clean の開始に失敗しました。';
    } finally {
      bundledTorchActionPending = false;
    }
  };

  const triggerRuntimeBuild = async (payload: { envName: string; force: boolean }) => {
    runtimeEnvActionPending = true;
    runtimeEnvActionError = '';
    try {
      runtimeEnvSnapshot = await api.system.buildRuntimeEnv({
        env_name: payload.envName,
        force: payload.force
      });
    } catch (error) {
      runtimeEnvActionError =
        error instanceof Error ? error.message : 'runtime env build の開始に失敗しました。';
    } finally {
      runtimeEnvActionPending = false;
    }
  };

  const triggerRuntimeDelete = async (envName: string) => {
    runtimeEnvActionPending = true;
    runtimeEnvActionError = '';
    try {
      runtimeEnvSnapshot = await api.system.deleteRuntimeEnv({ env_name: envName });
    } catch (error) {
      runtimeEnvActionError =
        error instanceof Error ? error.message : 'runtime env delete の開始に失敗しました。';
    } finally {
      runtimeEnvActionPending = false;
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
    huggingfaceToken?: string;
    clear?: boolean;
  }) => {
    userSettingsPending = true;
    userSettingsError = '';
    userSettingsSuccess = '';
    try {
      userSettings = await api.user.updateSettings({
        huggingface_token: payload.clear ? null : payload.huggingfaceToken?.trim() ?? null,
        clear_huggingface_token: Boolean(payload.clear)
      });
      userSettingsSuccess = payload.clear ? 'HF token を削除しました。' : 'HF token を更新しました。';
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
        { subscription_id: 'system.page.runtime-envs', kind: 'system.runtime-envs', params: {} }
      ];
    }
    return [];
  };

  const handleRealtimeEvent = (event: TabRealtimeEvent) => {
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
      case 'system.runtime-envs':
        runtimeEnvSnapshot = event.payload as RuntimeEnvSnapshot;
        return;
    }
  };

  let realtimeContributor: TabRealtimeContributorHandle | null = null;

  onMount(() => {
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
    if (pendingTabNavigation === activeTab) {
      return;
    }
    const currentUrl = new URL(page.url);
    const targetUrl = new URL(page.url);
    if (activeTab === 'status') {
      targetUrl.searchParams.delete('tab');
    } else {
      targetUrl.searchParams.set('tab', activeTab);
    }
    if (`${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}` === `${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}`) {
      return;
    }
    pendingTabNavigation = activeTab;
    void goto(`${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}`, {
      keepFocus: true,
      noScroll: true,
      invalidateAll: false,
    }).catch(() => {
      pendingTabNavigation = null;
    });
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
  <Tabs.Root bind:value={activeTab}>
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
          snapshot={systemStatusSnapshot}
          runtimeEnvSnapshot={runtimeEnvSnapshot}
          bundledTorchSnapshot={bundledTorchSnapshot}
          systemSettings={systemSettings}
          runtimeEnvActionPending={runtimeEnvActionPending}
          runtimeEnvActionError={runtimeEnvActionError}
          bundledTorchActionPending={bundledTorchActionPending}
          bundledTorchActionError={bundledTorchActionError}
          onRuntimeBuild={triggerRuntimeBuild}
          onRuntimeDelete={triggerRuntimeDelete}
          onBuild={triggerBuild}
          onClean={triggerClean}
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

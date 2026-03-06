<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { untrack } from 'svelte';
  import { Tabs } from 'bits-ui';

  import { api } from '$lib/api/client';
  import ProfileTab from '$lib/components/system/ProfileTab.svelte';
  import RuntimeTab from '$lib/components/system/RuntimeTab.svelte';
  import SettingsTab from '$lib/components/system/SettingsTab.svelte';
  import SystemStatusTab from '$lib/components/system/SystemStatusTab.svelte';
  import { connectBundledTorchStream } from '$lib/realtime/bundledTorch';
  import { connectRuntimeEnvStream } from '$lib/realtime/runtimeEnv';
  import { connectStream } from '$lib/realtime/stream';
  import { connectSystemStatusStream } from '$lib/realtime/systemStatus';
  import type { BundledTorchBuildSnapshot } from '$lib/types/bundledTorch';
  import type { RuntimeEnvSnapshot } from '$lib/types/runtimeEnv';
  import type { SystemSettings, UserSettings } from '$lib/types/settings';
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

  type OperateStatusStreamPayload = {
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

  $effect(() => {
    const queryTab = normalizeTab(page.url.searchParams.get('tab'));
    if (untrack(() => activeTab) !== queryTab) {
      activeTab = queryTab;
    }
  });

  $effect(() => {
    const rawTab = page.url.searchParams.get('tab');
    const queryTab = normalizeTab(rawTab);
    const expectedTab = activeTab === 'status' ? null : activeTab;
    if (rawTab === expectedTab || (rawTab === null && activeTab === queryTab)) {
      return;
    }
    const nextUrl = new URL(page.url);
    if (activeTab === 'status') {
      nextUrl.searchParams.delete('tab');
    } else {
      nextUrl.searchParams.set('tab', activeTab);
    }
    void goto(nextUrl, { replaceState: true, noScroll: true, keepFocus: true });
  });

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
  }) => {
    systemSettingsPending = true;
    systemSettingsError = '';
    systemSettingsSuccess = '';
    try {
      systemSettings = await api.system.updateSettings({
        bundled_torch: {
          pytorch_version: payload.pytorchVersion.trim(),
          torchvision_version: payload.torchvisionVersion.trim()
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

  onMount(() => {
    void loadInitialState();

    const stopSystemStatusStream = connectSystemStatusStream({
      onMessage: (payload) => {
        systemStatusSnapshot = payload;
      }
    });
    const stopOperateStream = connectStream<OperateStatusStreamPayload>({
      path: '/api/stream/operate/status',
      onMessage: (payload) => {
        networkStatus = payload.operate_status?.network ?? null;
      }
    });
    const stopBundledTorchStream = connectBundledTorchStream({
      onMessage: (payload) => {
        bundledTorchSnapshot = payload;
      }
    });
    const stopRuntimeEnvStream = connectRuntimeEnvStream({
      onMessage: (payload) => {
        runtimeEnvSnapshot = payload;
      }
    });

    return () => {
      stopSystemStatusStream();
      stopOperateStream();
      stopBundledTorchStream();
      stopRuntimeEnvStream();
    };
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
      <SystemStatusTab snapshot={systemStatusSnapshot} network={networkStatus} />
    </Tabs.Content>

    <Tabs.Content value="profile" class="mt-6 space-y-6">
      <ProfileTab />
    </Tabs.Content>

    <Tabs.Content value="runtime" class="mt-6 space-y-6">
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
    </Tabs.Content>

    <Tabs.Content value="settings" class="mt-6 space-y-6">
      <SettingsTab
        systemSettings={systemSettings}
        userSettings={userSettings}
        systemPending={systemSettingsPending}
        userPending={userSettingsPending}
        systemError={systemSettingsError}
        userError={userSettingsError}
        systemSuccess={systemSettingsSuccess}
        userSuccess={userSettingsSuccess}
        onSaveSystemSettings={saveSystemSettings}
        onSaveUserSettings={saveUserSettings}
      />
    </Tabs.Content>
  </Tabs.Root>
</section>

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { Button } from 'bits-ui';
  import { toStore } from 'svelte/store';
  import { createQuery } from '@tanstack/svelte-query';
  import { api } from '$lib/api/client';
  import { connectStream } from '$lib/realtime/stream';
  import { queryClient } from '$lib/queryClient';

  type VlaborProfile = {
    name: string;
    description?: string;
    updated_at?: string;
  };

  type ProfilesResponse = {
    profiles?: VlaborProfile[];
    active_profile_name?: string;
  };

  type ActiveProfileResponse = {
    profile_name?: string;
    profile_snapshot?: Record<string, unknown>;
  };

  type ProfileStatusResponse = {
    profile_name?: string;
    profile_snapshot?: Record<string, unknown>;
    cameras?: Array<{ name: string; enabled: boolean; connected: boolean; topics?: string[] }>;
    arms?: Array<{ name: string; enabled: boolean; connected: boolean }>;
    topics?: string[];
  };

  type VlaborStatusResponse = {
    status?: string;
    service?: string;
    state?: string;
    status_detail?: string;
    running_for?: string;
    created_at?: string;
    container_id?: string;
  };

  type TeleopSessionActionResponse = {
    success?: boolean;
    session_id?: string;
    message?: string;
    status?: VlaborStatusResponse;
  };

  const profilesQuery = createQuery<ProfilesResponse>({
    queryKey: ['profiles', 'list'],
    queryFn: api.profiles.list
  });

  const activeProfileQuery = createQuery<ActiveProfileResponse>({
    queryKey: ['profiles', 'active'],
    queryFn: api.profiles.active
  });

  const activeProfileName = $derived(
    $activeProfileQuery.data?.profile_name ?? $profilesQuery.data?.active_profile_name ?? ''
  );

  const activeStatusQuery = createQuery<ProfileStatusResponse>(
    toStore(() => ({
      queryKey: ['profiles', 'active', 'status'],
      queryFn: api.profiles.activeStatus,
      enabled: Boolean(activeProfileName)
    }))
  );

  const vlaborStatusQuery = createQuery<VlaborStatusResponse>({
    queryKey: ['profiles', 'vlabor', 'status'],
    queryFn: api.profiles.vlaborStatus
  });

  const vlaborState = $derived($vlaborStatusQuery.data?.status ?? 'unknown');
  const vlaborDetail = $derived(
    $vlaborStatusQuery.data?.status_detail ?? $vlaborStatusQuery.data?.running_for ?? ''
  );

  const activeProfileDescription = $derived.by(() => {
    const name = activeProfileName;
    if (!name) return 'プロファイルが選択されていません。';
    const profile = ($profilesQuery.data?.profiles ?? []).find((item) => item.name === name);
    return profile?.description ?? '説明は未設定です。';
  });

  let switchingProfile = $state(false);
  let selectionError = $state('');
  let actionPending = $state(false);
  let actionMessage = $state('');
  let actionIntent: 'start' | 'stop' | '' = $state('');

  const actionStatusLabel = $derived.by(() => {
    if (actionIntent === 'start') return '起動中…';
    if (actionIntent === 'stop') return '停止中…';
    return '';
  });

  async function refetchQuery(snapshot?: { refetch?: () => Promise<unknown> }) {
    if (snapshot && typeof snapshot.refetch === 'function') {
      await snapshot.refetch();
    }
  }

  async function handleProfileChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    const profileName = target.value;
    if (!profileName) return;
    switchingProfile = true;
    selectionError = '';
    try {
      await api.profiles.setActive({ profile_name: profileName });
      await refetchQuery($activeProfileQuery);
      await refetchQuery($profilesQuery);
      await refetchQuery($activeStatusQuery);
    } catch (error) {
      console.error(error);
      selectionError = error instanceof Error ? error.message : 'プロファイル切り替えに失敗しました。';
    } finally {
      switchingProfile = false;
    }
  }

  let stopVlaborStream = () => {};

  onMount(() => {
    stopVlaborStream = connectStream({
      path: '/api/stream/profiles/vlabor',
      onMessage: (payload) => {
        queryClient.setQueryData(['profiles', 'vlabor', 'status'], payload);
      }
    });
  });

  onDestroy(() => {
    stopVlaborStream();
  });

  async function startVlabor() {
    actionPending = true;
    actionIntent = 'start';
    actionMessage = '';
    try {
      const created = (await api.teleop.createSession({
        profile: activeProfileName || undefined
      })) as TeleopSessionActionResponse;
      const sessionId = created?.session_id ?? 'teleop';
      await api.teleop.startSession({ session_id: sessionId });
      await refetchQuery($vlaborStatusQuery);
      await refetchQuery($activeStatusQuery);
    } catch (error) {
      console.error(error);
      const detail = error instanceof Error ? error.message : '起動に失敗しました。';
      actionMessage = `${detail} Docker権限やバックエンドログを確認してください。`;
      actionIntent = '';
    } finally {
      actionPending = false;
      actionIntent = '';
    }
  }

  async function stopVlabor() {
    actionPending = true;
    actionIntent = 'stop';
    actionMessage = '';
    try {
      await api.teleop.stopSession({ session_id: 'teleop' });
      await refetchQuery($vlaborStatusQuery);
      await refetchQuery($activeStatusQuery);
    } catch (error) {
      console.error(error);
      const detail = error instanceof Error ? error.message : '停止に失敗しました。';
      actionMessage = `${detail} Docker権限やバックエンドログを確認してください。`;
      actionIntent = '';
    } finally {
      actionPending = false;
      actionIntent = '';
    }
  }
</script>

<section class="card-strong p-8">
  <p class="section-title">Setup</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">デバイス・プロファイル設定</h1>
      <p class="mt-2 text-sm text-slate-600">VLAborプロファイルの選択と状態確認。</p>
    </div>
    <div class="flex flex-wrap gap-2">
      {#if vlaborState === 'running'}
        <Button.Root class="btn-ghost" onclick={stopVlabor} disabled={actionPending}>
          停止
        </Button.Root>
      {:else}
        <Button.Root class="btn-ghost" onclick={startVlabor} disabled={actionPending || !activeProfileName}>
          起動
        </Button.Root>
      {/if}
    </div>
    {#if actionMessage}
      <p class="mt-2 text-xs text-rose-500">{actionMessage}</p>
    {/if}
  </div>
</section>

<section class="card p-6">
  <div class="flex flex-wrap items-center justify-between gap-4">
    <div>
      <p class="text-xs uppercase tracking-widest text-slate-400">Active Profile</p>
      <h2 class="mt-1 text-2xl font-semibold text-slate-900">{activeProfileName || '-'}</h2>
      <p class="mt-2 text-sm text-slate-600">{activeProfileDescription}</p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <select
        class="input min-w-[260px]"
        disabled={switchingProfile || !($profilesQuery.data?.profiles ?? []).length}
        value={activeProfileName}
        onchange={handleProfileChange}
      >
        <option value="" disabled>プロファイルを選択</option>
        {#each $profilesQuery.data?.profiles ?? [] as profile}
          <option value={profile.name}>{profile.name}</option>
        {/each}
      </select>
      {#if actionStatusLabel}
        <span class="rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-700">{actionStatusLabel}</span>
      {:else if vlaborState === 'restarting'}
        <span class="rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-700">再起動中</span>
      {:else if vlaborState === 'running'}
        <span class="rounded-full bg-emerald-100 px-3 py-1 text-xs text-emerald-700">稼働中</span>
      {:else if vlaborState === 'stopped'}
        <span class="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">停止</span>
      {:else}
        <span class="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">不明</span>
      {/if}
      {#if vlaborDetail}
        <span class="text-xs text-slate-400">{vlaborDetail}</span>
      {/if}
      {#if vlaborState === 'running'}
        <a
          class="inline-flex h-9 items-center justify-center rounded-full border border-emerald-200 bg-emerald-50 px-4 text-xs font-semibold text-emerald-700"
          href="http://vlabor.local:8888"
          target="_blank"
          rel="noreferrer"
        >
          VLabor UI を開く
        </a>
      {/if}
    </div>
  </div>
  {#if selectionError}
    <p class="mt-3 text-xs text-rose-500">{selectionError}</p>
  {/if}
</section>

<section class="grid gap-6 lg:grid-cols-2">
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">プロファイルの生データ</h2>
    <div class="mt-4 text-sm text-slate-600">
      <pre class="max-h-[360px] overflow-auto rounded-xl border border-slate-200/60 bg-white/70 p-4 text-xs text-slate-700">
{JSON.stringify($activeProfileQuery.data?.profile_snapshot ?? {}, null, 2)}
      </pre>
    </div>
  </div>
  <div class="card p-6">
    <h2 class="text-lg font-semibold text-slate-900">デバイス状態</h2>
    <div class="mt-4 space-y-4 text-sm text-slate-600">
      {#if $activeStatusQuery.isLoading}
        <p>読み込み中...</p>
      {:else}
        <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <p class="label">カメラ</p>
          <div class="mt-2 space-y-2">
            {#each $activeStatusQuery.data?.cameras ?? [] as cam}
              <div class="flex items-center justify-between">
                <span>{cam.name}</span>
                <span class="text-xs text-slate-500">
                  {cam.enabled ? (cam.connected ? '✅ 接続' : '⚠️ 未接続') : '⏸️ 無効'}
                </span>
              </div>
            {/each}
          </div>
        </div>
        <div class="rounded-xl border border-slate-200/60 bg-white/70 px-4 py-3">
          <p class="label">ロボット/アーム</p>
          <div class="mt-2 space-y-2">
            {#each $activeStatusQuery.data?.arms ?? [] as arm}
              <div class="flex items-center justify-between">
                <span>{arm.name}</span>
                <span class="text-xs text-slate-500">
                  {arm.connected ? '✅ 接続' : '⚠️ 未接続'}
                </span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  </div>
</section>

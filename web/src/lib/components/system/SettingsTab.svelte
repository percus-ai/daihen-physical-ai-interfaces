<script lang="ts">
  import { Combobox } from 'bits-ui';
  import ArrowsClockwise from 'phosphor-svelte/lib/ArrowsClockwise';
  import CaretDoubleDown from 'phosphor-svelte/lib/CaretDoubleDown';
  import CaretDoubleUp from 'phosphor-svelte/lib/CaretDoubleUp';
  import CaretUpDown from 'phosphor-svelte/lib/CaretUpDown';
  import Check from 'phosphor-svelte/lib/Check';
  import Eye from 'phosphor-svelte/lib/Eye';
  import EyeSlash from 'phosphor-svelte/lib/EyeSlash';
  import FloppyDisk from 'phosphor-svelte/lib/FloppyDisk';
  import Key from 'phosphor-svelte/lib/Key';
  import Package from 'phosphor-svelte/lib/Package';
  import User from 'phosphor-svelte/lib/User';

  import type {
    FeaturesRepoSuggestions,
    SystemSettings,
    UserSettings
  } from '$lib/types/settings';

  type SettingsSection = 'profile' | 'credentials' | 'package';
  type SettingTone = 'ready' | 'pending' | 'missing' | 'error';

  let {
    systemSettings = null,
    userSettings = null,
    systemPending = false,
    userPending = false,
    systemError = '',
    userError = '',
    systemSuccess = '',
    userSuccess = '',
    onSaveSystemSettings,
    onSaveUserSettings,
    featuresRepoSuggestions = null,
    featuresRepoSuggestionsPending = false,
    onRefreshFeaturesRepoSuggestions,
  }: {
    systemSettings?: SystemSettings | null;
    userSettings?: UserSettings | null;
    systemPending?: boolean;
    userPending?: boolean;
    systemError?: string;
    userError?: string;
    systemSuccess?: string;
    userSuccess?: string;
    onSaveSystemSettings: (payload: {
      repoUrl: string;
      repoRef: string;
      repoCommit?: string;
    }) => void | Promise<void>;
    onSaveUserSettings: (payload: {
      username?: string;
      firstName?: string;
      lastName?: string;
      huggingfaceToken?: string;
      clear?: boolean;
    }) => void | Promise<void>;
    featuresRepoSuggestions?: FeaturesRepoSuggestions | null;
    featuresRepoSuggestionsPending?: boolean;
    onRefreshFeaturesRepoSuggestions: (payload: {
      repoUrl: string;
      repoRef?: string;
    }) => void | Promise<void>;
  } = $props();

  let activeSection = $state<SettingsSection>('profile');
  let systemFeaturesRepoUrl = $state('');
  let systemFeaturesRepoRef = $state('');
  let systemFeaturesRepoCommit = $state('');
  let userProfileUsername = $state('');
  let userProfileFirstName = $state('');
  let userProfileLastName = $state('');
  let userHuggingFaceToken = $state('');
  let branchOpen = $state(false);
  let commitOpen = $state(false);
  let selectedBranchValue = $state('');
  let selectedCommitValue = $state('');
  let lastHydratedSystemSettingsKey = $state('');
  let lastHydratedUserSettingsKey = $state('');
  let lastHydratedUserTokenKey = $state('');
  let userHuggingFaceTokenDirty = $state(false);
  let userHuggingFaceTokenVisible = $state(false);

  $effect(() => {
    const nextKey = JSON.stringify({
      updated_at: systemSettings?.updated_at ?? null,
      repo_url: systemSettings?.features_repo?.repo_url ?? '',
      repo_ref: systemSettings?.features_repo?.repo_ref ?? '',
      repo_commit: systemSettings?.features_repo?.repo_commit ?? ''
    });
    if (!systemSettings || nextKey === lastHydratedSystemSettingsKey) {
      return;
    }

    systemFeaturesRepoUrl = systemSettings.features_repo?.repo_url ?? '';
    systemFeaturesRepoRef = systemSettings.features_repo?.repo_ref ?? '';
    selectedBranchValue = systemSettings.features_repo?.repo_ref ?? '';
    systemFeaturesRepoCommit = systemSettings.features_repo?.repo_commit ?? '';
    selectedCommitValue = systemSettings.features_repo?.repo_commit ?? '';
    lastHydratedSystemSettingsKey = nextKey;
  });

  $effect(() => {
    const nextKey = JSON.stringify({
      user_id: userSettings?.user_id ?? null,
      username: userSettings?.profile?.username ?? '',
      first_name: userSettings?.profile?.first_name ?? '',
      last_name: userSettings?.profile?.last_name ?? '',
      updated_at: userSettings?.profile?.updated_at ?? null
    });
    if (!userSettings || nextKey === lastHydratedUserSettingsKey) {
      return;
    }

    userProfileUsername = userSettings.profile?.username ?? '';
    userProfileFirstName = userSettings.profile?.first_name ?? '';
    userProfileLastName = userSettings.profile?.last_name ?? '';
    lastHydratedUserSettingsKey = nextKey;
  });

  $effect(() => {
    const nextKey = JSON.stringify({
      has_token: userSettings?.huggingface?.has_token ?? false,
      token: userSettings?.huggingface?.token ?? '',
      updated_at: userSettings?.huggingface?.updated_at ?? null
    });
    if (!userSettings || nextKey === lastHydratedUserTokenKey || userHuggingFaceTokenDirty) {
      return;
    }

    userHuggingFaceToken = userSettings.huggingface?.token ?? '';
    lastHydratedUserTokenKey = nextKey;
  });

  const profileConfigured = $derived(
    Boolean(
      userSettings?.profile?.username ||
        userSettings?.profile?.first_name ||
        userSettings?.profile?.last_name
    )
  );
  const credentialsConfigured = $derived(Boolean(userSettings?.huggingface?.has_token));
  const packageConfigured = $derived(
    Boolean(systemSettings?.features_repo?.repo_url?.trim()) &&
      Boolean(systemSettings?.features_repo?.repo_ref?.trim())
  );

  const profileTone = $derived<SettingTone>(
    userError ? 'error' : userPending ? 'pending' : profileConfigured ? 'ready' : 'missing'
  );
  const credentialsTone = $derived<SettingTone>(
    userError ? 'error' : userPending ? 'pending' : credentialsConfigured ? 'ready' : 'missing'
  );
  const packageTone = $derived<SettingTone>(
    systemError ? 'error' : systemPending ? 'pending' : packageConfigured ? 'ready' : 'missing'
  );

  const settingsSections = $derived([
    {
      id: 'profile' as const,
      label: 'プロフィール',
      description: 'ユーザー名と氏名',
      tone: profileTone
    },
    {
      id: 'credentials' as const,
      label: '認証情報',
      description: '外部サービスのトークン',
      tone: credentialsTone
    },
    {
      id: 'package' as const,
      label: 'パッケージ',
      description: '取得元とバージョン',
      tone: packageTone
    }
  ]);

  const branchLookupItems = $derived.by(() =>
    (featuresRepoSuggestions?.branches ?? []).map((branch) => ({ value: branch, label: branch }))
  );
  const filteredBranchItems = $derived.by(() => {
    const query = systemFeaturesRepoRef.trim().toLowerCase();
    if (!query) return branchLookupItems;
    return branchLookupItems.filter((item) => item.label.toLowerCase().includes(query));
  });
  const commitLookupItems = $derived.by(() =>
    (featuresRepoSuggestions?.commits ?? []).map((commit) => ({
      value: commit.sha,
      label: `${commit.short_sha} ${commit.message}`.trim(),
      shortSha: commit.short_sha,
      message: commit.message
    }))
  );
  const filteredCommitItems = $derived.by(() => {
    const query = systemFeaturesRepoCommit.trim().toLowerCase();
    if (!query) return commitLookupItems;
    return commitLookupItems.filter(
      (item) =>
        item.value.toLowerCase().includes(query) ||
        item.shortSha.toLowerCase().includes(query) ||
        item.message.toLowerCase().includes(query)
    );
  });
  const canSaveUserToken = $derived(
    userHuggingFaceTokenDirty &&
      Boolean(userHuggingFaceToken.trim()) &&
      userHuggingFaceToken.trim() !== (userSettings?.huggingface?.token ?? '').trim()
  );

  const statusLabel = (tone: SettingTone) => {
    switch (tone) {
      case 'pending':
        return '保存中';
      case 'error':
        return 'エラー';
      case 'missing':
        return '未設定';
      default:
        return '';
    }
  };

  const shouldShowStatus = (tone: SettingTone) => tone !== 'ready';

  const statusClass = (tone: SettingTone) => {
    switch (tone) {
      case 'ready':
        return 'border-emerald-200 bg-emerald-50 text-emerald-700';
      case 'pending':
        return 'border-amber-200 bg-amber-50 text-amber-700';
      case 'error':
        return 'border-rose-200 bg-rose-50 text-rose-700';
      default:
        return 'border-slate-200 bg-slate-100 text-slate-600';
    }
  };

  const activeButtonClass = (sectionId: SettingsSection) =>
    activeSection === sectionId
      ? 'border-brand/40 bg-white text-slate-950 shadow-sm ring-1 ring-brand/10'
      : 'border-transparent text-slate-600 hover:border-slate-200 hover:bg-white/80 hover:text-slate-950';

  const feedbackPanelClass = (tone: 'error' | 'success') =>
    tone === 'error'
      ? 'border-rose-200 bg-rose-50 text-rose-700'
      : 'border-emerald-200 bg-emerald-50 text-emerald-700';
  const clearButtonClass =
    'text-xs font-semibold text-slate-500 transition hover:text-slate-800 disabled:cursor-not-allowed disabled:text-slate-300';

  const saveUserToken = async () => {
    if (!userHuggingFaceTokenDirty) return;
    const token = userHuggingFaceToken.trim();
    if (!token) return;
    await onSaveUserSettings({ huggingfaceToken: token, clear: false });
    userHuggingFaceTokenDirty = false;
  };

  const saveUserProfile = async () => {
    await onSaveUserSettings({
      username: userProfileUsername,
      firstName: userProfileFirstName,
      lastName: userProfileLastName
    });
  };

  const savePackageSettings = async () => {
    await onSaveSystemSettings({
      repoUrl: systemFeaturesRepoUrl,
      repoRef: systemFeaturesRepoRef,
      repoCommit: systemFeaturesRepoCommit
    });
  };

  const refreshPackageSuggestions = () => {
    void onRefreshFeaturesRepoSuggestions({
      repoUrl: systemFeaturesRepoUrl,
      repoRef: systemFeaturesRepoRef
    });
  };

  const openBranchSuggestions = () => {
    branchOpen = true;
    refreshPackageSuggestions();
  };

  const openCommitSuggestions = () => {
    commitOpen = true;
    refreshPackageSuggestions();
  };
</script>

<section class="space-y-5">
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="section-title">設定</p>
      <h2 class="mt-2 text-2xl font-semibold text-slate-900">設定</h2>
      <p class="mt-2 max-w-2xl text-sm text-slate-600">
        ユーザー情報、外部サービスの認証情報、処理で使うパッケージの取得元を管理します。
      </p>
    </div>
    <div class="flex flex-wrap gap-2">
      {#if shouldShowStatus(profileTone)}
        <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${statusClass(profileTone)}`}>
          プロフィール: {statusLabel(profileTone)}
        </span>
      {/if}
      {#if shouldShowStatus(credentialsTone)}
        <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${statusClass(credentialsTone)}`}>
          認証情報: {statusLabel(credentialsTone)}
        </span>
      {/if}
      {#if shouldShowStatus(packageTone)}
        <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${statusClass(packageTone)}`}>
          パッケージ: {statusLabel(packageTone)}
        </span>
      {/if}
    </div>
  </div>

  <div class="grid min-h-[520px] overflow-hidden rounded-2xl border border-slate-200 bg-white lg:grid-cols-[15rem_minmax(0,1fr)]">
    <nav class="border-b border-slate-200 bg-slate-50/80 p-3 lg:border-b-0 lg:border-r" aria-label="設定カテゴリ">
      <div class="grid gap-2 sm:grid-cols-3 lg:grid-cols-1">
        {#each settingsSections as section (section.id)}
          <button
            class={`flex min-h-[74px] w-full items-start gap-3 rounded-xl border px-3 py-3 text-left transition ${activeButtonClass(section.id)}`}
            type="button"
            aria-current={activeSection === section.id ? 'page' : undefined}
            onclick={() => {
              activeSection = section.id;
            }}
          >
            <span class="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600">
              {#if section.id === 'profile'}
                <User size={18} />
              {:else if section.id === 'credentials'}
                <Key size={18} />
              {:else}
                <Package size={18} />
              {/if}
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-sm font-semibold">{section.label}</span>
              <span class="mt-1 block text-xs leading-5 text-slate-500">{section.description}</span>
              {#if shouldShowStatus(section.tone)}
                <span class={`mt-2 inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusClass(section.tone)}`}>
                  {statusLabel(section.tone)}
                </span>
              {/if}
            </span>
          </button>
        {/each}
      </div>
    </nav>

    <div class="min-w-0 p-5 lg:p-6">
      {#if activeSection === 'profile'}
        <div class="mx-auto flex min-h-[480px] max-w-3xl flex-col gap-6">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div class="flex items-center gap-3">
                <span class="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-700">
                  <User size={20} />
                </span>
                <div>
                  <h3 class="text-xl font-semibold text-slate-900">プロフィール</h3>
                  <p class="mt-1 text-sm text-slate-600">ユーザー名と氏名を設定します。</p>
                </div>
              </div>
            </div>
            <span class="chip max-w-full truncate">ユーザーID: {userSettings?.user_id ?? '-'}</span>
          </div>

          {#if userError}
            <div class={`rounded-xl border px-4 py-3 text-sm ${feedbackPanelClass('error')}`}>{userError}</div>
          {/if}
          {#if userSuccess}
            <div class={`rounded-xl border px-4 py-3 text-sm ${feedbackPanelClass('success')}`}>{userSuccess}</div>
          {/if}

          <div class="grid gap-4 md:grid-cols-2">
            <label class="md:col-span-2">
              <span class="mb-1.5 flex items-center justify-between gap-2">
                <span class="text-sm font-semibold text-slate-700">ユーザー名</span>
                <button
                  class={clearButtonClass}
                  type="button"
                  onclick={() => {
                    userProfileUsername = '';
                  }}
                  disabled={userPending || !userProfileUsername.trim()}
                  aria-label="ユーザー名をクリア"
                >
                  クリア
                </button>
              </span>
              <input
                bind:value={userProfileUsername}
                class="input"
                placeholder="tanaka.tarou"
                disabled={userPending}
              />
            </label>
            <label>
              <span class="mb-1.5 flex items-center justify-between gap-2">
                <span class="text-sm font-semibold text-slate-700">姓</span>
                <button
                  class={clearButtonClass}
                  type="button"
                  onclick={() => {
                    userProfileLastName = '';
                  }}
                  disabled={userPending || !userProfileLastName.trim()}
                  aria-label="姓をクリア"
                >
                  クリア
                </button>
              </span>
              <input
                bind:value={userProfileLastName}
                class="input"
                placeholder="田中"
                disabled={userPending}
              />
            </label>
            <label>
              <span class="mb-1.5 flex items-center justify-between gap-2">
                <span class="text-sm font-semibold text-slate-700">名</span>
                <button
                  class={clearButtonClass}
                  type="button"
                  onclick={() => {
                    userProfileFirstName = '';
                  }}
                  disabled={userPending || !userProfileFirstName.trim()}
                  aria-label="名をクリア"
                >
                  クリア
                </button>
              </span>
              <input
                bind:value={userProfileFirstName}
                class="input"
                placeholder="太郎"
                disabled={userPending}
              />
            </label>
          </div>

          <div class="sticky bottom-0 z-10 mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white/95 py-4 backdrop-blur">
            <p class="text-xs text-slate-500">最終更新: {userSettings?.profile?.updated_at ?? '-'}</p>
            <button class="btn-primary" type="button" onclick={saveUserProfile} disabled={userPending}>
              <FloppyDisk size={16} />
              保存
            </button>
          </div>
        </div>
      {:else if activeSection === 'credentials'}
        <div class="mx-auto flex min-h-[480px] max-w-3xl flex-col gap-6">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div class="flex items-center gap-3">
              <span class="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-700">
                <Key size={20} />
              </span>
              <div>
                <h3 class="text-xl font-semibold text-slate-900">認証情報</h3>
                <p class="mt-1 text-sm text-slate-600">外部サービスで利用するトークンを管理します。</p>
              </div>
            </div>
            {#if shouldShowStatus(credentialsTone)}
              <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${statusClass(credentialsTone)}`}>
                {statusLabel(credentialsTone)}
              </span>
            {/if}
          </div>

          {#if userError}
            <div class={`rounded-xl border px-4 py-3 text-sm ${feedbackPanelClass('error')}`}>{userError}</div>
          {/if}
          {#if userSuccess}
            <div class={`rounded-xl border px-4 py-3 text-sm ${feedbackPanelClass('success')}`}>{userSuccess}</div>
          {/if}

          <label>
            <span class="mb-1.5 flex items-center justify-between gap-2">
              <span class="text-sm font-semibold text-slate-700">Hugging Face トークン</span>
              <button
                class={clearButtonClass}
                type="button"
                onclick={() => {
                  userHuggingFaceToken = '';
                  userHuggingFaceTokenDirty = true;
                }}
                disabled={userPending || !userHuggingFaceToken.trim()}
                aria-label="Hugging Face トークンをクリア"
              >
                クリア
              </button>
            </span>
            <span class="relative block">
              <input
                value={userHuggingFaceToken}
                class="input pr-12"
                type={userHuggingFaceTokenVisible ? 'text' : 'password'}
                placeholder="hf_xxx..."
                autocomplete="off"
                disabled={userPending}
                oninput={(event) => {
                  userHuggingFaceToken = (event.currentTarget as HTMLInputElement).value;
                  userHuggingFaceTokenDirty = true;
                }}
              />
              <button
                class="absolute right-2 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-45"
                type="button"
                aria-label={userHuggingFaceTokenVisible ? 'トークンを非表示' : 'トークンを表示'}
                disabled={userPending}
                onclick={() => {
                  userHuggingFaceTokenVisible = !userHuggingFaceTokenVisible;
                }}
              >
                {#if userHuggingFaceTokenVisible}
                  <EyeSlash size={16} />
                {:else}
                  <Eye size={16} />
                {/if}
              </button>
            </span>
          </label>

          <div class="sticky bottom-0 z-10 mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white/95 py-4 backdrop-blur">
            <p class="text-xs text-slate-500">最終更新: {userSettings?.huggingface?.updated_at ?? '-'}</p>
            <div class="flex flex-wrap gap-2">
              <button
                class="btn-primary"
                type="button"
                onclick={saveUserToken}
                disabled={userPending || !canSaveUserToken}
              >
                <FloppyDisk size={16} />
                保存
              </button>
            </div>
          </div>
        </div>
      {:else}
        <div class="mx-auto flex min-h-[480px] max-w-3xl flex-col gap-6">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div class="flex items-center gap-3">
              <span class="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-700">
                <Package size={20} />
              </span>
              <div>
                <h3 class="text-xl font-semibold text-slate-900">パッケージの取得元</h3>
                <p class="mt-1 text-sm text-slate-600">
                  学習・推論などの処理で使うパッケージの取得元とバージョンを指定します。
                </p>
              </div>
            </div>
            {#if shouldShowStatus(packageTone)}
              <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${statusClass(packageTone)}`}>
                {statusLabel(packageTone)}
              </span>
            {/if}
          </div>

          {#if systemError}
            <div class={`rounded-xl border px-4 py-3 text-sm ${feedbackPanelClass('error')}`}>{systemError}</div>
          {/if}
          {#if systemSuccess}
            <div class={`rounded-xl border px-4 py-3 text-sm ${feedbackPanelClass('success')}`}>{systemSuccess}</div>
          {/if}

          <div class="grid gap-4">
            <label>
              <span class="mb-1.5 flex items-center justify-between gap-2">
                <span class="text-sm font-semibold text-slate-700">取得元URL</span>
                <button
                  class={clearButtonClass}
                  type="button"
                  onclick={() => {
                    systemFeaturesRepoUrl = '';
                  }}
                  disabled={systemPending || !systemFeaturesRepoUrl.trim()}
                  aria-label="取得元URLをクリア"
                >
                  クリア
                </button>
              </span>
              <input
                bind:value={systemFeaturesRepoUrl}
                class="input"
                disabled={systemPending}
                onblur={() => onRefreshFeaturesRepoSuggestions({ repoUrl: systemFeaturesRepoUrl, repoRef: systemFeaturesRepoRef })}
              />
            </label>

            <label>
              <span class="mb-1.5 flex items-center justify-between gap-2">
                <span class="text-sm font-semibold text-slate-700">ブランチ</span>
                <button
                  class={clearButtonClass}
                  type="button"
                  onclick={() => {
                    systemFeaturesRepoRef = '';
                    selectedBranchValue = '';
                  }}
                  disabled={systemPending || !systemFeaturesRepoRef.trim()}
                  aria-label="ブランチをクリア"
                >
                  クリア
                </button>
              </span>
              <Combobox.Root
                type="single"
                value={selectedBranchValue}
                inputValue={systemFeaturesRepoRef}
                items={branchLookupItems}
                open={branchOpen}
                onOpenChange={(nextOpen) => {
                  branchOpen = nextOpen;
                }}
                onValueChange={(nextValue) => {
                  if (!nextValue) return;
                  selectedBranchValue = nextValue;
                  systemFeaturesRepoRef = nextValue;
                  branchOpen = false;
                }}
                disabled={systemPending}
              >
                <div class="relative">
                  <Combobox.Input
                    class="input pr-10"
                    disabled={systemPending}
                    autocomplete="off"
                    oninput={(event) => {
                      systemFeaturesRepoRef = (event.currentTarget as HTMLInputElement).value;
                      selectedBranchValue = '';
                      branchOpen = true;
                    }}
                    onfocus={openBranchSuggestions}
                  />
                  <Combobox.Trigger
                    class="absolute right-2 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100"
                    disabled={systemPending}
                    aria-label="ブランチ候補を開く"
                    onclick={openBranchSuggestions}
                  >
                    <CaretUpDown class="size-4" />
                  </Combobox.Trigger>
                </div>

                <Combobox.Portal>
                  <Combobox.Content
                    sideOffset={8}
                    class="z-50 max-h-[var(--bits-combobox-content-available-height)] w-[var(--bits-combobox-anchor-width)] rounded-xl border border-slate-200 bg-white p-1 shadow-lg"
                  >
                    <Combobox.ScrollUpButton class="flex w-full items-center justify-center py-1 text-slate-500">
                      <CaretDoubleUp class="size-3" />
                    </Combobox.ScrollUpButton>
                    <Combobox.Viewport class="max-h-64 p-1">
                      {#if filteredBranchItems.length === 0}
                        <div class="px-3 py-2 text-xs text-slate-500">一致するブランチがありません。</div>
                      {:else}
                        {#each filteredBranchItems as item (`branch-${item.value}`)}
                          <Combobox.Item value={item.value} label={item.label}>
                            {#snippet children({ selected, highlighted })}
                              <div
                                class={`flex cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm ${
                                  highlighted ? 'bg-slate-100 text-slate-900' : 'text-slate-700'
                                }`}
                              >
                                <span class="truncate">{item.label}</span>
                                {#if selected}
                                  <Check class="size-4 text-brand" />
                                {/if}
                              </div>
                            {/snippet}
                          </Combobox.Item>
                        {/each}
                      {/if}
                    </Combobox.Viewport>
                    <Combobox.ScrollDownButton class="flex w-full items-center justify-center py-1 text-slate-500">
                      <CaretDoubleDown class="size-3" />
                    </Combobox.ScrollDownButton>
                  </Combobox.Content>
                </Combobox.Portal>
              </Combobox.Root>
            </label>

            <label>
              <span class="mb-1.5 flex items-center justify-between gap-2">
                <span class="text-sm font-semibold text-slate-700">コミット</span>
                <button
                  class={clearButtonClass}
                  type="button"
                  onclick={() => {
                    systemFeaturesRepoCommit = '';
                    selectedCommitValue = '';
                  }}
                  disabled={systemPending || !systemFeaturesRepoCommit.trim()}
                  aria-label="コミットをクリア"
                >
                  クリア
                </button>
              </span>
              <Combobox.Root
                type="single"
                value={selectedCommitValue}
                inputValue={systemFeaturesRepoCommit}
                items={commitLookupItems}
                open={commitOpen}
                onOpenChange={(nextOpen) => {
                  commitOpen = nextOpen;
                }}
                onValueChange={(nextValue) => {
                  if (!nextValue) return;
                  selectedCommitValue = nextValue;
                  systemFeaturesRepoCommit = nextValue;
                  commitOpen = false;
                }}
                disabled={systemPending}
              >
                <div class="relative">
                  <Combobox.Input
                    class="input pr-10"
                    disabled={systemPending}
                    autocomplete="off"
                    oninput={(event) => {
                      systemFeaturesRepoCommit = (event.currentTarget as HTMLInputElement).value;
                      selectedCommitValue = '';
                      commitOpen = true;
                    }}
                    onfocus={openCommitSuggestions}
                  />
                  <Combobox.Trigger
                    class="absolute right-2 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100"
                    disabled={systemPending}
                    aria-label="コミット候補を開く"
                    onclick={openCommitSuggestions}
                  >
                    <CaretUpDown class="size-4" />
                  </Combobox.Trigger>
                </div>

                <Combobox.Portal>
                  <Combobox.Content
                    sideOffset={8}
                    class="z-50 max-h-[var(--bits-combobox-content-available-height)] w-[var(--bits-combobox-anchor-width)] rounded-xl border border-slate-200 bg-white p-1 shadow-lg"
                  >
                    <Combobox.ScrollUpButton class="flex w-full items-center justify-center py-1 text-slate-500">
                      <CaretDoubleUp class="size-3" />
                    </Combobox.ScrollUpButton>
                    <Combobox.Viewport class="max-h-64 p-1">
                      {#if filteredCommitItems.length === 0}
                        <div class="px-3 py-2 text-xs text-slate-500">一致するコミットがありません。</div>
                      {:else}
                        {#each filteredCommitItems as item (`commit-${item.value}`)}
                          <Combobox.Item value={item.value} label={item.label}>
                            {#snippet children({ selected, highlighted })}
                              <div
                                class={`flex cursor-pointer items-start justify-between gap-2 rounded-lg px-3 py-2 text-sm ${
                                  highlighted ? 'bg-slate-100 text-slate-900' : 'text-slate-700'
                                }`}
                              >
                                <div class="min-w-0">
                                  <p class="font-semibold text-slate-800">{item.shortSha}</p>
                                  <p class="truncate text-xs text-slate-500">{item.message}</p>
                                </div>
                                {#if selected}
                                  <Check class="mt-0.5 size-4 shrink-0 text-brand" />
                                {/if}
                              </div>
                            {/snippet}
                          </Combobox.Item>
                        {/each}
                      {/if}
                    </Combobox.Viewport>
                    <Combobox.ScrollDownButton class="flex w-full items-center justify-center py-1 text-slate-500">
                      <CaretDoubleDown class="size-3" />
                    </Combobox.ScrollDownButton>
                  </Combobox.Content>
                </Combobox.Portal>
              </Combobox.Root>
              <p class="mt-2 text-xs text-slate-500">
                {#if featuresRepoSuggestionsPending}
                  候補を取得中...
                {:else if featuresRepoSuggestions?.default_branch}
                  既定ブランチ: {featuresRepoSuggestions.default_branch}
                {:else}
                  取得元URLを入力するとブランチとコミットの候補を取得します。
                {/if}
              </p>
            </label>
          </div>

          <div class="sticky bottom-0 z-10 mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white/95 py-4 backdrop-blur">
            <p class="text-xs text-slate-500">最終更新: {systemSettings?.updated_at ?? '-'}</p>
            <div class="flex flex-wrap gap-2">
              <button
                class="btn-ghost"
                type="button"
                onclick={refreshPackageSuggestions}
                disabled={systemPending || !systemFeaturesRepoUrl.trim()}
              >
                <ArrowsClockwise size={16} />
                候補を更新
              </button>
              <button
                class="btn-primary"
                type="button"
                onclick={savePackageSettings}
                disabled={systemPending || !systemFeaturesRepoUrl.trim() || !systemFeaturesRepoRef.trim()}
              >
                <FloppyDisk size={16} />
                保存
              </button>
            </div>
          </div>
        </div>
      {/if}
    </div>
  </div>
</section>

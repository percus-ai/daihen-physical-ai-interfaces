<script lang="ts">
  import { Combobox } from 'bits-ui';
  import CaretUpDown from 'phosphor-svelte/lib/CaretUpDown';
  import Check from 'phosphor-svelte/lib/Check';
  import CaretDoubleUp from 'phosphor-svelte/lib/CaretDoubleUp';
  import CaretDoubleDown from 'phosphor-svelte/lib/CaretDoubleDown';

  import type {
    FeaturesRepoSuggestions,
    SystemSettings,
    UserSettings
  } from '$lib/types/settings';

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
      pytorchVersion: string;
      torchvisionVersion: string;
      repoUrl: string;
      repoRef: string;
      repoCommit?: string;
    }) => void | Promise<void>;
    onSaveUserSettings: (payload: {
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

  let systemTorchVersion = $state('');
  let systemTorchvisionVersion = $state('');
  let systemFeaturesRepoUrl = $state('');
  let systemFeaturesRepoRef = $state('');
  let systemFeaturesRepoCommit = $state('');
  let userHuggingFaceToken = $state('');
  let branchOpen = $state(false);
  let commitOpen = $state(false);
  let selectedBranchValue = $state('');
  let selectedCommitValue = $state('');
  let lastHydratedSystemSettingsKey = $state('');

  $effect(() => {
    const nextKey = JSON.stringify({
      updated_at: systemSettings?.updated_at ?? null,
      pytorch_version: systemSettings?.bundled_torch?.pytorch_version ?? '',
      torchvision_version: systemSettings?.bundled_torch?.torchvision_version ?? '',
      repo_url: systemSettings?.features_repo?.repo_url ?? '',
      repo_ref: systemSettings?.features_repo?.repo_ref ?? '',
      repo_commit: systemSettings?.features_repo?.repo_commit ?? ''
    });
    if (!systemSettings || nextKey === lastHydratedSystemSettingsKey) {
      return;
    }

    systemTorchVersion = systemSettings.bundled_torch?.pytorch_version ?? '';
    systemTorchvisionVersion = systemSettings.bundled_torch?.torchvision_version ?? '';
    systemFeaturesRepoUrl = systemSettings.features_repo?.repo_url ?? '';
    systemFeaturesRepoRef = systemSettings.features_repo?.repo_ref ?? '';
    selectedBranchValue = systemSettings.features_repo?.repo_ref ?? '';
    systemFeaturesRepoCommit = systemSettings.features_repo?.repo_commit ?? '';
    selectedCommitValue = systemSettings.features_repo?.repo_commit ?? '';
    lastHydratedSystemSettingsKey = nextKey;
  });

  const saveUserToken = async () => {
    const token = userHuggingFaceToken.trim();
    if (!token) return;
    await onSaveUserSettings({ huggingfaceToken: token, clear: false });
    userHuggingFaceToken = '';
  };

  const visualStatus = (state: 'ready' | 'pending' | 'missing' | 'error') => {
    switch (state) {
      case 'ready':
        return {
          label: 'Configured',
          chip: 'border-emerald-200 bg-emerald-50 text-emerald-700',
          panel: 'border-emerald-200/80 bg-emerald-50/40',
          accent: 'bg-emerald-500',
          input: 'border-emerald-200 focus:border-emerald-400'
        };
      case 'pending':
        return {
          label: 'Saving',
          chip: 'border-amber-200 bg-amber-50 text-amber-700',
          panel: 'border-amber-200/80 bg-amber-50/40',
          accent: 'bg-amber-500',
          input: 'border-amber-200 focus:border-amber-400'
        };
      case 'error':
        return {
          label: 'Error',
          chip: 'border-rose-200 bg-rose-50 text-rose-700',
          panel: 'border-rose-200/80 bg-rose-50/40',
          accent: 'bg-rose-500',
          input: 'border-rose-200 focus:border-rose-400'
        };
      default:
        return {
          label: 'Not Configured',
          chip: 'border-slate-200 bg-slate-100 text-slate-600',
          panel: 'border-slate-200/80 bg-slate-50/70',
          accent: 'bg-slate-300',
          input: 'border-slate-200 focus:border-slate-400'
        };
    }
  };

  const userVisual = $derived(
    visualStatus(
      userError
        ? 'error'
        : userPending
          ? 'pending'
          : userSettings?.huggingface?.has_token
            ? 'ready'
            : 'missing'
    )
  );
  const systemConfigured = $derived(
    Boolean(systemSettings?.bundled_torch?.pytorch_version?.trim()) &&
      Boolean(systemSettings?.bundled_torch?.torchvision_version?.trim())
  );
  const systemVisual = $derived(
    visualStatus(
      systemError
        ? 'error'
        : systemPending
          ? 'pending'
          : systemConfigured
            ? 'ready'
            : 'missing'
    )
  );

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

  const openBranchSuggestions = () => {
    branchOpen = true;
    void onRefreshFeaturesRepoSuggestions({ repoUrl: systemFeaturesRepoUrl, repoRef: systemFeaturesRepoRef });
  };

  const openCommitSuggestions = () => {
    commitOpen = true;
    void onRefreshFeaturesRepoSuggestions({ repoUrl: systemFeaturesRepoUrl, repoRef: systemFeaturesRepoRef });
  };
</script>

<section class="space-y-6">
  <div class={`card border p-6 ${userVisual.panel}`}>
    <div class="flex items-start justify-between gap-4">
      <div class="flex items-start gap-3">
        <div class={`mt-1 h-10 w-1.5 shrink-0 rounded-full ${userVisual.accent}`}></div>
        <div>
          <p class="section-title">User</p>
          <h2 class="mt-2 text-xl font-semibold text-slate-900">User Settings</h2>
          <p class="mt-2 text-sm text-slate-600">ログインユーザー単位の secrets と既定値を管理します。</p>
        </div>
      </div>
      <div class="flex flex-wrap gap-2">
        <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${userVisual.chip}`}>{userVisual.label}</span>
        <span class="chip">{userSettings?.user_id ?? '-'}</span>
      </div>
    </div>

    <div class="mt-5 rounded-2xl border border-slate-200/70 bg-white/80 p-4">
      <p class="label">Hugging Face</p>
      <div class="mt-3 space-y-2 text-sm text-slate-600">
        <p>configured: {userSettings?.huggingface?.has_token ? 'yes' : 'no'}</p>
        <p>preview: {userSettings?.huggingface?.token_preview ?? '-'}</p>
        <p>updated: {userSettings?.huggingface?.updated_at ?? '-'}</p>
      </div>
    </div>

    {#if userError}
      <div class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{userError}</div>
    {/if}
    {#if userSuccess}
      <div class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{userSuccess}</div>
    {/if}

    <div class="mt-4 grid gap-3">
      <label class="text-sm text-slate-600">
        <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">HF token</span>
        <input
          bind:value={userHuggingFaceToken}
          class={`w-full rounded-xl border bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none ${userVisual.input}`}
          placeholder="hf_xxx..."
          disabled={userPending}
        />
      </label>
      <div class="flex flex-wrap gap-2">
        <button
          class="btn-primary"
          type="button"
          onclick={saveUserToken}
          disabled={userPending || !userHuggingFaceToken.trim()}
        >
          保存
        </button>
        <button
          class="btn-ghost"
          type="button"
          onclick={() => {
            userHuggingFaceToken = '';
            onSaveUserSettings({ clear: true });
          }}
          disabled={userPending || !userSettings?.huggingface?.has_token}
        >
          token を削除
        </button>
      </div>
    </div>
  </div>

  <div class={`card border p-6 ${systemVisual.panel}`}>
    <div class="flex items-start justify-between gap-4">
      <div class="flex items-start gap-3">
        <div class={`mt-1 h-10 w-1.5 shrink-0 rounded-full ${systemVisual.accent}`}></div>
        <div>
          <p class="section-title">System</p>
          <h2 class="mt-2 text-xl font-semibold text-slate-900">System Settings</h2>
          <p class="mt-2 text-sm text-slate-600">コンピュータ単位の既定値を管理します。</p>
        </div>
      </div>
      <span class={`rounded-full border px-3 py-1 text-xs font-semibold ${systemVisual.chip}`}>{systemVisual.label}</span>
    </div>

    <div class="mt-5 rounded-2xl border border-slate-200/70 bg-white/80 p-4">
      <p class="label">Bundled Torch defaults</p>
      <div class="mt-3 space-y-2 text-sm text-slate-600">
        <p>pytorch: {systemSettings?.bundled_torch?.pytorch_version ?? '-'}</p>
        <p>torchvision: {systemSettings?.bundled_torch?.torchvision_version ?? '-'}</p>
        <p>features repo: {systemSettings?.features_repo?.repo_url ?? '-'}</p>
        <p>branch: {systemSettings?.features_repo?.repo_ref ?? '-'}</p>
        <p>commit: {systemSettings?.features_repo?.repo_commit ?? '-'}</p>
        <p>updated: {systemSettings?.updated_at ?? '-'}</p>
      </div>
    </div>

    {#if systemError}
      <div class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{systemError}</div>
    {/if}
    {#if systemSuccess}
      <div class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{systemSuccess}</div>
    {/if}

    <div class="mt-4 grid gap-3">
      <label class="text-sm text-slate-600">
        <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Default PyTorch version</span>
        <input
          bind:value={systemTorchVersion}
          class={`w-full rounded-xl border bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none ${systemVisual.input}`}
          disabled={systemPending}
        />
      </label>
      <label class="text-sm text-slate-600">
        <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Default torchvision version</span>
        <input
          bind:value={systemTorchvisionVersion}
          class={`w-full rounded-xl border bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none ${systemVisual.input}`}
          disabled={systemPending}
        />
      </label>
      <label class="text-sm text-slate-600">
        <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Features repo URL</span>
        <input
          bind:value={systemFeaturesRepoUrl}
          class={`w-full rounded-xl border bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none ${systemVisual.input}`}
          disabled={systemPending}
          onblur={() => onRefreshFeaturesRepoSuggestions({ repoUrl: systemFeaturesRepoUrl, repoRef: systemFeaturesRepoRef })}
        />
      </label>
      <label class="text-sm text-slate-600">
        <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Features repo branch</span>
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
              class={`w-full rounded-xl border bg-white px-3 py-2 pr-10 text-sm text-slate-900 focus:outline-none ${systemVisual.input}`}
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
              aria-label="Features repo branch 候補を開く"
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
                  <div class="px-3 py-2 text-xs text-slate-500">一致する branch がありません。</div>
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
      <label class="text-sm text-slate-600">
        <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Features repo commit</span>
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
              class={`w-full rounded-xl border bg-white px-3 py-2 pr-10 text-sm text-slate-900 focus:outline-none ${systemVisual.input}`}
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
              aria-label="Features repo commit 候補を開く"
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
                  <div class="px-3 py-2 text-xs text-slate-500">一致する commit がありません。</div>
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
            GitHub から候補を取得中...
          {:else if featuresRepoSuggestions?.default_branch}
            default branch: {featuresRepoSuggestions.default_branch}
          {:else}
            repo URL を入力すると branch / commit 候補を取得します。
          {/if}
        </p>
      </label>
      <div class="flex flex-wrap gap-2">
        <button
          class="btn-primary"
          type="button"
          onclick={() => onSaveSystemSettings({
            pytorchVersion: systemTorchVersion,
            torchvisionVersion: systemTorchvisionVersion,
            repoUrl: systemFeaturesRepoUrl,
            repoRef: systemFeaturesRepoRef,
            repoCommit: systemFeaturesRepoCommit
          })}
          disabled={systemPending || !systemTorchVersion.trim() || !systemTorchvisionVersion.trim() || !systemFeaturesRepoUrl.trim() || !systemFeaturesRepoRef.trim()}
        >
          保存
        </button>
        <button
          class="btn-ghost"
          type="button"
          onclick={() => onRefreshFeaturesRepoSuggestions({ repoUrl: systemFeaturesRepoUrl, repoRef: systemFeaturesRepoRef })}
          disabled={systemPending || !systemFeaturesRepoUrl.trim()}
        >
          候補を更新
        </button>
      </div>
    </div>
  </div>
</section>

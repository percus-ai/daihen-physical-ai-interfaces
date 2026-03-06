<script lang="ts">
  import type { SystemSettings, UserSettings } from '$lib/types/settings';

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
    }) => void | Promise<void>;
    onSaveUserSettings: (payload: {
      huggingfaceToken?: string;
      clear?: boolean;
    }) => void | Promise<void>;
  } = $props();

  let systemTorchVersion = $state('');
  let systemTorchvisionVersion = $state('');
  let userHuggingFaceToken = $state('');

  $effect(() => {
    if (systemSettings?.bundled_torch?.pytorch_version && !systemTorchVersion) {
      systemTorchVersion = systemSettings.bundled_torch.pytorch_version;
    }
    if (systemSettings?.bundled_torch?.torchvision_version && !systemTorchvisionVersion) {
      systemTorchvisionVersion = systemSettings.bundled_torch.torchvision_version;
    }
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
      <div class="flex flex-wrap gap-2">
        <button
          class="btn-primary"
          type="button"
          onclick={() => onSaveSystemSettings({
            pytorchVersion: systemTorchVersion,
            torchvisionVersion: systemTorchvisionVersion
          })}
          disabled={systemPending || !systemTorchVersion.trim() || !systemTorchvisionVersion.trim()}
        >
          保存
        </button>
      </div>
    </div>
  </div>
</section>

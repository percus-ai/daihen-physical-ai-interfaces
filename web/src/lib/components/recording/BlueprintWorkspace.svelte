<script lang="ts">
  import { onDestroy } from 'svelte';
  import { Button } from 'bits-ui';
  import toast from 'svelte-french-toast';

  import BlueprintCombobox from '$lib/components/blueprints/BlueprintCombobox.svelte';
  import { loadBlueprintDraft, saveBlueprintDraft, type BlueprintSessionKind } from '$lib/blueprints/draftStorage';
  import {
    createBlueprintManager,
    type WebuiBlueprintDetail,
    type WebuiBlueprintSummary
  } from '$lib/blueprints/blueprintManager';
  import type { BlueprintNode } from '$lib/recording/blueprint';

  let {
    sessionId = '',
    sessionKind = '' as BlueprintSessionKind | '',
    blueprint,
    persistDraft = true,
    disabled = false,
    onApplyBlueprintDetail = undefined
  }: {
    sessionId?: string;
    sessionKind?: BlueprintSessionKind | '';
    blueprint: BlueprintNode;
    persistDraft?: boolean;
    disabled?: boolean;
    onApplyBlueprintDetail?: (detail: { id: string; name: string; blueprint: BlueprintNode }) => void;
  } = $props();

  let activeBlueprintId = $state('');
  let activeBlueprintName = $state('');
  let savedBlueprints = $state<WebuiBlueprintSummary[]>([]);
  let blueprintBusy = $state(false);
  let blueprintActionPending = $state(false);
  let lastResolveSignature = $state('');

  const notifyError = (message: string) => {
    if (!message || typeof window === 'undefined') return;
    toast.error(message);
  };

  const notifyNotice = (message: string) => {
    if (!message || typeof window === 'undefined') return;
    toast.success(message);
  };

  const applyBlueprintDetail = (detail: WebuiBlueprintDetail, useDraft: boolean, kind: BlueprintSessionKind) => {
    activeBlueprintId = detail.id;
    activeBlueprintName = detail.name;

    let nextBlueprint = detail.blueprint;
    if (persistDraft && useDraft && sessionId) {
      const draft = loadBlueprintDraft(kind, sessionId, detail.id);
      if (draft) nextBlueprint = draft;
    }

    onApplyBlueprintDetail?.({
      id: detail.id,
      name: detail.name,
      blueprint: nextBlueprint
    });
  };

  const blueprintManager = createBlueprintManager({
    getSessionId: () => sessionId,
    getSessionKind: () => sessionKind,
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
      notifyError(message);
    },
    setNotice: (message) => {
      notifyNotice(message);
    },
    applyBlueprintDetail
  });

  const resolveSessionBlueprint = blueprintManager.resolveSessionBlueprint;
  const handleOpenBlueprint = blueprintManager.openBlueprint;
  const handleSaveBlueprint = blueprintManager.saveBlueprint;
  const handleDuplicateBlueprint = blueprintManager.duplicateBlueprint;
  const handleDeleteBlueprint = blueprintManager.deleteBlueprint;
  const handleResetBlueprint = blueprintManager.resetBlueprint;

  const handleSaveBlueprintWithToast = async () => {
    if (typeof window === 'undefined') {
      await handleSaveBlueprint();
      return;
    }
    const loadingToastId = toast.loading('保存中...');
    try {
      await handleSaveBlueprint();
    } finally {
      toast.dismiss(loadingToastId);
    }
  };

  $effect(() => {
    const nextDisabled = disabled || blueprintBusy || blueprintActionPending || !sessionKind;
    // When disabled, don't auto-resolve or auto-save.
    if (nextDisabled) return;
    if (!sessionId || !sessionKind) return;
    const signature = `${sessionKind}:${sessionId}`;
    if (signature === lastResolveSignature) return;
    lastResolveSignature = signature;
    void resolveSessionBlueprint();
  });

  $effect(() => {
    if (disabled) return;
    if (!persistDraft) return;
    if (!sessionId || !sessionKind || !activeBlueprintId) return;
    saveBlueprintDraft(sessionKind, sessionId, activeBlueprintId, blueprint);
  });

  onDestroy(() => {
    // Nothing to cleanup inside blueprintManager yet, but keep onDestroy in place for future refactors.
  });
</script>

<div class="rounded-xl border border-slate-200/60 bg-white/70 p-3">
  <div class="flex flex-wrap items-end gap-3">
    <div class="min-w-[240px] flex-1">
      <p class="label">保存済みブループリント</p>
      <div class="mt-2">
        <BlueprintCombobox
          items={savedBlueprints}
          value={activeBlueprintId}
          disabled={disabled || blueprintBusy || blueprintActionPending || !sessionKind}
          onSelect={handleOpenBlueprint}
        />
      </div>
    </div>

    <label class="min-w-[220px] flex-1 text-xs font-semibold text-slate-600">
      <span>名前</span>
      <input class="input mt-1" type="text" bind:value={activeBlueprintName} />
    </label>

    <div class="flex flex-wrap gap-2">
      <Button.Root
        class="btn-primary"
        type="button"
        disabled={disabled || blueprintBusy || blueprintActionPending || !activeBlueprintId || !sessionKind}
        onclick={() => {
          void handleSaveBlueprintWithToast();
        }}
      >
        保存
      </Button.Root>
      <Button.Root
        class="btn-ghost"
        type="button"
        disabled={disabled || blueprintBusy || blueprintActionPending || !activeBlueprintId || !sessionKind}
        onclick={handleDuplicateBlueprint}
      >
        複製
      </Button.Root>
      <Button.Root
        class="btn-ghost"
        type="button"
        disabled={disabled || blueprintBusy || blueprintActionPending || !activeBlueprintId || !sessionKind}
        onclick={handleResetBlueprint}
      >
        リセット
      </Button.Root>
      <Button.Root
        class="btn-ghost border-rose-200/70 text-rose-600 hover:border-rose-300/80"
        type="button"
        disabled={disabled || blueprintBusy || blueprintActionPending || !activeBlueprintId || !sessionKind}
        onclick={handleDeleteBlueprint}
      >
        削除
      </Button.Root>
    </div>
  </div>
  <p class="mt-2 text-[11px] text-slate-500">
    {persistDraft ? '編集中の内容はローカルに自動保存されます。' : 'ドラフトの自動保存は無効です。'}
  </p>
</div>


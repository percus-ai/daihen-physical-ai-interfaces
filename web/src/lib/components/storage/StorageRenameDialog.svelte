<script lang="ts">
  import { Button, Dialog } from 'bits-ui';

  type RenameItemKind = 'dataset' | 'model';

  type Props = {
    open?: boolean;
    itemKind: RenameItemKind;
    currentName: string;
    pending?: boolean;
    errorMessage?: string;
    onConfirm?: (nextName: string) => Promise<unknown>;
  };

  let {
    open = $bindable(false),
    itemKind,
    currentName,
    pending = false,
    errorMessage = '',
    onConfirm
  }: Props = $props();

  let draftName = $state('');
  let localError = $state('');

  const itemKindLabel = $derived(itemKind === 'model' ? 'モデル' : 'データセット');
  const visibleError = $derived(localError || errorMessage);

  $effect(() => {
    if (!open) {
      localError = '';
      return;
    }
    draftName = currentName;
    localError = '';
  });

  const handleSubmit = async (event?: SubmitEvent) => {
    event?.preventDefault();
    if (!onConfirm || pending) return;

    const nextName = draftName.trim();
    if (!nextName) {
      localError = '名前を入力してください。';
      return;
    }

    localError = '';
    await onConfirm(nextName);
  };
</script>

<Dialog.Root bind:open={open}>
  <Dialog.Portal>
    <Dialog.Overlay class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]" />
    <Dialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,30rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-5 shadow-xl outline-none"
    >
      <form onsubmit={handleSubmit}>
        <div class="flex items-start justify-between gap-4">
          <div>
            <Dialog.Title class="text-base font-semibold text-slate-900">
              {itemKindLabel}名を変更
            </Dialog.Title>
            <Dialog.Description class="mt-2 text-sm text-slate-600">
              表示名のみ更新します。ID は変わりません。
            </Dialog.Description>
          </div>
          <button
            class="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
            type="button"
            disabled={pending}
            onclick={() => (open = false)}
          >
            閉じる
          </button>
        </div>

        <div class="mt-5">
          <label class="label" for="storage-rename-name">名前</label>
          <input
            id="storage-rename-name"
            class="input mt-2"
            type="text"
            bind:value={draftName}
            maxlength="64"
            placeholder="new_name"
            disabled={pending}
            oninput={() => {
              localError = '';
            }}
          />
        </div>

        {#if visibleError}
          <p class="mt-3 text-sm text-rose-600">{visibleError}</p>
        {/if}

        <div class="mt-5 flex items-center justify-end gap-2">
          <button class="btn-ghost" type="button" disabled={pending} onclick={() => (open = false)}>
            キャンセル
          </button>
          <Button.Root class="btn-primary" type="submit" disabled={pending}>
            {pending ? '保存中...' : '保存'}
          </Button.Root>
        </div>
      </form>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

<script lang="ts">
  import { Button, Dialog } from 'bits-ui';

  type Props = {
    open?: boolean;
    selectedCount: number;
    suggestedName: string;
    profileName?: string;
    pending?: boolean;
    errorMessage?: string;
    onConfirm?: (datasetName: string) => Promise<unknown> | unknown;
  };

  let {
    open = $bindable(false),
    selectedCount,
    suggestedName,
    profileName = '',
    pending = false,
    errorMessage = '',
    onConfirm
  }: Props = $props();

  let draftName = $state('');
  let localError = $state('');

  const visibleError = $derived(localError || errorMessage);

  $effect(() => {
    if (!open) {
      localError = '';
      return;
    }
    draftName = suggestedName;
    localError = '';
  });

  const handleSubmit = async (event?: SubmitEvent) => {
    event?.preventDefault();
    if (!onConfirm || pending) return;

    const nextName = draftName.trim();
    if (!nextName) {
      localError = 'マージ先データセット名を入力してください。';
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
        <div>
          <div>
            <Dialog.Title class="text-base font-semibold text-slate-900">
              データセットをマージ
            </Dialog.Title>
            <Dialog.Description class="mt-2 text-sm text-slate-600">
              {selectedCount} 件のデータセットを 1 つにまとめます。
            </Dialog.Description>
            {#if profileName}
              <p class="mt-2 text-xs text-slate-500">対象プロファイル: {profileName}</p>
            {/if}
          </div>
        </div>

        <div class="mt-5">
          <label class="label" for="dataset-merge-name">マージ先データセット名</label>
          <input
            id="dataset-merge-name"
            class="input mt-2"
            type="text"
            bind:value={draftName}
            maxlength="64"
            placeholder="merged_dataset"
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
            {pending ? '開始中...' : 'マージ開始'}
          </Button.Root>
        </div>
      </form>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

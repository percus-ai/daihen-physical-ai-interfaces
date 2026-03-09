<script lang="ts">
  import { AlertDialog, Button } from 'bits-ui';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';

  type ArchiveItemKind = 'dataset' | 'model';

  type Props = {
    open?: boolean;
    itemKind: ArchiveItemKind;
    itemLabel: string;
    pending?: boolean;
    errorMessage?: string;
    onConfirm?: () => Promise<unknown>;
  };

  let {
    open = $bindable(false),
    itemKind,
    itemLabel,
    pending = false,
    errorMessage = '',
    onConfirm
  }: Props = $props();

  const itemKindLabel = $derived(itemKind === 'model' ? 'モデル' : 'データセット');
  const description = $derived.by(() => {
    const syncNote = itemKind === 'model' ? ' 同期中の場合は中断を要求します。' : '';
    return `${itemLabel} をアーカイブしますか？${syncNote}`;
  });

  const handleConfirm = async () => {
    if (!onConfirm || pending) return;
    await onConfirm();
  };
</script>

<AlertDialog.Root bind:open={open}>
  <AlertDialog.Portal>
    <AlertDialog.Overlay class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]" />
    <AlertDialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      <AlertDialog.Title class="text-base font-semibold text-slate-900">
        {itemKindLabel}をアーカイブ
      </AlertDialog.Title>
      <AlertDialog.Description class="mt-2 text-sm text-slate-600">
        {description}
      </AlertDialog.Description>
      {#if errorMessage}
        <p class="mt-3 text-sm text-rose-600">{errorMessage}</p>
      {/if}

      <div class="mt-5 flex items-center justify-end gap-2">
        <AlertDialog.Cancel class="btn-ghost" type="button" disabled={pending}>
          キャンセル
        </AlertDialog.Cancel>
        <Button.Root class="btn-primary" type="button" disabled={pending} onclick={handleConfirm}>
          {pending ? 'アーカイブ中...' : 'アーカイブ'}
        </Button.Root>
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>

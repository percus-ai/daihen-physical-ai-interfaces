<script lang="ts">
  import { AlertDialog, Button } from 'bits-ui';

  import { preventModalAutoFocus } from '$lib/components/modal/focus';

  type Props = {
    open?: boolean;
    reportId?: string;
    settingId?: string;
    pending?: boolean;
    errorMessage?: string;
    onCopy?: (reportId: string) => Promise<void> | void;
  };

  let {
    open = $bindable(false),
    reportId = '',
    settingId = '',
    pending = false,
    errorMessage = '',
    onCopy
  }: Props = $props();

  let copied = $state(false);

  const handleCopy = async () => {
    if (!reportId || !onCopy) return;
    await onCopy(reportId);
    copied = true;
    window.setTimeout(() => {
      copied = false;
    }, 1800);
  };
</script>

<AlertDialog.Root bind:open={open}>
  <AlertDialog.Portal>
    <AlertDialog.Overlay class="fixed inset-0 z-40 bg-slate-900/45 backdrop-blur-[1px]" />
    <AlertDialog.Content
      class="fixed left-1/2 top-1/2 z-50 w-[min(92vw,32rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      <AlertDialog.Title class="text-base font-semibold text-slate-900">エラーレポート</AlertDialog.Title>
      <AlertDialog.Description class="mt-2 text-sm text-slate-600">
        {#if settingId}
          {settingId} の失敗レポートを作成しました。管理者には次のレポートIDを伝えてください。
        {:else}
          失敗レポートを作成しました。管理者には次のレポートIDを伝えてください。
        {/if}
      </AlertDialog.Description>

      <div class="mt-4 nested-block-pane p-4">
        {#if pending}
          <p class="text-sm text-slate-500">レポートを作成しています...</p>
        {:else if errorMessage}
          <p class="text-sm text-rose-600">{errorMessage}</p>
        {:else}
          <p class="label">レポートID</p>
          <div class="mt-2 flex items-center gap-2">
            <code class="min-w-0 flex-1 overflow-x-auto rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-slate-100">
              {reportId}
            </code>
            <Button.Root class="btn-primary shrink-0" type="button" onclick={handleCopy}>
              {copied ? 'コピー済み' : 'コピー'}
            </Button.Root>
          </div>
        {/if}
      </div>

      <div class="mt-5 flex items-center justify-end gap-2">
        <AlertDialog.Cancel class="btn-ghost" type="button" onclick={() => (open = false)}>
          閉じる
        </AlertDialog.Cancel>
      </div>
    </AlertDialog.Content>
  </AlertDialog.Portal>
</AlertDialog.Root>

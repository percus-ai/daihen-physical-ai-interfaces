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

      <div class="mt-4">
        {#if pending}
          <p class="text-sm text-slate-500">レポートを作成しています...</p>
        {:else if errorMessage}
          <p class="text-sm text-rose-600">{errorMessage}</p>
        {:else}
          <p class="label">レポートID</p>
          <div class="mt-2 flex items-center gap-2">
            <code class="min-w-0 flex-1 overflow-x-auto text-sm font-semibold text-slate-900">
              {reportId}
            </code>
            <Button.Root class="btn-ghost inline-flex h-10 w-10 shrink-0 items-center justify-center p-0" type="button" onclick={handleCopy} aria-label="レポートIDをコピー">
              {#if copied}
                <svg viewBox="0 0 16 16" class="h-4 w-4" aria-hidden="true">
                  <path
                    d="M3.5 8.5 6.5 11.5 12.5 4.5"
                    fill="none"
                    stroke="currentColor"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="1.5"
                  />
                </svg>
              {:else}
                <svg viewBox="0 0 16 16" class="h-4 w-4" aria-hidden="true">
                  <rect x="5" y="3" width="8" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5" />
                  <path
                    d="M3.5 10.5H3A1.5 1.5 0 0 1 1.5 9V4A1.5 1.5 0 0 1 3 2.5h5A1.5 1.5 0 0 1 9.5 4v.5"
                    fill="none"
                    stroke="currentColor"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="1.5"
                  />
                </svg>
              {/if}
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

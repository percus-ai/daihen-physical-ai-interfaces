<script lang="ts">
  import { Dialog } from 'bits-ui';
  import type { Snippet } from 'svelte';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';

  let {
    open = $bindable(false),
    zIndexBase = 80,
    inset = '0.75rem',
    contentClass = '',
    children
  }: {
    open?: boolean;
    zIndexBase?: number;
    inset?: string;
    contentClass?: string;
    // Svelte 5 passes component children via this prop.
    children?: Snippet;
  } = $props();

  const zOverlay = $derived(Math.max(0, Math.floor(Number(zIndexBase) || 0)));
  const zContent = $derived(zOverlay + 1);

</script>

<Dialog.Root bind:open={open}>
  <Dialog.Portal>
    <Dialog.Overlay
      class="fixed inset-0 bg-slate-900/45 backdrop-blur-[1px]"
      style={`z-index:${zOverlay};`}
    />
    <Dialog.Content
      class={`fixed overflow-hidden rounded-2xl border border-slate-200/70 bg-white p-4 shadow-xl outline-none ${contentClass}`}
      style={`inset:${inset};z-index:${zContent};`}
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      {@render children?.()}
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

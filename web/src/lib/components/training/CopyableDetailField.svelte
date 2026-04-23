<script lang="ts">
  import Check from 'phosphor-svelte/lib/Check';
  import Copy from 'phosphor-svelte/lib/Copy';

  let {
    label,
    value,
    copyText,
    copyable = false,
    mono = false,
    breakAll = false,
    title
  }: {
    label: string;
    value?: string | number | null;
    copyText?: string | number | null;
    copyable?: boolean;
    mono?: boolean;
    breakAll?: boolean;
    title?: string;
  } = $props();

  let copied = $state(false);

  const displayValue = $derived(
    value === null || value === undefined || String(value).trim() === '' ? '-' : String(value)
  );
  const resolvedCopyText = $derived(
    copyText === null || copyText === undefined
      ? value === null || value === undefined
        ? ''
        : String(value)
      : String(copyText)
  );
  const canCopy = $derived(copyable && Boolean(resolvedCopyText.trim()));
  const valueClass = $derived(
    [
      'font-semibold text-slate-800',
      breakAll ? 'break-all' : 'break-words',
      mono ? 'font-mono text-[13px]' : ''
    ]
      .filter(Boolean)
      .join(' ')
  );

  const copyValue = async () => {
    const text = resolvedCopyText.trim();
    if (!canCopy || !text) return;
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
      window.setTimeout(() => {
        copied = false;
      }, 1500);
    } catch {
      copied = false;
    }
  };
</script>

<div class="min-w-0">
  <dt class="text-xs font-semibold text-slate-500">{label}</dt>
  <dd class="mt-1 min-w-0">
    <span class={valueClass} title={title ?? (displayValue === '-' ? '' : displayValue)}>
      {displayValue}
    </span>
    {#if canCopy}
      <button
        class="ml-1 inline-flex h-5 w-5 shrink-0 items-center justify-center align-middle rounded border border-transparent bg-transparent text-slate-400 transition hover:border-slate-300 hover:bg-white/60 hover:text-slate-700 focus-visible:border-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/20"
        type="button"
        aria-label={`${label}をコピー`}
        title={`${label}をコピー`}
        onclick={() => void copyValue()}
      >
        {#if copied}
          <Check size={12} weight="bold" />
        {:else}
          <Copy size={12} weight="bold" />
        {/if}
      </button>
    {/if}
  </dd>
</div>

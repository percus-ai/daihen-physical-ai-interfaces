<script lang="ts">
  import FunnelSimple from 'phosphor-svelte/lib/FunnelSimple';
  import { Button, Popover } from 'bits-ui';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';
  import { resolveFilterValues, type ListFilterField } from '$lib/listFilters';

  type Props = {
    open?: boolean;
    fields: ListFilterField[];
    values: Record<string, string>;
    defaults: Record<string, string>;
    active?: boolean;
    align?: 'start' | 'center' | 'end';
    sideOffset?: number;
    pending?: boolean;
    onApply?: (nextValues: Record<string, string>) => Promise<unknown> | unknown;
  };

  let {
    open = $bindable(false),
    fields,
    values,
    defaults,
    active = false,
    align = 'end',
    sideOffset = 10,
    pending = false,
    onApply
  }: Props = $props();

  let draftValues = $state<Record<string, string>>({});

  const triggerBaseClass = 'inline-flex h-10 items-center justify-center gap-2 rounded-full border px-4 text-sm font-semibold transition';
  const triggerClass = $derived(
    active
      ? `${triggerBaseClass} border-brand/30 bg-brand/10 text-brand-ink hover:border-brand/50 hover:bg-brand/15`
      : `${triggerBaseClass} border-slate-200 bg-white text-slate-600 hover:border-brand/40 hover:text-brand`
  );

  $effect(() => {
    if (!open) return;
    draftValues = resolveFilterValues(fields, values, defaults);
  });

  const updateDraftValue = (key: string, value: string) => {
    draftValues = {
      ...draftValues,
      [key]: value
    };
  };

  const resetDraft = () => {
    draftValues = resolveFilterValues(fields, defaults, defaults);
  };

  const hasChanges = $derived.by(() =>
    fields.some((field) => (draftValues[field.key] ?? '') !== (values[field.key] ?? defaults[field.key] ?? ''))
  );
  const canClear = $derived.by(() =>
    fields.some((field) => (draftValues[field.key] ?? defaults[field.key] ?? '') !== (defaults[field.key] ?? ''))
  );

  const handleApply = async (event?: SubmitEvent) => {
    event?.preventDefault();
    if (!onApply || pending || !hasChanges) return;
    await onApply(resolveFilterValues(fields, draftValues, defaults));
  };

  const handleClear = () => {
    if (pending || !canClear) return;
    resetDraft();
  };
</script>

<Popover.Root bind:open={open}>
  <Popover.Trigger class={triggerClass}>
    <FunnelSimple size={16} />
    フィルタ
  </Popover.Trigger>
  <Popover.Portal>
    <Popover.Content
      class="z-50 w-[min(92vw,26rem)] rounded-3xl border border-slate-200 bg-white p-5 shadow-xl outline-none"
      {align}
      sideOffset={sideOffset}
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      <form onsubmit={handleApply}>
        <div class="flex items-center justify-between gap-3">
          <h3 class="text-sm font-semibold text-slate-900">フィルタ</h3>
        </div>

        <div class="mt-4 space-y-4">
          {#each fields as field (field.key)}
            <label class="block text-sm text-slate-700">
              <span class="label">{field.label}</span>
              {#if field.type === 'text'}
                <input
                  class="input mt-2"
                  type="text"
                  value={draftValues[field.key] ?? ''}
                  placeholder={field.placeholder ?? ''}
                  disabled={pending}
                  oninput={(event) => updateDraftValue(field.key, event.currentTarget.value)}
                />
              {:else}
                <select
                  class="input mt-2"
                  value={draftValues[field.key] ?? ''}
                  disabled={pending}
                  onchange={(event) => updateDraftValue(field.key, event.currentTarget.value)}
                >
                  {#each field.options as option}
                    <option value={option.value}>{option.label}</option>
                  {/each}
                </select>
              {/if}
            </label>
          {/each}
        </div>

        <div class="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-4">
          <div class="flex flex-wrap items-center gap-2">
            <Button.Root class="btn-primary" type="submit" disabled={pending || !hasChanges}>
              {pending ? '適用中...' : '適用'}
            </Button.Root>
            <button class="btn-ghost" type="button" disabled={pending || !canClear} onclick={handleClear}>クリア</button>
          </div>
          <button
            class="inline-flex h-10 items-center justify-center rounded-full border border-slate-200 px-4 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
            type="button"
            onclick={() => (open = false)}
          >
            閉じる
          </button>
        </div>
      </form>
    </Popover.Content>
  </Popover.Portal>
</Popover.Root>

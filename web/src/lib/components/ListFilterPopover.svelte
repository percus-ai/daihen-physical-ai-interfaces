<script lang="ts">
  import FunnelSimple from 'phosphor-svelte/lib/FunnelSimple';
  import { Button, Dialog } from 'bits-ui';
  import { preventModalAutoFocus } from '$lib/components/modal/focus';
  import { getFieldKeys, resolveFilterValues, type ListFilterField } from '$lib/listFilters';

  type Props = {
    open?: boolean;
    fields: ListFilterField[];
    values: Record<string, string>;
    defaults: Record<string, string>;
    active?: boolean;
    pending?: boolean;
    onApply?: (nextValues: Record<string, string>) => Promise<unknown> | unknown;
  };

  let {
    open = $bindable(false),
    fields,
    values,
    defaults,
    active = false,
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

  const sections = $derived.by(() => {
    const orderedSections: string[] = [];
    const fieldsBySection = new Map<string, ListFilterField[]>();
    for (const field of fields) {
      const section = field.section ?? '条件';
      if (!fieldsBySection.has(section)) {
        orderedSections.push(section);
        fieldsBySection.set(section, []);
      }
      fieldsBySection.get(section)?.push(field);
    }
    return orderedSections.map((section) => ({
      section,
      fields: fieldsBySection.get(section) ?? []
    }));
  });

  const resetDraft = () => {
    draftValues = resolveFilterValues(fields, defaults, defaults);
  };

  const hasChanges = $derived.by(() =>
    fields.some((field) =>
      getFieldKeys(field).some((key) => (draftValues[key] ?? '') !== (values[key] ?? defaults[key] ?? ''))
    )
  );
  const canClear = $derived.by(() =>
    fields.some((field) =>
      getFieldKeys(field).some((key) => (draftValues[key] ?? defaults[key] ?? '') !== (defaults[key] ?? ''))
    )
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

<Dialog.Root bind:open={open}>
  <Dialog.Trigger class={triggerClass}>
    <FunnelSimple size={16} />
    表示設定
  </Dialog.Trigger>
  <Dialog.Portal>
    <Dialog.Overlay class="fixed inset-0 z-40 bg-slate-900/30 backdrop-blur-[1px]" />
    <Dialog.Content
      class="fixed inset-y-0 right-0 z-50 flex w-[min(92vw,30rem)] flex-col border-l border-slate-200 bg-white shadow-2xl outline-none"
      onOpenAutoFocus={preventModalAutoFocus}
      onCloseAutoFocus={preventModalAutoFocus}
    >
      <form class="flex h-full flex-col" onsubmit={handleApply}>
        <div class="border-b border-slate-200 px-5 py-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <Dialog.Title class="text-base font-semibold text-slate-900">表示設定</Dialog.Title>
              <Dialog.Description class="mt-1 text-sm text-slate-600">
                一覧の表示条件をまとめて変更します。
              </Dialog.Description>
            </div>
          </div>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <div class="space-y-5">
            {#each sections as { section, fields: sectionFields } (section)}
              <section>
                <h4 class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{section}</h4>
                <div class="mt-3 space-y-4">
                  {#each sectionFields as field (`${section}:${field.label}`)}
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
                      {:else if field.type === 'select'}
                        <select
                          class="input mt-2"
                          value={draftValues[field.key] ?? ''}
                          disabled={pending}
                          onchange={(event) => updateDraftValue(field.key, event.currentTarget.value)}
                        >
                          {#each field.options as option}
                            <option value={option.value} disabled={option.disabled}>{option.label}</option>
                          {/each}
                        </select>
                      {:else if field.type === 'date-range'}
                        <div class="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
                          <input
                            class="input"
                            type="date"
                            value={draftValues[field.keyFrom] ?? ''}
                            placeholder={field.placeholderFrom ?? ''}
                            disabled={pending}
                            oninput={(event) => updateDraftValue(field.keyFrom, event.currentTarget.value)}
                          />
                          <span class="text-center text-xs font-semibold text-slate-400">〜</span>
                          <input
                            class="input"
                            type="date"
                            value={draftValues[field.keyTo] ?? ''}
                            placeholder={field.placeholderTo ?? ''}
                            disabled={pending}
                            oninput={(event) => updateDraftValue(field.keyTo, event.currentTarget.value)}
                          />
                        </div>
                      {:else}
                        <div class="mt-2 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
                          <input
                            class="input"
                            type="number"
                            value={draftValues[field.keyMin] ?? ''}
                            placeholder={field.placeholderMin ?? ''}
                            min={field.min}
                            max={field.max}
                            step={field.step ?? 1}
                            disabled={pending}
                            oninput={(event) => updateDraftValue(field.keyMin, event.currentTarget.value)}
                          />
                          <span class="text-center text-xs font-semibold text-slate-400">〜</span>
                          <input
                            class="input"
                            type="number"
                            value={draftValues[field.keyMax] ?? ''}
                            placeholder={field.placeholderMax ?? ''}
                            min={field.min}
                            max={field.max}
                            step={field.step ?? 1}
                            disabled={pending}
                            oninput={(event) => updateDraftValue(field.keyMax, event.currentTarget.value)}
                          />
                        </div>
                      {/if}
                    </label>
                  {/each}
                </div>
              </section>
            {/each}
          </div>
        </div>

        <div class="border-t border-slate-200 bg-white px-5 py-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
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
        </div>
      </form>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

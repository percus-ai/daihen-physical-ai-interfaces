<script lang="ts">
  import { Combobox } from 'bits-ui';
  import CaretUpDown from 'phosphor-svelte/lib/CaretUpDown';
  import Check from 'phosphor-svelte/lib/Check';
  import CaretDoubleUp from 'phosphor-svelte/lib/CaretDoubleUp';
  import CaretDoubleDown from 'phosphor-svelte/lib/CaretDoubleDown';

  export type FilterCandidateItem = {
    value: string;
    label: string;
  };

  let {
    items,
    value = '',
    inputValue = '',
    disabled = false,
    placeholder = '候補を検索',
    emptyMessage = '一致する候補がありません。',
    onSelect,
    onInput
  }: {
    items: FilterCandidateItem[];
    value?: string;
    inputValue?: string;
    disabled?: boolean;
    placeholder?: string;
    emptyMessage?: string;
    onSelect?: (value: string) => void | Promise<void>;
    onInput?: (value: string) => void | Promise<void>;
  } = $props();

  let searchValue = $state('');

  const filteredItems = $derived.by(() => {
    if (!searchValue.trim()) return items;
    const normalizedQuery = searchValue.toLowerCase();
    return items.filter((item) => item.label.toLowerCase().includes(normalizedQuery));
  });

  const handleInput = (event: Event) => {
    const nextValue = (event.currentTarget as HTMLInputElement).value;
    searchValue = nextValue;
    void onInput?.(nextValue);
  };

  const handleValueChange = (nextValue: string) => {
    if (!nextValue) return;
    const matchedItem = items.find((item) => item.value === nextValue);
    searchValue = matchedItem?.label ?? nextValue;
    void onSelect?.(nextValue);
  };

  $effect(() => {
    inputValue;
    searchValue = inputValue;
  });
</script>

<Combobox.Root
  type="single"
  {value}
  inputValue={searchValue}
  onValueChange={handleValueChange}
  items={items}
  {disabled}
>
  <div class="relative">
    <Combobox.Input class="input pr-10" {disabled} {placeholder} autocomplete="off" oninput={handleInput} />
    <Combobox.Trigger
      class="absolute right-2 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100"
      {disabled}
      aria-label="候補一覧を開く"
    >
      <CaretUpDown class="size-4" />
    </Combobox.Trigger>
  </div>

  <Combobox.Portal>
    <Combobox.Content
      sideOffset={8}
      class="z-50 max-h-[var(--bits-combobox-content-available-height)] w-[var(--bits-combobox-anchor-width)] rounded-xl border border-slate-200 bg-white p-1 shadow-lg"
    >
      <Combobox.ScrollUpButton class="flex w-full items-center justify-center py-1 text-slate-500">
        <CaretDoubleUp class="size-3" />
      </Combobox.ScrollUpButton>
      <Combobox.Viewport class="max-h-64 p-1">
        {#if filteredItems.length === 0}
          <div class="px-3 py-2 text-xs text-slate-500">{emptyMessage}</div>
        {:else}
          {#each filteredItems as item, idx (`${idx}-${item.value}`)}
            <Combobox.Item value={item.value} label={item.label}>
              {#snippet children({ selected, highlighted })}
                <div
                  class={`flex cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm ${
                    highlighted ? 'bg-slate-100 text-slate-900' : 'text-slate-700'
                  }`}
                >
                  <span class="truncate">{item.label}</span>
                  {#if selected}
                    <Check class="size-4 text-brand" />
                  {/if}
                </div>
              {/snippet}
            </Combobox.Item>
          {/each}
        {/if}
      </Combobox.Viewport>
      <Combobox.ScrollDownButton class="flex w-full items-center justify-center py-1 text-slate-500">
        <CaretDoubleDown class="size-3" />
      </Combobox.ScrollDownButton>
    </Combobox.Content>
  </Combobox.Portal>
</Combobox.Root>

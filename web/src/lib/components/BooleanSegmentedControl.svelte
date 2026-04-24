<script lang="ts">
  import { ToggleGroup } from 'bits-ui';
  import HelpLabel from '$lib/components/HelpLabel.svelte';

  let {
    checked = $bindable(false),
    disabled = false,
    text,
    help
  }: {
    checked?: boolean;
    disabled?: boolean;
    text: string;
    help: string;
  } = $props();

  const enabledValue = 'enabled';
  const disabledValue = 'disabled';
  const rootClass =
    'mt-2 grid h-10 w-44 max-w-full shrink-0 grid-cols-2 rounded-md border border-slate-200 bg-slate-100 p-1 text-sm data-[disabled]:opacity-60';
  const itemBaseClass =
    'inline-flex items-center justify-center rounded-[5px] px-3 font-semibold text-slate-500 transition disabled:cursor-not-allowed disabled:text-slate-300';
  const enabledItemClass = `${itemBaseClass} data-[state=on]:bg-white data-[state=on]:text-emerald-700 data-[state=on]:shadow-sm`;
  const disabledItemClass = `${itemBaseClass} data-[state=on]:bg-white data-[state=on]:text-slate-900 data-[state=on]:shadow-sm`;
  const value = $derived(checked ? enabledValue : disabledValue);

  const handleValueChange = (nextValue: string) => {
    if (nextValue === enabledValue) {
      checked = true;
      return;
    }
    if (nextValue === disabledValue) {
      checked = false;
    }
  };
</script>

<div class="text-sm font-semibold text-slate-700">
  <HelpLabel {text} {help} />
  <ToggleGroup.Root
    type="single"
    class={rootClass}
    value={value}
    onValueChange={handleValueChange}
    {disabled}
    title={help}
    aria-label={text}
  >
    <ToggleGroup.Item class={enabledItemClass} value={enabledValue}>有効</ToggleGroup.Item>
    <ToggleGroup.Item class={disabledItemClass} value={disabledValue}>無効</ToggleGroup.Item>
  </ToggleGroup.Root>
</div>

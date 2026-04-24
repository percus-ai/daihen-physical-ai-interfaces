<script lang="ts">
  import { ToggleGroup } from 'bits-ui';
  import HelpLabel from '$lib/components/HelpLabel.svelte';

  type SegmentedBooleanValue = 'true' | 'false';

  let {
    value = $bindable<SegmentedBooleanValue>('false'),
    defaultValue = 'false',
    disabled = false,
    text,
    help
  }: {
    value?: SegmentedBooleanValue;
    defaultValue?: SegmentedBooleanValue;
    disabled?: boolean;
    text: string;
    help: string;
  } = $props();

  const rootClass =
    'mt-2 grid h-10 w-44 max-w-full shrink-0 grid-cols-2 rounded-md border border-slate-200 bg-slate-100 p-1 text-sm data-[disabled]:opacity-60';
  const itemBaseClass =
    'inline-flex items-center justify-center rounded-[5px] px-3 font-semibold text-slate-500 transition disabled:cursor-not-allowed disabled:text-slate-300';
  const enabledItemClass = `${itemBaseClass} data-[state=on]:bg-white data-[state=on]:text-emerald-700 data-[state=on]:shadow-sm`;
  const disabledItemClass = `${itemBaseClass} data-[state=on]:bg-white data-[state=on]:text-slate-900 data-[state=on]:shadow-sm`;
  const resetButtonClass =
    'text-[11px] font-semibold text-slate-400 underline decoration-dotted underline-offset-2 transition hover:text-slate-900 disabled:cursor-default disabled:text-slate-300 disabled:no-underline disabled:hover:text-slate-300';
  const canReset = $derived(!disabled && value !== defaultValue);

  const handleValueChange = (nextValue: string) => {
    if (nextValue === 'true' || nextValue === 'false') {
      value = nextValue;
    }
  };

  const resetToDefault = () => {
    value = defaultValue;
  };
</script>

<div class="text-sm font-semibold text-slate-700">
  <div class="flex items-center gap-2">
    <HelpLabel {text} {help} />
    <button
      type="button"
      class={resetButtonClass}
      onclick={resetToDefault}
      disabled={!canReset}
      title="ポリシー既定値にリセット"
    >
      リセット
    </button>
  </div>
  <ToggleGroup.Root
    type="single"
    class={rootClass}
    {value}
    onValueChange={handleValueChange}
    {disabled}
    title={help}
    aria-label={text}
  >
    <ToggleGroup.Item class={enabledItemClass} value="true">有効</ToggleGroup.Item>
    <ToggleGroup.Item class={disabledItemClass} value="false">無効</ToggleGroup.Item>
  </ToggleGroup.Root>
</div>

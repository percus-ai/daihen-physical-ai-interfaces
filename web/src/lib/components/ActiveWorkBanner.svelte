<script lang="ts">
  import { Button } from 'bits-ui';

  type WorkState = 'running' | 'waiting' | 'ending';

  type WorkMetric = {
    label: string;
    value: string;
    hidden?: boolean;
  };

  let {
    state = 'running',
    title,
    task = '',
    metrics = [],
    primaryHref,
    primaryLabel = '開く',
    secondaryLabel = '終了',
    secondaryDisabled = false,
    onSecondary,
    warning = '',
    error = ''
  }: {
    state?: WorkState;
    title: string;
    task?: string;
    metrics?: WorkMetric[];
    primaryHref: string;
    primaryLabel?: string;
    secondaryLabel?: string;
    secondaryDisabled?: boolean;
    onSecondary?: () => void | Promise<void>;
    warning?: string;
    error?: string;
  } = $props();

  const STATE_STYLES: Record<
    WorkState,
    {
      label: string;
      dot: string;
      title: string;
    }
  > = {
    running: {
      label: '実行中',
      dot: 'bg-emerald-500',
      title: 'text-emerald-700'
    },
    waiting: {
      label: '待機中',
      dot: 'bg-amber-500',
      title: 'text-amber-700'
    },
    ending: {
      label: '終了中',
      dot: 'bg-slate-500',
      title: 'text-slate-700'
    }
  };

  const currentStyle = $derived(STATE_STYLES[state]);
  const visibleMetrics = $derived(metrics.filter((metric) => !metric.hidden && metric.value));
  const labelClass = 'shrink-0 font-semibold text-slate-500';
  const valueClass = 'min-w-0 truncate font-semibold text-slate-800';
  const handleSecondary = () => {
    void onSecondary?.();
  };
</script>

<section
  class="overflow-hidden rounded-xl border border-slate-200/80 bg-white"
  aria-label={`${title}: ${currentStyle.label}`}
  aria-live="polite"
>
  <div class="grid md:grid-cols-[minmax(0,1fr)_112px]">
    <div class="min-w-0 px-4 py-3">
      <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span class="inline-flex min-w-0 items-center gap-2">
          <span class={`h-2.5 w-2.5 shrink-0 rounded-full ${currentStyle.dot}`}></span>
          <span class={`font-semibold leading-none ${currentStyle.title}`}>{currentStyle.label}</span>
        </span>
        <span class="min-w-0 truncate font-semibold text-slate-700">{title}</span>
      </div>

      <div class="mt-2 space-y-1 text-sm">
        <p class="flex min-w-0">
          <span class={labelClass}>タスク：</span>
          <span class={valueClass}>{task || '-'}</span>
        </p>

        {#if visibleMetrics.length}
          <div class="flex min-w-0 flex-wrap gap-x-4 gap-y-1 text-slate-600">
            {#each visibleMetrics as metric}
              <p class="flex min-w-0">
                <span class={labelClass}>{metric.label}：</span>
                <span class={`${valueClass} tabular-nums`}>
                  {metric.value}
                </span>
              </p>
            {/each}
          </div>
        {/if}

        {#if warning}
          <p class="flex min-w-0 text-amber-700">
            <span class={labelClass}>注意：</span>
            <span class="min-w-0 truncate">
              {warning}
            </span>
          </p>
        {/if}
        {#if error}
          <p class="flex min-w-0 text-rose-600">
            <span class={labelClass}>エラー：</span>
            <span class="min-w-0 truncate">
              {error}
            </span>
          </p>
        {/if}
      </div>
    </div>

    <div class="flex gap-2 p-3 md:flex-col">
      <Button.Root class="btn-primary h-9 w-full whitespace-nowrap px-3 py-1.5 text-sm" href={primaryHref}>
        {primaryLabel}
      </Button.Root>
      {#if onSecondary}
        <Button.Root
          class="btn-ghost h-9 w-full whitespace-nowrap border-rose-200/70 px-3 py-1.5 text-sm text-rose-600 hover:border-rose-300/80 hover:text-rose-700"
          type="button"
          onclick={handleSecondary}
          disabled={secondaryDisabled}
        >
          {secondaryLabel}
        </Button.Root>
      {/if}
    </div>
  </div>
</section>

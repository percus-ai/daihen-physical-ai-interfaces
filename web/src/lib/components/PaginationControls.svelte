<script lang="ts">
  import { Pagination } from 'bits-ui';
  import { describePageRange, resolvePageCount } from '$lib/pagination';

  let {
    currentPage,
    pageSize,
    totalItems,
    disabled = false,
    compact = false,
    onPageChange
  }: {
    currentPage: number;
    pageSize: number;
    totalItems: number;
    disabled?: boolean;
    compact?: boolean;
    onPageChange: (page: number) => void;
  } = $props();

  let stableTotalItems = $state(0);
  const resolvedTotalItems = $derived(disabled && totalItems <= 0 ? stableTotalItems : totalItems);
  const pageCount = $derived(resolvePageCount(resolvedTotalItems, pageSize));
  const rangeLabel = $derived(describePageRange(currentPage, pageSize, resolvedTotalItems));
  const paginationNavButtonClass =
    'inline-flex h-10 items-center justify-center rounded-full border px-4 text-sm font-semibold transition';
  const paginationPageButtonClass =
    'inline-flex h-10 min-w-10 items-center justify-center rounded-full border px-0 text-sm font-semibold transition';
  const neutralButtonTone =
    'border-slate-200 bg-white text-slate-600 hover:border-brand/40 hover:text-brand disabled:opacity-45 disabled:hover:border-slate-200 disabled:hover:text-slate-600';
  const compactPages = $derived.by(() => {
    const start = Math.max(1, currentPage - 1);
    const end = Math.min(pageCount, currentPage + 1);
    return Array.from({ length: end - start + 1 }, (_, index) => start + index);
  });

  $effect(() => {
    if (disabled && totalItems <= 0) {
      return;
    }
    stableTotalItems = totalItems;
  });

  const handlePageChange = (page: number) => {
    if (disabled || page === currentPage || page < 1 || page > pageCount) return;
    onPageChange(page);
  };
</script>

{#if pageCount > 1}
  {#if compact}
    <div class="flex items-center gap-1.5">
      <button
        class={`${paginationPageButtonClass} ${neutralButtonTone}`}
        type="button"
        disabled={disabled || currentPage <= 1}
        aria-label="最初のページ"
        onclick={() => handlePageChange(1)}
      >
        &laquo;
      </button>
      {#each compactPages as pageNumber}
        <button
          class={`${paginationPageButtonClass} ${
            pageNumber === currentPage
              ? 'border-brand/30 bg-brand text-white'
              : neutralButtonTone
          }`}
          type="button"
          disabled={disabled || pageNumber === currentPage}
          aria-label={`${pageNumber}ページへ移動`}
          onclick={() => handlePageChange(pageNumber)}
        >
          {pageNumber}
        </button>
      {/each}
      <button
        class={`${paginationPageButtonClass} ${neutralButtonTone}`}
        type="button"
        disabled={disabled || currentPage >= pageCount}
        aria-label="最後のページ"
        onclick={() => handlePageChange(pageCount)}
      >
        &raquo;
      </button>
    </div>
  {:else}
    <div class="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200/70 pt-4">
      <p class="text-xs text-slate-500">{rangeLabel}</p>
      <Pagination.Root
        count={resolvedTotalItems}
        perPage={pageSize}
        page={currentPage}
        onPageChange={handlePageChange}
        siblingCount={1}
      >
        {#snippet children({ pages })}
          <div class="flex items-center gap-1">
            <Pagination.PrevButton
              class={`${paginationNavButtonClass} ${neutralButtonTone}`}
              disabled={disabled}
            >
              前へ
            </Pagination.PrevButton>

            {#each pages as item (item.key)}
              {#if item.type === 'ellipsis'}
                <span class="px-1 text-xs text-slate-400">...</span>
              {:else}
                <Pagination.Page
                  page={item}
                  class={`${paginationPageButtonClass} ${
                    item.value === currentPage
                      ? 'border-brand/30 bg-brand text-white hover:border-brand/50 hover:bg-brand'
                      : neutralButtonTone
                  }`}
                  disabled={disabled}
                >
                  {item.value}
                </Pagination.Page>
              {/if}
            {/each}

            <Pagination.NextButton
              class={`${paginationNavButtonClass} ${neutralButtonTone}`}
              disabled={disabled}
            >
              次へ
            </Pagination.NextButton>
          </div>
        {/snippet}
      </Pagination.Root>
    </div>
  {/if}
{/if}

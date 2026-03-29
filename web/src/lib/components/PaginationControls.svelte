<script lang="ts">
  import { Pagination } from 'bits-ui';
  import { describePageRange, resolvePageCount } from '$lib/pagination';

  let {
    currentPage,
    pageSize,
    totalItems,
    disabled = false,
    onPageChange
  }: {
    currentPage: number;
    pageSize: number;
    totalItems: number;
    disabled?: boolean;
    onPageChange: (page: number) => void;
  } = $props();

  const pageCount = $derived(resolvePageCount(totalItems, pageSize));
  const rangeLabel = $derived(describePageRange(currentPage, pageSize, totalItems));

  const handlePageChange = (page: number) => {
    if (disabled || page === currentPage || page < 1 || page > pageCount) return;
    onPageChange(page);
  };
</script>

<div class="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200/70 pt-4">
  <p class="text-xs text-slate-500">{rangeLabel}</p>
  <Pagination.Root count={totalItems} perPage={pageSize} page={currentPage} onPageChange={handlePageChange} siblingCount={1}>
    {#snippet children({ pages })}
      <div class="flex items-center gap-1">
        <Pagination.PrevButton class="btn-ghost px-3 py-1.5 text-xs" disabled={disabled}>
          前へ
        </Pagination.PrevButton>

        {#each pages as item (item.key)}
          {#if item.type === 'ellipsis'}
            <span class="px-1 text-xs text-slate-400">...</span>
          {:else}
            <Pagination.Page
              page={item}
              class={`min-w-9 px-3 py-1.5 text-xs ${item.value === currentPage ? 'btn-primary' : 'btn-ghost'}`}
              disabled={disabled}
            >
              {item.value}
            </Pagination.Page>
          {/if}
        {/each}

        <Pagination.NextButton class="btn-ghost px-3 py-1.5 text-xs" disabled={disabled}>
          次へ
        </Pagination.NextButton>
      </div>
    {/snippet}
  </Pagination.Root>
</div>

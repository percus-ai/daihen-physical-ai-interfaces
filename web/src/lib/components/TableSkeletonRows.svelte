<script lang="ts">
  type TableSkeletonCell = {
    tdClass: string;
    barClass?: string;
    barRadiusClass?: string;
    wrapperClass?: string;
  };

  let {
    rows,
    cells,
    rowClass = 'border-t border-slate-200/60'
  }: {
    rows: number[];
    cells: TableSkeletonCell[];
    rowClass?: string;
  } = $props();
</script>

{#each rows as rowIndex (`table-skeleton-${rowIndex}`)}
  <tr aria-hidden="true" class={rowClass}>
    {#each cells as cell, cellIndex (`table-skeleton-${rowIndex}-${cellIndex}`)}
      <td class={cell.tdClass}>
        {#if cell.barClass}
          <div class={cell.wrapperClass ?? ''}>
            <div class={`animate-pulse ${cell.barRadiusClass ?? 'rounded'} bg-slate-200/80 ${cell.barClass}`}></div>
          </div>
        {/if}
      </td>
    {/each}
  </tr>
{/each}

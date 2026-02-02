<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let direction: 'row' | 'column' = 'row';
  export let sizes: [number, number] = [0.5, 0.5];
  export let min = 0.15;
  export let editable = true;
  export let handleSize = 10;
  export let handleInset = 6;
  export let handleGutter = 2;
  export let gapSize = 16;

  const dispatch = createEventDispatcher<{ resize: { sizes: [number, number] } }>();
  let container: HTMLDivElement | null = null;
  let dragging = false;

  const clamp = (value: number, minValue: number, maxValue: number) =>
    Math.min(Math.max(value, minValue), maxValue);

  const handlePointerDown = (event: PointerEvent) => {
    if (!editable) return;
    if (!container) return;
    dragging = true;
    container.setPointerCapture(event.pointerId);
    document.body.style.userSelect = 'none';
    handlePointerMove(event);
  };

  const handlePointerMove = (event: PointerEvent) => {
    if (!editable) return;
    if (!dragging || !container) return;
    const rect = container.getBoundingClientRect();
    const total = direction === 'row' ? rect.width : rect.height;
    if (total <= 0) return;
    const offset = direction === 'row' ? event.clientX - rect.left : event.clientY - rect.top;
    let ratio = offset / total;
    ratio = clamp(ratio, min, 1 - min);
    dispatch('resize', { sizes: [ratio, 1 - ratio] });
  };

  const handlePointerUp = () => {
    if (!dragging) return;
    dragging = false;
    document.body.style.userSelect = '';
  };
</script>

  <div
    class={`split-pane ${direction}`}
    bind:this={container}
    role="presentation"
    style={`--first-size:${sizes[0]}; --second-size:${sizes[1]}; --handle-size:${editable ? handleSize : gapSize}px; --handle-inset:${handleInset}px; --handle-gutter:${handleGutter}px;`}
    onpointermove={handlePointerMove}
    onpointerup={handlePointerUp}
    onpointerleave={handlePointerUp}
  >
    <div class="pane">
      <slot name="first" />
    </div>
    <div
      class={`handle ${editable ? 'active' : 'hidden'}`}
      role="separator"
      tabindex={editable ? 0 : -1}
      onpointerdown={handlePointerDown}
    >
      <div class="handle-bar"></div>
    </div>
    <div class="pane">
      <slot name="second" />
    </div>
  </div>

<style>
  .split-pane {
    display: grid;
    height: 100%;
    width: 100%;
    gap: 0;
    position: relative;
  }
  .split-pane.row {
    grid-template-columns:
      calc((100% - var(--handle-size, 0px)) * var(--first-size, 0.5))
      var(--handle-size, 0px)
      calc((100% - var(--handle-size, 0px)) * var(--second-size, 0.5));
  }
  .split-pane.column {
    grid-template-rows:
      calc((100% - var(--handle-size, 0px)) * var(--first-size, 0.5))
      var(--handle-size, 0px)
      calc((100% - var(--handle-size, 0px)) * var(--second-size, 0.5));
  }
  .pane {
    min-height: 0;
    min-width: 0;
    overflow: hidden;
  }
  .handle {
    display: flex;
    align-items: stretch;
    justify-content: stretch;
    align-self: stretch;
    justify-self: stretch;
    cursor: col-resize;
    touch-action: none;
    padding: var(--handle-inset) var(--handle-gutter);
    z-index: 1;
  }
  .handle.active {
    background: rgba(148, 163, 184, 0.12);
    border-radius: 999px;
  }
  .handle-bar {
    flex: 1;
    border-radius: 999px;
    min-width: 4px;
    min-height: 4px;
    background: rgba(148, 163, 184, 0.7);
    box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.35);
  }
  .split-pane > .handle {
    cursor: col-resize;
  }
  .split-pane.column > .handle {
    cursor: row-resize;
    padding: var(--handle-gutter) var(--handle-inset);
  }
  .handle.hidden {
    pointer-events: none;
    opacity: 0;
    padding: 0;
  }
</style>

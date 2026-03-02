<script lang="ts">
  import { onDestroy } from 'svelte';

  import SessionViewerModal from '$lib/components/recording/SessionViewerModal.svelte';
  import { sessionViewer, type SessionViewerState } from '$lib/viewer/sessionViewerStore';

  let open = $state(false);
  let datasetId = $state('');
  let episodeIndex = $state(0);
  let title = $state('Session Viewer');
  let initialInspectorTab = $state<'blueprint' | 'selection' | 'search'>('selection');
  let startInEditMode = $state(false);

  let lastSyncedSignature = $state('');

  const computeSignature = (state: {
    open: boolean;
    datasetId: string;
    episodeIndex: number;
    title: string;
    initialInspectorTab: string;
    startInEditMode: boolean;
  }) =>
    [
      state.open ? '1' : '0',
      state.datasetId,
      String(state.episodeIndex),
      state.title,
      state.initialInspectorTab,
      state.startInEditMode ? '1' : '0'
    ].join('|');

  const applyFromStore = (next: SessionViewerState) => {
    open = Boolean(next.open);
    datasetId = String(next.datasetId ?? '');
    episodeIndex = Math.max(0, Math.floor(Number(next.episodeIndex) || 0));
    title = String(next.title ?? 'Session Viewer');
    initialInspectorTab = (next.initialInspectorTab ?? 'selection') as typeof initialInspectorTab;
    startInEditMode = Boolean(next.startInEditMode);
    lastSyncedSignature = computeSignature({
      open,
      datasetId,
      episodeIndex,
      title,
      initialInspectorTab,
      startInEditMode
    });
  };

  const unsub = sessionViewer.state.subscribe(applyFromStore);
  onDestroy(unsub);

  $effect(() => {
    const signature = computeSignature({
      open,
      datasetId,
      episodeIndex,
      title,
      initialInspectorTab,
      startInEditMode
    });
    if (signature === lastSyncedSignature) return;
    lastSyncedSignature = signature;

    sessionViewer.state.set({
      open,
      datasetId,
      episodeIndex,
      title,
      initialInspectorTab,
      startInEditMode
    });
  });
</script>

<SessionViewerModal
  bind:open={open}
  datasetId={datasetId}
  episodeIndex={episodeIndex}
  title={title}
  initialInspectorTab={initialInspectorTab}
  startInEditMode={startInEditMode}
/>


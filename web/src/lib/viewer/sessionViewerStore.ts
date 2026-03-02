import { writable } from 'svelte/store';

export type SessionViewerOpenArgs = {
  datasetId: string;
  episodeIndex?: number;
  title?: string;
  initialInspectorTab?: 'blueprint' | 'selection' | 'search';
  startInEditMode?: boolean;
};

export type SessionViewerState = {
  open: boolean;
  datasetId: string;
  episodeIndex: number;
  title: string;
  initialInspectorTab: 'blueprint' | 'selection' | 'search';
  startInEditMode: boolean;
};

const DEFAULT_STATE: SessionViewerState = {
  open: false,
  datasetId: '',
  episodeIndex: 0,
  title: 'Session Viewer',
  initialInspectorTab: 'selection',
  startInEditMode: false
};

const store = writable<SessionViewerState>({ ...DEFAULT_STATE });

const clampEpisodeIndex = (value: unknown) => {
  const next = Math.max(0, Math.floor(Number(value) || 0));
  return Number.isFinite(next) ? next : 0;
};

export const sessionViewer = {
  state: store,
  open: (args: SessionViewerOpenArgs) => {
    const datasetId = String(args.datasetId ?? '');
    if (!datasetId) return;
    store.set({
      open: true,
      datasetId,
      episodeIndex: clampEpisodeIndex(args.episodeIndex),
      title: String(args.title ?? DEFAULT_STATE.title),
      initialInspectorTab: (args.initialInspectorTab ?? DEFAULT_STATE.initialInspectorTab),
      startInEditMode: Boolean(args.startInEditMode)
    });
  },
  close: () => {
    store.update((prev) => ({ ...prev, open: false }));
  },
  setOpen: (open: boolean) => {
    store.update((prev) => ({ ...prev, open: Boolean(open) }));
  },
  reset: () => {
    store.set({ ...DEFAULT_STATE });
  }
} as const;


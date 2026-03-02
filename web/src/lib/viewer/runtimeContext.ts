import type { DatasetPlaybackController } from '$lib/recording/datasetPlayback';
import type { Readable } from 'svelte/store';

export type ViewerRuntime =
  | {
      kind: 'ros';
      mode: 'recording' | 'operate';
      sessionId: string;
      sessionKind: '' | 'recording' | 'inference' | 'teleop';
    }
  | {
      kind: 'dataset';
      mode: 'recording' | 'operate';
      datasetId: string;
      episodeIndex: number;
      videoWindows?: Record<string, { from_s: number; to_s: number }>;
      playback: DatasetPlaybackController | null;
      onPrevEpisode?: () => void;
      onNextEpisode?: () => void;
    };

export type ViewerRuntimeStore = Readable<ViewerRuntime>;

export const VIEWER_RUNTIME = Symbol('viewerRuntime');

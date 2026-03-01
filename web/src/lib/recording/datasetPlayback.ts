export type DatasetPlaybackState = {
  playing: boolean;
  currentTime: number;
  duration: number;
  rate: number;
  ready: boolean;
};

export type DatasetPlaybackController = {
  getState: () => DatasetPlaybackState;
  subscribe: (fn: (state: DatasetPlaybackState) => void) => () => void;
  register: (video: HTMLVideoElement) => () => void;
  play: () => void;
  pause: () => void;
  stop: () => void;
  seek: (time: number) => void;
  setRate: (rate: number) => void;
  reset: () => void;
};

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

export const createDatasetPlaybackController = (): DatasetPlaybackController => {
  let state: DatasetPlaybackState = {
    playing: false,
    currentTime: 0,
    duration: 0,
    rate: 1,
    ready: false
  };

  const subscribers = new Set<(value: DatasetPlaybackState) => void>();
  const videos = new Set<HTMLVideoElement>();

  let leader: HTMLVideoElement | null = null;
  let ignoreTimeUpdates = false;

  const notify = () => {
    for (const subscriber of subscribers) subscriber(state);
  };

  const setState = (patch: Partial<DatasetPlaybackState>) => {
    state = { ...state, ...patch };
    notify();
  };

  const pickLeader = () => {
    leader = videos.values().next().value ?? null;
  };

  const updateDuration = () => {
    let maxDuration = 0;
    let hasMetadata = false;
    for (const video of videos) {
      if (Number.isFinite(video.duration) && video.duration > maxDuration) {
        maxDuration = video.duration;
      }
      if (video.readyState >= 1) hasMetadata = true;
    }
    const nextDuration = maxDuration;
    const nextCurrentTime =
      nextDuration > 0 && Number.isFinite(nextDuration)
        ? clamp(state.currentTime, 0, nextDuration)
        : Math.max(0, state.currentTime);
    setState({ duration: nextDuration, currentTime: nextCurrentTime, ready: hasMetadata || state.ready });
  };

  const seekInternal = (time: number) => {
    const nextTime =
      state.duration > 0 && Number.isFinite(state.duration)
        ? clamp(time, 0, state.duration)
        : Math.max(0, time);

    ignoreTimeUpdates = true;
    setState({ currentTime: nextTime });
    for (const video of videos) {
      try {
        const boundedTime =
          Number.isFinite(video.duration) && video.duration > 0
            ? clamp(nextTime, 0, video.duration)
            : nextTime;
        video.currentTime = boundedTime;
      } catch {
        // ignored
      }
    }
    queueMicrotask(() => {
      ignoreTimeUpdates = false;
    });
  };

  const playAll = () => {
    for (const video of videos) {
      try {
        const promise = video.play();
        if (promise && typeof (promise as Promise<void>).catch === 'function') {
          void (promise as Promise<void>).catch(() => {});
        }
      } catch {
        // ignored
      }
    }
  };

  const pauseAll = () => {
    for (const video of videos) {
      try {
        video.pause();
      } catch {
        // ignored
      }
    }
  };

  return {
    getState: () => state,
    subscribe: (fn) => {
      subscribers.add(fn);
      fn(state);
      return () => {
        subscribers.delete(fn);
      };
    },
    register: (video) => {
      videos.add(video);
      if (!leader) leader = video;

      try {
        video.playbackRate = state.rate;
      } catch {
        // ignored
      }

      if (state.currentTime > 0) {
        try {
          video.currentTime = state.currentTime;
        } catch {
          // ignored
        }
      }

      if (state.playing) playAll();

      const onLoadedMetadata = () => {
        updateDuration();
      };
      const onDurationChange = () => {
        updateDuration();
      };
      const onTimeUpdate = () => {
        if (ignoreTimeUpdates) return;
        if (leader !== video) return;
        if (!Number.isFinite(video.currentTime)) return;
        setState({ currentTime: video.currentTime });
      };
      const onPlay = () => {
        if (!leader) leader = video;
        setState({ playing: true });
      };
      const onPause = () => {
        const anyPlaying = Array.from(videos).some((v) => !v.paused && !v.ended);
        setState({ playing: anyPlaying });
      };
      const onRateChange = () => {
        if (!Number.isFinite(video.playbackRate)) return;
        setState({ rate: video.playbackRate });
      };

      video.addEventListener('loadedmetadata', onLoadedMetadata);
      video.addEventListener('durationchange', onDurationChange);
      video.addEventListener('timeupdate', onTimeUpdate);
      video.addEventListener('play', onPlay);
      video.addEventListener('pause', onPause);
      video.addEventListener('ratechange', onRateChange);

      updateDuration();

      return () => {
        video.removeEventListener('loadedmetadata', onLoadedMetadata);
        video.removeEventListener('durationchange', onDurationChange);
        video.removeEventListener('timeupdate', onTimeUpdate);
        video.removeEventListener('play', onPlay);
        video.removeEventListener('pause', onPause);
        video.removeEventListener('ratechange', onRateChange);

        videos.delete(video);
        if (leader === video) pickLeader();
        updateDuration();
      };
    },
    play: () => {
      setState({ playing: true });
      playAll();
    },
    pause: () => {
      pauseAll();
      setState({ playing: false });
    },
    stop: () => {
      pauseAll();
      setState({ playing: false });
      seekInternal(0);
    },
    seek: (time) => {
      seekInternal(time);
    },
    setRate: (rate) => {
      const nextRate = Number.isFinite(rate) && rate > 0 ? rate : 1;
      setState({ rate: nextRate });
      for (const video of videos) {
        try {
          video.playbackRate = nextRate;
        } catch {
          // ignored
        }
      }
    },
    reset: () => {
      pauseAll();
      setState({ playing: false, currentTime: 0, duration: 0, ready: false, rate: 1 });
      for (const video of videos) {
        try {
          video.playbackRate = 1;
          video.currentTime = 0;
        } catch {
          // ignored
        }
      }
    }
  };
};

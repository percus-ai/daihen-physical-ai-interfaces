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
  let rafId: number | null = null;
  let lastRafAt = 0;
  let lastReportedTime = -1;
  const targetUpdateIntervalMs = 1000 / 30; // keep UI responsive without spamming renders
  let clockBaseTime = 0;
  let clockBaseAt = 0;
  let lastClockSyncAt = 0;

  const requestVideoFrame = (video: HTMLVideoElement, cb: () => void): number | null => {
    const fn = (
      video as unknown as {
        requestVideoFrameCallback?: (cb: () => void) => number;
      }
    ).requestVideoFrameCallback;
    if (typeof fn !== 'function') return null;
    // Must call as a method; extracting loses `this` and throws "Illegal invocation".
    return fn.call(video, cb);
  };

  const cancelVideoFrame = (video: HTMLVideoElement, id: number) => {
    const fn = (
      video as unknown as {
        cancelVideoFrameCallback?: (id: number) => void;
      }
    ).cancelVideoFrameCallback;
    if (typeof fn !== 'function') return;
    try {
      fn.call(video, id);
    } catch {
      // ignored
    }
  };
  let rvfcId: number | null = null;

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

  const nowMs = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

  const syncClockBase = (time?: number) => {
    const now = nowMs();
    const nextTime =
      typeof time === 'number' && Number.isFinite(time)
        ? time
        : leader && Number.isFinite(leader.currentTime)
          ? leader.currentTime
          : state.currentTime;
    clockBaseTime = Math.max(0, nextTime);
    clockBaseAt = now;
    lastClockSyncAt = now;
  };

  const stopClock = () => {
    if (rafId != null && typeof window !== 'undefined') {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    if (rvfcId != null && leader) {
      cancelVideoFrame(leader, rvfcId);
      rvfcId = null;
    }
    lastRafAt = 0;
    lastReportedTime = -1;
  };

  const startClock = () => {
    if (!leader) return;
    if (!state.playing) return;
    if (rafId != null || rvfcId != null) return;

    // Initialize base for smooth wall-clock time even if `currentTime` updates sparsely.
    syncClockBase();

    const updateFromClock = () => {
      if (!leader) return;
      const now = nowMs();
      if (ignoreTimeUpdates) return;

      let est = clockBaseTime + ((now - clockBaseAt) / 1000) * (Number.isFinite(state.rate) ? state.rate : 1);
      if (state.duration > 0 && Number.isFinite(state.duration)) est = clamp(est, 0, state.duration);
      if (Number.isFinite(est) && Math.abs(est - lastReportedTime) > 1e-3) {
        lastReportedTime = est;
        setState({ currentTime: est });
      }

      // Periodically resync to avoid drift.
      if (now - lastClockSyncAt > 250 && Number.isFinite(leader.currentTime)) {
        const actual = leader.currentTime;
        if (Number.isFinite(actual) && Math.abs(actual - est) > 0.08) {
          syncClockBase(actual);
        } else {
          lastClockSyncAt = now;
        }
      }
    };

    const tick = (now: number) => {
      if (!state.playing) {
        stopClock();
        return;
      }
      if (!leader) {
        stopClock();
        return;
      }
      if (ignoreTimeUpdates) {
        rafId = window.requestAnimationFrame(tick);
        return;
      }
      if (now - lastRafAt < targetUpdateIntervalMs) {
        rafId = window.requestAnimationFrame(tick);
        return;
      }
      lastRafAt = now;
      updateFromClock();
      rafId = window.requestAnimationFrame(tick);
    };

    if (
      typeof (leader as unknown as { requestVideoFrameCallback?: unknown }).requestVideoFrameCallback === 'function'
    ) {
      const step = () => {
        if (!state.playing) {
          stopClock();
          return;
        }
        if (!leader) {
          stopClock();
          return;
        }
        if (!ignoreTimeUpdates) {
          // Use real video time as a periodic sync point.
          const time = leader.currentTime;
          if (Number.isFinite(time)) syncClockBase(time);
          updateFromClock();
        }
        rvfcId = requestVideoFrame(leader, step);
      };
      rvfcId = requestVideoFrame(leader, step);
    }

    if (typeof window !== 'undefined') {
      rafId = window.requestAnimationFrame(tick);
    }
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
    syncClockBase(nextTime);
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
        if (!Number.isFinite(video.currentTime)) return;
        if (leader !== video) {
          // If the current leader is not actually playing, switch to the active one.
          if (!leader || leader.paused || leader.ended) {
            leader = video;
            stopClock();
            startClock();
          } else {
            return;
          }
        }
        setState({ currentTime: video.currentTime });
        syncClockBase(video.currentTime);
      };
      const onPlay = () => {
        // Prefer the element that is actually playing as the leader.
        leader = video;
        stopClock();
        syncClockBase(video.currentTime);
        setState({ playing: true });
        startClock();
      };
      const onPause = () => {
        const anyPlaying = Array.from(videos).some((v) => !v.paused && !v.ended);
        setState({ playing: anyPlaying });
        if (!anyPlaying) stopClock();
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
        if (!leader) stopClock();
      };
    },
    play: () => {
      setState({ playing: true });
      playAll();
      startClock();
    },
    pause: () => {
      pauseAll();
      setState({ playing: false });
      stopClock();
    },
    stop: () => {
      pauseAll();
      setState({ playing: false });
      stopClock();
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
      stopClock();
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

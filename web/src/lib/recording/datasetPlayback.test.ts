import { describe, expect, it } from 'vitest';

import { createDatasetPlaybackController } from '$lib/recording/datasetPlayback';

type Listener = (event: Event) => void;

class FakeVideo {
  currentTime = 0;
  duration = 0;
  readyState = 0;
  playbackRate = 1;
  paused = true;
  ended = false;

  private listeners = new Map<string, Set<Listener>>();
  private nextRvfcId = 1;

  requestVideoFrameCallback?: (cb: () => void) => number;
  cancelVideoFrameCallback?: (id: number) => void;

  constructor(opts?: { enableRvfc?: boolean }) {
    if (opts?.enableRvfc) {
      this.requestVideoFrameCallback = function (this: unknown, _cb: () => void) {
        if (this !== videoSelf) {
          throw new TypeError('Illegal invocation');
        }
        return (videoSelf.nextRvfcId += 1);
      };
      const videoSelf = this;
      this.cancelVideoFrameCallback = function (this: unknown, _id: number) {
        if (this !== videoSelf) throw new TypeError('Illegal invocation');
      };
    }
  }

  addEventListener(type: string, fn: Listener) {
    const set = this.listeners.get(type) ?? new Set<Listener>();
    set.add(fn);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, fn: Listener) {
    this.listeners.get(type)?.delete(fn);
  }

  dispatch(type: string) {
    const event = new Event(type);
    for (const fn of this.listeners.get(type) ?? []) {
      fn(event);
    }
  }

  play() {
    this.paused = false;
    this.dispatch('play');
    return Promise.resolve();
  }

  pause() {
    this.paused = true;
    this.dispatch('pause');
  }
}

describe('datasetPlayback', () => {
  it('tracks duration + ready from metadata', () => {
    const controller = createDatasetPlaybackController();
    const video = new FakeVideo() as unknown as HTMLVideoElement;

    const unregister = controller.register(video);
    expect(controller.getState().ready).toBe(false);

    (video as unknown as FakeVideo).duration = 12.5;
    (video as unknown as FakeVideo).readyState = 1;
    (video as unknown as FakeVideo).dispatch('loadedmetadata');

    expect(controller.getState().duration).toBe(12.5);
    expect(controller.getState().ready).toBe(true);

    unregister();
  });

  it('seek clamps to duration and updates video currentTime', () => {
    const controller = createDatasetPlaybackController();
    const video = new FakeVideo() as unknown as HTMLVideoElement;
    controller.register(video);

    (video as unknown as FakeVideo).duration = 10;
    (video as unknown as FakeVideo).readyState = 1;
    (video as unknown as FakeVideo).dispatch('loadedmetadata');

    controller.seek(999);
    expect(controller.getState().currentTime).toBe(10);
    expect((video as unknown as FakeVideo).currentTime).toBe(10);
  });

  it('setRate sets playbackRate for registered videos', () => {
    const controller = createDatasetPlaybackController();
    const video = new FakeVideo() as unknown as HTMLVideoElement;
    controller.register(video);

    controller.setRate(2);
    expect(controller.getState().rate).toBe(2);
    expect((video as unknown as FakeVideo).playbackRate).toBe(2);
  });

  it('does not throw when requestVideoFrameCallback exists (method binding)', () => {
    const controller = createDatasetPlaybackController();
    const video = new FakeVideo({ enableRvfc: true }) as unknown as HTMLVideoElement;
    controller.register(video);

    expect(() => controller.play()).not.toThrow();
    controller.pause();
  });

  it('uses the shortest duration across videos and stops at the common end', async () => {
    const controller = createDatasetPlaybackController();
    const v1 = new FakeVideo() as unknown as HTMLVideoElement;
    const v2 = new FakeVideo() as unknown as HTMLVideoElement;
    controller.register(v1);
    controller.register(v2);

    (v1 as unknown as FakeVideo).duration = 10;
    (v1 as unknown as FakeVideo).readyState = 1;
    (v1 as unknown as FakeVideo).dispatch('loadedmetadata');
    (v2 as unknown as FakeVideo).duration = 30;
    (v2 as unknown as FakeVideo).readyState = 1;
    (v2 as unknown as FakeVideo).dispatch('loadedmetadata');

    // Allow internal queueMicrotask() flushes (seek application after metadata).
    await Promise.resolve();

    expect(controller.getState().duration).toBe(10);

    controller.play();
    (v2 as unknown as FakeVideo).currentTime = 12;
    (v2 as unknown as FakeVideo).dispatch('timeupdate');

    expect(controller.getState().playing).toBe(false);
    expect(controller.getState().currentTime).toBe(10);
    expect((v1 as unknown as FakeVideo).paused).toBe(true);
    expect((v2 as unknown as FakeVideo).paused).toBe(true);
  });
});

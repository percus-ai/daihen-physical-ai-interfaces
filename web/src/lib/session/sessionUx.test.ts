import { describe, expect, it } from 'vitest';

import { computeScrollTargetTop } from './sessionUx';

describe('sessionUx', () => {
  it('keeps the current scroll position when the element already fits in the viewport', () => {
    expect(
      computeScrollTargetTop({
        currentScrollY: 120,
        elementBottom: 640,
        viewportHeight: 800
      })
    ).toBe(120);
  });

  it('scrolls enough to reveal the bottom of the element', () => {
    expect(
      computeScrollTargetTop({
        currentScrollY: 320,
        elementBottom: 980,
        viewportHeight: 720,
        marginPx: 24
      })
    ).toBe(604);
  });
});

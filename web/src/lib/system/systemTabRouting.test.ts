import { describe, expect, it } from 'vitest';

import {
  buildSystemTabHref,
  normalizeSystemTab,
  reconcileSystemTabState,
  resolveSystemTabFromUrl
} from './systemTabRouting';

describe('systemTabRouting', () => {
  it('normalizes unknown tabs to status', () => {
    expect(normalizeSystemTab(null)).toBe('status');
    expect(normalizeSystemTab('unknown')).toBe('status');
    expect(normalizeSystemTab('profile')).toBe('profile');
  });

  it('resolves status from /system without a tab query', () => {
    expect(resolveSystemTabFromUrl(new URL('https://example.com/system'))).toBe('status');
  });

  it('builds a clean href for the status tab', () => {
    expect(buildSystemTabHref(new URL('https://example.com/system?tab=profile#summary'), 'status')).toBe(
      '/system#summary'
    );
  });

  it('builds a href with the selected tab query', () => {
    expect(buildSystemTabHref(new URL('https://example.com/system'), 'runtime')).toBe('/system?tab=runtime');
  });

  it('adopts url tab changes when navigation came from outside the tab control', () => {
    expect(
      reconcileSystemTabState({
        activeTab: 'profile',
        urlTab: 'status',
        pendingTabNavigation: null
      })
    ).toEqual({
      activeTab: 'status',
      pendingTabNavigation: null
    });
  });

  it('clears pending navigation once the url catches up', () => {
    expect(
      reconcileSystemTabState({
        activeTab: 'runtime',
        urlTab: 'runtime',
        pendingTabNavigation: 'runtime'
      })
    ).toEqual({
      activeTab: 'runtime',
      pendingTabNavigation: null
    });
  });
});

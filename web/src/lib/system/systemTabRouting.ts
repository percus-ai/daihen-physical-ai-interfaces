export const SYSTEM_TABS = ['status', 'profile', 'runtime', 'settings'] as const;

export type SystemTab = (typeof SYSTEM_TABS)[number];

export const normalizeSystemTab = (value: string | null | undefined): SystemTab => {
  if (value && SYSTEM_TABS.includes(value as SystemTab)) {
    return value as SystemTab;
  }
  return 'status';
};

export const resolveSystemTabFromUrl = (currentUrl: URL): SystemTab =>
  normalizeSystemTab(currentUrl.searchParams.get('tab'));

export const buildSystemTabHref = (currentUrl: URL, tab: SystemTab): string => {
  const nextUrl = new URL(currentUrl);
  if (tab === 'status') {
    nextUrl.searchParams.delete('tab');
  } else {
    nextUrl.searchParams.set('tab', tab);
  }
  return `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
};

export const reconcileSystemTabState = (state: {
  activeTab: SystemTab;
  urlTab: SystemTab;
  pendingTabNavigation: SystemTab | null;
}): {
  activeTab: SystemTab;
  pendingTabNavigation: SystemTab | null;
} => {
  if (state.pendingTabNavigation !== null && state.urlTab === state.pendingTabNavigation) {
    return {
      activeTab: state.activeTab,
      pendingTabNavigation: null
    };
  }

  if (state.pendingTabNavigation === null && state.urlTab !== state.activeTab) {
    return {
      activeTab: state.urlTab,
      pendingTabNavigation: null
    };
  }

  return {
    activeTab: state.activeTab,
    pendingTabNavigation: state.pendingTabNavigation
  };
};

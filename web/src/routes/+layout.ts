import type { LayoutLoad } from './$types';
import { redirect } from '@sveltejs/kit';

import { api } from '$lib/api/client';

export const ssr = false;

export const load: LayoutLoad = async ({ url }) => {
  if (url.pathname.startsWith('/auth')) {
    return {};
  }
  try {
    const status = await api.auth.status();
    if (!status.authenticated) {
      throw new Error('unauthenticated');
    }
  } catch {
    throw redirect(302, '/auth');
  }
  return {};
};

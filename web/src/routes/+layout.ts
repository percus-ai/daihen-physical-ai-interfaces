import type { LayoutLoad } from './$types';
import { redirect } from '@sveltejs/kit';

import { getBackendUrl } from '$lib/config';

export const ssr = false;

export const load: LayoutLoad = async ({ url, fetch }) => {
  if (url.pathname.startsWith('/auth')) {
    return {};
  }
  try {
    const baseUrl = getBackendUrl();
    const fetchJson = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
      const res = await fetch(`${baseUrl}${path}`, {
        ...init,
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...(init.headers ?? {})
        }
      });
      if (!res.ok) throw new Error(`request failed: ${res.status}`);
      return res.json();
    };

    const status = await fetchJson<{
      authenticated?: boolean;
      expires_at?: number | null;
      session_expires_at?: number | null;
    }>('/api/auth/status');
    const now = Math.floor(Date.now() / 1000);
    let authenticated = Boolean(status.authenticated);
    let expiresAt = status.expires_at;
    let sessionExpiresAt = status.session_expires_at;
    const refreshLeewaySeconds = 60;

    if (!authenticated && sessionExpiresAt && sessionExpiresAt > now) {
      try {
        const refreshed = await fetchJson<{
          authenticated?: boolean;
          expires_at?: number | null;
          session_expires_at?: number | null;
        }>('/api/auth/refresh', { method: 'POST' });
        authenticated = Boolean(refreshed.authenticated);
        expiresAt = refreshed.expires_at;
        sessionExpiresAt = refreshed.session_expires_at;
      } catch {
        authenticated = false;
      }
    }

    if (authenticated && expiresAt && expiresAt <= now + refreshLeewaySeconds) {
      try {
        await fetchJson('/api/auth/refresh', { method: 'POST' });
      } catch {
        authenticated = false;
      }
    }

    if (!authenticated) {
      throw new Error('unauthenticated');
    }
  } catch {
    throw redirect(302, '/auth');
  }
  return {};
};

/**
 * API client for Backend.
 */

import { getBackendUrl } from '../config';

export async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const baseUrl = getBackendUrl();
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

export const api = {
  health: () => fetchApi<{ status: string }>('/health'),
  projects: {
    list: () => fetchApi<any[]>('/api/projects'),
    get: (id: string) => fetchApi<any>(`/api/projects/${id}`),
  },
  datasets: {
    list: () => fetchApi<any[]>('/api/datasets'),
  },
  training: {
    start: (config: any) => fetchApi<any>('/api/training/start', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  },
};

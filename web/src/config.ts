/**
 * Backend URL configuration.
 * Users can configure this in browser settings (stored in localStorage).
 */

const STORAGE_KEY = 'PERCUS_BACKEND_URL';
const DEFAULT_URL = 'http://localhost:8000';

export function getBackendUrl(): string {
  if (typeof window === 'undefined') return DEFAULT_URL;
  return localStorage.getItem(STORAGE_KEY) ?? DEFAULT_URL;
}

export function setBackendUrl(url: string): void {
  localStorage.setItem(STORAGE_KEY, url);
}

export function clearBackendUrl(): void {
  localStorage.removeItem(STORAGE_KEY);
}

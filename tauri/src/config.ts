/**
 * Backend URL configuration for Tauri.
 * Default to localhost since backend runs as sidecar.
 */

const STORAGE_KEY = 'PERCUS_BACKEND_URL';
const DEFAULT_URL = 'http://localhost:8000';

export function getBackendUrl(): string {
  // In Tauri, default to localhost (sidecar)
  // User can override for remote backend
  return localStorage.getItem(STORAGE_KEY) ?? DEFAULT_URL;
}

export function setBackendUrl(url: string): void {
  localStorage.setItem(STORAGE_KEY, url);
}

export function isLocalBackend(): boolean {
  return getBackendUrl().includes('localhost');
}

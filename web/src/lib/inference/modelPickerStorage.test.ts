import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  RECENT_MODEL_LIMIT,
  loadFavoriteModelIds,
  loadRecentModelIds,
  recordRecentModelId,
  recordRecentModelUsage,
  retainKnownModelIds,
  saveFavoriteModelIds,
  saveRecentModelIds,
  toggleFavoriteModelId
} from './modelPickerStorage';

const createStorage = () => {
  const storage = new Map<string, string>();
  return {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => {
      storage.set(key, value);
    },
    removeItem: (key: string) => {
      storage.delete(key);
    },
    clear: () => {
      storage.clear();
    }
  };
};

describe('modelPickerStorage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal('localStorage', createStorage());
  });

  it('loads and saves favorites as a normalized unique list', () => {
    saveFavoriteModelIds([' model-a ', 'model-b', 'model-a', '', 'model-c']);

    expect(loadFavoriteModelIds()).toEqual(['model-a', 'model-b', 'model-c']);
  });

  it('drops invalid saved payloads', () => {
    localStorage.setItem('inference-model-picker:v1:favorites', '{broken json');

    expect(loadFavoriteModelIds()).toEqual([]);
    expect(localStorage.getItem('inference-model-picker:v1:favorites')).toBeNull();
  });

  it('toggles favorites while keeping most recently added first', () => {
    expect(toggleFavoriteModelId(['model-a', 'model-b'], 'model-c')).toEqual(['model-c', 'model-a', 'model-b']);
    expect(toggleFavoriteModelId(['model-a', 'model-b'], 'model-a')).toEqual(['model-b']);
  });

  it('records recent models with deduplication and limit', () => {
    const initial = Array.from({ length: RECENT_MODEL_LIMIT }, (_, index) => `model-${index}`);
    const next = recordRecentModelId(initial, 'model-3');
    expect(next[0]).toBe('model-3');
    expect(next).toHaveLength(RECENT_MODEL_LIMIT);
    expect(next.filter((modelId) => modelId === 'model-3')).toHaveLength(1);
  });

  it('retains only models that still exist', () => {
    expect(retainKnownModelIds(['model-a', 'model-b', 'model-c'], ['model-c', 'model-a'])).toEqual(['model-a', 'model-c']);
  });

  it('keeps saved ids when the available model list is empty', () => {
    expect(retainKnownModelIds(['model-a', 'model-b'], [])).toEqual(['model-a', 'model-b']);
  });

  it('loads and saves recent models', () => {
    saveRecentModelIds(['model-a', 'model-b']);

    expect(loadRecentModelIds()).toEqual(['model-a', 'model-b']);
  });

  it('records recent model usage directly into localStorage', () => {
    saveRecentModelIds(['model-a', 'model-b']);

    expect(recordRecentModelUsage('model-c')).toEqual(['model-c', 'model-a', 'model-b']);
    expect(loadRecentModelIds()).toEqual(['model-c', 'model-a', 'model-b']);
  });
});

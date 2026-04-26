import { describe, expect, it } from 'vitest';
import { updateSelectedId, updateSelectedPageIds } from './tableSelection';

describe('tableSelection', () => {
  it('updates one row without dropping ids from other pages', () => {
    expect(updateSelectedId(['page-1-a'], 'page-2-a', true)).toEqual(['page-1-a', 'page-2-a']);
    expect(updateSelectedId(['page-1-a', 'page-2-a'], 'page-2-a', false)).toEqual(['page-1-a']);
  });

  it('selects only the current page ids and preserves previous pages', () => {
    expect(updateSelectedPageIds(['page-1-a'], ['page-2-a', 'page-2-b'], true)).toEqual([
      'page-1-a',
      'page-2-a',
      'page-2-b'
    ]);
  });

  it('clears only the current page ids', () => {
    expect(updateSelectedPageIds(['page-1-a', 'page-2-a', 'page-2-b'], ['page-2-a', 'page-2-b'], false)).toEqual([
      'page-1-a'
    ]);
  });

  it('does not duplicate selected ids', () => {
    expect(updateSelectedPageIds(['page-1-a', 'page-2-a'], ['page-2-a', 'page-2-b'], true)).toEqual([
      'page-1-a',
      'page-2-a',
      'page-2-b'
    ]);
  });
});

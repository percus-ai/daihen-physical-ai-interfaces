import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createViewNode } from '$lib/recording/blueprint';

const loadBlueprintDraft = vi.fn();

vi.mock('./draftStorage', async () => {
  const actual = await vi.importActual<typeof import('./draftStorage')>('./draftStorage');
  return {
    ...actual,
    loadBlueprintDraft
  };
});

describe('sessionBlueprintState', () => {
  beforeEach(() => {
    loadBlueprintDraft.mockReset();
  });

  it('builds a stable session signature only when both parts exist', async () => {
    const { getBlueprintSessionSignature } = await import('./sessionBlueprintState');

    expect(getBlueprintSessionSignature('', 'session-1')).toBe('');
    expect(getBlueprintSessionSignature('recording', '')).toBe('');
    expect(getBlueprintSessionSignature('recording', 'session-1')).toBe('recording:session-1');
  });

  it('uses the saved draft when draft persistence is enabled', async () => {
    const detail = {
      id: 'bp-1',
      name: 'Blueprint',
      blueprint: createViewNode('camera', { topic: '/camera/front' })
    };
    const draft = createViewNode('joint_state', { topic: '/arm/joint_states' });
    loadBlueprintDraft.mockReturnValue(draft);

    const { materializeSessionBlueprintState } = await import('./sessionBlueprintState');
    expect(
      materializeSessionBlueprintState({
        detail,
        persistDraft: true,
        sessionKind: 'recording',
        sessionId: 'session-1'
      })
    ).toEqual({
      id: 'bp-1',
      name: 'Blueprint',
      blueprint: draft
    });
  });

  it('keeps the server blueprint when draft persistence is disabled', async () => {
    const detail = {
      id: 'bp-1',
      name: 'Blueprint',
      blueprint: createViewNode('camera', { topic: '/camera/front' })
    };
    loadBlueprintDraft.mockReturnValue(createViewNode('joint_state', { topic: '/arm/joint_states' }));

    const { materializeSessionBlueprintState } = await import('./sessionBlueprintState');
    expect(
      materializeSessionBlueprintState({
        detail,
        persistDraft: false,
        sessionKind: 'recording',
        sessionId: 'session-1'
      })
    ).toEqual({
      id: 'bp-1',
      name: 'Blueprint',
      blueprint: detail.blueprint
    });
  });
});

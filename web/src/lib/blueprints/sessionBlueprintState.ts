import type { BlueprintNode } from '$lib/recording/blueprint';

import { loadBlueprintDraft, type BlueprintSessionKind } from './draftStorage';
import type { WebuiBlueprintDetail } from './blueprintManager';

export type SessionBlueprintState = {
  id: string;
  name: string;
  blueprint: BlueprintNode;
};

export const getBlueprintSessionSignature = (
  sessionKind: BlueprintSessionKind | '',
  sessionId: string
) => {
  if (!sessionKind || !sessionId) return '';
  return `${sessionKind}:${sessionId}`;
};

export const materializeSessionBlueprintState = (options: {
  detail: WebuiBlueprintDetail;
  persistDraft: boolean;
  sessionKind: BlueprintSessionKind;
  sessionId: string;
}): SessionBlueprintState => {
  const { detail, persistDraft, sessionKind, sessionId } = options;
  let blueprint = detail.blueprint;

  if (persistDraft && sessionId) {
    const draft = loadBlueprintDraft(sessionKind, sessionId, detail.id);
    if (draft) {
      blueprint = draft;
    }
  }

  return {
    id: detail.id,
    name: detail.name,
    blueprint
  };
};

import { normalizeBlueprintDocument, type BlueprintDocument } from '$lib/recording/blueprint';

import { loadBlueprintDraft, type BlueprintSessionKind } from './draftStorage';
import type { WebuiBlueprintDetail } from './blueprintManager';

export type SessionBlueprintState = {
  id: string;
  name: string;
  blueprint: BlueprintDocument;
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
  let blueprint = normalizeBlueprintDocument(detail.blueprint);

  if (persistDraft && sessionId) {
    const draft = loadBlueprintDraft(sessionKind, sessionId, detail.id);
    if (draft) {
      blueprint = normalizeBlueprintDocument(draft);
    }
  }

  return {
    id: detail.id,
    name: detail.name,
    blueprint
  };
};

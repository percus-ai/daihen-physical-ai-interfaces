import type { RecorderStatus } from '$lib/recording/recorderStatus';

export type SessionRecorderStatus = {
  datasetId: string;
  matchesSession: boolean;
  state: string;
  phase: string;
  isFinalizing: boolean;
  lastError: string;
};

export const resolveSessionRecorderStatus = (
  status: RecorderStatus | Record<string, unknown> | null | undefined,
  sessionId: string
): SessionRecorderStatus => {
  const payload = (status ?? {}) as Record<string, unknown>;
  const datasetId = typeof payload.dataset_id === 'string' ? payload.dataset_id : '';
  const matchesSession = !sessionId || (Boolean(datasetId) && datasetId === sessionId);
  const rawState = String(payload.state ?? payload.status ?? '');
  const rawPhase = String(payload.phase ?? 'wait');

  return {
    datasetId,
    matchesSession,
    state: matchesSession ? rawState : 'inactive',
    phase: matchesSession ? rawPhase : 'wait',
    isFinalizing: matchesSession && (Boolean(payload.is_finalizing_episode) || rawPhase === 'finalizing'),
    lastError: matchesSession ? String(payload.last_error ?? '') : ''
  };
};

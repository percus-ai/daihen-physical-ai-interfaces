export type TimedTrainingMetricPoint = {
  step?: number;
  ts?: string | null;
};

export type TrainingEtaEstimate = {
  latestStep: number;
  remainingSteps: number;
  secondsPerStep: number;
  estimatedRemainingMs: number;
  estimatedEndMs: number;
  sampleStartStep: number;
  sampleEndStep: number;
};

type NormalizedTimedPoint = {
  step: number;
  tsMs: number;
};

const DEFAULT_SAMPLE_SIZE = 20;

const parseTimestampMs = (value: string | null | undefined): number | null => {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
};

const normalizeTimedPoints = (points: TimedTrainingMetricPoint[]): NormalizedTimedPoint[] => {
  return points
    .map((point) => {
      const tsMs = parseTimestampMs(point.ts);
      if (typeof point.step !== 'number' || !Number.isFinite(point.step) || point.step < 0 || tsMs === null) {
        return null;
      }
      return { step: point.step, tsMs };
    })
    .filter((point): point is NormalizedTimedPoint => point !== null)
    .sort((left, right) => left.step - right.step || left.tsMs - right.tsMs);
};

export const estimateTrainingEta = (
  points: TimedTrainingMetricPoint[],
  totalSteps: number | null | undefined,
  nowMs: number,
  sampleSize: number = DEFAULT_SAMPLE_SIZE
): TrainingEtaEstimate | null => {
  if (!totalSteps || totalSteps <= 0 || !Number.isFinite(totalSteps) || !Number.isFinite(nowMs)) {
    return null;
  }

  const normalized = normalizeTimedPoints(points);
  const latest = normalized.at(-1);
  if (!latest) return null;

  const remainingSteps = Math.max(0, Math.ceil(totalSteps - latest.step));
  if (remainingSteps === 0) {
    return {
      latestStep: latest.step,
      remainingSteps,
      secondsPerStep: 0,
      estimatedRemainingMs: 0,
      estimatedEndMs: nowMs,
      sampleStartStep: latest.step,
      sampleEndStep: latest.step
    };
  }

  const recentPoints = normalized.slice(-Math.max(2, sampleSize));
  const baseline = recentPoints.find((point) => point.step < latest.step && point.tsMs < latest.tsMs);
  if (!baseline) return null;

  const stepDelta = latest.step - baseline.step;
  const timeDeltaMs = latest.tsMs - baseline.tsMs;
  if (stepDelta <= 0 || timeDeltaMs <= 0) return null;

  const secondsPerStep = timeDeltaMs / 1000 / stepDelta;
  if (!Number.isFinite(secondsPerStep) || secondsPerStep <= 0) return null;

  const estimatedRemainingMs = remainingSteps * secondsPerStep * 1000;
  return {
    latestStep: latest.step,
    remainingSteps,
    secondsPerStep,
    estimatedRemainingMs,
    estimatedEndMs: nowMs + estimatedRemainingMs,
    sampleStartStep: baseline.step,
    sampleEndStep: latest.step
  };
};

export const formatSecondsPerStep = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-';
  if (value === 0) return '0秒/step';
  if (value < 1) return `${value.toFixed(2)}秒/step`;
  if (value < 10) return `${value.toFixed(1)}秒/step`;
  return `${Math.round(value).toLocaleString('ja-JP')}秒/step`;
};

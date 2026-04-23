export type LossMetricPoint = {
  step: number;
  loss: number;
};

export type LossChartPoint = LossMetricPoint & {
  x: number;
  y: number;
};

export type CheckpointMarkerStatus = 'pending' | 'saved' | 'uploading' | 'uploaded';

export type CheckpointMarker = {
  step: number;
  status: CheckpointMarkerStatus;
};

export type LossChartCheckpointMarker = CheckpointMarker & {
  x: number;
};

export type LossChartModel = {
  hasData: boolean;
  xMax: number;
  yMax: number;
  xTicks: number[];
  yTicks: number[];
  checkpointMarkers: LossChartCheckpointMarker[];
  trainPoints: LossChartPoint[];
  valPoints: LossChartPoint[];
  trainPath: string;
  valPath: string;
};

export type LossChartHover = {
  step: number;
  x: number;
  trainPoint: LossChartPoint | null;
  valPoint: LossChartPoint | null;
};

export const LOSS_CHART_WIDTH = 1000;
export const LOSS_CHART_HEIGHT = 340;
export const LOSS_CHART_PADDING = {
  top: 24,
  right: 28,
  bottom: 42,
  left: 58
};

const plotWidth = LOSS_CHART_WIDTH - LOSS_CHART_PADDING.left - LOSS_CHART_PADDING.right;
const plotHeight = LOSS_CHART_HEIGHT - LOSS_CHART_PADDING.top - LOSS_CHART_PADDING.bottom;
const plotRight = LOSS_CHART_WIDTH - LOSS_CHART_PADDING.right;
const plotBottom = LOSS_CHART_HEIGHT - LOSS_CHART_PADDING.bottom;

const clamp = (value: number, min: number, max: number): number => {
  return Math.min(max, Math.max(min, value));
};

const isFinitePoint = (point: LossMetricPoint): boolean => {
  return Number.isFinite(point.step) && Number.isFinite(point.loss) && point.step >= 0;
};

const normalizeSeries = (series: LossMetricPoint[]): LossMetricPoint[] => {
  return series
    .filter(isFinitePoint)
    .slice()
    .sort((left, right) => left.step - right.step);
};

const normalizeCheckpointMarkers = (
  markers: CheckpointMarker[],
  xMax: number
): LossChartCheckpointMarker[] => {
  return markers
    .filter((marker) => Number.isFinite(marker.step) && marker.step > 0 && marker.step <= xMax)
    .map((marker) => ({
      step: marker.step,
      status: marker.status,
      x: getChartX(marker.step, xMax)
    }))
    .sort((left, right) => left.step - right.step);
};

const buildTicks = (max: number, count: number): number[] => {
  if (max <= 0) return [0];
  return Array.from({ length: count }, (_, index) => {
    const ratio = index / (count - 1);
    return Math.round(max * ratio);
  }).filter((value, index, values) => index === 0 || value !== values[index - 1]);
};

const buildLossTicks = (max: number): number[] => {
  const tickCount = 5;
  return Array.from({ length: tickCount }, (_, index) => {
    const ratio = index / (tickCount - 1);
    return max * ratio;
  });
};

const resolveXMax = (
  train: LossMetricPoint[],
  val: LossMetricPoint[],
  configuredTotalSteps: number | null | undefined
): number => {
  if (configuredTotalSteps && configuredTotalSteps > 0) {
    return configuredTotalSteps;
  }

  const maxStep = Math.max(0, ...train.map((point) => point.step), ...val.map((point) => point.step));
  return maxStep > 0 ? maxStep : 1;
};

const resolveYMax = (train: LossMetricPoint[], val: LossMetricPoint[]): number => {
  const maxLoss = Math.max(0, ...train.map((point) => point.loss), ...val.map((point) => point.loss));
  if (maxLoss <= 0) return 1;
  return maxLoss * 1.08;
};

const toChartPoint = (point: LossMetricPoint, xMax: number, yMax: number): LossChartPoint => {
  const x = LOSS_CHART_PADDING.left + (point.step / xMax) * plotWidth;
  const y = plotBottom - (point.loss / yMax) * plotHeight;
  return {
    ...point,
    x: clamp(x, LOSS_CHART_PADDING.left, plotRight),
    y: clamp(y, LOSS_CHART_PADDING.top, plotBottom)
  };
};

const buildPath = (points: LossChartPoint[]): string => {
  return points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(' ');
};

const nearestPoint = (
  points: LossChartPoint[],
  step: number
): LossChartPoint | null => {
  if (!points.length) return null;
  return points.reduce((nearest, point) => {
    return Math.abs(point.step - step) < Math.abs(nearest.step - step) ? point : nearest;
  });
};

export const formatStepValue = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-';
  if (Math.abs(value) >= 1000) {
    return `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)}k`;
  }
  return Math.round(value).toLocaleString('ja-JP');
};

export const formatLossValue = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-';
  const abs = Math.abs(value);
  if (abs === 0) return '0';
  if (abs < 0.001) return value.toExponential(2);
  if (abs < 1) return value.toFixed(4);
  if (abs < 10) return value.toFixed(3);
  return value.toFixed(2);
};

export const buildLossChartModel = (
  trainSeries: LossMetricPoint[],
  valSeries: LossMetricPoint[],
  configuredTotalSteps?: number | null,
  checkpointMarkers: CheckpointMarker[] = []
): LossChartModel => {
  const train = normalizeSeries(trainSeries);
  const val = normalizeSeries(valSeries);
  const xMax = resolveXMax(train, val, configuredTotalSteps);
  const yMax = resolveYMax(train, val);
  const trainPoints = train.map((point) => toChartPoint(point, xMax, yMax));
  const valPoints = val.map((point) => toChartPoint(point, xMax, yMax));

  return {
    hasData: trainPoints.length > 0 || valPoints.length > 0,
    xMax,
    yMax,
    xTicks: buildTicks(xMax, 7),
    yTicks: buildLossTicks(yMax),
    checkpointMarkers: normalizeCheckpointMarkers(checkpointMarkers, xMax),
    trainPoints,
    valPoints,
    trainPath: buildPath(trainPoints),
    valPath: buildPath(valPoints)
  };
};

export const getLossChartHover = (
  model: LossChartModel,
  viewBoxX: number
): LossChartHover | null => {
  const points = [...model.trainPoints, ...model.valPoints];
  if (!points.length) return null;

  const clampedX = clamp(viewBoxX, LOSS_CHART_PADDING.left, plotRight);
  const step = ((clampedX - LOSS_CHART_PADDING.left) / plotWidth) * model.xMax;
  const target = nearestPoint(points, step);
  if (!target) return null;

  return {
    step: target.step,
    x: target.x,
    trainPoint: model.trainPoints.find((point) => point.step === target.step) ?? null,
    valPoint: model.valPoints.find((point) => point.step === target.step) ?? null
  };
};

export const getChartX = (step: number, xMax: number): number => {
  return LOSS_CHART_PADDING.left + (step / xMax) * plotWidth;
};

export const getChartY = (loss: number, yMax: number): number => {
  return plotBottom - (loss / yMax) * plotHeight;
};

import { formatBytes } from '$lib/format';
import type { StorageDatasetInfo, StorageDatasetSourceInfo } from '$lib/api/client';

export type DatasetDetailMetric = {
  label: string;
  value: string;
};

const formatCount = (value: number | null | undefined, suffix = ''): string => {
  if (value === null || value === undefined) return '未取得';
  return `${new Intl.NumberFormat('ja-JP').format(value)}${suffix}`;
};

const formatDecimal = (value: number | null | undefined, digits = 1, suffix = ''): string => {
  if (value === null || value === undefined) return '未取得';
  return `${value.toFixed(digits)}${suffix}`;
};

export const formatDurationSeconds = (value: number | null | undefined): string => {
  if (value === null || value === undefined || value <= 0) return '未取得';
  const rounded = Math.round(value);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const seconds = rounded % 60;
  if (hours > 0) return `${hours}時間 ${minutes}分`;
  if (minutes > 0) return `${minutes}分 ${seconds}秒`;
  return `${seconds}秒`;
};

export const buildDatasetDetailMetrics = (dataset: StorageDatasetInfo | null | undefined): DatasetDetailMetric[] => {
  const detail = dataset?.detail;
  return [
    { label: 'サイズ', value: formatBytes(dataset?.size_bytes) },
    { label: 'エピソード数', value: formatCount(dataset?.episode_count, '件') },
    { label: '総フレーム数', value: formatCount(detail?.total_frames, ' frames') },
    { label: 'FPS', value: formatDecimal(detail?.fps, 1) },
    { label: '総時間', value: formatDurationSeconds(detail?.duration_seconds) },
    { label: 'カメラ数', value: formatCount(detail?.camera_count, '系統') },
    { label: '信号項目', value: formatCount(detail?.signal_field_count, '件') }
  ];
};

export const buildSourceDatasetFacts = (source: StorageDatasetSourceInfo): string[] => {
  const facts: string[] = [];
  if (source.episode_count !== null && source.episode_count !== undefined) {
    facts.push(`${new Intl.NumberFormat('ja-JP').format(source.episode_count)} episodes`);
  }
  if (source.total_frames !== null && source.total_frames !== undefined) {
    facts.push(`${new Intl.NumberFormat('ja-JP').format(source.total_frames)} frames`);
  }
  if (source.fps !== null && source.fps !== undefined) {
    facts.push(`${source.fps.toFixed(1)} FPS`);
  }
  if (source.duration_seconds !== null && source.duration_seconds !== undefined && source.duration_seconds > 0) {
    facts.push(formatDurationSeconds(source.duration_seconds));
  }
  if (source.size_bytes !== null && source.size_bytes !== undefined && source.size_bytes > 0) {
    facts.push(formatBytes(source.size_bytes));
  }
  return facts;
};

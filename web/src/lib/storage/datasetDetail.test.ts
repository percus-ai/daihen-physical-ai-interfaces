import { describe, expect, it } from 'vitest';
import { buildDatasetDetailMetrics, buildSourceDatasetFacts, formatDurationSeconds } from './datasetDetail';

describe('datasetDetail helpers', () => {
  it('formats synced dataset metrics with local detail values', () => {
    const metrics = buildDatasetDetailMetrics({
      id: 'dataset-a',
      name: 'Dataset A',
      source_datasets: [],
      size_bytes: 1024,
      episode_count: 12,
      detail: {
        total_frames: 3600,
        fps: 30,
        duration_seconds: 120,
        use_videos: true,
        camera_count: 2,
        signal_field_count: 4,
        cameras: [],
        signal_fields: []
      }
    });

    expect(metrics).toEqual([
      { label: 'サイズ', value: '1.0 KB' },
      { label: 'エピソード数', value: '12件' },
      { label: '総フレーム数', value: '3,600 frames' },
      { label: 'FPS', value: '30.0' },
      { label: '総時間', value: '2分 0秒' },
      { label: 'カメラ数', value: '2系統' },
      { label: '信号項目', value: '4件' }
    ]);
  });

  it('marks local-only metrics as unavailable when dataset is not synced', () => {
    const metrics = buildDatasetDetailMetrics({
      id: 'dataset-b',
      name: 'Dataset B',
      source_datasets: [],
      size_bytes: 2048,
      episode_count: 3,
      is_local: false,
      detail: null
    });

    expect(metrics[0]).toEqual({ label: 'サイズ', value: '2.0 KB' });
    expect(metrics[1]).toEqual({ label: 'エピソード数', value: '3件' });
    expect(metrics.slice(2).every((metric) => metric.value === '未取得')).toBe(true);
  });

  it('builds compact lineage facts from enriched source datasets', () => {
    expect(
      buildSourceDatasetFacts({
        dataset_id: 'source-a',
        name: 'Source A',
        episode_count: 8,
        total_frames: 240,
        fps: 30,
        duration_seconds: 8,
        size_bytes: 4096
      })
    ).toEqual(['8 episodes', '240 frames', '30.0 FPS', '8秒', '4.0 KB']);
  });

  it('formats duration in a human readable way', () => {
    expect(formatDurationSeconds(3720)).toBe('1時間 2分');
    expect(formatDurationSeconds(45)).toBe('45秒');
    expect(formatDurationSeconds(undefined)).toBe('未取得');
  });
});

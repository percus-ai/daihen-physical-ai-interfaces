import { describe, expect, it } from 'vitest';

import {
  buildLossChartModel,
  formatLossValue,
  getLossChartHover,
  LOSS_CHART_PADDING,
  LOSS_CHART_WIDTH
} from '$lib/training/lossChart';

describe('lossChart', () => {
  it('uses configured total steps as the x-axis maximum', () => {
    const chart = buildLossChartModel([{ step: 100, loss: 0.2 }], [], 3000);

    expect(chart.xMax).toBe(3000);
    expect(chart.xTicks.at(-1)).toBe(3000);
  });

  it('falls back to the maximum observed step when total steps are missing', () => {
    const chart = buildLossChartModel([{ step: 100, loss: 0.2 }], [{ step: 250, loss: 0.4 }]);

    expect(chart.xMax).toBe(250);
  });

  it('returns the closest point for hover lookups', () => {
    const chart = buildLossChartModel(
      [
        { step: 100, loss: 0.2 },
        { step: 200, loss: 0.1 }
      ],
      [{ step: 200, loss: 0.15 }],
      300
    );
    const plotWidth = LOSS_CHART_WIDTH - LOSS_CHART_PADDING.left - LOSS_CHART_PADDING.right;
    const xAtStep200 = LOSS_CHART_PADDING.left + (200 / 300) * plotWidth;
    const hover = getLossChartHover(chart, xAtStep200);

    expect(hover?.step).toBe(200);
    expect(hover?.trainPoint?.loss).toBe(0.1);
    expect(hover?.valPoint?.loss).toBe(0.15);
  });

  it('places checkpoint markers on the configured x-axis', () => {
    const chart = buildLossChartModel(
      [{ step: 100, loss: 0.2 }],
      [],
      1000,
      [
        { step: 500, status: 'saved' },
        { step: 1500, status: 'uploaded' }
      ]
    );
    const plotWidth = LOSS_CHART_WIDTH - LOSS_CHART_PADDING.left - LOSS_CHART_PADDING.right;

    expect(chart.checkpointMarkers).toHaveLength(1);
    expect(chart.checkpointMarkers[0].step).toBe(500);
    expect(chart.checkpointMarkers[0].status).toBe('saved');
    expect(chart.checkpointMarkers[0].x).toBeCloseTo(LOSS_CHART_PADDING.left + plotWidth / 2);
  });

  it('formats small loss values without losing precision', () => {
    expect(formatLossValue(0.012345)).toBe('0.0123');
    expect(formatLossValue(0.0000123)).toBe('1.23e-5');
  });
});

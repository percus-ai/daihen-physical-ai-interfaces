import { describe, expect, it } from 'vitest';

import { GPU_MODELS, getGpuModelLabel } from '$lib/policies';

describe('GPU model policies', () => {
  it('keeps backend-compatible values for Ada and A6000 models', () => {
    expect(GPU_MODELS.find((gpu) => gpu.label === 'RTX 6000ADA')?.value).toBe('RTX6000ADA');
    expect(GPU_MODELS.find((gpu) => gpu.label === 'RTX A6000')?.value).toBe('RTXA6000');
  });

  it('maps backend values to UI labels', () => {
    expect(getGpuModelLabel('RTX6000ADA')).toBe('RTX 6000ADA');
    expect(getGpuModelLabel('RTXA6000')).toBe('RTX A6000');
    expect(getGpuModelLabel('H100')).toBe('H100');
  });
});

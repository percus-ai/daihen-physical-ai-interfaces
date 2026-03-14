import { describe, expect, it } from 'vitest';

import { getDashboardStorageUsageBytes } from './storageUsageSummary';

describe('storageUsageSummary', () => {
  it('uses total storage usage for the dashboard summary', () => {
    expect(
      getDashboardStorageUsageBytes({
        datasets_size_bytes: 10,
        models_size_bytes: 20,
        archive_size_bytes: 30,
        total_size_bytes: 60
      })
    ).toBe(60);
  });

  it('falls back to zero when usage is unavailable', () => {
    expect(getDashboardStorageUsageBytes()).toBe(0);
  });
});

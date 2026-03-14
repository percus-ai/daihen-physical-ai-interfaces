import type { StorageUsageResponse } from '$lib/api/client';

export const getDashboardStorageUsageBytes = (
  usage?: StorageUsageResponse | null
): number => usage?.total_size_bytes ?? 0;

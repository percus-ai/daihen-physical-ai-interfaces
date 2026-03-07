export type GpuAvailabilityItem = {
  gpu_model: string;
  gpu_count: number;
  instance_type: string;
  spot_available?: boolean;
  ondemand_available?: boolean;
  spot_locations?: string[];
  ondemand_locations?: string[];
  spot_price_per_hour?: number | null;
};

export type GpuAvailabilityResponse = {
  available?: GpuAvailabilityItem[];
};

export type TrainingInstanceCandidate = {
  provider: 'verda' | 'vast';
  candidate_id: string;
  title: string;
  instance_type?: string | null;
  offer_id?: number | null;
  gpu_model: string;
  gpu_count: number;
  mode: 'spot' | 'ondemand';
  route?: string;
  location?: string | null;
  price_per_hour?: number | null;
  detail?: string;
  storage_gb?: number | null;
  gpu_memory_gb?: number | null;
  cpu_cores?: number | null;
  system_memory_gb?: number | null;
};

export type TrainingInstanceCandidatesResponse = {
  candidates?: TrainingInstanceCandidate[];
  checked_at?: string;
};

export type TrainingProviderCapabilityResponse = {
  verda_enabled?: boolean;
  vast_enabled?: boolean;
  missing_vast_env?: string[];
};

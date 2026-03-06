export type HealthLevel = 'healthy' | 'degraded' | 'error' | 'unknown';

export type StatusAlert = {
  code: string;
  level: HealthLevel;
  summary: string;
  source: string;
};

export type OverallStatus = {
  level: HealthLevel;
  summary: string;
  active_alerts?: StatusAlert[];
};

export type RuntimeTorchStatus = {
  version?: string | null;
  cuda_version?: string | null;
  source?: string;
  gpu_capability?: string | null;
  cuda_compatible?: boolean | null;
};

export type RuntimeDetails = {
  torchvision_version?: string | null;
  torchaudio_version?: string | null;
  packages_hash?: string | null;
  bundled_torch_present?: boolean;
  error?: string | null;
};

export type RuntimeGroupStatus = {
  runtime_key: string;
  level: HealthLevel;
  policies?: string[];
  env_name: string;
  torch?: RuntimeTorchStatus;
  details?: RuntimeDetails;
};

export type RecorderDependencies = {
  cameras_ready?: boolean | null;
  robot_ready?: boolean | null;
  storage_ready?: boolean | null;
};

export type RecorderStatusSnapshot = {
  level: HealthLevel;
  state?: string;
  process_alive?: boolean;
  session_id?: string | null;
  active_profile?: string | null;
  dataset_id?: string | null;
  output_path?: string | null;
  last_frame_at?: string | null;
  write_ok?: boolean | null;
  disk_ok?: boolean | null;
  dependencies?: RecorderDependencies;
  last_error?: string | null;
};

export type InferenceStatusSnapshot = {
  level: HealthLevel;
  state?: string;
  session_id?: string | null;
  policy_type?: string | null;
  model_id?: string | null;
  device?: string | null;
  env_name?: string | null;
  runtime_key?: string | null;
  worker_alive?: boolean;
  queue_length?: number | null;
  last_error?: string | null;
};

export type ContainerStatusSnapshot = {
  name: string;
  state: string;
};

export type VlaborStatusSnapshot = {
  level: HealthLevel;
  state?: string;
  containers?: ContainerStatusSnapshot[];
  last_error?: string | null;
};

export type Ros2StatusSnapshot = {
  level: HealthLevel;
  state?: string;
  required_nodes_ok?: boolean | null;
  required_topics_ok?: boolean | null;
  missing_nodes?: string[];
  missing_topics?: string[];
  last_error?: string | null;
};

export type ServicesStatus = {
  recorder?: RecorderStatusSnapshot;
  inference?: InferenceStatusSnapshot;
  vlabor?: VlaborStatusSnapshot;
  ros2?: Ros2StatusSnapshot;
};

export type GpuDeviceSnapshot = {
  index: number;
  name: string;
  memory_total_mb?: number | null;
  memory_used_mb?: number | null;
  utilization_gpu_pct?: number | null;
  temperature_c?: number | null;
};

export type GpuSnapshot = {
  level: HealthLevel;
  driver_version?: string | null;
  cuda_version?: string | null;
  gpus?: GpuDeviceSnapshot[];
};

export type SystemStatusSnapshot = {
  generated_at: string;
  overall?: OverallStatus;
  runtime_groups?: RuntimeGroupStatus[];
  services?: ServicesStatus;
  gpu?: GpuSnapshot;
};

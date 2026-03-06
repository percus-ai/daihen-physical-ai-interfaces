export type RuntimeEnvState = 'idle' | 'building' | 'deleting' | 'completed' | 'failed';

export type RuntimeEnvLogEntry = {
  at: string;
  type: string;
  step?: string | null;
  message?: string | null;
  error?: string | null;
  percent?: number | null;
};

export type RuntimeEnvStatusSnapshot = {
  env_name: string;
  description?: string | null;
  policies?: string[];
  exists: boolean;
  gpu_required: boolean;
  python_path?: string | null;
  packages_hash?: string | null;
  state: RuntimeEnvState;
  current_step?: string | null;
  progress_percent?: number | null;
  message?: string | null;
  started_at?: string | null;
  updated_at: string;
  finished_at?: string | null;
  last_error?: string | null;
  logs?: RuntimeEnvLogEntry[];
  can_build: boolean;
  can_rebuild: boolean;
  can_delete: boolean;
};

export type RuntimeEnvSnapshot = {
  updated_at: string;
  active_env_name?: string | null;
  envs: RuntimeEnvStatusSnapshot[];
};

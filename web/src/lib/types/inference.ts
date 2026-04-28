export type InferenceModel = {
  model_id?: string;
  name?: string;
  created_at?: string | null;
  owner_user_id?: string | null;
  owner_name?: string | null;
  profile_name?: string | null;
  policy_type?: string;
  training_steps?: number | null;
  batch_size?: number | null;
  source?: string;
  size_mb?: number;
  is_loaded?: boolean;
  is_local?: boolean;
  task_candidates?: string[];
};

export type InferenceValueOption = {
  value: string;
  label: string;
  total_count?: number;
};

export type InferenceOwnerOption = {
  user_id: string;
  label: string;
  total_count?: number;
};

export type InferenceNumericOption = {
  value: number;
  label: string;
  total_count?: number;
};

export type InferenceModelsResponse = {
  models?: InferenceModel[];
  owner_options?: InferenceOwnerOption[];
  profile_options?: InferenceValueOption[];
  training_steps_options?: InferenceNumericOption[];
  batch_size_options?: InferenceNumericOption[];
};

export type InferenceRuntimeTarget = {
  id: string;
  kind: 'cpu' | 'cuda' | string;
  label: string;
  display_name?: string | null;
  description?: string | null;
  device: string;
  available?: boolean;
  config_id?: string | null;
  env_name?: string | null;
  build_id?: string | null;
  supported_platforms?: string[];
  current_platform?: string | null;
  platform_supported?: boolean | null;
  supported_sms?: string[];
  current_sm?: string | null;
  sm_supported?: boolean | null;
};

export type InferenceRuntimeTargetsResponse = {
  policy_type?: string | null;
  current_platform?: string | null;
  current_sm?: string | null;
  targets?: InferenceRuntimeTarget[];
  recommended_target_id?: string;
};

export type RunnerStatus = {
  active?: boolean;
  session_id?: string;
  task?: string;
  queue_length?: number;
  last_error?: string;
  recording_dataset_id?: string | null;
};

export type InferenceRunnerStatusResponse = {
  runner_status?: RunnerStatus;
  gpu_host_status?: {
    status?: string;
    session_id?: string;
    pid?: number;
    last_error?: string;
  };
};

export type OperateStatusResponse = {
  network?: {
    status?: string;
    details?: {
      zmq?: { status?: string };
      zenoh?: { status?: string };
      rosbridge?: { status?: string };
    };
  };
};

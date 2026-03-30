export type InferenceModel = {
  model_id?: string;
  name?: string;
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

export type InferenceDeviceInfo = {
  device?: string;
  available?: boolean;
  memory_total_mb?: number | null;
  memory_free_mb?: number | null;
};

export type InferenceDeviceCompatibilityResponse = {
  devices?: InferenceDeviceInfo[];
  recommended?: string;
};

export type RunnerStatus = {
  active?: boolean;
  session_id?: string;
  task?: string;
  queue_length?: number;
  last_error?: string;
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

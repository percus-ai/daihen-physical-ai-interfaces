export type BundledTorchState = 'idle' | 'building' | 'cleaning' | 'completed' | 'failed';
export type BundledTorchAction = 'build' | 'rebuild' | 'clean';

export type BundledTorchPlatformInfo = {
  platform_name: string;
  is_jetson: boolean;
  pytorch_build_required: boolean;
  supported: boolean;
  gpu_name?: string | null;
  cuda_version?: string | null;
};

export type BundledTorchInstallStatus = {
  exists: boolean;
  pytorch_version?: string | null;
  torchvision_version?: string | null;
  numpy_version?: string | null;
  pytorch_path?: string | null;
  torchvision_path?: string | null;
  is_valid: boolean;
};

export type BundledTorchLogEntry = {
  at: string;
  type: string;
  step?: string | null;
  message?: string | null;
  line?: string | null;
  percent?: number | null;
};

export type BundledTorchBuildSnapshot = {
  platform: BundledTorchPlatformInfo;
  install: BundledTorchInstallStatus;
  recommended_pytorch_version?: string | null;
  recommended_torchvision_version?: string | null;
  recommended_reason?: string | null;
  state: BundledTorchState;
  current_action?: BundledTorchAction | null;
  current_step?: string | null;
  message?: string | null;
  started_at?: string | null;
  updated_at: string;
  finished_at?: string | null;
  requested_pytorch_version?: string | null;
  requested_torchvision_version?: string | null;
  last_error?: string | null;
  logs?: BundledTorchLogEntry[];
  can_build: boolean;
  can_clean: boolean;
  can_rebuild: boolean;
};

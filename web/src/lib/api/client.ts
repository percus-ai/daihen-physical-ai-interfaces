import { getBackendUrl } from '$lib/config';
import { cacheAuthenticatedGate, invalidateAuthGate } from '$lib/auth/gate';
import type { BundledTorchBuildSnapshot } from '$lib/types/bundledTorch';
import type { RuntimeEnvSnapshot } from '$lib/types/runtimeEnv';
import type { SystemSettings, UserSettings } from '$lib/types/settings';
import type { FeaturesRepoSuggestions } from '$lib/types/settings';

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

export type ExperimentDetail = {
  id: string;
  model_id?: string | null;
  profile_instance_id?: string | null;
  name?: string | null;
  purpose?: string | null;
  evaluation_count?: number;
  metric?: string;
  metric_options?: string[] | null;
  result_image_files?: string[] | null;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type ExperimentListResponse = {
  experiments?: ExperimentDetail[];
  total?: number;
};

export type ExperimentEvaluation = {
  id?: string;
  experiment_id?: string;
  trial_index: number;
  value?: string;
  blueprint_id?: string | null;
  image_files?: string[] | null;
  notes?: string | null;
  episode_links?: ExperimentEpisodeLink[];
  created_at?: string;
};

export type ExperimentEpisodeLink = {
  dataset_id: string;
  episode_index: number;
  sort_order: number;
};

export type ExperimentEpisodeLinkInput = {
  dataset_id: string;
  episode_index: number;
  sort_order?: number | null;
};

export type ExperimentEvaluationReplaceItem = {
  value?: string | null;
  blueprint_id?: string | null;
  image_files?: string[] | null;
  notes?: string | null;
  episode_links?: ExperimentEpisodeLinkInput[] | null;
};

export type ExperimentEvaluationReplaceRequest = {
  items: ExperimentEvaluationReplaceItem[];
};

export type ExperimentEvaluationListResponse = {
  evaluations?: ExperimentEvaluation[];
  total?: number;
};

export type ExperimentAnalysis = {
  id?: string;
  experiment_id?: string;
  block_index?: number;
  name?: string | null;
  purpose?: string | null;
  notes?: string | null;
  image_files?: string[] | null;
  created_at?: string;
  updated_at?: string;
};

export type ExperimentAnalysisListResponse = {
  analyses?: ExperimentAnalysis[];
  total?: number;
};

export type RecordingSortBy = 'created_at' | 'dataset_name' | 'owner_name' | 'profile_name' | 'episode_count' | 'size_bytes' | 'upload_status';
export type TrainingJobSortBy = 'created_at' | 'updated_at' | 'job_name' | 'owner_name' | 'policy_type' | 'status';

export type ExperimentEvaluationSummary = {
  total?: number;
  counts?: Record<string, number>;
  rates?: Record<string, number>;
};

export type ExperimentMediaUrlResponse = {
  urls?: Record<string, string>;
};

export type ExperimentUploadResponse = {
  keys?: string[];
};

export type StartupOperationAcceptedResponse = {
  operation_id: string;
  message?: string;
};

export type TabSessionLifecycle = {
  visibility: 'foreground' | 'background' | 'closing';
  reason?: string | null;
};

export type TabSessionRoute = {
  id: string;
  url: string;
  params: Record<string, string>;
};

type RealtimeSubscriptionBase = {
  subscription_id: string;
};

export type ProfilesActiveSubscription = RealtimeSubscriptionBase & {
  kind: 'profiles.active';
  params?: Record<string, never>;
};

export type ProfilesVlaborSubscription = RealtimeSubscriptionBase & {
  kind: 'profiles.vlabor';
  params?: Record<string, never>;
};

export type SystemStatusSubscription = RealtimeSubscriptionBase & {
  kind: 'system.status';
  params?: Record<string, never>;
};

export type OperateStatusSubscription = RealtimeSubscriptionBase & {
  kind: 'operate.status';
  params?: Record<string, never>;
};

export type SystemRuntimeEnvsSubscription = RealtimeSubscriptionBase & {
  kind: 'system.runtime-envs';
  params?: Record<string, never>;
};

export type SystemBundledTorchSubscription = RealtimeSubscriptionBase & {
  kind: 'system.bundled-torch';
  params?: Record<string, never>;
};

export type BuildsStatusSubscription = RealtimeSubscriptionBase & {
  kind: 'builds.status';
  params?: Record<string, never>;
};

export type BuildsLogsSubscription = RealtimeSubscriptionBase & {
  kind: 'builds.logs';
  params?: Record<string, never>;
};

export type RecordingUploadStatusSubscription = RealtimeSubscriptionBase & {
  kind: 'recording.upload-status';
  params: {
    session_id: string;
  };
};

export type StartupOperationSubscription = RealtimeSubscriptionBase & {
  kind: 'startup.operation';
  params: {
    operation_id: string;
  };
};

export type TrainingProvisionOperationSubscription = RealtimeSubscriptionBase & {
  kind: 'training.provision-operation';
  params: {
    operation_id: string;
  };
};

export type TrainingJobOperationsSubscription = RealtimeSubscriptionBase & {
  kind: 'training.job.operations';
  params: {
    job_id: string;
  };
};

export type StorageModelSyncSubscription = RealtimeSubscriptionBase & {
  kind: 'storage.model-sync';
  params: {
    job_id: string;
  };
};

export type StorageDatasetSyncSubscription = RealtimeSubscriptionBase & {
  kind: 'storage.dataset-sync';
  params: {
    job_id: string;
  };
};

export type StorageDatasetMergeSubscription = RealtimeSubscriptionBase & {
  kind: 'storage.dataset-merge';
  params: {
    job_id: string;
  };
};

export type TrainingJobCoreSubscription = RealtimeSubscriptionBase & {
  kind: 'training.job.core';
  params: {
    job_id: string;
  };
};

export type TrainingJobProvisionSubscription = RealtimeSubscriptionBase & {
  kind: 'training.job.provision';
  params: {
    job_id: string;
  };
};

export type TrainingJobMetricsSubscription = RealtimeSubscriptionBase & {
  kind: 'training.job.metrics';
  params: {
    job_id: string;
    limit?: number | null;
  };
};

export type TrainingJobLogsSubscription = RealtimeSubscriptionBase & {
  kind: 'training.job.logs';
  params: {
    job_id: string;
    log_type?: 'training' | 'setup';
    tail_lines?: number | null;
  };
};

export type TabSessionSubscription =
  | ProfilesActiveSubscription
  | ProfilesVlaborSubscription
  | SystemStatusSubscription
  | OperateStatusSubscription
  | SystemRuntimeEnvsSubscription
  | SystemBundledTorchSubscription
  | BuildsStatusSubscription
  | BuildsLogsSubscription
  | RecordingUploadStatusSubscription
  | StartupOperationSubscription
  | TrainingProvisionOperationSubscription
  | TrainingJobOperationsSubscription
  | StorageModelSyncSubscription
  | StorageDatasetSyncSubscription
  | StorageDatasetMergeSubscription
  | TrainingJobCoreSubscription
  | TrainingJobProvisionSubscription
  | TrainingJobMetricsSubscription
  | TrainingJobLogsSubscription;

export type TabSessionStateRequest = {
  revision: number;
  lifecycle: TabSessionLifecycle;
  route: TabSessionRoute;
  subscriptions: TabSessionSubscription[];
};

export type TabSessionStateResponse = {
  tab_session_id: string;
  revision: number;
  lifecycle: TabSessionLifecycle;
  route: TabSessionRoute;
  subscriptions: TabSessionSubscription[];
};

export type TabSessionStatePutResponse = {
  tab_session_id: string;
  revision: number;
  applied_at: string;
  subscription_count: number;
};

export type StartupOperationStatusResponse = {
  operation_id: string;
  kind: 'inference_start' | 'recording_create';
  state: 'queued' | 'running' | 'completed' | 'failed';
  phase?: string;
  progress_percent?: number;
  message?: string | null;
  target_session_id?: string | null;
  error?: string | null;
  detail?: {
    files_done?: number;
    total_files?: number;
    transferred_bytes?: number;
    total_bytes?: number;
    current_file?: string | null;
  };
  updated_at?: string | null;
};

export type BuildSettingState = 'unbuilt' | 'building' | 'success' | 'failed';
export type BuildSettingKind = 'env' | 'shared';
export type BuildJobState = 'queued' | 'running' | 'completed' | 'failed';

export type BuildSettingActions = {
  run: boolean;
  cancel: boolean;
  delete: boolean;
  create_error_report: boolean;
};

export type BuildSettingSummary = {
  kind: BuildSettingKind;
  setting_id: string;
  display_name: string;
  description?: string | null;
  state: BuildSettingState;
  selected?: boolean;
  config_origin?: 'default' | 'data' | null;
  config_id?: string | null;
  env_name?: string | null;
  package?: string | null;
  variant?: string | null;
  latest_build_id?: string | null;
  current_build_id?: string | null;
  current_job_id?: string | null;
  current_step_name?: string | null;
  current_step_index?: number | null;
  total_steps?: number | null;
  progress_percent?: number | null;
  latest_started_at?: string | null;
  latest_finished_at?: string | null;
  latest_error_summary?: string | null;
  actions: BuildSettingActions;
};

export type EnvBuildSettingsListResponse = {
  selected_config_id?: string | null;
  items: BuildSettingSummary[];
};

export type SharedBuildSettingsListResponse = {
  items: BuildSettingSummary[];
};

export type BuildJobSummary = {
  job_id: string;
  build_id: string;
  kind: BuildSettingKind;
  setting_id: string;
  state: BuildJobState;
  current_step_name?: string | null;
  current_step_index?: number | null;
  total_steps?: number | null;
  progress_percent?: number | null;
  message?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type BuildRunAcceptedResponse = {
  accepted: boolean;
  job: BuildJobSummary;
};

export type BuildJobCancelResponse = {
  accepted: boolean;
  job: BuildJobSummary;
};

export type BuildArtifactDeleteResponse = {
  deleted: boolean;
  kind: BuildSettingKind;
  setting_id: string;
  build_id: string;
};

export type BuildErrorReportResponse = {
  report_id: string;
  kind: BuildSettingKind;
  setting_id: string;
  build_id: string;
  object_path: string;
  uploaded_at: string;
};

export type BuildsStatusSnapshot = {
  running_jobs: BuildJobSummary[];
  envs: EnvBuildSettingsListResponse;
  shared: SharedBuildSettingsListResponse;
};

export type BuildLogEvent = {
  seq: number;
  job_id: string;
  build_id: string;
  kind: BuildSettingKind;
  setting_id: string;
  step: string;
  stream: 'stdout' | 'stderr' | string;
  line: string;
  emitted_at: string;
};

export type InferenceRunnerStartPayload = {
  model_id: string;
  device?: string;
  profile?: string;
  task?: string;
  num_episodes?: number;
  policy_options?: {
    pi0?: {
      denoising_steps?: number;
    };
    pi05?: {
      denoising_steps?: number;
    };
  };
};

export type InferenceRunnerSettingsApplyPayload = {
  task?: string;
  episode_time_s?: number;
  reset_time_s?: number;
  denoising_steps?: number;
};

export type InferenceRunnerSettingsApplyResponse = {
  success: boolean;
  message?: string;
  task?: string;
  episode_time_s?: number;
  reset_time_s?: number;
  denoising_steps?: number | null;
};

export type InferenceRecordingDecisionPayload = {
  continue_recording: boolean;
};

export type InferenceRecordingDecisionResponse = {
  success: boolean;
  message?: string;
  recording_dataset_id?: string | null;
  awaiting_continue_confirmation?: boolean;
};

export type InferenceRunnerControlResponse = {
  success: boolean;
  message?: string;
  paused?: boolean;
  teleop_enabled?: boolean;
  recorder_state?: string | null;
};

export type DatasetViewerCameraInfo = {
  key: string;
  label: string;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  codec?: string | null;
  pix_fmt?: string | null;
};

export type DatasetViewerResponse = {
  dataset_id: string;
  is_local: boolean;
  download_required: boolean;
  total_episodes: number;
  fps: number;
  use_videos: boolean;
  cameras: DatasetViewerCameraInfo[];
  dataset_meta?: Record<string, unknown> | null;
};

export type DatasetViewerEpisode = {
  episode_index: number;
  frame_count: number;
  duration_s: number;
  effective_fps: number;
};

export type DatasetViewerEpisodeListResponse = {
  dataset_id: string;
  episodes: DatasetViewerEpisode[];
  total: number;
};

export type DatasetViewerSignalField = {
  key: string;
  label: string;
  shape: number[];
  names?: string[] | null;
  dtype: string;
};

export type DatasetViewerSignalFieldsResponse = {
  dataset_id: string;
  fields: DatasetViewerSignalField[];
};

export type DatasetViewerSignalSeriesResponse = {
  dataset_id: string;
  episode_index: number;
  field: string;
  fps: number;
  names: string[];
  positions: number[][];
  timestamps: number[];
};

export type DatasetViewerEpisodeVideoWindow = {
  key: string;
  relative_path: string;
  from_s: number;
  to_s: number;
};

export type DatasetViewerEpisodeVideoWindowResponse = {
  dataset_id: string;
  episode_index: number;
  videos: DatasetViewerEpisodeVideoWindow[];
};

export type DatasetSyncJobState = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export type DatasetSyncJobDetail = {
  files_done?: number;
  total_files?: number;
  transferred_bytes?: number;
  total_bytes?: number;
  current_file?: string | null;
};

export type DatasetSyncJobStatus = {
  job_id: string;
  dataset_id: string;
  state: DatasetSyncJobState;
  progress_percent?: number;
  message?: string | null;
  error?: string | null;
  detail?: DatasetSyncJobDetail;
  created_at?: string | null;
  updated_at?: string | null;
};

export type DatasetSyncJobAcceptedResponse = {
  accepted: boolean;
  job_id: string;
  dataset_id: string;
  state: DatasetSyncJobState;
  message?: string;
};

export type DatasetSyncJobListResponse = {
  jobs: DatasetSyncJobStatus[];
};

export type DatasetSyncJobCancelResponse = {
  job_id: string;
  accepted: boolean;
  state: DatasetSyncJobState;
  message?: string;
};

export type DatasetMergeJobState = 'queued' | 'running' | 'completed' | 'failed';

export type DatasetMergeJobDetail = {
  dataset_name?: string;
  source_dataset_ids?: string[];
  step?: string;
  downloaded_dataset_ids?: string[];
  current_dataset_id?: string | null;
  current_file?: string | null;
  files_done?: number;
  total_files?: number;
  total_size?: number;
  transferred_bytes?: number;
};

export type DatasetMergeJobStatus = {
  job_id: string;
  state: DatasetMergeJobState;
  progress_percent?: number;
  message?: string | null;
  error?: string | null;
  detail?: DatasetMergeJobDetail;
  result_dataset_id?: string | null;
  result_size_bytes?: number;
  result_episode_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
};

export type DatasetMergeJobAcceptedResponse = {
  accepted: boolean;
  job_id: string;
  state: DatasetMergeJobState;
  message?: string;
};

export type ModelSyncJobState = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export type ModelSyncJobDetail = {
  files_done?: number;
  total_files?: number;
  transferred_bytes?: number;
  total_bytes?: number;
  current_file?: string | null;
};

export type ModelSyncJobStatus = {
  job_id: string;
  model_id: string;
  state: ModelSyncJobState;
  progress_percent?: number;
  message?: string | null;
  error?: string | null;
  detail?: ModelSyncJobDetail;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ModelSyncJobAcceptedResponse = {
  job_id: string;
  model_id: string;
  state: ModelSyncJobState;
  message?: string;
};

export type ModelSyncJobListResponse = {
  jobs?: ModelSyncJobStatus[];
};

export type ModelSyncJobCancelResponse = {
  job_id: string;
  accepted: boolean;
  state: ModelSyncJobState;
  message: string;
};

export type StorageSortOrder = 'asc' | 'desc';
export type StorageDatasetSortBy = 'created_at' | 'updated_at' | 'name' | 'owner_name' | 'profile_name' | 'size_bytes' | 'episode_count' | 'sync_status';
export type StorageModelSortBy = 'created_at' | 'updated_at' | 'name' | 'owner_name' | 'profile_name' | 'size_bytes' | 'policy_type' | 'sync_status';

export type StorageDatasetListQuery = {
  includeArchived?: boolean;
  profileName?: string;
  ownerUserId?: string;
  status?: string;
  datasetType?: string;
  syncStatus?: string;
  search?: string;
  createdFrom?: string;
  createdTo?: string;
  sizeMin?: number;
  sizeMax?: number;
  episodeCountMin?: number;
  episodeCountMax?: number;
  limit?: number;
  offset?: number;
  sortBy?: StorageDatasetSortBy;
  sortOrder?: StorageSortOrder;
};

export type StorageModelListQuery = {
  includeArchived?: boolean;
  profileName?: string;
  ownerUserId?: string;
  status?: string;
  policyType?: string;
  datasetId?: string;
  syncStatus?: string;
  search?: string;
  createdFrom?: string;
  createdTo?: string;
  sizeMin?: number;
  sizeMax?: number;
  limit?: number;
  offset?: number;
  sortBy?: StorageModelSortBy;
  sortOrder?: StorageSortOrder;
};

export type RecordingListQuery = {
  ownerUserId?: string;
  profileName?: string;
  uploadStatus?: string;
  search?: string;
  createdFrom?: string;
  createdTo?: string;
  sizeMin?: number;
  sizeMax?: number;
  episodeCountMin?: number;
  episodeCountMax?: number;
  sortBy?: RecordingSortBy;
  sortOrder?: StorageSortOrder;
  limit?: number;
  offset?: number;
};

export type TrainingJobListQuery = {
  days?: number;
  ownerUserId?: string;
  status?: string;
  policyType?: string;
  search?: string;
  createdFrom?: string;
  createdTo?: string;
  sortBy?: TrainingJobSortBy;
  sortOrder?: StorageSortOrder;
  limit?: number;
  offset?: number;
};

export type StorageRenameRequest = {
  name: string;
};

export type StorageUsageResponse = {
  datasets_size_bytes?: number;
  datasets_count?: number;
  models_size_bytes?: number;
  models_count?: number;
  archive_size_bytes?: number;
  archive_count?: number;
  total_size_bytes?: number;
};

export type BulkActionResultStatus = 'succeeded' | 'failed' | 'skipped';

export type BulkActionResult = {
  id: string;
  status: BulkActionResultStatus;
  message?: string;
  job_id?: string | null;
};

export type BulkActionResponse = {
  requested: number;
  succeeded: number;
  failed: number;
  skipped: number;
  results: BulkActionResult[];
};

export type ArchiveBulkResponse = {
  success: boolean;
  restored?: string[];
  deleted?: string[];
  errors?: string[];
};

export type StorageDatasetSourceInfo = {
  dataset_id: string;
  name: string;
  content_hash?: string | null;
  task_detail?: string | null;
  status?: string | null;
  episode_count?: number | null;
  size_bytes?: number | null;
  total_frames?: number | null;
  fps?: number | null;
  duration_seconds?: number | null;
  is_local?: boolean | null;
};

export type StorageDatasetCameraInfo = {
  key: string;
  label: string;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  codec?: string | null;
  pix_fmt?: string | null;
};

export type StorageDatasetSignalFieldInfo = {
  key: string;
  label: string;
  dtype?: string | null;
  axis_count: number;
  names: string[];
};

export type StorageDatasetDetailInfo = {
  total_frames?: number | null;
  fps?: number | null;
  duration_seconds?: number | null;
  use_videos?: boolean | null;
  camera_count?: number | null;
  signal_field_count?: number | null;
  cameras: StorageDatasetCameraInfo[];
  signal_fields: StorageDatasetSignalFieldInfo[];
};

export type StorageDatasetInfo = {
  id: string;
  name: string;
  owner_user_id?: string | null;
  owner_email?: string | null;
  owner_name?: string | null;
  profile_name?: string | null;
  profile_snapshot?: Record<string, unknown> | null;
  source?: string | null;
  status?: string | null;
  dataset_type?: string | null;
  task_detail?: string | null;
  content_hash?: string | null;
  archived_at?: string | null;
  source_datasets: StorageDatasetSourceInfo[];
  episode_count?: number | null;
  size_bytes?: number | null;
  is_local?: boolean;
  detail?: StorageDatasetDetailInfo | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type StorageDatasetListResponse = {
  datasets?: StorageDatasetInfo[];
  total?: number;
};

export type StorageModelInfo = {
  dataset?: {
    id: string;
    name: string;
    status?: string | null;
    profile_name?: string | null;
    episode_count?: number | null;
    size_bytes?: number | null;
    is_local?: boolean | null;
  } | null;
  id: string;
  name: string;
  owner_user_id?: string | null;
  owner_email?: string | null;
  owner_name?: string | null;
  dataset_id?: string | null;
  profile_name?: string | null;
  profile_snapshot?: Record<string, unknown> | null;
  policy_type?: string | null;
  training_steps?: number | null;
  batch_size?: number | null;
  size_bytes?: number | null;
  is_local?: boolean;
  source?: string | null;
  status?: string | null;
  archived_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type RescueCPUResult = {
  job_id: string;
  old_instance_id: string;
  volume_id: string;
  instance_id: string;
  instance_type: string;
  ip: string;
  ssh_user: string;
  ssh_private_key: string;
  ssh_port?: number | null;
  location: string;
  message: string;
};

export type RescueCPUProgressMessage = {
  type?: string;
  phase?: string;
  progress_percent?: number;
  message?: string;
  error?: string;
  elapsed?: number;
  timeout?: number;
  result?: RescueCPUResult;
};

export type RemoteCheckpointListResponse = {
  job_id: string;
  checkpoint_names: string[];
  checkpoint_root: string;
  ssh_available: boolean;
  requires_rescue_cpu: boolean;
  message: string;
};

export type RemoteCheckpointUploadResult = {
  job_id: string;
  checkpoint_name: string;
  step: number;
  r2_step_path: string;
  model_id: string;
  db_registered: boolean;
  message: string;
};

export type RemoteCheckpointUploadProgressMessage = {
  type?: string;
  phase?: string;
  progress_percent?: number;
  message?: string;
  error?: string;
  checkpoint_name?: string;
  step?: number;
  model_id?: string;
  model_r2_path?: string;
  result?: RemoteCheckpointUploadResult;
};

export type TrainingProviderCapabilityResponse = {
  verda_enabled?: boolean;
  vast_enabled?: boolean;
  missing_vast_env?: string[];
};

export type LastTrainingConfigResponse = {
  job_id?: string | null;
  job_name?: string | null;
  created_at?: string | null;
  training_config?: Record<string, unknown> | null;
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

export type TrainingProvisionOperationAcceptedResponse = {
  accepted?: boolean;
  operation_id: string;
  state?: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  message?: string;
};

export type TrainingProvisionOperationStatusResponse = {
  operation_id: string;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  step?: string;
  message?: string | null;
  failure_reason?: string | null;
  provider?: 'verda' | 'vast';
  instance_id?: string | null;
  job_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type TrainingJobOperationKind = 'checkpoint_upload' | 'rescue_cpu';
export type TrainingJobOperationState = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export type TrainingJobOperationAcceptedResponse = {
  accepted?: boolean;
  operation_id: string;
  job_id: string;
  kind: TrainingJobOperationKind;
  state?: TrainingJobOperationState;
  message?: string;
  reused?: boolean;
};

export type TrainingJobOperationStatusResponse = {
  operation_id: string;
  job_id: string;
  kind: TrainingJobOperationKind;
  state: TrainingJobOperationState;
  phase?: string;
  progress_percent?: number;
  message?: string | null;
  error?: string | null;
  detail?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

let refreshPromise: Promise<boolean> | null = null;

function withJsonHeaders(options: RequestInit = {}): RequestInit {
  const method = (options.method ?? 'GET').toUpperCase();
  if (method === 'GET' || method === 'HEAD') {
    return {
      ...options,
      headers: {
        ...options.headers
      }
    };
  }
  return {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  };
}

async function baseFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const baseUrl = getBackendUrl();
  return fetch(`${baseUrl}${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      ...options.headers
    }
  });
}

async function parseApiError(response: Response): Promise<string> {
  let detail = `API error: ${response.status}`;
  try {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/json')) {
      const payload = await response.json();
      if (payload?.detail) {
        detail = String(payload.detail);
      }
    } else {
      const text = await response.text();
      if (text) detail = text;
    }
  } catch {
    // ignore parsing errors
  }
  return detail;
}

async function fetchJsonNoRefresh<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await baseFetch(path, withJsonHeaders(options));

  if (!response.ok) {
    throw new ApiError(response.status, await parseApiError(response));
  }

  return response.json();
}

async function fetchTextNoRefresh(path: string, options: RequestInit = {}): Promise<string> {
  const response = await baseFetch(path, options);
  if (!response.ok) {
    throw new ApiError(response.status, await parseApiError(response));
  }
  return response.text();
}

async function fetchFormNoRefresh<T>(
  path: string,
  formData: FormData,
  options: RequestInit = {}
): Promise<T> {
  const response = await baseFetch(path, {
    ...options,
    method: options.method ?? 'POST',
    body: formData
  });

  if (!response.ok) {
    throw new ApiError(response.status, await parseApiError(response));
  }

  return response.json();
}

async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        await fetchJsonNoRefresh('/api/auth/refresh', { method: 'POST' });
        cacheAuthenticatedGate();
        return true;
      } catch {
        invalidateAuthGate();
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

async function withAuthRetry<T>(fn: () => Promise<T>): Promise<T> {
  try {
    const result = await fn();
    cacheAuthenticatedGate();
    return result;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const refreshed = await refreshSession();
      if (refreshed) {
        const result = await fn();
        cacheAuthenticatedGate();
        return result;
      }
      invalidateAuthGate();
    }
    throw err;
  }
}

export async function fetchApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  return withAuthRetry(() => fetchJsonNoRefresh<T>(path, options));
}

export async function fetchText(path: string, options: RequestInit = {}): Promise<string> {
  return withAuthRetry(() => fetchTextNoRefresh(path, options));
}

function buildQueryString(params: Record<string, string | number | boolean | null | undefined>): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    searchParams.set(key, String(value));
  }
  const query = searchParams.toString();
  return query ? `?${query}` : '';
}

export async function fetchForm<T>(
  path: string,
  formData: FormData,
  options: RequestInit = {}
): Promise<T> {
  return withAuthRetry(() => fetchFormNoRefresh<T>(path, formData, options));
}

export const api = {
  health: () => fetchApi<{ status: string }>('/health'),
  auth: {
    status: () =>
      fetchApi<{
        authenticated: boolean;
        user_id?: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/status'),
    token: () =>
      fetchApi<{
        access_token: string;
        refresh_token?: string;
        user_id?: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/token'),
    refresh: () =>
      fetchJsonNoRefresh<{
        authenticated: boolean;
        user_id?: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/refresh', { method: 'POST' }),
    login: (email: string, password: string) =>
      fetchApi<{
        success: boolean;
        user_id: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password })
      }),
    logout: () =>
      fetchApi<{
        authenticated: boolean;
        user_id?: string;
        expires_at?: number;
        session_expires_at?: number;
      }>('/api/auth/logout', { method: 'POST' })
  },
  analytics: {
    overview: () => fetchApi('/api/analytics/overview'),
    profiles: () => fetchApi('/api/analytics/profiles'),
    training: () => fetchApi('/api/analytics/training'),
    storage: () => fetchApi('/api/analytics/storage')
  },
  builds: {
    envs: () => fetchApi<EnvBuildSettingsListResponse>('/api/builds/envs'),
    shared: () => fetchApi<SharedBuildSettingsListResponse>('/api/builds/shared'),
    runEnv: (configId: string, envName: string) =>
      fetchApi<BuildRunAcceptedResponse>(`/api/builds/envs/${encodeURIComponent(configId)}/${encodeURIComponent(envName)}/run`, {
        method: 'POST'
      }),
    runShared: (packageName: string, variant: string) =>
      fetchApi<BuildRunAcceptedResponse>(
        `/api/builds/shared/${encodeURIComponent(packageName)}/${encodeURIComponent(variant)}/run`,
        {
          method: 'POST'
        }
      ),
    cancelJob: (jobId: string) =>
      fetchApi<BuildJobCancelResponse>(`/api/builds/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: 'POST'
      }),
    deleteEnvArtifact: (configId: string, envName: string, buildId: string) =>
      fetchApi<BuildArtifactDeleteResponse>(
        `/api/builds/envs/${encodeURIComponent(configId)}/${encodeURIComponent(envName)}/artifacts/${encodeURIComponent(buildId)}`,
        {
          method: 'DELETE'
        }
      ),
    deleteSharedArtifact: (packageName: string, variant: string, buildId: string) =>
      fetchApi<BuildArtifactDeleteResponse>(
        `/api/builds/shared/${encodeURIComponent(packageName)}/${encodeURIComponent(variant)}/artifacts/${encodeURIComponent(buildId)}`,
        {
          method: 'DELETE'
        }
      ),
    createEnvErrorReport: (configId: string, envName: string, buildId: string) =>
      fetchApi<BuildErrorReportResponse>(
        `/api/builds/envs/${encodeURIComponent(configId)}/${encodeURIComponent(envName)}/artifacts/${encodeURIComponent(buildId)}/error-report`,
        {
          method: 'POST'
        }
      ),
    createSharedErrorReport: (packageName: string, variant: string, buildId: string) =>
      fetchApi<BuildErrorReportResponse>(
        `/api/builds/shared/${encodeURIComponent(packageName)}/${encodeURIComponent(variant)}/artifacts/${encodeURIComponent(buildId)}/error-report`,
        {
          method: 'POST'
        }
      )
  },
  system: {
    health: () => fetchApi('/api/system/health'),
    resources: () => fetchApi('/api/system/resources'),
    logs: () => fetchApi('/api/system/logs'),
    info: () => fetchApi('/api/system/info'),
    gpu: () => fetchApi('/api/system/gpu'),
    bundledTorchStatus: () => fetchApi<BundledTorchBuildSnapshot>('/api/system/bundled-torch/status'),
    buildBundledTorch: (payload: {
      pytorch_version?: string | null;
      torchvision_version?: string | null;
      force?: boolean;
    }) =>
      fetchApi<BundledTorchBuildSnapshot>('/api/system/bundled-torch/build', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    cleanBundledTorch: () =>
      fetchApi<BundledTorchBuildSnapshot>('/api/system/bundled-torch/clean', {
        method: 'POST'
      }),
    runtimeEnvStatus: () => fetchApi<RuntimeEnvSnapshot>('/api/system/runtime-envs/status'),
    buildRuntimeEnv: (payload: { env_name: string; force?: boolean }) =>
      fetchApi<RuntimeEnvSnapshot>('/api/system/runtime-envs/build', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    deleteRuntimeEnv: (payload: { env_name: string }) =>
      fetchApi<RuntimeEnvSnapshot>('/api/system/runtime-envs/delete', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    settings: () => fetchApi<SystemSettings>('/api/system/settings'),
    updateSettings: (payload: {
      bundled_torch?: { pytorch_version: string; torchvision_version: string };
      features_repo?: { repo_url: string; repo_ref: string; repo_commit?: string | null };
    }) =>
      fetchApi<SystemSettings>('/api/system/settings', {
        method: 'PUT',
        body: JSON.stringify(payload)
      }),
    featuresRepoSuggestions: (params: {
      repo_url: string;
      repo_ref?: string | null;
      signal?: AbortSignal;
    }) => {
      const query = new URLSearchParams({ repo_url: params.repo_url });
      if (params.repo_ref) query.set('repo_ref', params.repo_ref);
      return fetchApi<FeaturesRepoSuggestions>(
        `/api/system/settings/features-repo/suggestions?${query.toString()}`,
        { signal: params.signal }
      );
    }
  },
  config: {
    get: () => fetchApi('/api/config')
  },
  user: {
    config: () => fetchApi('/api/user/config'),
    devices: () => fetchApi('/api/user/devices'),
    settings: () => fetchApi<UserSettings>('/api/user/settings'),
    updateSettings: (payload: {
      username?: string | null;
      first_name?: string | null;
      last_name?: string | null;
      huggingface_token?: string | null;
      clear_huggingface_token?: boolean;
    }) =>
      fetchApi<UserSettings>('/api/user/settings', {
        method: 'PUT',
        body: JSON.stringify(payload)
      })
  },
  hardware: {
    status: () => fetchApi('/api/hardware'),
    cameras: () => fetchApi('/api/hardware/cameras'),
    serialPorts: () => fetchApi('/api/hardware/serial-ports')
  },
  webuiBlueprints: {
    list: () => fetchApi('/api/webui/blueprints'),
    create: (payload: { name: string; blueprint: Record<string, unknown> }) =>
      fetchApi('/api/webui/blueprints', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    get: (blueprintId: string) => fetchApi(`/api/webui/blueprints/${encodeURIComponent(blueprintId)}`),
    update: (
      blueprintId: string,
      payload: { name?: string; blueprint?: Record<string, unknown> }
    ) =>
      fetchApi(`/api/webui/blueprints/${encodeURIComponent(blueprintId)}`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      }),
    delete: (blueprintId: string) =>
      fetchApi(`/api/webui/blueprints/${encodeURIComponent(blueprintId)}`, {
        method: 'DELETE'
      }),
    resolveSession: (payload: { session_kind: 'recording' | 'teleop' | 'inference'; session_id: string }) =>
      fetchApi('/api/webui/blueprints/session/resolve', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    bindSession: (payload: {
      session_kind: 'recording' | 'teleop' | 'inference';
      session_id: string;
      blueprint_id: string;
    }) =>
      fetchApi('/api/webui/blueprints/session/binding', {
        method: 'PUT',
        body: JSON.stringify(payload)
      })
  },
  profiles: {
    list: () => fetchApi('/api/profiles'),
    active: () => fetchApi('/api/profiles/active'),
    setActive: (payload: { profile_name: string }) =>
      fetchApi('/api/profiles/active', { method: 'PUT', body: JSON.stringify(payload) }),
    activeStatus: () => fetchApi('/api/profiles/active/status'),
    vlaborStatus: () => fetchApi('/api/profiles/vlabor/status'),
    restartVlabor: () => fetchApi('/api/profiles/vlabor/restart', { method: 'POST' })
  },
  realtime: {
    tabSessionState: (tabSessionId: string) =>
      fetchApi<TabSessionStateResponse>(
        `/api/realtime/tab-sessions/${encodeURIComponent(tabSessionId)}/state`
      ),
    putTabSessionState: (tabSessionId: string, payload: TabSessionStateRequest) =>
      fetchApi<TabSessionStatePutResponse>(
        `/api/realtime/tab-sessions/${encodeURIComponent(tabSessionId)}/state`,
        {
          method: 'PUT',
          body: JSON.stringify(payload)
        }
      ),
    deleteTabSession: (tabSessionId: string) =>
      fetchText(`/api/realtime/tab-sessions/${encodeURIComponent(tabSessionId)}`, {
        method: 'DELETE'
      }).then(() => undefined)
  },
  teleop: {
    createSession: (payload: {
      profile?: string;
      domain_id?: number;
      dev_mode?: boolean;
    } = {}) =>
      fetchApi('/api/teleop/session/create', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    startSession: (payload: { session_id: string }) =>
      fetchApi('/api/teleop/session/start', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    stopSession: (payload: { session_id?: string } = {}) =>
      fetchApi('/api/teleop/session/stop', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    sessionStatus: () => fetchApi('/api/teleop/session/status')
  },
  recording: {
    list: (query: RecordingListQuery = {}) =>
      fetchApi(
        `/api/recording/recordings${buildQueryString({
          owner_user_id: query.ownerUserId,
          profile_name: query.profileName,
          upload_status: query.uploadStatus,
          search: query.search,
          created_from: query.createdFrom,
          created_to: query.createdTo,
          size_min: query.sizeMin,
          size_max: query.sizeMax,
          episode_count_min: query.episodeCountMin,
          episode_count_max: query.episodeCountMax,
          sort_by: query.sortBy,
          sort_order: query.sortOrder,
          limit: query.limit,
          offset: query.offset
        })}`
      ),
    bulkArchive: (ids: string[]) =>
      fetchApi<BulkActionResponse>('/api/recording/recordings/bulk/archive', {
        method: 'POST',
        body: JSON.stringify({ ids })
      }),
    bulkReupload: (ids: string[]) =>
      fetchApi<BulkActionResponse>('/api/recording/recordings/bulk/reupload', {
        method: 'POST',
        body: JSON.stringify({ ids })
      }),
    createSession: (payload: {
      dataset_name: string;
      task: string;
      profile?: string;
      num_episodes: number;
      episode_time_s: number;
      reset_time_s: number;
    }) =>
      fetchApi<StartupOperationAcceptedResponse>('/api/recording/session/create', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    startSession: (payload: { dataset_id: string }) =>
      fetchApi('/api/recording/session/start', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    stopSession: (payload: {
      dataset_id?: string | null;
      save_current?: boolean;
    }) =>
      fetchApi('/api/recording/session/stop', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    pauseSession: () =>
      fetchApi('/api/recording/session/pause', {
        method: 'POST'
      }),
    resumeSession: () =>
      fetchApi('/api/recording/session/resume', {
        method: 'POST'
      }),
    updateSession: (payload: {
      dataset_id?: string;
      task?: string;
      episode_time_s?: number;
      reset_time_s?: number;
      num_episodes?: number;
    }) =>
      fetchApi('/api/recording/session/update', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    retakePreviousEpisode: () =>
      fetchApi('/api/recording/episode/retake-previous', {
        method: 'POST'
      }),
    cancelEpisode: () =>
      fetchApi('/api/recording/episode/cancel', {
        method: 'POST'
      }),
    nextEpisode: () =>
      fetchApi('/api/recording/episode/next', {
        method: 'POST'
      }),
    cancelSession: (datasetId?: string) =>
      fetchApi(`/api/recording/session/cancel${datasetId ? `?dataset_id=${datasetId}` : ''}`, {
        method: 'POST'
      }),
    sessionStatus: (sessionId: string) =>
      fetchApi(`/api/recording/sessions/${sessionId}/status`),
    sessionUploadStatus: (sessionId: string) =>
      fetchApi(`/api/recording/sessions/${sessionId}/upload-status`)
  },
  storage: {
    datasets: (query: StorageDatasetListQuery = {}) =>
      fetchApi<StorageDatasetListResponse>(
        `/api/storage/datasets${buildQueryString({
          include_archived: query.includeArchived,
          profile_name: query.profileName,
          owner_user_id: query.ownerUserId,
          status: query.status,
          dataset_type: query.datasetType,
          sync_status: query.syncStatus,
          search: query.search,
          created_from: query.createdFrom,
          created_to: query.createdTo,
          size_min: query.sizeMin,
          size_max: query.sizeMax,
          episode_count_min: query.episodeCountMin,
          episode_count_max: query.episodeCountMax,
          limit: query.limit,
          offset: query.offset,
          sort_by: query.sortBy,
          sort_order: query.sortOrder
        })}`
      ),
    models: (query: StorageModelListQuery = {}) =>
      fetchApi(
        `/api/storage/models${buildQueryString({
          include_archived: query.includeArchived,
          profile_name: query.profileName,
          owner_user_id: query.ownerUserId,
          status: query.status,
          policy_type: query.policyType,
          dataset_id: query.datasetId,
          sync_status: query.syncStatus,
          search: query.search,
          created_from: query.createdFrom,
          created_to: query.createdTo,
          size_min: query.sizeMin,
          size_max: query.sizeMax,
          limit: query.limit,
          offset: query.offset,
          sort_by: query.sortBy,
          sort_order: query.sortOrder
        })}`
      ),
    dataset: (datasetId: string) => fetchApi<StorageDatasetInfo>(`/api/storage/datasets/${datasetId}`),
    renameDataset: (datasetId: string, payload: StorageRenameRequest) =>
      fetchApi<StorageDatasetInfo>(`/api/storage/datasets/${datasetId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload)
      }),
    datasetViewer: (datasetId: string) =>
      fetchApi<DatasetViewerResponse>(`/api/storage/dataset-viewer/datasets/${datasetId}`),
    datasetViewerEpisodes: (datasetId: string) =>
      fetchApi<DatasetViewerEpisodeListResponse>(
        `/api/storage/dataset-viewer/datasets/${datasetId}/episodes`
      ),
    datasetViewerSignalFields: (datasetId: string) =>
      fetchApi<DatasetViewerSignalFieldsResponse>(
        `/api/storage/dataset-viewer/datasets/${datasetId}/signals`
      ),
    datasetViewerSignalSeries: (datasetId: string, episodeIndex: number, field: string) =>
      fetchApi<DatasetViewerSignalSeriesResponse>(
        `/api/storage/dataset-viewer/datasets/${datasetId}/episodes/${episodeIndex}/signals?field=${encodeURIComponent(field)}`
      ),
    datasetViewerEpisodeVideoWindow: (datasetId: string, episodeIndex: number) =>
      fetchApi<DatasetViewerEpisodeVideoWindowResponse>(
        `/api/storage/dataset-viewer/datasets/${datasetId}/episodes/${episodeIndex}/videos/window`
      ),
    datasetViewerVideoUrl: (datasetId: string, videoKey: string, episodeIndex: number) =>
      `${getBackendUrl()}/api/storage/dataset-viewer/datasets/${encodeURIComponent(datasetId)}/episodes/${episodeIndex}/videos/${encodeURIComponent(videoKey)}`,
    syncDataset: (datasetId: string) =>
      fetchApi<DatasetSyncJobAcceptedResponse>('/api/storage/dataset-sync/jobs', {
        method: 'POST',
        body: JSON.stringify({ dataset_id: datasetId })
      }),
    datasetSyncJobs: (includeTerminal = false) =>
      fetchApi<DatasetSyncJobListResponse>(
        `/api/storage/dataset-sync/jobs${includeTerminal ? '?include_terminal=true' : ''}`
      ),
    datasetSyncJob: (jobId: string) =>
      fetchApi<DatasetSyncJobStatus>(`/api/storage/dataset-sync/jobs/${encodeURIComponent(jobId)}`),
    cancelDatasetSyncJob: (jobId: string) =>
      fetchApi<DatasetSyncJobCancelResponse>(
        `/api/storage/dataset-sync/jobs/${encodeURIComponent(jobId)}/cancel`,
        { method: 'POST' }
      ),
    startDatasetMergeJob: (payload: { dataset_name: string; source_dataset_ids: string[] }) =>
      fetchApi<DatasetMergeJobAcceptedResponse>('/api/storage/dataset-merge/jobs', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    datasetMergeJob: (jobId: string) =>
      fetchApi<DatasetMergeJobStatus>(`/api/storage/dataset-merge/jobs/${encodeURIComponent(jobId)}`),
    model: (modelId: string) => fetchApi<StorageModelInfo>(`/api/storage/models/${modelId}`),
    renameModel: (modelId: string, payload: StorageRenameRequest) =>
      fetchApi<StorageModelInfo>(`/api/storage/models/${modelId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload)
      }),
    usage: () => fetchApi<StorageUsageResponse>('/api/storage/usage'),
    archiveDataset: (datasetId: string) =>
      fetchApi(`/api/storage/datasets/${datasetId}`, { method: 'DELETE' }),
    bulkArchiveDatasets: (ids: string[]) =>
      fetchApi<BulkActionResponse>('/api/storage/bulk/datasets/archive', {
        method: 'POST',
        body: JSON.stringify({ ids })
      }),
    restoreDataset: (datasetId: string) =>
      fetchApi(`/api/storage/datasets/${datasetId}/restore`, { method: 'POST' }),
    reuploadDataset: (datasetId: string) =>
      fetchApi(`/api/storage/datasets/${datasetId}/reupload`, { method: 'POST' }),
    bulkReuploadDatasets: (ids: string[]) =>
      fetchApi<BulkActionResponse>('/api/storage/bulk/datasets/reupload', {
        method: 'POST',
        body: JSON.stringify({ ids })
      }),
    syncModel: (modelId: string) =>
      fetchApi<ModelSyncJobAcceptedResponse>(`/api/storage/models/${modelId}/sync`, { method: 'POST' }),
    bulkSyncModels: (ids: string[]) =>
      fetchApi<BulkActionResponse>('/api/storage/bulk/models/sync', {
        method: 'POST',
        body: JSON.stringify({ ids })
      }),
    modelSyncJobs: (includeTerminal = false) =>
      fetchApi<ModelSyncJobListResponse>(
        `/api/storage/model-sync/jobs${includeTerminal ? '?include_terminal=true' : ''}`
      ),
    modelSyncJob: (jobId: string) =>
      fetchApi<ModelSyncJobStatus>(`/api/storage/model-sync/jobs/${encodeURIComponent(jobId)}`),
    cancelModelSyncJob: (jobId: string) =>
      fetchApi<ModelSyncJobCancelResponse>(
        `/api/storage/model-sync/jobs/${encodeURIComponent(jobId)}/cancel`,
        { method: 'POST' }
      ),
    archiveModel: (modelId: string) =>
      fetchApi(`/api/storage/models/${modelId}`, { method: 'DELETE' }),
    bulkArchiveModels: (ids: string[]) =>
      fetchApi<BulkActionResponse>('/api/storage/bulk/models/archive', {
        method: 'POST',
        body: JSON.stringify({ ids })
      }),
    restoreModel: (modelId: string) =>
      fetchApi(`/api/storage/models/${modelId}/restore`, { method: 'POST' }),
    restoreArchive: (payload: { dataset_ids: string[]; model_ids: string[] }) =>
      fetchApi<ArchiveBulkResponse>('/api/storage/archive/restore', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    deleteArchive: (payload: { dataset_ids: string[]; model_ids: string[] }) =>
      fetchApi<ArchiveBulkResponse>('/api/storage/archive/delete', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    deleteArchivedDataset: (datasetId: string) =>
      fetchApi(`/api/storage/archive/datasets/${datasetId}`, { method: 'DELETE' }),
    deleteArchivedModel: (modelId: string) =>
      fetchApi(`/api/storage/archive/models/${modelId}`, { method: 'DELETE' })
  },
  experiments: {
    list: (params: {
      model_id?: string;
      profile_instance_id?: string;
      updated_from?: string;
      updated_to?: string;
      evaluation_count_min?: number;
      evaluation_count_max?: number;
      limit?: number;
      offset?: number;
    } = {}) => {
      const query = new URLSearchParams();
      if (params.model_id) query.set('model_id', params.model_id);
      if (params.profile_instance_id) query.set('profile_instance_id', params.profile_instance_id);
      if (params.updated_from) query.set('updated_from', params.updated_from);
      if (params.updated_to) query.set('updated_to', params.updated_to);
      if (typeof params.evaluation_count_min === 'number') query.set('evaluation_count_min', String(params.evaluation_count_min));
      if (typeof params.evaluation_count_max === 'number') query.set('evaluation_count_max', String(params.evaluation_count_max));
      if (typeof params.limit === 'number') query.set('limit', String(params.limit));
      if (typeof params.offset === 'number') query.set('offset', String(params.offset));
      const queryString = query.toString();
      return fetchApi<ExperimentListResponse>(`/api/experiments${queryString ? `?${queryString}` : ''}`);
    },
    get: (experimentId: string) => fetchApi<ExperimentDetail>(`/api/experiments/${experimentId}`),
    create: (payload: Record<string, unknown>) =>
      fetchApi<ExperimentDetail>('/api/experiments', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    update: (experimentId: string, payload: Record<string, unknown>) =>
      fetchApi<ExperimentDetail>(`/api/experiments/${experimentId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload)
      }),
    delete: (experimentId: string) =>
      fetchApi<{ deleted: boolean }>(`/api/experiments/${experimentId}`, { method: 'DELETE' }),
    evaluations: (experimentId: string) =>
      fetchApi<ExperimentEvaluationListResponse>(`/api/experiments/${experimentId}/evaluations`),
    replaceEvaluations: (experimentId: string, payload: ExperimentEvaluationReplaceRequest) =>
      fetchApi<{ updated: boolean; count: number }>(`/api/experiments/${experimentId}/evaluations`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      }),
    evaluationSummary: (experimentId: string) =>
      fetchApi<ExperimentEvaluationSummary>(`/api/experiments/${experimentId}/evaluation_summary`),
    analyses: (experimentId: string) =>
      fetchApi<ExperimentAnalysisListResponse>(`/api/experiments/${experimentId}/analyses`),
    replaceAnalyses: (experimentId: string, payload: Record<string, unknown>) =>
      fetchApi<{ updated: boolean; count: number }>(`/api/experiments/${experimentId}/analyses`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      }),
    mediaUrls: (keys: string[]) =>
      fetchApi<ExperimentMediaUrlResponse>('/api/experiments/media-urls', {
        method: 'POST',
        body: JSON.stringify({ keys })
      }),
    upload: (
      experimentId: string,
      formData: FormData,
      params: { scope: 'experiment' | 'evaluation' | 'analysis'; trial_index?: number; block_index?: number }
    ) => {
      const query = new URLSearchParams({ scope: params.scope });
      if (params.trial_index) query.set('trial_index', String(params.trial_index));
      if (params.block_index) query.set('block_index', String(params.block_index));
      return fetchForm<ExperimentUploadResponse>(
        `/api/experiments/${experimentId}/uploads?${query.toString()}`,
        formData
      );
    }
  },
  training: {
    providerCapabilities: () =>
      fetchApi<TrainingProviderCapabilityResponse>('/api/training/provider-capabilities'),
    lastConfig: () => fetchApi<LastTrainingConfigResponse>('/api/training/jobs/last-config'),
    jobs: (query: TrainingJobListQuery = {}) =>
      fetchApi(
        `/api/training/jobs${buildQueryString({
          days: query.days,
          owner_user_id: query.ownerUserId,
          status: query.status,
          policy_type: query.policyType,
          search: query.search,
          created_from: query.createdFrom,
          created_to: query.createdTo,
          sort_by: query.sortBy,
          sort_order: query.sortOrder,
          limit: query.limit,
          offset: query.offset
        })}`
      ),
    job: (jobId: string) => fetchApi(`/api/training/jobs/${jobId}`),
    startProvisionOperation: (data: Record<string, unknown>) =>
      fetchApi<TrainingProvisionOperationAcceptedResponse>('/api/training/provision-operations', {
        method: 'POST',
        body: JSON.stringify(data)
      }),
    provisionOperation: (operationId: string) =>
      fetchApi<TrainingProvisionOperationStatusResponse>(
        `/api/training/provision-operations/${encodeURIComponent(operationId)}`
      ),
    instanceStatus: (jobId: string) => fetchApi(`/api/training/jobs/${jobId}/instance-status`),
    stopJob: (jobId: string) => fetchApi(`/api/training/jobs/${jobId}/stop`, { method: 'POST' }),
    updateJob: (jobId: string, payload: { job_name?: string }) =>
      fetchApi(`/api/training/jobs/${jobId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload)
      }),
    deleteJob: (jobId: string) => fetchApi(`/api/training/jobs/${jobId}`, { method: 'DELETE' }),
    bulkArchiveJobs: (ids: string[]) =>
      fetchApi<BulkActionResponse>('/api/training/jobs/bulk/archive', {
        method: 'POST',
        body: JSON.stringify({ ids })
      }),
    logs: (jobId: string, logType: string, lines: number = 30) =>
      fetchApi(`/api/training/jobs/${jobId}/logs?log_type=${logType}&lines=${lines}`),
    downloadLogs: (jobId: string, logType: string) =>
      fetchText(`/api/training/jobs/${jobId}/logs/download?log_type=${logType}`),
    metrics: (jobId: string, limit: number = 2000) =>
      fetchApi(`/api/training/jobs/${jobId}/metrics?limit=${limit}`),
    progress: (jobId: string) => fetchApi(`/api/training/jobs/${jobId}/progress`),
    remoteCheckpoints: (jobId: string) =>
      fetchApi<RemoteCheckpointListResponse>(`/api/training/jobs/${jobId}/checkpoints/remote`),
    startCheckpointUploadOperation: (jobId: string, checkpointName: string) =>
      fetchApi<TrainingJobOperationAcceptedResponse>(
        `/api/training/jobs/${jobId}/operations/checkpoint-upload`,
        {
          method: 'POST',
          body: JSON.stringify({ checkpoint_name: checkpointName })
        }
      ),
    startRescueCpuOperation: (jobId: string) =>
      fetchApi<TrainingJobOperationAcceptedResponse>(
        `/api/training/jobs/${jobId}/operations/rescue-cpu`,
        {
          method: 'POST'
        }
      ),
    gpuAvailability: (provider: 'verda' | 'vast') =>
      fetchApi(`/api/training/gpu-availability?provider=${encodeURIComponent(provider)}`),
    instanceCandidates: (params: {
      provider: 'verda' | 'vast';
      gpu_model?: string;
      gpu_count?: number;
      mode?: 'spot' | 'ondemand';
      storage_size?: number;
      max_price?: number | null;
    }) => {
      const query = new URLSearchParams({ provider: params.provider });
      if (params.gpu_model) query.set('gpu_model', params.gpu_model);
      if (typeof params.gpu_count === 'number') query.set('gpu_count', String(params.gpu_count));
      if (params.mode) query.set('mode', params.mode);
      if (typeof params.storage_size === 'number') query.set('storage_size', String(params.storage_size));
      if (typeof params.max_price === 'number' && !Number.isNaN(params.max_price)) {
        query.set('max_price', String(params.max_price));
      }
      return fetchApi<TrainingInstanceCandidatesResponse>(`/api/training/instance-candidates?${query.toString()}`);
    },
    verdaStorage: () => fetchApi('/api/training/verda/storage'),
    verdaStorageDelete: (payload: { volume_ids: string[] }) =>
      fetchApi('/api/training/verda/storage/delete', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    verdaStorageRestore: (payload: { volume_ids: string[] }) =>
      fetchApi('/api/training/verda/storage/restore', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    verdaStoragePurge: (payload: { volume_ids: string[] }) =>
      fetchApi('/api/training/verda/storage/purge', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    vastStorage: () => fetchApi('/api/training/vast/storage'),
    vastStorageDelete: (payload: { volume_ids: string[] }) =>
      fetchApi('/api/training/vast/storage/delete', {
        method: 'POST',
        body: JSON.stringify(payload)
      })
  },
  operate: {
    status: () => fetchApi('/api/operate/status')
  },
  startup: {
    operation: (operationId: string) =>
      fetchApi<StartupOperationStatusResponse>(`/api/startup/operations/${encodeURIComponent(operationId)}`)
  },
  inference: {
    models: () => fetchApi('/api/inference/models'),
    deviceCompatibility: () => fetchApi('/api/inference/device-compatibility'),
    runnerStatus: () => fetchApi('/api/inference/runner/status'),
    runnerStart: (payload: InferenceRunnerStartPayload) =>
      fetchApi<StartupOperationAcceptedResponse>('/api/inference/runner/start', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    runnerStop: (payload: Record<string, unknown>) =>
      fetchApi('/api/inference/runner/stop', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    pauseRunner: () =>
      fetchApi<InferenceRunnerControlResponse>('/api/inference/runner/pause', {
        method: 'POST'
      }),
    resumeRunner: () =>
      fetchApi<InferenceRunnerControlResponse>('/api/inference/runner/resume', {
        method: 'POST'
      }),
    applySettings: (payload: InferenceRunnerSettingsApplyPayload) =>
      fetchApi<InferenceRunnerSettingsApplyResponse>('/api/inference/runner/settings/apply', {
        method: 'POST',
        body: JSON.stringify(payload)
      }),
    decideRecording: (payload: InferenceRecordingDecisionPayload) =>
      fetchApi<InferenceRecordingDecisionResponse>('/api/inference/runner/recording/decision', {
        method: 'POST',
        body: JSON.stringify(payload)
      })
  }
};

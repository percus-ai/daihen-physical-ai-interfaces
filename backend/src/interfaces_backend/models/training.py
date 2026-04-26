"""Training job models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from interfaces_backend.services.profile_snapshot import extract_profile_name


class JobStatus(str, Enum):
    """Training job status."""

    STARTING = "starting"
    DEPLOYING = "deploying"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    TERMINATED = "terminated"


class CleanupStatus(str, Enum):
    """Cleanup status for failed/terminated jobs."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class TrainingMode(str, Enum):
    """Training mode."""

    TRAIN = "train"
    RESUME_HUB = "resume_hub"
    RESUME_LOCAL = "resume_local"


class JobInfo(BaseModel):
    """Training job information."""

    job_id: str
    job_name: str
    owner_user_id: Optional[str] = None
    owner_email: Optional[str] = None
    owner_name: Optional[str] = None
    instance_id: str
    ip: Optional[str] = None
    status: JobStatus
    dataset_id: Optional[str] = None
    dataset_name: Optional[str] = None
    profile_instance_id: Optional[str] = None
    profile_name: Optional[str] = None
    profile_snapshot: Optional[dict] = None
    policy_type: Optional[str] = None
    failure_reason: Optional[str] = None
    termination_reason: Optional[str] = None
    cleanup_status: Optional[CleanupStatus] = None
    mode: TrainingMode

    # SSH connection info
    ssh_user: str = "root"
    ssh_private_key: str = "~/.ssh/id_rsa"
    ssh_port: Optional[int] = Field(None, ge=1, le=65535, description="SSH port")
    remote_base_dir: str = "/root"

    # Checkpoint
    checkpoint_repo_id: Optional[str] = None

    # Timestamps
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None

    # GPU info
    gpu_model: Optional[str] = None
    gpus_per_instance: Optional[int] = None

    # Completion info
    exit_code: Optional[int] = None
    completed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(use_enum_values=True)

    @model_validator(mode="before")
    @classmethod
    def _derive_profile_name_from_snapshot(cls, value):
        if not isinstance(value, dict):
            return value
        if value.get("profile_name"):
            return value
        profile_name = extract_profile_name(value.get("profile_snapshot"))
        if not profile_name:
            return value
        next_value = dict(value)
        next_value["profile_name"] = profile_name
        return next_value

    @field_validator(
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "deleted_at",
        mode="before",
    )
    @classmethod
    def _coerce_naive_datetime_to_utc(cls, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return value
            if normalized.endswith("Z"):
                normalized = f"{normalized[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return value
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        return value


class JobListResponse(BaseModel):
    """Response for job list endpoint."""

    jobs: list[JobInfo]
    total: int
    owner_options: list["TrainingOwnerFilterOption"] = Field(default_factory=list)
    status_options: list["TrainingValueFilterOption"] = Field(default_factory=list)
    policy_options: list["TrainingValueFilterOption"] = Field(default_factory=list)


class TrainingOwnerFilterOption(BaseModel):
    user_id: str
    label: str
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    total_count: int = 0
    available_count: int = 0


class TrainingValueFilterOption(BaseModel):
    value: str
    label: str
    total_count: int = 0
    available_count: int = 0


JobListSortBy = Literal["created_at", "updated_at", "job_name", "owner_name", "policy_type", "status"]
SortOrder = Literal["asc", "desc"]


class JobDetailResponse(BaseModel):
    """Response for job detail endpoint."""

    job: JobInfo
    provision_operation: Optional["TrainingProvisionOperationStatusResponse"] = None
    remote_status: Optional[str] = None
    progress: Optional[dict] = None
    latest_train_metrics: Optional[dict] = None
    latest_val_metrics: Optional[dict] = None
    summary: Optional[dict] = None
    early_stopping: Optional[dict] = None
    training_config: Optional[dict] = None


class LastTrainingConfigResponse(BaseModel):
    """Latest saved training config for the current user."""

    job_id: Optional[str] = None
    job_name: Optional[str] = None
    created_at: Optional[datetime] = None
    training_config: Optional[dict] = None


class JobLogsResponse(BaseModel):
    """Response for job logs endpoint."""

    job_id: str
    logs: str
    lines: int
    source: Optional[str] = None


TrainingJobLogType = Literal["training", "setup"]


class TrainingJobLogStreamRequest(BaseModel):
    """Request to start publishing a job log track."""

    log_type: TrainingJobLogType = "training"


class TrainingJobLogStreamResponse(BaseModel):
    """Accepted realtime log stream descriptor."""

    job_id: str
    log_type: TrainingJobLogType
    key: str
    state: str


class TrainingJobLogAppendRealtimeDetail(BaseModel):
    """Append payload for training.job.logs."""

    job_id: str
    log_type: TrainingJobLogType
    lines: list[str] = Field(default_factory=list)


class TrainingJobLogControlRealtimeDetail(BaseModel):
    """Control payload for training.job.logs."""

    type: Literal["connected", "stream_ended", "job_missing", "ip_missing"]
    job_id: str
    log_type: TrainingJobLogType
    status: Optional[str] = None
    message: str = ""


class JobProgressResponse(BaseModel):
    """Response for job progress endpoint."""

    job_id: str
    step: str = "N/A"
    loss: str = "N/A"


class JobActionResponse(BaseModel):
    """Response for job action (stop, delete)."""

    job_id: str
    success: bool
    message: str


class JobUpdateRequest(BaseModel):
    """Request to update editable job fields."""

    job_name: Optional[str] = None


BulkActionResultStatus = Literal["succeeded", "failed", "skipped"]


class BulkActionRequest(BaseModel):
    """Request for bulk job operations."""

    ids: list[str] = Field(default_factory=list)


class BulkActionResult(BaseModel):
    """Per-item result for a bulk operation."""

    id: str
    status: BulkActionResultStatus
    message: str = ""
    job_id: Optional[str] = None


class BulkActionResponse(BaseModel):
    """Summary response for a bulk operation."""

    requested: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[BulkActionResult] = Field(default_factory=list)


class JobStatusUpdate(BaseModel):
    """Status update for a job."""

    job_id: str
    old_status: str
    new_status: str
    instance_status: str
    reason: str


class JobStatusCheckResponse(BaseModel):
    """Response for bulk status check."""

    updates: list[JobStatusUpdate]
    checked_count: int


class JobMetricPoint(BaseModel):
    """Single metric point for a job."""

    step: Optional[int] = None
    loss: Optional[float] = None
    ts: Optional[str] = None


class JobMetricsResponse(BaseModel):
    """Metrics series for a job."""

    job_id: str
    train: list[JobMetricPoint] = Field(default_factory=list)
    val: list[JobMetricPoint] = Field(default_factory=list)


# --- Job Creation Models ---


class DatasetConfig(BaseModel):
    """Dataset configuration for training."""

    class DatasetSplitConfig(BaseModel):
        """Dataset split configuration."""

        train_ratio: float = Field(0.7, gt=0.0, le=1.0, description="Train split ratio")
        seed: int = Field(42, description="Split random seed")

    id: str = Field(..., description="Dataset ID")
    source: str = Field("r2", description="Dataset source: r2, hub, local")
    hf_repo_id: Optional[str] = Field(None, description="HuggingFace repo ID (for hub source)")
    video_backend: Optional[str] = Field(None, description="Video decode backend: torchcodec, pyav, etc.")
    split: Optional[DatasetSplitConfig] = Field(None, description="Dataset split config")


class PolicyConfig(BaseModel):
    """Policy configuration for training."""

    type: str = Field("act", description="Policy type: act, pi0, groot, smolvla, etc.")
    initialization: Optional[Literal["pretrained", "scratch"]] = Field(
        None,
        description="Policy initialization mode: pretrained or scratch",
    )
    pretrained_path: Optional[str] = Field(None, description="Pretrained model path")
    base_model_path: Optional[str] = Field(None, description="Base foundation model path")
    compile_model: Optional[bool] = Field(None, description="Enable torch.compile")
    gradient_checkpointing: Optional[bool] = Field(None, description="Enable gradient checkpointing")
    dtype: Optional[str] = Field(None, description="Model dtype: float32, float16, bfloat16")
    use_amp: Optional[bool] = Field(None, description="Enable AMP (mixed precision)")

    @model_validator(mode="after")
    def validate_initialization(self) -> "PolicyConfig":
        if self.initialization == "scratch":
            if self.pretrained_path:
                raise ValueError("policy.pretrained_path must not be set when initialization=scratch")
            if self.base_model_path:
                raise ValueError("policy.base_model_path must not be set when initialization=scratch")
            return self
        if self.initialization == "pretrained" and not (self.pretrained_path or self.base_model_path):
            raise ValueError(
                "policy.pretrained_path or policy.base_model_path is required when initialization=pretrained"
            )
        return self


class TrainingParams(BaseModel):
    """Training parameters."""

    steps: Optional[int] = Field(None, description="Number of training steps")
    batch_size: Optional[int] = Field(None, description="Batch size")
    save_freq: Optional[int] = Field(None, ge=50, description="Checkpoint save frequency")
    log_freq: Optional[int] = Field(None, ge=1, description="Logging frequency (steps)")
    num_workers: Optional[int] = Field(None, ge=0, description="Dataloader workers")
    save_checkpoint: Optional[bool] = Field(None, description="Save checkpoints during training")
    drop_last: Optional[bool] = Field(None, description="Drop incomplete final train batch")
    persistent_workers: Optional[bool] = Field(None, description="Keep DataLoader workers alive across epochs")


class ValidationConfig(BaseModel):
    """Validation parameters."""

    enable: bool = Field(True, description="Enable validation during training")
    eval_freq: Optional[int] = Field(None, ge=1, description="Validation frequency (steps)")
    max_batches: Optional[int] = Field(None, ge=1, description="Max validation batches")
    batch_size: Optional[int] = Field(None, ge=1, description="Validation batch size")


class EarlyStoppingConfig(BaseModel):
    """Early stopping parameters."""

    enable: bool = Field(True, description="Enable early stopping")
    patience: int = Field(5, ge=1, description="Patience (number of worsening evals)")
    min_delta: float = Field(0.002, description="Minimum change to qualify as improvement")
    mode: str = Field("min", description="Mode: min or max")


class CloudConfig(BaseModel):
    """Cloud instance configuration."""

    provider: str = Field(
        "verda",
        description="Cloud provider: verda, vast",
        pattern="^(verda|vast)$",
    )
    gpu_model: Optional[str] = Field(None, description="Selected candidate GPU model")
    gpus_per_instance: Optional[int] = Field(None, ge=1, le=8, description="Selected candidate GPU count")
    storage_size: Optional[int] = Field(None, description="Storage size in GB")
    location: str = Field("auto", description="Location: auto, FIN-01, ICE-01, etc.")
    is_spot: Optional[bool] = Field(None, description="Selected candidate uses spot instance")
    selected_mode: Optional[str] = Field(
        None,
        description="Selected candidate mode: spot or ondemand",
        pattern="^(spot|ondemand)$",
    )
    selected_instance_type: Optional[str] = Field(
        None,
        description="Selected Verda instance type",
    )
    selected_offer_id: Optional[int] = Field(
        None,
        description="Selected Vast offer id",
    )
    selected_price_per_hour: Optional[float] = Field(
        None,
        ge=0,
        description="Selected candidate hourly price from the UI",
    )

    # Vast.ai specific (v1)
    interruptible: Optional[bool] = Field(None, description="Selected Vast interruptible instance")
    max_price: Optional[float] = Field(None, ge=0, description="Max price ($/hour) for Vast interruptible")
    ssh_port: Optional[int] = Field(None, ge=1, le=65535, description="SSH port (resolved after launch)")

    @model_validator(mode="after")
    def validate_selected_target(self) -> "CloudConfig":
        provider = str(self.provider or "").strip().lower()
        if provider == "verda":
            if not str(self.selected_instance_type or "").strip():
                raise ValueError("cloud.selected_instance_type is required for verda")
            if self.selected_mode not in {"spot", "ondemand"}:
                raise ValueError("cloud.selected_mode is required for verda")
        elif provider == "vast":
            if self.selected_offer_id is None:
                raise ValueError("cloud.selected_offer_id is required for vast")
            if self.selected_mode not in {"spot", "ondemand"}:
                raise ValueError("cloud.selected_mode is required for vast")
        return self


class JobCreateRequest(BaseModel):
    """Request to create a new training job."""
    job_name: Optional[str] = Field(None, description="Job display name")
    dataset: Optional[DatasetConfig] = Field(None, description="Dataset config")
    policy: Optional[PolicyConfig] = Field(None, description="Policy config")
    training: TrainingParams = Field(default_factory=TrainingParams)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    early_stopping: EarlyStoppingConfig = Field(default_factory=EarlyStoppingConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    checkpoint_repo_id: Optional[str] = Field(None, description="HF repo for checkpoint upload")
    wandb_enable: bool = Field(True, description="Enable Weights & Biases logging")
    background: bool = Field(True, description="Run in background mode")
    sync_dataset: bool = Field(False, description="Sync dataset to R2 before training")


class JobCreateResponse(BaseModel):
    """Response for job creation."""

    job_id: str
    instance_id: str
    status: str
    message: str
    ip: Optional[str] = None


TrainingProvisionOperationState = Literal["queued", "running", "completed", "failed", "cancelled"]
TrainingJobOperationKind = Literal["checkpoint_upload", "rescue_cpu"]
TrainingJobOperationState = Literal["queued", "running", "completed", "failed", "cancelled"]


class TrainingProvisionOperationAcceptedResponse(BaseModel):
    """Accepted response for training provision operation."""

    accepted: bool = True
    operation_id: str
    state: TrainingProvisionOperationState = "queued"
    message: str = "accepted"


class TrainingProvisionOperationStatusResponse(BaseModel):
    """Current status for a training provision operation."""

    operation_id: str
    state: TrainingProvisionOperationState
    step: str = "queued"
    message: Optional[str] = None
    failure_reason: Optional[str] = None
    provider: Literal["verda", "vast"]
    instance_id: Optional[str] = None
    job_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class TrainingJobOperationAcceptedResponse(BaseModel):
    """Accepted response for training job operation."""

    accepted: bool = True
    operation_id: str
    job_id: str
    kind: TrainingJobOperationKind
    state: TrainingJobOperationState = "queued"
    message: str = "accepted"
    reused: bool = False


class TrainingJobOperationStatusResponse(BaseModel):
    """Current status for a training job operation."""

    operation_id: str
    job_id: str
    kind: TrainingJobOperationKind
    state: TrainingJobOperationState
    phase: str = "queued"
    progress_percent: float = 0.0
    message: Optional[str] = None
    error: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class InstanceStatusResponse(BaseModel):
    """Response for instance status check."""

    job_id: str
    instance_id: str
    instance_status: Optional[str] = Field(None, description="Verda instance status")
    job_status: str = Field(..., description="Local job status")
    ip: Optional[str] = None
    remote_process_status: Optional[str] = Field(None, description="SSH process status")
    gpu_model: Optional[str] = None
    gpus_per_instance: Optional[int] = None
    created_at: Optional[str] = None
    message: str = ""


# --- Checkpoint Models (for continue training) ---


class CheckpointDatasetInfo(BaseModel):
    """Dataset information embedded in checkpoint for compatibility checking."""

    camera_names: list[str] = Field(default_factory=list, description="Camera names used in training")
    action_dim: int = Field(0, description="Action dimension")
    state_dim: int = Field(0, description="State dimension")


class CheckpointInfo(BaseModel):
    """Checkpoint information for listing."""

    job_name: str = Field(..., description="Training job name")
    policy_type: str = Field(..., description="Policy type (act, pi0, smolvla, etc.)")
    step: int = Field(..., description="Latest/selected step number")
    dataset_id: str = Field(..., description="Training dataset ID")
    dataset_info: CheckpointDatasetInfo = Field(
        default_factory=CheckpointDatasetInfo,
        description="Dataset compatibility info"
    )
    created_at: str = Field(..., description="Job creation timestamp")
    size_mb: float = Field(0.0, description="Total checkpoint size in MB")
    pretrained_path: Optional[str] = Field(None, description="Base pretrained model path")
    author: Optional[str] = Field(None, description="Author user id")


class CheckpointListResponse(BaseModel):
    """Response for checkpoint list endpoint."""

    checkpoints: list[CheckpointInfo]
    total: int


class CheckpointDetailResponse(BaseModel):
    """Response for checkpoint detail endpoint."""

    job_name: str
    policy_type: str
    dataset_id: str
    dataset_info: CheckpointDatasetInfo = Field(default_factory=CheckpointDatasetInfo)
    pretrained_path: Optional[str] = None
    available_steps: list[int] = Field(default_factory=list, description="All available step numbers")
    latest_step: int = Field(0, description="Latest step number")
    created_at: str = ""
    size_mb: float = 0.0
    author: Optional[str] = None


class CheckpointDownloadRequest(BaseModel):
    """Request to download a checkpoint."""

    step: Optional[int] = Field(None, description="Specific step to download (None for latest)")
    target_path: Optional[str] = Field(None, description="Custom target path (optional)")


class CheckpointDownloadResponse(BaseModel):
    """Response for checkpoint download."""

    success: bool
    job_name: str
    step: int
    target_path: str
    message: str


# --- Verda Storage Models ---


class VerdaStorageItem(BaseModel):
    """Verda storage volume summary."""

    id: str
    name: Optional[str] = None
    size_gb: int = 0
    status: str = "unknown"
    state: str = "active"  # active or deleted
    is_os_volume: bool = False
    volume_type: Optional[str] = None
    location: Optional[str] = None
    instance_id: Optional[str] = None
    created_at: Optional[str] = None
    deleted_at: Optional[str] = None


class VerdaStorageListResponse(BaseModel):
    """Response for Verda storage list."""

    items: list[VerdaStorageItem]
    total: int


class VerdaStorageActionRequest(BaseModel):
    """Request for Verda storage actions."""

    volume_ids: list[str]


class VerdaStorageActionFailure(BaseModel):
    """Failure detail for Verda storage actions."""

    id: str
    reason: str


class VerdaStorageActionResult(BaseModel):
    """Result for Verda storage actions."""

    success_ids: list[str] = Field(default_factory=list)
    failed: list[VerdaStorageActionFailure] = Field(default_factory=list)
    skipped: list[VerdaStorageActionFailure] = Field(default_factory=list)


# --- Vast Storage Models ---


class VastStorageItem(BaseModel):
    """Vast storage volume summary."""

    id: str
    label: str = ""
    size_gb: Optional[int] = None
    state: str = ""
    instance_id: Optional[str] = None


class VastStorageListResponse(BaseModel):
    """Response for Vast storage list."""

    items: list[VastStorageItem]
    total: int


class VastStorageActionRequest(BaseModel):
    """Request for Vast storage actions."""

    volume_ids: list[str]


class VastStorageActionResult(BaseModel):
    """Result for Vast storage actions."""

    success_ids: list[str] = Field(default_factory=list)
    failed: list[VerdaStorageActionFailure] = Field(default_factory=list)


class RescueCPUResponse(BaseModel):
    """Response for starting a CPU rescue instance for checkpoint extraction."""

    job_id: str
    old_instance_id: str
    volume_id: str
    instance_id: str
    instance_type: str
    ip: str
    ssh_user: str = "root"
    ssh_private_key: str
    ssh_port: Optional[int] = Field(None, ge=1, le=65535, description="SSH port")
    location: str
    message: str


class RemoteCheckpointListResponse(BaseModel):
    """Response for remote checkpoint directory listing."""

    job_id: str
    checkpoint_names: list[str] = Field(default_factory=list)
    checkpoint_root: str
    ssh_available: bool = True
    requires_rescue_cpu: bool = False
    message: str = ""


class RemoteCheckpointUploadRequest(BaseModel):
    """Request for uploading a selected remote checkpoint to R2."""

    checkpoint_name: str = Field(..., description="Checkpoint directory name (numeric)")


class RemoteCheckpointUploadResponse(BaseModel):
    """Response for uploading selected remote checkpoint to R2."""

    job_id: str
    checkpoint_name: str
    step: int
    r2_step_path: str
    model_id: str
    db_registered: bool
    message: str


class DatasetCompatibilityCheckRequest(BaseModel):
    """Request for dataset compatibility check."""

    checkpoint_job_name: str = Field(..., description="Source checkpoint job name")
    dataset_id: str = Field(..., description="Target dataset ID to check")


class DatasetCompatibilityCheckResponse(BaseModel):
    """Result of dataset compatibility check for continue training."""

    is_compatible: bool = Field(..., description="Whether datasets are compatible")
    errors: list[str] = Field(default_factory=list, description="Critical errors (blocking)")
    warnings: list[str] = Field(default_factory=list, description="Warnings (non-blocking)")
    checkpoint_info: CheckpointDatasetInfo = Field(default_factory=CheckpointDatasetInfo)
    dataset_info: CheckpointDatasetInfo = Field(default_factory=CheckpointDatasetInfo)


# --- Continue Training Models ---


class ContinueCheckpointConfig(BaseModel):
    """Checkpoint reference for continue training."""

    job_name: str = Field(..., description="Source checkpoint job name")
    step: Optional[int] = Field(None, description="Specific step (None for latest)")


class ContinueDatasetConfig(BaseModel):
    """Dataset config for continue training."""

    id: str = Field(..., description="Dataset ID")
    use_original: bool = Field(True, description="Use original training dataset")
    video_backend: Optional[str] = Field(None, description="Video decode backend: torchcodec, pyav, etc.")


class ContinueTrainingParams(BaseModel):
    """Training params for continue training."""

    additional_steps: int = Field(..., description="Additional steps to train")
    batch_size: Optional[int] = Field(None, description="Batch size")
    save_freq: Optional[int] = Field(None, description="Checkpoint save frequency")
    log_freq: Optional[int] = Field(None, ge=1, description="Logging frequency (steps)")
    num_workers: Optional[int] = Field(None, ge=0, description="Dataloader workers")
    save_checkpoint: Optional[bool] = Field(None, description="Save checkpoints during training")
    drop_last: Optional[bool] = Field(None, description="Drop incomplete final train batch")
    persistent_workers: Optional[bool] = Field(None, description="Keep DataLoader workers alive across epochs")


class JobCreateContinueRequest(BaseModel):
    """Request to create a continue training job."""

    type: str = Field("continue", description="Job type: must be 'continue'")
    checkpoint: ContinueCheckpointConfig = Field(..., description="Source checkpoint")
    dataset: ContinueDatasetConfig = Field(..., description="Dataset config")
    training: ContinueTrainingParams = Field(..., description="Training params")
    policy: Optional[PolicyConfig] = Field(None, description="Policy overrides")
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    early_stopping: EarlyStoppingConfig = Field(default_factory=EarlyStoppingConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    wandb_enable: bool = Field(True, description="Enable W&B logging")
    author: Optional[str] = Field(None, description="Author user id")


# =============================================================================
# GPU Availability
# =============================================================================


class GpuAvailabilityInfo(BaseModel):
    """GPU availability information for a specific configuration."""

    gpu_model: str = Field(..., description="GPU model name (e.g., 'H100', 'A100')")
    gpu_count: int = Field(..., description="Number of GPUs")
    instance_type: str = Field(..., description="Verda instance type")
    spot_available: bool = Field(..., description="Spot instance available")
    ondemand_available: bool = Field(..., description="On-demand instance available")
    spot_locations: list[str] = Field(default_factory=list, description="Locations with spot availability")
    ondemand_locations: list[str] = Field(default_factory=list, description="Locations with on-demand availability")
    spot_price_per_hour: Optional[float] = Field(None, description="Spot price per hour")


class GpuAvailabilityResponse(BaseModel):
    """Response for GPU availability check."""

    available: list[GpuAvailabilityInfo] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.now)


class TrainingInstanceCandidate(BaseModel):
    """Selectable cloud instance candidate."""

    provider: str = Field(..., pattern="^(verda|vast)$")
    candidate_id: str
    title: str
    instance_type: Optional[str] = None
    offer_id: Optional[int] = None
    gpu_model: str
    gpu_count: int
    mode: str = Field(..., pattern="^(spot|ondemand)$")
    route: str = ""
    location: Optional[str] = None
    price_per_hour: Optional[float] = None
    detail: str = ""
    storage_gb: Optional[int] = None
    gpu_memory_gb: Optional[float] = None
    cpu_cores: Optional[float] = None
    system_memory_gb: Optional[float] = None


class TrainingInstanceCandidatesResponse(BaseModel):
    """Response for selectable cloud instance candidates."""

    candidates: list[TrainingInstanceCandidate] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.now)


class TrainingProviderCapabilityResponse(BaseModel):
    """Provider capability flags for training UI."""

    verda_enabled: bool = Field(True, description="Whether Verda provider can be selected")
    vast_enabled: bool = Field(False, description="Whether Vast.ai provider can be selected")
    missing_vast_env: list[str] = Field(
        default_factory=list,
        description="Missing required env vars for Vast.ai",
    )

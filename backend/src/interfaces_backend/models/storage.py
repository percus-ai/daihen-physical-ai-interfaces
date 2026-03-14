"""Storage API request/response models (DB-backed)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# --- API Request/Response Models ---


class DatasetSourceInfo(BaseModel):
    """Source dataset snapshot captured for merged datasets."""

    dataset_id: str = Field(..., description="Source dataset ID")
    name: str = Field(..., description="Source dataset name at merge time")
    content_hash: Optional[str] = Field(None, description="Source dataset content hash at merge time")
    task_detail: Optional[str] = Field(None, description="Source dataset task detail at merge time")


class DatasetInfo(BaseModel):
    """Dataset information for API responses."""

    id: str = Field(..., description="Dataset ID")
    name: str = Field(..., description="Dataset name")
    owner_user_id: Optional[str] = Field(None, description="Owner user id")
    owner_email: Optional[str] = Field(None, description="Owner email")
    owner_name: Optional[str] = Field(None, description="Owner name")
    profile_name: Optional[str] = Field(None, description="VLAbor profile name")
    profile_snapshot: Optional[dict] = Field(None, description="Profile snapshot")
    source: str = Field("r2", description="Data source")
    status: str = Field("active", description="Data status")
    dataset_type: str = Field("recorded", description="Dataset type")
    source_datasets: List[DatasetSourceInfo] = Field(
        default_factory=list,
        description="Source datasets captured when this dataset was merged",
    )
    episode_count: int = Field(0, description="Number of episodes")
    size_bytes: int = Field(0, description="Size in bytes")
    is_local: bool = Field(False, description="Dataset is downloaded locally")
    created_at: Optional[str] = Field(None, description="Creation time")
    updated_at: Optional[str] = Field(None, description="Last update time")


class DatasetListResponse(BaseModel):
    """Response for dataset list endpoint."""

    datasets: List[DatasetInfo]
    total: int


StorageSortOrder = Literal["asc", "desc"]
DatasetListSortBy = Literal["created_at", "updated_at", "name", "size_bytes", "episode_count"]
ModelListSortBy = Literal["created_at", "updated_at", "name", "size_bytes", "policy_type"]


class DatasetListQuery(BaseModel):
    include_archived: bool = Field(False, description="Include archived datasets when status filter is omitted")
    profile_name: Optional[str] = Field(None, description="Filter by profile name")
    owner_user_id: Optional[str] = Field(None, description="Filter by owner user id")
    status: Optional[str] = Field(None, description="Filter by dataset status")
    dataset_type: Optional[str] = Field(None, description="Filter by dataset type")
    search: Optional[str] = Field(None, description="Search dataset id and name")
    limit: Optional[int] = Field(None, ge=1, le=500, description="Maximum number of results to return")
    offset: int = Field(0, ge=0, description="Number of matching rows to skip")
    sort_by: DatasetListSortBy = Field("created_at", description="Dataset list sort field")
    sort_order: StorageSortOrder = Field("desc", description="Sort direction")


class DatasetMergeRequest(BaseModel):
    """Request to merge multiple datasets into one."""

    dataset_name: str = Field(..., description="Merged dataset name")
    source_dataset_ids: List[str] = Field(..., description="Source dataset IDs (>=2)")


class DatasetMergeResponse(BaseModel):
    """Response for dataset merge."""

    success: bool
    dataset_id: str
    message: str
    size_bytes: int = 0
    episode_count: int = 0


DatasetMergeJobState = Literal["queued", "running", "completed", "failed"]


class DatasetMergeJobDetail(BaseModel):
    dataset_name: str = ""
    source_dataset_ids: List[str] = Field(default_factory=list)
    step: str = ""

    downloaded_dataset_ids: List[str] = Field(default_factory=list)

    current_dataset_id: Optional[str] = None
    current_file: Optional[str] = None

    files_done: int = 0
    total_files: int = 0
    total_size: int = 0
    transferred_bytes: int = 0


class DatasetMergeJobStatus(BaseModel):
    job_id: str
    state: DatasetMergeJobState
    progress_percent: float = 0.0
    message: Optional[str] = None
    error: Optional[str] = None
    detail: DatasetMergeJobDetail = Field(default_factory=DatasetMergeJobDetail)

    result_dataset_id: Optional[str] = None
    result_size_bytes: int = 0
    result_episode_count: int = 0

    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DatasetMergeJobAcceptedResponse(BaseModel):
    accepted: bool = True
    job_id: str
    state: DatasetMergeJobState = "queued"
    message: str = "accepted"


class ModelInfo(BaseModel):
    """Model information for API responses."""

    id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Model name")
    owner_user_id: Optional[str] = Field(None, description="Owner user id")
    owner_email: Optional[str] = Field(None, description="Owner email")
    owner_name: Optional[str] = Field(None, description="Owner name")
    dataset_id: Optional[str] = Field(None, description="Dataset ID")
    profile_name: Optional[str] = Field(None, description="VLAbor profile name")
    profile_snapshot: Optional[dict] = Field(None, description="Profile snapshot")
    policy_type: Optional[str] = Field(None, description="Policy type")
    training_steps: Optional[int] = Field(None, description="Training steps")
    batch_size: Optional[int] = Field(None, description="Batch size")
    size_bytes: int = Field(0, description="Size in bytes")
    is_local: bool = Field(False, description="Model is downloaded locally")
    source: str = Field("r2", description="Data source")
    status: str = Field("active", description="Data status")
    created_at: Optional[str] = Field(None, description="Creation time")
    updated_at: Optional[str] = Field(None, description="Last update time")


class ModelListResponse(BaseModel):
    """Response for model list endpoint."""

    models: List[ModelInfo]
    total: int


class ModelListQuery(BaseModel):
    include_archived: bool = Field(False, description="Include archived models when status filter is omitted")
    profile_name: Optional[str] = Field(None, description="Filter by profile name")
    owner_user_id: Optional[str] = Field(None, description="Filter by owner user id")
    status: Optional[str] = Field(None, description="Filter by model status")
    policy_type: Optional[str] = Field(None, description="Filter by policy type")
    dataset_id: Optional[str] = Field(None, description="Filter by source dataset id")
    search: Optional[str] = Field(None, description="Search model id and name")
    limit: Optional[int] = Field(None, ge=1, le=500, description="Maximum number of results to return")
    offset: int = Field(0, ge=0, description="Number of matching rows to skip")
    sort_by: ModelListSortBy = Field("created_at", description="Model list sort field")
    sort_order: StorageSortOrder = Field("desc", description="Sort direction")


class StorageRenameRequest(BaseModel):
    name: str = Field(..., description="Display name")


ModelSyncJobState = Literal["queued", "running", "completed", "failed", "cancelled"]


class ModelSyncJobDetail(BaseModel):
    files_done: int = 0
    total_files: int = 0
    transferred_bytes: int = 0
    total_bytes: int = 0
    current_file: Optional[str] = None


class ModelSyncJobStatus(BaseModel):
    job_id: str
    model_id: str
    state: ModelSyncJobState
    progress_percent: float = 0.0
    message: Optional[str] = None
    error: Optional[str] = None
    detail: ModelSyncJobDetail = Field(default_factory=ModelSyncJobDetail)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ModelSyncJobAcceptedResponse(BaseModel):
    job_id: str
    model_id: str
    state: ModelSyncJobState = "queued"
    message: str = "accepted"


class ModelSyncJobListResponse(BaseModel):
    jobs: List[ModelSyncJobStatus] = Field(default_factory=list)


class ModelSyncJobCancelResponse(BaseModel):
    job_id: str
    accepted: bool
    state: ModelSyncJobState
    message: str


DatasetSyncJobState = Literal["queued", "running", "completed", "failed", "cancelled"]


class DatasetSyncJobCreateRequest(BaseModel):
    dataset_id: str = Field(..., description="Dataset ID")


class DatasetSyncJobDetail(BaseModel):
    files_done: int = 0
    total_files: int = 0
    transferred_bytes: int = 0
    total_bytes: int = 0
    current_file: Optional[str] = None


class DatasetSyncJobStatus(BaseModel):
    job_id: str
    dataset_id: str
    state: DatasetSyncJobState
    progress_percent: float = 0.0
    message: Optional[str] = None
    error: Optional[str] = None
    detail: DatasetSyncJobDetail = Field(default_factory=DatasetSyncJobDetail)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DatasetSyncJobAcceptedResponse(BaseModel):
    accepted: bool = True
    job_id: str
    dataset_id: str
    state: DatasetSyncJobState = "queued"
    message: str = "accepted"


class DatasetSyncJobListResponse(BaseModel):
    jobs: List[DatasetSyncJobStatus] = Field(default_factory=list)


class DatasetSyncJobCancelResponse(BaseModel):
    job_id: str
    accepted: bool
    state: DatasetSyncJobState
    message: str


class ArchiveResponse(BaseModel):
    """Response for archive/restore operations."""

    id: str
    success: bool
    message: str
    status: str


class DatasetReuploadResponse(BaseModel):
    """Response for dataset re-upload operation."""

    id: str
    success: bool
    message: str


class DatasetViewerCameraInfo(BaseModel):
    """Camera stream info for dataset viewer."""

    key: str = Field(..., description="Feature key, e.g. observation.images.cam_top")
    label: str = Field(..., description="Camera label")
    width: Optional[int] = Field(None, description="Video width")
    height: Optional[int] = Field(None, description="Video height")
    fps: Optional[int] = Field(None, description="Video FPS")
    codec: Optional[str] = Field(None, description="Video codec")
    pix_fmt: Optional[str] = Field(None, description="Pixel format")


class DatasetViewerResponse(BaseModel):
    """Dataset viewer metadata."""

    dataset_id: str = Field(..., description="Dataset ID")
    is_local: bool = Field(..., description="Whether dataset exists locally")
    download_required: bool = Field(..., description="Whether local download is required before playback")
    total_episodes: int = Field(0, description="Total episode count")
    fps: int = Field(0, description="Dataset FPS")
    use_videos: bool = Field(False, description="Whether dataset stores videos")
    cameras: List[DatasetViewerCameraInfo] = Field(default_factory=list)
    dataset_meta: Optional[dict] = Field(None, description="Dataset metadata for viewer context")


class DatasetViewerEpisode(BaseModel):
    """Episode metadata for dataset viewer."""

    episode_index: int = Field(..., description="Episode index (0-based)")
    frame_count: int = Field(0, description="Frame count for this episode")
    duration_s: float = Field(0.0, description="Duration in seconds for this episode")
    effective_fps: float = Field(0.0, description="Effective FPS for this episode")


class DatasetViewerEpisodeListResponse(BaseModel):
    """Episode list for dataset viewer."""

    dataset_id: str = Field(..., description="Dataset ID")
    episodes: List[DatasetViewerEpisode] = Field(default_factory=list)
    total: int = Field(0, description="Number of episodes")


class DatasetViewerSignalField(BaseModel):
    """Vector field metadata available for dataset viewer charts."""

    key: str = Field(..., description="Feature key, e.g. action")
    label: str = Field(..., description="Display label")
    shape: List[int] = Field(default_factory=list, description="Feature shape")
    names: Optional[List[str]] = Field(None, description="Axis names")
    dtype: str = Field(..., description="Feature dtype")


class DatasetViewerSignalFieldsResponse(BaseModel):
    """Signal field list for dataset viewer."""

    dataset_id: str = Field(..., description="Dataset ID")
    fields: List[DatasetViewerSignalField] = Field(default_factory=list)


class DatasetViewerSignalSeriesResponse(BaseModel):
    """Episode signal series for chart rendering."""

    dataset_id: str = Field(..., description="Dataset ID")
    episode_index: int = Field(..., description="Episode index (0-based)")
    field: str = Field(..., description="Feature key")
    fps: int = Field(0, description="Dataset FPS")
    names: List[str] = Field(default_factory=list, description="Axis names")
    positions: List[List[float]] = Field(default_factory=list, description="Frame-wise vectors")
    timestamps: List[float] = Field(default_factory=list, description="Frame timestamps in seconds")


class DatasetViewerEpisodeVideoWindow(BaseModel):
    """Episode-local time window for a video chunk file."""

    key: str = Field(..., description="Video key, e.g. observation.images.cam_top")
    relative_path: str = Field(..., description="Relative path under dataset root")
    from_s: float = Field(0.0, description="Episode start time (seconds) in the underlying video file")
    to_s: float = Field(0.0, description="Episode end time (seconds) in the underlying video file")


class DatasetViewerEpisodeVideoWindowResponse(BaseModel):
    """Per-episode video windows for chunked LeRobot datasets."""

    dataset_id: str = Field(..., description="Dataset ID")
    episode_index: int = Field(..., description="Episode index (0-based)")
    videos: List[DatasetViewerEpisodeVideoWindow] = Field(default_factory=list)


class StorageUsageResponse(BaseModel):
    """Response for storage usage endpoint."""

    datasets_count: int = 0
    datasets_size_bytes: int = 0
    models_count: int = 0
    models_size_bytes: int = 0
    archive_count: int = 0
    archive_size_bytes: int = 0
    total_size_bytes: int = 0


class ArchiveListResponse(BaseModel):
    """Response for archived items list."""

    datasets: List[DatasetInfo] = Field(default_factory=list)
    models: List[ModelInfo] = Field(default_factory=list)
    total: int = 0


class ArchiveBulkRequest(BaseModel):
    """Request for bulk archive operations."""

    dataset_ids: List[str] = Field(default_factory=list)
    model_ids: List[str] = Field(default_factory=list)


class ArchiveBulkResponse(BaseModel):
    """Response for bulk archive operations."""

    success: bool
    restored: List[str] = Field(default_factory=list)
    deleted: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


BulkActionResultStatus = Literal["succeeded", "failed", "skipped"]


class BulkActionRequest(BaseModel):
    """Request for bulk item operations."""

    ids: List[str] = Field(default_factory=list)


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
    results: List[BulkActionResult] = Field(default_factory=list)


class HuggingFaceDatasetImportRequest(BaseModel):
    """Request to import a dataset from HuggingFace."""

    repo_id: str = Field(..., description="HuggingFace repo ID")
    dataset_id: Optional[str] = Field(None, description="Dataset ID to store (UUID)")
    dataset_name: Optional[str] = Field(None, description="Dataset display name")
    profile_name: Optional[str] = Field(None, description="VLAbor profile name")
    name: Optional[str] = Field(None, description="Dataset display name")
    force: bool = Field(False, description="Overwrite local data if exists")


class HuggingFaceModelImportRequest(BaseModel):
    """Request to import a model from HuggingFace."""

    repo_id: str = Field(..., description="HuggingFace repo ID")
    model_id: Optional[str] = Field(None, description="Model ID to store (UUID)")
    model_name: Optional[str] = Field(None, description="Model display name")
    dataset_id: Optional[str] = Field(None, description="Associated dataset ID")
    profile_name: Optional[str] = Field(None, description="VLAbor profile name")
    force: bool = Field(False, description="Overwrite local data if exists")


class HuggingFaceExportRequest(BaseModel):
    """Request to export a dataset or model to HuggingFace."""

    repo_id: str = Field(..., description="HuggingFace repo ID")
    private: bool = Field(False, description="Create private repository")
    commit_message: Optional[str] = Field(None, description="Commit message")


class HuggingFaceTransferResponse(BaseModel):
    """Response for HuggingFace import/export."""

    success: bool
    message: str
    item_id: str
    repo_url: Optional[str] = None

"""Storage API router for datasets/models (DB-backed)."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from huggingface_hub import HfApi, snapshot_download, upload_folder
from postgrest.exceptions import APIError
import pyarrow.parquet as pq

from interfaces_backend.models.storage import (
    ArchiveListResponse,
    ArchiveBulkRequest,
    ArchiveBulkResponse,
    ArchiveResponse,
    BulkActionRequest,
    BulkActionResponse,
    BulkActionResult,
    DatasetViewerCameraInfo,
    DatasetViewerEpisode,
    DatasetViewerEpisodeListResponse,
    DatasetViewerResponse,
    DatasetSyncJobAcceptedResponse,
    DatasetSyncJobCancelResponse,
    DatasetSyncJobCreateRequest,
    DatasetSyncJobListResponse,
    DatasetSyncJobStatus,
    DatasetViewerSignalField,
    DatasetViewerSignalFieldsResponse,
    DatasetViewerSignalSeriesResponse,
    DatasetViewerEpisodeVideoWindow,
    DatasetViewerEpisodeVideoWindowResponse,
    DatasetReuploadResponse,
    DatasetMergeRequest,
    DatasetMergeResponse,
    DatasetMergeJobAcceptedResponse,
    DatasetMergeJobStatus,
    DatasetInfo,
    DatasetDetailInfo,
    DatasetCameraInfo,
    DatasetListQuery,
    DatasetListResponse,
    DatasetListSortBy,
    DatasetSignalFieldInfo,
    HuggingFaceDatasetImportRequest,
    HuggingFaceExportRequest,
    HuggingFaceModelImportRequest,
    HuggingFaceTransferResponse,
    ModelInfo,
    ModelListQuery,
    ModelListResponse,
    ModelListSortBy,
    OwnerFilterOption,
    ValueFilterOption,
    ModelSyncJobAcceptedResponse,
    ModelSyncJobCancelResponse,
    ModelSyncJobListResponse,
    ModelSyncJobStatus,
    StorageSortOrder,
    StorageRenameRequest,
    StorageUsageResponse,
    DatasetSourceInfo,
)
from interfaces_backend.services.dataset_lifecycle import get_dataset_lifecycle
from interfaces_backend.services.dataset_merge_jobs import get_dataset_merge_jobs_service
from interfaces_backend.services.dataset_sync_jobs import get_dataset_sync_jobs_service
from interfaces_backend.services.model_sync_jobs import get_model_sync_jobs_service
from interfaces_backend.services.profile_snapshot import extract_profile_name
from interfaces_backend.services.session_manager import require_user_id
from interfaces_backend.services.settings_service import resolve_huggingface_token_for_user
from interfaces_backend.services.storage_bulk_actions import (
    archive_dataset_for_bulk,
    archive_model_for_bulk,
    reupload_dataset_for_bulk,
    set_dataset_status,
    sync_model_for_bulk,
)
from interfaces_backend.services.user_directory import resolve_user_directory_entries
from interfaces_backend.services.vlabor_profiles import resolve_profile_spec
from percus_ai.db import (
    get_supabase_async_client,
    get_supabase_session,
    reset_request_session,
    set_request_session,
    upsert_with_owner,
)
from percus_ai.storage.hash import compute_directory_hash, compute_directory_size
from percus_ai.storage.hub import download_model, get_local_model_info, upload_model
from percus_ai.storage.models import (
    DataSource,
    DataStatus,
    DatasetMetadata,
    DatasetType,
    SourceDatasetInfo as DatasetMetadataSourceInfo,
    SyncInfo,
)
from percus_ai.storage.naming import validate_dataset_name, generate_dataset_id
from percus_ai.storage.paths import get_datasets_dir, get_models_dir
from percus_ai.storage.r2_db_sync import R2DBSyncService
from lerobot.datasets.aggregate import aggregate_datasets
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/storage", tags=["storage"])
_executor = ThreadPoolExecutor(max_workers=1)


def _require_hf_token_for_current_user() -> str:
    user_id = require_user_id()
    token = resolve_huggingface_token_for_user(user_id)
    if not token:
        raise HTTPException(status_code=400, detail="HF_TOKEN is required")
    return token


def _dataset_is_local(dataset_id: str) -> bool:
    dataset_path = get_datasets_dir() / dataset_id
    return dataset_path.exists()


def _model_is_local(model_id: str) -> bool:
    model_path = get_models_dir() / model_id
    return model_path.exists()


def _delete_local_dataset(dataset_id: str) -> None:
    dataset_path = get_datasets_dir() / dataset_id
    if dataset_path.exists():
        shutil.rmtree(dataset_path)


def _delete_local_model(model_id: str) -> None:
    model_path = get_models_dir() / model_id
    if model_path.exists():
        shutil.rmtree(model_path)


def _camera_label_from_key(video_key: str) -> str:
    prefix = "observation.images."
    if video_key.startswith(prefix):
        return video_key[len(prefix) :]
    return video_key.split(".")[-1]


def _validate_dataset_id_path(dataset_id: str) -> None:
    """Guard against path traversal when using dataset_id in filesystem paths."""
    if not dataset_id or not isinstance(dataset_id, str):
        raise HTTPException(status_code=400, detail="dataset_id is required")
    if dataset_id.strip() != dataset_id:
        raise HTTPException(status_code=400, detail="Invalid dataset id")
    if dataset_id.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid dataset id")
    if "\\" in dataset_id:
        raise HTTPException(status_code=400, detail="Invalid dataset id")
    parts = PurePosixPath(dataset_id).parts
    if not parts:
        raise HTTPException(status_code=400, detail="Invalid dataset id")
    if any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail="Invalid dataset id")


async def _resolve_dataset_row_and_path(dataset_id: str) -> tuple[Optional[dict], Path]:
    """Resolve dataset row (if visible in DB) and local path (if present)."""
    _validate_dataset_id_path(dataset_id)
    dataset_path = get_datasets_dir() / dataset_id
    local_exists = dataset_path.exists()

    client = await get_supabase_async_client()
    try:
        rows = (await client.table("datasets").select("*").eq("id", dataset_id).execute()).data or []
    except APIError as exc:
        message = str(exc).lower()
        if "invalid input syntax for type uuid" in message:
            raise HTTPException(status_code=400, detail=f"Invalid dataset id: {dataset_id}") from exc
        if local_exists:
            logger.warning("DB query failed for dataset %s; falling back to local cache: %s", dataset_id, exc)
            return None, dataset_path
        raise HTTPException(status_code=500, detail=f"Failed to query dataset: {exc}") from exc
    except Exception as exc:
        if local_exists:
            logger.warning("DB query failed for dataset %s; falling back to local cache: %s", dataset_id, exc)
            return None, dataset_path
        raise HTTPException(status_code=500, detail=f"Failed to query dataset: {exc}") from exc

    if rows:
        return rows[0], dataset_path
    if local_exists:
        return None, dataset_path
    raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")


def _build_dataset_viewer_response(
    dataset_id: str,
    metadata: LeRobotDatasetMetadata,
    dataset_meta: Optional[dict] = None,
) -> DatasetViewerResponse:
    cameras: list[DatasetViewerCameraInfo] = []
    for video_key in metadata.video_keys:
        feature = metadata.features.get(video_key) if isinstance(metadata.features, dict) else None
        info = feature.get("info") if isinstance(feature, dict) else {}
        cameras.append(
            DatasetViewerCameraInfo(
                key=video_key,
                label=_camera_label_from_key(video_key),
                width=info.get("video.width"),
                height=info.get("video.height"),
                fps=info.get("video.fps"),
                codec=info.get("video.codec"),
                pix_fmt=info.get("video.pix_fmt"),
            )
        )

    return DatasetViewerResponse(
        dataset_id=dataset_id,
        is_local=True,
        download_required=False,
        total_episodes=metadata.total_episodes,
        fps=metadata.fps,
        use_videos=bool(metadata.video_path) and len(metadata.video_keys) > 0,
        cameras=cameras,
        dataset_meta=dataset_meta,
    )


_NUMERIC_DTYPES = {
    "float16",
    "float32",
    "float64",
    "int8",
    "int16",
    "int32",
    "int64",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
}


def _is_vector_feature(feature: object) -> bool:
    if not isinstance(feature, dict):
        return False
    dtype = str(feature.get("dtype") or "").lower().strip()
    if dtype not in _NUMERIC_DTYPES:
        return False
    shape = feature.get("shape")
    if not isinstance(shape, (list, tuple)) or len(shape) != 1:
        return False
    try:
        return int(shape[0]) >= 1
    except Exception:
        return False


def _resolve_axis_names(feature: dict, axis_dim: int) -> list[str]:
    names = feature.get("names")
    if isinstance(names, list) and len(names) == axis_dim:
        resolved = [str(name) for name in names]
        if all(name.strip() for name in resolved):
            return resolved
    return [f"joint_{idx + 1}" for idx in range(axis_dim)]


def _to_float_vector(raw: Any, axis_dim: int) -> list[float]:
    if isinstance(raw, (list, tuple)):
        src = list(raw)
    else:
        src = [raw]
    values: list[float] = []
    for idx in range(axis_dim):
        item = src[idx] if idx < len(src) else 0.0
        try:
            values.append(float(item))
        except Exception:
            values.append(0.0)
    return values


async def _detach_models_from_dataset(client, dataset_id: str) -> None:
    await client.table("models").update({"dataset_id": None}).eq("dataset_id", dataset_id).execute()


async def _detach_training_jobs_from_dataset(client, dataset_id: str) -> None:
    await client.table("training_jobs").update({"dataset_id": None}).eq("dataset_id", dataset_id).execute()
    try:
        await (
            client.table("training_jobs")
            .update({"new_dataset_id": None})
            .eq("new_dataset_id", dataset_id)
            .execute()
        )
    except APIError as exc:
        if _is_missing_column_error(exc, table_name="training_jobs", column_name="new_dataset_id"):
            logger.info("Skip training_jobs.new_dataset_id detach: column not found")
            return
        raise


async def _detach_episode_links_from_dataset(client, dataset_id: str) -> None:
    await (
        client.table("experiment_evaluation_episode_links")
        .delete()
        .eq("dataset_id", dataset_id)
        .execute()
    )


async def _detach_dataset_references(client, dataset_id: str) -> None:
    await _detach_models_from_dataset(client, dataset_id)
    await _detach_training_jobs_from_dataset(client, dataset_id)
    await _detach_episode_links_from_dataset(client, dataset_id)


def _is_missing_column_error(exc: APIError, *, table_name: str, column_name: str) -> bool:
    if str(getattr(exc, "code", "")).strip() != "PGRST204":
        return False
    message = str(getattr(exc, "message", "") or "").lower()
    return table_name.lower() in message and column_name.lower() in message


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_source_datasets(raw: object) -> list[DatasetSourceInfo]:
    if not isinstance(raw, list):
        return []

    normalized: list[DatasetSourceInfo] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        dataset_id = _normalize_optional_text(item.get("dataset_id"))
        if not dataset_id or dataset_id in seen:
            continue
        seen.add(dataset_id)
        normalized.append(
            DatasetSourceInfo(
                dataset_id=dataset_id,
                name=_normalize_optional_text(item.get("name")) or dataset_id,
                content_hash=_normalize_optional_text(item.get("content_hash")),
                task_detail=_normalize_optional_text(item.get("task_detail")),
            )
        )
    return normalized


def _build_source_dataset_snapshots(rows: list[dict]) -> list[DatasetSourceInfo]:
    snapshots: list[DatasetSourceInfo] = []
    seen: set[str] = set()
    for row in rows:
        dataset_id = _normalize_optional_text(row.get("id"))
        if not dataset_id or dataset_id in seen:
            continue
        seen.add(dataset_id)
        snapshots.append(
            DatasetSourceInfo(
                dataset_id=dataset_id,
                name=_normalize_optional_text(row.get("name")) or dataset_id,
                content_hash=_normalize_optional_text(row.get("content_hash")),
                task_detail=_normalize_optional_text(row.get("task_detail")),
            )
        )
    return snapshots


def _current_user_id_for_metadata() -> str:
    session = get_supabase_session() or {}
    return str(session.get("user_id") or "unknown")


def _write_dataset_metadata_file(
    *,
    dataset_id: str,
    dataset_name: str,
    dataset_root: Path,
    profile_snapshot: Optional[dict],
    content_hash: str,
    source_datasets: list[DatasetSourceInfo],
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    metadata = DatasetMetadata(
        id=dataset_id,
        name=dataset_name,
        source=DataSource.R2,
        status=DataStatus.ACTIVE,
        created_by=_current_user_id_for_metadata(),
        created_at=now,
        updated_at=now,
        dataset_type=DatasetType.MERGED,
        profile_snapshot=profile_snapshot if isinstance(profile_snapshot, dict) else None,
        source_datasets=[
            DatasetMetadataSourceInfo(
                dataset_id=item.dataset_id,
                name=item.name,
                content_hash=item.content_hash,
                task_detail=item.task_detail,
            )
            for item in source_datasets
        ],
        sync=SyncInfo(hash=content_hash, size_bytes=0),
    )

    meta_path = dataset_root / ".meta.json"
    for _ in range(3):
        meta_path.write_text(
            json.dumps(metadata.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        size_bytes = compute_directory_size(dataset_root)
        if size_bytes == metadata.sync.size_bytes:
            return size_bytes
        metadata.sync.size_bytes = size_bytes

    final_size = compute_directory_size(dataset_root)
    if final_size != metadata.sync.size_bytes:
        metadata.sync.size_bytes = final_size
    meta_path.write_text(
        json.dumps(metadata.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return compute_directory_size(dataset_root)


def _load_local_dataset_metadata(dataset_id: str, dataset_path: Optional[Path] = None) -> Optional[LeRobotDatasetMetadata]:
    resolved_path = dataset_path or (get_datasets_dir() / dataset_id)
    if not resolved_path.exists():
        return None
    try:
        return LeRobotDatasetMetadata(dataset_id, root=resolved_path)
    except Exception as exc:
        logger.warning("Failed to load local dataset metadata for %s: %s", dataset_id, exc)
        return None


def _dataset_duration_seconds(metadata: LeRobotDatasetMetadata) -> Optional[float]:
    total_frames = _coerce_int(getattr(metadata, "total_frames", 0), 0)
    fps = _coerce_float(getattr(metadata, "fps", 0), 0.0)
    if total_frames > 0 and fps > 0:
        return float(total_frames) / fps

    total_duration = 0.0
    for episode_index in range(_coerce_int(getattr(metadata, "total_episodes", 0), 0)):
        _, duration_s, _ = _episode_summary(metadata, episode_index)
        total_duration += max(0.0, duration_s)
    return total_duration if total_duration > 0 else None


def _build_dataset_signal_field_infos(metadata: LeRobotDatasetMetadata) -> list[DatasetSignalFieldInfo]:
    feature_map = metadata.features if isinstance(metadata.features, dict) else {}
    fields: list[DatasetSignalFieldInfo] = []
    excluded_keys = {"episode_index", "frame_index", "index", "task_index", "timestamp"}
    for key in sorted(feature_map.keys()):
        if key in excluded_keys:
            continue
        feature = feature_map.get(key)
        if not _is_vector_feature(feature):
            continue
        shape = feature.get("shape") if isinstance(feature, dict) else []
        axis_count = int(shape[0]) if isinstance(shape, (list, tuple)) and shape else 0
        if axis_count < 1:
            continue
        fields.append(
            DatasetSignalFieldInfo(
                key=key,
                label=key,
                dtype=str(feature.get("dtype") or "") if isinstance(feature, dict) else "",
                axis_count=axis_count,
                names=_resolve_axis_names(feature, axis_count) if isinstance(feature, dict) else [],
            )
        )
    return fields


def _build_dataset_camera_infos(metadata: LeRobotDatasetMetadata) -> list[DatasetCameraInfo]:
    cameras: list[DatasetCameraInfo] = []
    feature_map = metadata.features if isinstance(metadata.features, dict) else {}
    for video_key in metadata.video_keys:
        feature = feature_map.get(video_key) if isinstance(feature_map, dict) else None
        info = feature.get("info") if isinstance(feature, dict) else {}
        cameras.append(
            DatasetCameraInfo(
                key=video_key,
                label=_camera_label_from_key(video_key),
                width=info.get("video.width"),
                height=info.get("video.height"),
                fps=info.get("video.fps"),
                codec=info.get("video.codec"),
                pix_fmt=info.get("video.pix_fmt"),
            )
        )
    return cameras


def _build_dataset_detail_info(metadata: LeRobotDatasetMetadata) -> DatasetDetailInfo:
    cameras = _build_dataset_camera_infos(metadata)
    signal_fields = _build_dataset_signal_field_infos(metadata)
    total_frames = _coerce_int(getattr(metadata, "total_frames", 0), 0)
    fps = _coerce_float(getattr(metadata, "fps", 0), 0.0)
    return DatasetDetailInfo(
        total_frames=total_frames if total_frames > 0 else None,
        fps=fps if fps > 0 else None,
        duration_seconds=_dataset_duration_seconds(metadata),
        use_videos=bool(metadata.video_path) and len(metadata.video_keys) > 0,
        camera_count=len(cameras),
        signal_field_count=len(signal_fields),
        cameras=cameras,
        signal_fields=signal_fields,
    )


def _dataset_row_to_info(
    row: dict,
    *,
    detail: Optional[DatasetDetailInfo] = None,
    source_datasets: Optional[list[DatasetSourceInfo]] = None,
) -> DatasetInfo:
    profile_snapshot = row.get("profile_snapshot")
    return DatasetInfo(
        id=row.get("id"),
        name=row.get("name") or row.get("id"),
        owner_user_id=row.get("owner_user_id"),
        owner_email=None,
        owner_name=None,
        profile_name=_normalize_optional_text(row.get("profile_name")),
        profile_snapshot=profile_snapshot if isinstance(profile_snapshot, dict) else None,
        source=row.get("source") or "r2",
        status=row.get("status") or "active",
        dataset_type=row.get("dataset_type") or "recorded",
        task_detail=_normalize_optional_text(row.get("task_detail")),
        content_hash=_normalize_optional_text(row.get("content_hash")),
        archived_at=row.get("archived_at"),
        source_datasets=source_datasets if source_datasets is not None else _normalize_source_datasets(row.get("source_datasets")),
        episode_count=row.get("episode_count") or 0,
        size_bytes=row.get("size_bytes") or 0,
        is_local=_dataset_is_local(row.get("id")),
        detail=detail,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _dataset_row_to_meta(row: dict) -> dict:
    return _dataset_row_to_info(row).model_dump()


async def _load_dataset_row_optional(client, dataset_id: str) -> Optional[dict]:
    try:
        rows = (await client.table("datasets").select("*").eq("id", dataset_id).execute()).data or []
    except Exception as exc:
        logger.warning("Failed to load dataset row for %s: %s", dataset_id, exc)
        return None
    return rows[0] if rows else None


def _join_task_detail_entries(entries: list[str]) -> Optional[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        text = _normalize_optional_text(entry)
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    if not normalized:
        return None
    return "\n".join(normalized)


async def _resolve_dataset_task_detail(client, row: dict, *, visited: Optional[set[str]] = None) -> Optional[str]:
    direct = _normalize_optional_text(row.get("task_detail"))
    if direct:
        return direct

    dataset_id = _normalize_optional_text(row.get("id"))
    lineage = _normalize_source_datasets(row.get("source_datasets"))
    if not dataset_id or not lineage:
        return None

    next_visited = set(visited or set())
    if dataset_id in next_visited:
        return None
    next_visited.add(dataset_id)

    entries: list[str] = []
    multi_source = len(lineage) > 1

    for source in lineage:
        if source.dataset_id in next_visited:
            continue

        source_row = await _load_dataset_row_optional(client, source.dataset_id)
        resolved_detail = None
        if source_row:
            resolved_detail = await _resolve_dataset_task_detail(client, source_row, visited=next_visited)
        if not resolved_detail:
            resolved_detail = source.task_detail
        normalized_detail = _normalize_optional_text(resolved_detail)
        if not normalized_detail:
            continue
        if multi_source:
            entries.append(f"{source.name}: {normalized_detail}")
            continue
        entries.append(normalized_detail)

    return _join_task_detail_entries(entries)


async def _resolve_source_datasets(client, source_datasets: list[DatasetSourceInfo]) -> list[DatasetSourceInfo]:
    resolved: list[DatasetSourceInfo] = []
    for source in source_datasets:
        enriched = source.model_copy(deep=True)
        row = await _load_dataset_row_optional(client, source.dataset_id)
        if row:
            enriched.status = _normalize_optional_text(row.get("status"))
            enriched.episode_count = _coerce_int(row.get("episode_count"), 0)
            enriched.size_bytes = _coerce_int(row.get("size_bytes"), 0)
            enriched.is_local = _dataset_is_local(source.dataset_id)
            if not enriched.content_hash:
                enriched.content_hash = _normalize_optional_text(row.get("content_hash"))
            if not enriched.task_detail:
                enriched.task_detail = await _resolve_dataset_task_detail(client, row)
        else:
            enriched.is_local = _dataset_is_local(source.dataset_id)

        source_metadata = _load_local_dataset_metadata(source.dataset_id)
        if source_metadata is not None:
            detail = _build_dataset_detail_info(source_metadata)
            enriched.total_frames = detail.total_frames
            enriched.fps = detail.fps
            enriched.duration_seconds = detail.duration_seconds
            if enriched.episode_count is None:
                enriched.episode_count = _coerce_int(getattr(source_metadata, "total_episodes", 0), 0)
        resolved.append(enriched)
    return resolved


async def _resolve_dataset_info(client, row: dict) -> DatasetInfo:
    dataset_id = str(row.get("id") or "").strip()
    metadata = _load_local_dataset_metadata(dataset_id) if dataset_id else None
    source_datasets = await _resolve_source_datasets(client, _normalize_source_datasets(row.get("source_datasets")))
    dataset = _dataset_row_to_info(
        row,
        detail=_build_dataset_detail_info(metadata) if metadata is not None else None,
        source_datasets=source_datasets,
    )

    owner_user_id = str(row.get("owner_user_id") or "").strip()
    owner_directory = await resolve_user_directory_entries([owner_user_id] if owner_user_id else [])
    owner_entry = owner_directory.get(owner_user_id)
    dataset.owner_email = owner_entry.email or None if owner_entry else None
    dataset.owner_name = owner_entry.name or None if owner_entry else None

    if not dataset.task_detail:
        dataset.task_detail = await _resolve_dataset_task_detail(client, row)
    if metadata is not None and not dataset.episode_count:
        dataset.episode_count = _coerce_int(getattr(metadata, "total_episodes", 0), 0)
    return dataset


def _model_row_to_info(row: dict) -> ModelInfo:
    model_id = row.get("id")
    profile_snapshot = row.get("profile_snapshot")
    return ModelInfo(
        id=model_id,
        name=row.get("name") or model_id,
        owner_user_id=row.get("owner_user_id"),
        owner_email=None,
        dataset_id=row.get("dataset_id"),
        profile_name=_normalize_optional_text(row.get("profile_name")),
        profile_snapshot=profile_snapshot if isinstance(profile_snapshot, dict) else None,
        policy_type=row.get("policy_type"),
        training_steps=row.get("training_steps"),
        batch_size=row.get("batch_size"),
        size_bytes=row.get("size_bytes") or 0,
        artifact_path=_normalize_optional_text(row.get("artifact_path")),
        is_local=_model_is_local(str(model_id)) if model_id else False,
        source=row.get("source") or "r2",
        status=row.get("status") or "active",
        archived_at=row.get("archived_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _build_model_dataset_summary(row: Optional[dict]) -> Optional[ModelInfo.DatasetSummary]:
    if not row:
        return None
    dataset_id = _normalize_optional_text(row.get("id"))
    if not dataset_id:
        return None
    return ModelInfo.DatasetSummary(
        id=dataset_id,
        name=_normalize_optional_text(row.get("name")) or dataset_id,
        status=_normalize_optional_text(row.get("status")),
        profile_name=_normalize_optional_text(row.get("profile_name")),
        episode_count=_coerce_int(row.get("episode_count"), 0),
        size_bytes=_coerce_int(row.get("size_bytes"), 0),
        is_local=_dataset_is_local(dataset_id),
    )


async def _resolve_model_info(client, row: dict) -> ModelInfo:
    model = _model_row_to_info(row)
    owner_user_id = str(row.get("owner_user_id") or "").strip()
    owner_directory = await resolve_user_directory_entries([owner_user_id])
    owner_entry = owner_directory.get(owner_user_id)
    model.owner_email = owner_entry.email or None if owner_entry else None
    model.owner_name = owner_entry.name or None if owner_entry else None
    dataset_id = _normalize_optional_text(row.get("dataset_id"))
    if dataset_id:
        model.dataset = _build_model_dataset_summary(await _load_dataset_row_optional(client, dataset_id))
    return model


def _build_bulk_action_response(results: list[BulkActionResult], requested: int | None = None) -> BulkActionResponse:
    succeeded = sum(1 for result in results if result.status == "succeeded")
    failed = sum(1 for result in results if result.status == "failed")
    skipped = sum(1 for result in results if result.status == "skipped")
    return BulkActionResponse(
        requested=requested if requested is not None else len(results),
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        results=results,
    )


def _apply_common_storage_list_filters(query, *, include_archived: bool, status: Optional[str], owner_user_id: Optional[str], search: Optional[str]):
    status = _normalize_optional_text(status)
    owner_user_id = _normalize_optional_text(owner_user_id)
    search = _normalize_optional_text(search)
    if status:
        query = query.eq("status", status)
    elif not include_archived:
        query = query.eq("status", "active")
    if owner_user_id:
        query = query.eq("owner_user_id", owner_user_id)
    if search:
        escaped = search.replace(",", "\\,")
        query = query.ilike("name", f"%{escaped}%")
    return query


def _normalize_datetime_filter_start(value: Optional[str]) -> Optional[str]:
    normalized = _normalize_optional_text(value)
    if not normalized:
        return None
    if len(normalized) == 10:
        return f"{normalized}T00:00:00+00:00"
    return normalized


def _normalize_datetime_filter_end(value: Optional[str]) -> Optional[str]:
    normalized = _normalize_optional_text(value)
    if not normalized:
        return None
    if len(normalized) == 10:
        return f"{normalized}T23:59:59.999999+00:00"
    return normalized


def _apply_dataset_list_filters(query, list_query: DatasetListQuery):
    query = _apply_common_storage_list_filters(
        query,
        include_archived=list_query.include_archived,
        status=list_query.status,
        owner_user_id=list_query.owner_user_id,
        search=list_query.search,
    )
    profile_name = _normalize_optional_text(list_query.profile_name)
    dataset_type = _normalize_optional_text(list_query.dataset_type)
    created_from = _normalize_datetime_filter_start(list_query.created_from)
    created_to = _normalize_datetime_filter_end(list_query.created_to)
    size_min = list_query.size_min
    size_max = list_query.size_max
    episode_count_min = list_query.episode_count_min
    episode_count_max = list_query.episode_count_max
    if profile_name:
        query = query.eq("profile_name", profile_name)
    if dataset_type:
        query = query.eq("dataset_type", dataset_type)
    if created_from:
        query = query.gte("created_at", created_from)
    if created_to:
        query = query.lte("created_at", created_to)
    if size_min is not None:
        query = query.gte("size_bytes", size_min)
    if size_max is not None:
        query = query.lte("size_bytes", size_max)
    if episode_count_min is not None:
        query = query.gte("episode_count", episode_count_min)
    if episode_count_max is not None:
        query = query.lte("episode_count", episode_count_max)
    return query


def _apply_model_list_filters(query, list_query: ModelListQuery):
    query = _apply_common_storage_list_filters(
        query,
        include_archived=list_query.include_archived,
        status=list_query.status,
        owner_user_id=list_query.owner_user_id,
        search=list_query.search,
    )
    profile_name = _normalize_optional_text(list_query.profile_name)
    policy_type = _normalize_optional_text(list_query.policy_type)
    dataset_id = _normalize_optional_text(list_query.dataset_id)
    created_from = _normalize_datetime_filter_start(list_query.created_from)
    created_to = _normalize_datetime_filter_end(list_query.created_to)
    size_min = list_query.size_min
    size_max = list_query.size_max
    if profile_name:
        query = query.eq("profile_name", profile_name)
    if policy_type:
        query = query.eq("policy_type", policy_type)
    if dataset_id:
        escaped = dataset_id.replace(",", "\\,")
        query = query.ilike("dataset_id", f"%{escaped}%")
    if created_from:
        query = query.gte("created_at", created_from)
    if created_to:
        query = query.lte("created_at", created_to)
    if size_min is not None:
        query = query.gte("size_bytes", size_min)
    if size_max is not None:
        query = query.lte("size_bytes", size_max)
    return query


def _apply_storage_list_sort_and_paging(query, *, sort_by: str, sort_order: StorageSortOrder, offset: int, limit: Optional[int]):
    query = query.order(sort_by, desc=sort_order == "desc")
    if offset > 0:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query


def _dataset_sync_status_value(dataset_id: str, active_jobs_by_dataset_id: dict[str, DatasetSyncJobStatus], is_local: bool) -> str:
    job = active_jobs_by_dataset_id.get(dataset_id)
    if job and job.state in {"queued", "running"}:
        return "syncing"
    if is_local:
        return "synced"
    return "not_synced"


def _model_sync_status_value(model_id: str, active_jobs_by_model_id: dict[str, ModelSyncJobStatus], is_local: bool) -> str:
    job = active_jobs_by_model_id.get(model_id)
    if job and job.state in {"queued", "running"}:
        return "syncing"
    if is_local:
        return "synced"
    return "not_synced"


def _sync_status_label(value: str) -> str:
    if value == "syncing":
        return "同期中"
    if value == "synced":
        return "同期済"
    return "未同期"


def _build_owner_filter_options(
    items: list[DatasetInfo | ModelInfo],
    available_items: list[DatasetInfo | ModelInfo],
    owner_directory,
) -> list[OwnerFilterOption]:
    total_counts: dict[str, int] = {}
    available_counts: dict[str, int] = {}

    for item in items:
        owner_id = str(item.owner_user_id or "").strip()
        if owner_id:
            total_counts[owner_id] = total_counts.get(owner_id, 0) + 1

    for item in available_items:
        owner_id = str(item.owner_user_id or "").strip()
        if owner_id:
            available_counts[owner_id] = available_counts.get(owner_id, 0) + 1

    options: list[OwnerFilterOption] = []
    for owner_id, total_count in total_counts.items():
        owner_entry = owner_directory.get(owner_id)
        label = ((owner_entry.name or "").strip() or (owner_entry.email or "").strip() or owner_id) if owner_entry else owner_id
        options.append(
            OwnerFilterOption(
                user_id=owner_id,
                label=label,
                owner_name=owner_entry.name or None if owner_entry else None,
                owner_email=owner_entry.email or None if owner_entry else None,
                total_count=total_count,
                available_count=available_counts.get(owner_id, 0),
            )
        )

    options.sort(key=lambda option: (option.label.lower(), option.user_id))
    return options


def _build_value_filter_options(
    items: list[Any],
    available_items: list[Any],
    *,
    value_getter: Callable[[Any], str],
    label_getter: Optional[Callable[[str], str]] = None,
) -> list[ValueFilterOption]:
    total_counts: dict[str, int] = {}
    available_counts: dict[str, int] = {}

    for item in items:
        value = str(value_getter(item) or "").strip()
        if value:
            total_counts[value] = total_counts.get(value, 0) + 1

    for item in available_items:
        value = str(value_getter(item) or "").strip()
        if value:
            available_counts[value] = available_counts.get(value, 0) + 1

    options: list[ValueFilterOption] = []
    for value, total_count in total_counts.items():
        options.append(
            ValueFilterOption(
                value=value,
                label=label_getter(value) if label_getter else value,
                total_count=total_count,
                available_count=available_counts.get(value, 0),
            )
        )

    options.sort(key=lambda option: (option.label.lower(), option.value))
    return options


def _normalize_sort_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _dataset_sync_rank(dataset_id: str, active_jobs_by_dataset_id: dict[str, DatasetSyncJobStatus], is_local: bool) -> tuple[int, float]:
    job = active_jobs_by_dataset_id.get(dataset_id)
    if job and job.state in {"queued", "running"}:
        return (2, float(job.progress_percent or 0))
    if is_local:
        return (1, 100.0)
    return (0, 0.0)


def _model_sync_rank(model_id: str, active_jobs_by_model_id: dict[str, ModelSyncJobStatus], is_local: bool) -> tuple[int, float]:
    job = active_jobs_by_model_id.get(model_id)
    if job and job.state in {"queued", "running"}:
        return (2, float(job.progress_percent or 0))
    if is_local:
        return (1, 100.0)
    return (0, 0.0)


async def _load_dataset_rows(list_query: DatasetListQuery) -> tuple[list[dict], int]:
    client = await get_supabase_async_client()
    query = client.table("datasets").select("*", count="exact")
    query = _apply_dataset_list_filters(query, list_query)
    result = await query.execute()
    rows = result.data or []
    total = int(getattr(result, "count", len(rows)) or 0)
    return rows, total


async def _load_model_rows(list_query: ModelListQuery) -> tuple[list[dict], int]:
    client = await get_supabase_async_client()
    query = client.table("models").select("*", count="exact")
    query = _apply_model_list_filters(query, list_query)
    result = await query.execute()
    rows = result.data or []
    total = int(getattr(result, "count", len(rows)) or 0)
    return rows, total


async def _list_datasets(list_query: DatasetListQuery) -> DatasetListResponse:
    base_query = list_query.model_copy(
        update={
            "owner_user_id": None,
            "profile_name": None,
            "dataset_type": None,
            "sync_status": None,
            "limit": None,
            "offset": 0,
        }
    )
    rows, _ = await _load_dataset_rows(base_query)
    owner_directory = await resolve_user_directory_entries(
        [str(row.get("owner_user_id") or "").strip() for row in rows]
    )
    active_jobs = get_dataset_sync_jobs_service().list(user_id=require_user_id(), include_terminal=False).jobs
    active_jobs_by_dataset_id = {job.dataset_id: job for job in active_jobs}
    datasets: list[DatasetInfo] = []
    for row in rows:
        dataset = _dataset_row_to_info(row)
        owner_user_id = str(row.get("owner_user_id") or "").strip()
        owner_entry = owner_directory.get(owner_user_id)
        dataset.owner_email = owner_entry.email or None if owner_entry else None
        dataset.owner_name = owner_entry.name or None if owner_entry else None
        datasets.append(dataset)

    def _matches(dataset: DatasetInfo, *, ignore: frozenset[str] = frozenset()) -> bool:
        if "owner_user_id" not in ignore:
            owner_filter = _normalize_optional_text(list_query.owner_user_id)
            if owner_filter and _normalize_optional_text(dataset.owner_user_id) != owner_filter:
                return False
        if "profile_name" not in ignore:
            profile_filter = _normalize_optional_text(list_query.profile_name)
            if profile_filter and _normalize_optional_text(dataset.profile_name) != profile_filter:
                return False
        if "dataset_type" not in ignore:
            dataset_type_filter = _normalize_optional_text(list_query.dataset_type)
            if dataset_type_filter and _normalize_optional_text(dataset.dataset_type) != dataset_type_filter:
                return False
        if "sync_status" not in ignore:
            sync_status_filter = _normalize_optional_text(list_query.sync_status)
            if sync_status_filter:
                current_sync_status = _dataset_sync_status_value(
                    dataset.id, active_jobs_by_dataset_id, bool(dataset.is_local)
                )
                if current_sync_status != sync_status_filter:
                    return False
        return True

    owner_options = _build_owner_filter_options(
        datasets,
        [dataset for dataset in datasets if _matches(dataset, ignore=frozenset({"owner_user_id"}))],
        owner_directory,
    )
    profile_options = _build_value_filter_options(
        datasets,
        [dataset for dataset in datasets if _matches(dataset, ignore=frozenset({"profile_name"}))],
        value_getter=lambda dataset: dataset.profile_name or "",
    )
    dataset_type_options = _build_value_filter_options(
        datasets,
        [dataset for dataset in datasets if _matches(dataset, ignore=frozenset({"dataset_type"}))],
        value_getter=lambda dataset: dataset.dataset_type or "",
    )
    sync_status_options = _build_value_filter_options(
        datasets,
        [dataset for dataset in datasets if _matches(dataset, ignore=frozenset({"sync_status"}))],
        value_getter=lambda dataset: _dataset_sync_status_value(
            dataset.id, active_jobs_by_dataset_id, bool(dataset.is_local)
        ),
        label_getter=_sync_status_label,
    )
    filtered = [dataset for dataset in datasets if _matches(dataset)]

    reverse = list_query.sort_order == "desc"

    def _sort_key(dataset: DatasetInfo) -> tuple[object, str]:
        if list_query.sort_by == "name":
            primary: object = _normalize_sort_text(dataset.name or dataset.id)
        elif list_query.sort_by == "owner_name":
            primary = _normalize_sort_text(dataset.owner_name or dataset.owner_email or dataset.owner_user_id)
        elif list_query.sort_by == "profile_name":
            primary = _normalize_sort_text(dataset.profile_name)
        elif list_query.sort_by == "episode_count":
            primary = int(dataset.episode_count or 0)
        elif list_query.sort_by == "size_bytes":
            primary = int(dataset.size_bytes or 0)
        elif list_query.sort_by == "updated_at":
            primary = str(dataset.updated_at or "")
        elif list_query.sort_by == "sync_status":
            primary = _dataset_sync_rank(dataset.id, active_jobs_by_dataset_id, bool(dataset.is_local))
        else:
            primary = str(dataset.created_at or "")
        return primary, str(dataset.id or "")

    filtered.sort(key=_sort_key, reverse=reverse)
    total = len(filtered)
    paged = filtered[list_query.offset:]
    if list_query.limit is not None:
        paged = paged[:list_query.limit]
    return DatasetListResponse(
        datasets=paged,
        total=total,
        owner_options=owner_options,
        profile_options=profile_options,
        dataset_type_options=dataset_type_options,
        sync_status_options=sync_status_options,
    )


async def _list_models(list_query: ModelListQuery) -> ModelListResponse:
    base_query = list_query.model_copy(
        update={
            "owner_user_id": None,
            "profile_name": None,
            "policy_type": None,
            "sync_status": None,
            "limit": None,
            "offset": 0,
        }
    )
    rows, _ = await _load_model_rows(base_query)
    owner_directory = await resolve_user_directory_entries(
        [str(row.get("owner_user_id") or "").strip() for row in rows]
    )
    active_jobs = get_model_sync_jobs_service().list(user_id=require_user_id(), include_terminal=False).jobs
    active_jobs_by_model_id = {job.model_id: job for job in active_jobs}
    models: list[ModelInfo] = []
    for row in rows:
        model = _model_row_to_info(row)
        owner_user_id = str(row.get("owner_user_id") or "").strip()
        owner_entry = owner_directory.get(owner_user_id)
        model.owner_email = owner_entry.email or None if owner_entry else None
        model.owner_name = owner_entry.name or None if owner_entry else None
        models.append(model)

    def _matches(model: ModelInfo, *, ignore: frozenset[str] = frozenset()) -> bool:
        if "owner_user_id" not in ignore:
            owner_filter = _normalize_optional_text(list_query.owner_user_id)
            if owner_filter and _normalize_optional_text(model.owner_user_id) != owner_filter:
                return False
        if "profile_name" not in ignore:
            profile_filter = _normalize_optional_text(list_query.profile_name)
            if profile_filter and _normalize_optional_text(model.profile_name) != profile_filter:
                return False
        if "policy_type" not in ignore:
            policy_filter = _normalize_optional_text(list_query.policy_type)
            if policy_filter and _normalize_optional_text(model.policy_type) != policy_filter:
                return False
        if "sync_status" not in ignore:
            sync_status_filter = _normalize_optional_text(list_query.sync_status)
            if sync_status_filter:
                current_sync_status = _model_sync_status_value(
                    model.id, active_jobs_by_model_id, bool(model.is_local)
                )
                if current_sync_status != sync_status_filter:
                    return False
        return True

    owner_options = _build_owner_filter_options(
        models,
        [model for model in models if _matches(model, ignore=frozenset({"owner_user_id"}))],
        owner_directory,
    )
    profile_options = _build_value_filter_options(
        models,
        [model for model in models if _matches(model, ignore=frozenset({"profile_name"}))],
        value_getter=lambda model: model.profile_name or "",
    )
    policy_type_options = _build_value_filter_options(
        models,
        [model for model in models if _matches(model, ignore=frozenset({"policy_type"}))],
        value_getter=lambda model: model.policy_type or "",
    )
    sync_status_options = _build_value_filter_options(
        models,
        [model for model in models if _matches(model, ignore=frozenset({"sync_status"}))],
        value_getter=lambda model: _model_sync_status_value(
            model.id, active_jobs_by_model_id, bool(model.is_local)
        ),
        label_getter=_sync_status_label,
    )
    filtered = [model for model in models if _matches(model)]

    reverse = list_query.sort_order == "desc"

    def _sort_key(model: ModelInfo) -> tuple[object, str]:
        if list_query.sort_by == "name":
            primary: object = _normalize_sort_text(model.name or model.id)
        elif list_query.sort_by == "owner_name":
            primary = _normalize_sort_text(model.owner_name or model.owner_email or model.owner_user_id)
        elif list_query.sort_by == "profile_name":
            primary = _normalize_sort_text(model.profile_name)
        elif list_query.sort_by == "policy_type":
            primary = _normalize_sort_text(model.policy_type)
        elif list_query.sort_by == "size_bytes":
            primary = int(model.size_bytes or 0)
        elif list_query.sort_by == "updated_at":
            primary = str(model.updated_at or "")
        elif list_query.sort_by == "sync_status":
            primary = _model_sync_rank(model.id, active_jobs_by_model_id, bool(model.is_local))
        else:
            primary = str(model.created_at or "")
        return primary, str(model.id or "")

    filtered.sort(key=_sort_key, reverse=reverse)
    total = len(filtered)
    paged = filtered[list_query.offset:]
    if list_query.limit is not None:
        paged = paged[:list_query.limit]
    return ModelListResponse(
        models=paged,
        total=total,
        owner_options=owner_options,
        profile_options=profile_options,
        policy_type_options=policy_type_options,
        sync_status_options=sync_status_options,
    )


async def _require_dataset_row(client, dataset_id: str) -> dict:
    rows = (await client.table("datasets").select("*").eq("id", dataset_id).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    return rows[0]


async def _require_model_row(client, model_id: str) -> dict:
    rows = (await client.table("models").select("*").eq("id", model_id).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    return rows[0]


def _validate_storage_name_or_raise(name: str) -> str:
    normalized_name = str(name).strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Name is required")

    is_valid, errors = validate_dataset_name(normalized_name)
    if not is_valid:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return normalized_name


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets(
    include_archived: bool = Query(False, description="Include archived datasets"),
    profile_name: Optional[str] = Query(None, description="Filter by profile name"),
    owner_user_id: Optional[str] = Query(None, description="Filter by owner user id"),
    status: Optional[str] = Query(None, description="Filter by dataset status"),
    dataset_type: Optional[str] = Query(None, description="Filter by dataset type"),
    sync_status: Optional[str] = Query(None, description="Filter by sync status"),
    search: Optional[str] = Query(None, description="Search dataset name"),
    created_from: Optional[str] = Query(None, description="Filter by creation time lower bound"),
    created_to: Optional[str] = Query(None, description="Filter by creation time upper bound"),
    size_min: Optional[int] = Query(None, ge=0, description="Minimum size in bytes"),
    size_max: Optional[int] = Query(None, ge=0, description="Maximum size in bytes"),
    episode_count_min: Optional[int] = Query(None, ge=0, description="Minimum episode count"),
    episode_count_max: Optional[int] = Query(None, ge=0, description="Maximum episode count"),
    limit: Optional[int] = Query(None, ge=1, le=500, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    sort_by: DatasetListSortBy = Query("created_at", description="Sort field"),
    sort_order: StorageSortOrder = Query("desc", description="Sort direction"),
):
    """List datasets from DB."""
    return await _list_datasets(
        DatasetListQuery(
            include_archived=include_archived,
            profile_name=profile_name,
            owner_user_id=owner_user_id,
            status=status,
            dataset_type=dataset_type,
            sync_status=sync_status,
            search=search,
            created_from=created_from,
            created_to=created_to,
            size_min=size_min,
            size_max=size_max,
            episode_count_min=episode_count_min,
            episode_count_max=episode_count_max,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


async def _merge_datasets(
    request: DatasetMergeRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> DatasetMergeResponse:
    def report(message: dict) -> None:
        if progress_callback:
            progress_callback(message)

    source_dataset_ids = list(dict.fromkeys(request.source_dataset_ids))
    if len(source_dataset_ids) < 2:
        raise HTTPException(status_code=400, detail="At least two source datasets are required")

    is_valid, errors = validate_dataset_name(request.dataset_name)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid dataset name: {'; '.join(errors)}")

    merged_dataset_id = generate_dataset_id()
    client = await get_supabase_async_client()

    report({"type": "start", "step": "validate", "message": "Validating datasets"})
    source_rows = []
    for dataset_id in source_dataset_ids:
        rows = (
            await client.table("datasets").select("*").eq("id", dataset_id).execute()
        ).data or []
        if not rows:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
        row = rows[0]
        if row.get("status") != "active":
            raise HTTPException(status_code=400, detail=f"Dataset is not active: {dataset_id}")
        source_rows.append(row)
    report({"type": "step_complete", "step": "validate", "message": "Validation complete"})

    profile_names = {
        profile_name
        for row in source_rows
        for profile_name in [_normalize_optional_text(row.get("profile_name"))]
        if profile_name
    }
    if len(profile_names) > 1:
        raise HTTPException(status_code=400, detail="Profile mismatch across source datasets")
    profile_snapshot = next(
        (row.get("profile_snapshot") for row in source_rows if isinstance(row.get("profile_snapshot"), dict)),
        None,
    )
    source_datasets = _build_source_dataset_snapshots(source_rows)

    report({"type": "start", "step": "download", "message": "Ensuring local datasets"})
    sync_service = R2DBSyncService()
    for dataset_id in source_dataset_ids:
        report({"type": "progress", "step": "download", "dataset_id": dataset_id})
        result = await sync_service.ensure_dataset_local(dataset_id, auto_download=True)
        if not result.success:
            raise HTTPException(status_code=500, detail=f"Dataset download failed: {result.message}")
    report({"type": "step_complete", "step": "download", "message": "Local datasets ready"})

    datasets_dir = get_datasets_dir()
    merged_root = datasets_dir / merged_dataset_id
    if merged_root.exists():
        raise HTTPException(status_code=409, detail=f"Local dataset already exists: {merged_dataset_id}")

    report({"type": "start", "step": "aggregate", "message": "Aggregating datasets"})
    roots = [datasets_dir / dataset_id for dataset_id in source_dataset_ids]
    try:
        aggregate_datasets(
            repo_ids=source_dataset_ids,
            aggr_repo_id=merged_dataset_id,
            roots=roots,
            aggr_root=merged_root,
        )
    except Exception as e:
        if merged_root.exists():
            shutil.rmtree(merged_root)
        raise HTTPException(status_code=500, detail=f"Dataset merge failed: {e}") from e
    report({"type": "step_complete", "step": "aggregate", "message": "Aggregation complete"})

    content_hash = compute_directory_hash(merged_root, use_content=True)
    size_bytes = _write_dataset_metadata_file(
        dataset_id=merged_dataset_id,
        dataset_name=request.dataset_name,
        dataset_root=merged_root,
        profile_snapshot=profile_snapshot,
        content_hash=content_hash,
        source_datasets=source_datasets,
    )
    metadata = LeRobotDatasetMetadata(merged_dataset_id, root=merged_root)
    episode_count = metadata.total_episodes

    def upload_progress(message: dict) -> None:
        msg_type = message.get("type")
        if msg_type == "error":
            report({"type": "error", "error": message.get("error")})
            return
        type_map = {
            "start": "upload_start",
            "uploading": "uploading",
            "progress": "upload_progress",
            "uploaded": "upload_file_complete",
            "complete": "upload_complete",
        }
        report({**message, "type": type_map.get(msg_type, msg_type), "step": "upload"})

    report({"type": "start", "step": "upload", "message": "Uploading merged dataset"})
    ok, error = await sync_service.upload_dataset_with_progress(merged_dataset_id, upload_progress)
    if not ok:
        shutil.rmtree(merged_root)
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {error}")
    report({"type": "step_complete", "step": "upload", "message": "Upload complete"})

    payload = {
        "id": merged_dataset_id,
        "name": request.dataset_name,
        "profile_name": extract_profile_name(profile_snapshot),
        "profile_snapshot": profile_snapshot,
        "episode_count": episode_count,
        "dataset_type": "merged",
        "source_datasets": [item.model_dump(mode="python") for item in source_datasets],
        "source": "r2",
        "status": "active",
        "size_bytes": size_bytes,
        "content_hash": content_hash,
    }
    await upsert_with_owner("datasets", "id", payload)

    return DatasetMergeResponse(
        success=True,
        dataset_id=merged_dataset_id,
        message="Dataset merged",
        size_bytes=size_bytes,
        episode_count=episode_count,
    )

async def _run_dataset_merge_job(*, user_id: str, job_id: str, request: DatasetMergeRequest) -> None:
    jobs = get_dataset_merge_jobs_service()
    main_loop = asyncio.get_running_loop()
    session = get_supabase_session()

    def progress_callback(progress: dict) -> None:
        jobs.update_from_progress(job_id=job_id, progress=progress)

    def _merge_datasets_sync() -> DatasetMergeResponse:
        token = set_request_session(session)
        try:
            return asyncio.run(_merge_datasets(request, progress_callback))
        finally:
            reset_request_session(token)

    jobs.set_running(
        job_id=job_id,
        progress_percent=1.0,
        message="データセットマージを開始しました。",
        step="validate",
    )
    try:
        result = await main_loop.run_in_executor(_executor, _merge_datasets_sync)
    except HTTPException as exc:
        jobs.fail(job_id=job_id, message="データセットマージに失敗しました。", error=str(exc.detail))
    except Exception as exc:
        logger.exception("Dataset merge job failed unexpectedly: %s", job_id)
        jobs.fail(job_id=job_id, message="データセットマージに失敗しました。", error=str(exc))
    else:
        jobs.complete(job_id=job_id, result=result)


@router.post("/dataset-merge/jobs", response_model=DatasetMergeJobAcceptedResponse, status_code=202)
async def start_dataset_merge_job(request: DatasetMergeRequest):
    """Start a background dataset merge job with SSE progress."""
    user_id = require_user_id()
    jobs = get_dataset_merge_jobs_service()
    accepted = jobs.create(user_id=user_id, request=request)
    asyncio.create_task(_run_dataset_merge_job(user_id=user_id, job_id=accepted.job_id, request=request))
    return accepted


@router.get("/dataset-merge/jobs/{job_id}", response_model=DatasetMergeJobStatus)
async def get_dataset_merge_job(job_id: str):
    user_id = require_user_id()
    jobs = get_dataset_merge_jobs_service()
    return jobs.get(user_id=user_id, job_id=job_id)


@router.get("/datasets/{dataset_id:path}", response_model=DatasetInfo)
async def get_dataset(dataset_id: str):
    """Get dataset details from DB."""
    client = await get_supabase_async_client()
    return await _resolve_dataset_info(client, await _require_dataset_row(client, dataset_id))


@router.patch("/datasets/{dataset_id:path}", response_model=DatasetInfo)
async def rename_dataset(dataset_id: str, request: StorageRenameRequest):
    """Rename dataset display name without changing dataset_id."""
    require_user_id()
    normalized_name = _validate_storage_name_or_raise(request.name)

    client = await get_supabase_async_client()
    await _require_dataset_row(client, dataset_id)
    await client.table("datasets").update({"name": normalized_name}).eq("id", dataset_id).execute()
    return await _resolve_dataset_info(client, await _require_dataset_row(client, dataset_id))


@router.get(
    "/dataset-viewer/datasets/{dataset_id:path}/episodes",
    response_model=DatasetViewerEpisodeListResponse,
)
async def get_dataset_viewer_episodes(dataset_id: str):
    """List dataset episodes for viewer."""
    _row, dataset_path = await _resolve_dataset_row_and_path(dataset_id)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Local dataset not found: {dataset_id}")

    try:
        metadata = LeRobotDatasetMetadata(dataset_id, root=dataset_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset metadata: {exc}") from exc

    episodes = []
    for idx in range(metadata.total_episodes):
        frame_count, duration_s, effective_fps = _episode_summary(metadata, idx)
        episodes.append(
            DatasetViewerEpisode(
                episode_index=idx,
                frame_count=frame_count,
                duration_s=duration_s,
                effective_fps=effective_fps,
            )
        )
    return DatasetViewerEpisodeListResponse(
        dataset_id=dataset_id,
        episodes=episodes,
        total=len(episodes),
    )


@router.get(
    "/dataset-viewer/datasets/{dataset_id:path}/episodes/{episode_index}/signals",
    response_model=DatasetViewerSignalSeriesResponse,
)
async def get_dataset_viewer_signal_series(
    dataset_id: str,
    episode_index: int,
    field: str = Query(..., min_length=1),
):
    """Load one episode series for a specific vector field from dataset parquet."""
    if episode_index < 0:
        raise HTTPException(status_code=400, detail="episode_index must be >= 0")

    _row, dataset_path = await _resolve_dataset_row_and_path(dataset_id)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Local dataset not found: {dataset_id}")

    try:
        metadata = LeRobotDatasetMetadata(dataset_id, root=dataset_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset metadata: {exc}") from exc

    if episode_index >= metadata.total_episodes:
        raise HTTPException(
            status_code=404,
            detail=f"Episode index out of range: {episode_index} (total={metadata.total_episodes})",
        )

    feature_map = metadata.features if isinstance(metadata.features, dict) else {}
    feature = feature_map.get(field)
    if not _is_vector_feature(feature):
        raise HTTPException(status_code=404, detail=f"Signal field not found or not supported: {field}")

    shape = feature.get("shape") if isinstance(feature, dict) else []
    axis_dim = int(shape[0]) if isinstance(shape, (list, tuple)) and shape else 0
    if axis_dim <= 0:
        raise HTTPException(status_code=400, detail=f"Signal field has invalid shape: {field}")
    names = _resolve_axis_names(feature, axis_dim)

    try:
        relative_data_path = metadata.get_data_file_path(episode_index)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resolve data file path: {exc}") from exc
    data_path = dataset_path / relative_data_path
    if not data_path.exists():
        raise HTTPException(status_code=404, detail=f"Data file not found: {relative_data_path}")

    try:
        parquet = pq.ParquetFile(data_path)
        # parquet.schema.names returns leaf names (e.g. "element") for list types.
        # schema_arrow.names gives the correct top-level column names.
        schema_names = set(parquet.schema_arrow.names)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read parquet schema: {exc}") from exc

    # LeRobot datasets can store one parquet per episode (no episode_index column),
    # or a single parquet with episode_index partitioning. Support both.
    required_columns = {field}
    if not required_columns.issubset(schema_names):
        raise HTTPException(status_code=404, detail=f"Required columns missing in parquet: {sorted(required_columns)}")

    has_episode_index = "episode_index" in schema_names
    columns = [field]
    if has_episode_index:
        columns.append("episode_index")
    if "frame_index" in schema_names:
        columns.append("frame_index")
    if "timestamp" in schema_names:
        columns.append("timestamp")

    try:
        table = pq.read_table(
            data_path,
            columns=columns,
            filters=[("episode_index", "=", episode_index)] if has_episode_index else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load episode series: {exc}") from exc

    if table.num_rows == 0:
        return DatasetViewerSignalSeriesResponse(
            dataset_id=dataset_id,
            episode_index=episode_index,
            field=field,
            fps=metadata.fps,
            names=names,
            positions=[],
            timestamps=[],
        )

    raw_vectors = table.column(field).to_pylist()
    positions = [_to_float_vector(raw, axis_dim) for raw in raw_vectors]

    if "timestamp" in columns:
        timestamps_raw = table.column("timestamp").to_pylist()
        timestamps = [float(v) for v in timestamps_raw]
    else:
        fps = metadata.fps if metadata.fps > 0 else 30
        timestamps = [float(i) / float(fps) for i in range(len(positions))]

    if "frame_index" in columns:
        frame_indices = [int(v) for v in table.column("frame_index").to_pylist()]
        order = sorted(range(len(frame_indices)), key=lambda idx: frame_indices[idx])
        positions = [positions[idx] for idx in order]
        timestamps = [timestamps[idx] for idx in order]

    return DatasetViewerSignalSeriesResponse(
        dataset_id=dataset_id,
        episode_index=episode_index,
        field=field,
        fps=metadata.fps,
        names=names,
        positions=positions,
        timestamps=timestamps,
    )


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
        if parsed != parsed:  # NaN
            return default
        return parsed
    except Exception:
        return default


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _episode_summary(metadata: LeRobotDatasetMetadata, episode_index: int) -> tuple[int, float, float]:
    if episode_index < 0 or episode_index >= metadata.total_episodes:
        return 0, 0.0, 0.0

    ep = metadata.episodes[episode_index]
    if not isinstance(ep, dict):
        fallback_fps = max(0.0, _coerce_float(metadata.fps, 0.0))
        return 0, 0.0, fallback_fps

    frame_count = _coerce_int(ep.get("length"), 0)
    if frame_count <= 0:
        from_idx = _coerce_int(ep.get("dataset_from_index"), 0)
        to_idx = _coerce_int(ep.get("dataset_to_index"), 0)
        if to_idx > from_idx:
            frame_count = to_idx - from_idx

    duration_s = 0.0
    for video_key in metadata.video_keys:
        from_s = _coerce_float(ep.get(f"videos/{video_key}/from_timestamp"), -1.0)
        to_s = _coerce_float(ep.get(f"videos/{video_key}/to_timestamp"), -1.0)
        if from_s >= 0.0 and to_s > from_s:
            duration_s = to_s - from_s
            break

    if duration_s <= 0.0:
        dataset_fps = _coerce_float(metadata.fps, 0.0)
        if dataset_fps > 0.0 and frame_count > 0:
            duration_s = frame_count / dataset_fps

    if duration_s <= 0.0 or frame_count <= 0:
        fallback_fps = max(0.0, _coerce_float(metadata.fps, 0.0))
        return max(0, frame_count), max(0.0, duration_s), fallback_fps

    effective_fps = max(0.0, float(frame_count) / duration_s)
    return max(0, frame_count), max(0.0, duration_s), effective_fps


@router.get(
    "/dataset-viewer/datasets/{dataset_id:path}/episodes/{episode_index}/videos/window",
    response_model=DatasetViewerEpisodeVideoWindowResponse,
)
async def get_dataset_viewer_episode_video_window(dataset_id: str, episode_index: int):
    """Return per-video episode boundaries within chunked video files.

    LeRobot may concatenate multiple episodes into a single mp4 (chunk/file). The episode
    boundaries are stored in episode metadata as `videos/{key}/from_timestamp` and `to_timestamp`.
    """
    if episode_index < 0:
        raise HTTPException(status_code=400, detail="episode_index must be >= 0")

    _row, dataset_path = await _resolve_dataset_row_and_path(dataset_id)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Local dataset not found: {dataset_id}")

    try:
        metadata = LeRobotDatasetMetadata(dataset_id, root=dataset_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset metadata: {exc}") from exc

    if episode_index >= metadata.total_episodes:
        raise HTTPException(
            status_code=404,
            detail=f"Episode index out of range: {episode_index} (total={metadata.total_episodes})",
        )

    ep = metadata.episodes[episode_index]
    videos: list[DatasetViewerEpisodeVideoWindow] = []
    for video_key in metadata.video_keys:
        try:
            relative_path = metadata.get_video_file_path(episode_index, video_key)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to resolve video file path: {exc}") from exc

        from_s = _coerce_float(ep.get(f"videos/{video_key}/from_timestamp", 0.0), 0.0)
        to_s = _coerce_float(ep.get(f"videos/{video_key}/to_timestamp", 0.0), 0.0)
        videos.append(
            DatasetViewerEpisodeVideoWindow(
                key=video_key,
                relative_path=str(relative_path),
                from_s=max(0.0, from_s),
                to_s=max(0.0, to_s),
            )
        )

    return DatasetViewerEpisodeVideoWindowResponse(dataset_id=dataset_id, episode_index=episode_index, videos=videos)


# NOTE: This route must appear after `/videos/window` because Starlette matches routes in definition order.
@router.get("/dataset-viewer/datasets/{dataset_id:path}/episodes/{episode_index}/videos/{video_key:path}")
async def get_dataset_viewer_video(dataset_id: str, video_key: str, episode_index: int):
    """Stream a dataset episode video for playback."""
    if episode_index < 0:
        raise HTTPException(status_code=400, detail="episode_index must be >= 0")

    _row, dataset_path = await _resolve_dataset_row_and_path(dataset_id)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Local dataset not found: {dataset_id}")

    try:
        metadata = LeRobotDatasetMetadata(dataset_id, root=dataset_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset metadata: {exc}") from exc

    if video_key not in metadata.video_keys:
        raise HTTPException(status_code=404, detail=f"Video stream not found: {video_key}")
    if episode_index >= metadata.total_episodes:
        raise HTTPException(
            status_code=404,
            detail=f"Episode index out of range: {episode_index} (total={metadata.total_episodes})",
        )

    try:
        relative_path = metadata.get_video_file_path(episode_index, video_key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to resolve video file path: {exc}") from exc
    video_path = Path(dataset_path) / relative_path
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"Video file not found: {relative_path}")

    suffix = video_path.suffix.lower()
    media_type = "video/mp4" if suffix == ".mp4" else "video/webm" if suffix == ".webm" else "application/octet-stream"
    return FileResponse(
        path=video_path,
        media_type=media_type,
        filename=video_path.name,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/dataset-viewer/datasets/{dataset_id:path}/signals", response_model=DatasetViewerSignalFieldsResponse)
async def get_dataset_viewer_signal_fields(dataset_id: str):
    """List numeric vector fields that can be visualized as joint-state style charts."""
    _row, dataset_path = await _resolve_dataset_row_and_path(dataset_id)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Local dataset not found: {dataset_id}")

    try:
        metadata = LeRobotDatasetMetadata(dataset_id, root=dataset_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset metadata: {exc}") from exc

    feature_map = metadata.features if isinstance(metadata.features, dict) else {}
    fields: list[DatasetViewerSignalField] = []
    excluded_keys = {
        "episode_index",
        "frame_index",
        "index",
        "task_index",
        "timestamp",
    }
    for key in sorted(feature_map.keys()):
        if key in excluded_keys:
            continue
        feature = feature_map.get(key)
        if not _is_vector_feature(feature):
            continue
        try:
            shape = feature.get("shape") if isinstance(feature, dict) else []
            axis_dim = int(shape[0]) if isinstance(shape, (list, tuple)) and shape else 0
            if axis_dim < 2:
                continue
            fields.append(
                DatasetViewerSignalField(
                    key=key,
                    label=key,
                    shape=[axis_dim],
                    names=_resolve_axis_names(feature, axis_dim) if isinstance(feature, dict) else [],
                    dtype=str(feature.get("dtype") or "") if isinstance(feature, dict) else "",
                )
            )
        except Exception as exc:
            logger.warning("Skip invalid signal feature %s: %s", key, exc)
            continue

    return DatasetViewerSignalFieldsResponse(dataset_id=dataset_id, fields=fields)


@router.get("/dataset-viewer/datasets/{dataset_id:path}", response_model=DatasetViewerResponse)
async def get_dataset_viewer(dataset_id: str):
    """Get dataset viewer metadata."""
    row, dataset_path = await _resolve_dataset_row_and_path(dataset_id)
    dataset_meta = _dataset_row_to_meta(row) if row else None
    if not dataset_path.exists():
        if not row:
            raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
        return DatasetViewerResponse(
            dataset_id=dataset_id,
            is_local=False,
            download_required=True,
            total_episodes=int((row or {}).get("episode_count") or 0),
            fps=0,
            use_videos=False,
            cameras=[],
            dataset_meta=dataset_meta,
        )

    try:
        metadata = LeRobotDatasetMetadata(dataset_id, root=dataset_path)
        return _build_dataset_viewer_response(dataset_id, metadata, dataset_meta=dataset_meta)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load dataset metadata: {exc}") from exc


@router.delete("/datasets/{dataset_id:path}", response_model=ArchiveResponse)
async def archive_dataset(dataset_id: str):
    """Archive (soft delete) a dataset."""
    require_user_id()
    status, changed = await set_dataset_status(dataset_id, status="archived")
    if not changed:
        return ArchiveResponse(id=dataset_id, success=True, message="Dataset already archived", status="archived")
    return ArchiveResponse(id=dataset_id, success=True, message="Dataset archived", status=status)


@router.post("/datasets/{dataset_id:path}/restore", response_model=ArchiveResponse)
async def restore_dataset(dataset_id: str):
    """Restore dataset from archive."""
    require_user_id()
    status, changed = await set_dataset_status(dataset_id, status="active")
    if not changed:
        return ArchiveResponse(id=dataset_id, success=True, message="Dataset already active", status="active")
    return ArchiveResponse(id=dataset_id, success=True, message="Dataset restored", status=status)


@router.post("/datasets/{dataset_id:path}/reupload", response_model=DatasetReuploadResponse)
async def reupload_dataset(dataset_id: str):
    dataset_id = dataset_id.strip()
    if not dataset_id:
        raise HTTPException(status_code=400, detail="Dataset ID is required")

    local_path = get_datasets_dir() / dataset_id
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"Local dataset not found: {dataset_id}")
    if not local_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Invalid dataset path: {dataset_id}")

    lifecycle = get_dataset_lifecycle()
    ok, error = await lifecycle.reupload(dataset_id)
    if not ok:
        raise HTTPException(status_code=500, detail=f"Dataset re-upload failed: {error}")

    return DatasetReuploadResponse(
        id=dataset_id,
        success=True,
        message="Dataset re-upload completed",
    )


@router.post("/bulk/datasets/archive", response_model=BulkActionResponse)
async def bulk_archive_datasets(request: BulkActionRequest):
    require_user_id()
    results: list[BulkActionResult] = []
    for dataset_id in request.ids:
        results.append(await archive_dataset_for_bulk(dataset_id))
    return _build_bulk_action_response(results, requested=len(request.ids))


@router.post("/bulk/datasets/reupload", response_model=BulkActionResponse)
async def bulk_reupload_datasets(request: BulkActionRequest):
    require_user_id()
    results: list[BulkActionResult] = []
    for dataset_id in request.ids:
        results.append(await reupload_dataset_for_bulk(dataset_id))
    return _build_bulk_action_response(results, requested=len(request.ids))


@router.post("/dataset-sync/jobs", response_model=DatasetSyncJobAcceptedResponse, status_code=202)
async def sync_dataset(request: DatasetSyncJobCreateRequest):
    """Start a background dataset sync job."""
    dataset_id = request.dataset_id.strip()
    if not dataset_id:
        raise HTTPException(status_code=400, detail="Dataset ID is required")
    user_id = require_user_id()
    auth_session = get_supabase_session()

    client = await get_supabase_async_client()
    rows = (
        await client.table("datasets").select("id,status").eq("id", dataset_id).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    if rows[0].get("status") != "active":
        raise HTTPException(status_code=400, detail="Dataset is not active")

    jobs = get_dataset_sync_jobs_service()
    accepted = jobs.create(user_id=user_id, dataset_id=dataset_id, auth_session=auth_session)
    jobs.ensure_worker()
    return accepted


@router.get("/dataset-sync/jobs", response_model=DatasetSyncJobListResponse)
async def list_dataset_sync_jobs(include_terminal: bool = Query(False, description="Include completed jobs")):
    user_id = require_user_id()
    jobs = get_dataset_sync_jobs_service()
    return jobs.list(user_id=user_id, include_terminal=include_terminal)


@router.get("/dataset-sync/jobs/{job_id}", response_model=DatasetSyncJobStatus)
async def get_dataset_sync_job(job_id: str):
    user_id = require_user_id()
    jobs = get_dataset_sync_jobs_service()
    return jobs.get(user_id=user_id, job_id=job_id)


@router.post("/dataset-sync/jobs/{job_id}/cancel", response_model=DatasetSyncJobCancelResponse)
async def cancel_dataset_sync_job(job_id: str):
    user_id = require_user_id()
    jobs = get_dataset_sync_jobs_service()
    return jobs.cancel(
        user_id=user_id,
        job_id=job_id,
    )


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    include_archived: bool = Query(False, description="Include archived models"),
    profile_name: Optional[str] = Query(None, description="Filter by profile name"),
    owner_user_id: Optional[str] = Query(None, description="Filter by owner user id"),
    status: Optional[str] = Query(None, description="Filter by model status"),
    policy_type: Optional[str] = Query(None, description="Filter by policy type"),
    dataset_id: Optional[str] = Query(None, description="Filter by source dataset id"),
    sync_status: Optional[str] = Query(None, description="Filter by sync status"),
    search: Optional[str] = Query(None, description="Search model name"),
    created_from: Optional[str] = Query(None, description="Filter by creation time lower bound"),
    created_to: Optional[str] = Query(None, description="Filter by creation time upper bound"),
    size_min: Optional[int] = Query(None, ge=0, description="Minimum size in bytes"),
    size_max: Optional[int] = Query(None, ge=0, description="Maximum size in bytes"),
    limit: Optional[int] = Query(None, ge=1, le=500, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    sort_by: ModelListSortBy = Query("created_at", description="Sort field"),
    sort_order: StorageSortOrder = Query("desc", description="Sort direction"),
):
    """List models from DB."""
    return await _list_models(
        ModelListQuery(
            include_archived=include_archived,
            profile_name=profile_name,
            owner_user_id=owner_user_id,
            status=status,
            policy_type=policy_type,
            dataset_id=dataset_id,
            sync_status=sync_status,
            search=search,
            created_from=created_from,
            created_to=created_to,
            size_min=size_min,
            size_max=size_max,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )


@router.get("/models/{model_id}", response_model=ModelInfo)
async def get_model(model_id: str):
    """Get model details from DB."""
    client = await get_supabase_async_client()
    return await _resolve_model_info(client, await _require_model_row(client, model_id))


@router.patch("/models/{model_id}", response_model=ModelInfo)
async def rename_model(model_id: str, request: StorageRenameRequest):
    """Rename model display name without changing model_id."""
    require_user_id()
    normalized_name = _validate_storage_name_or_raise(request.name)

    client = await get_supabase_async_client()
    await _require_model_row(client, model_id)
    await client.table("models").update({"name": normalized_name}).eq("id", model_id).execute()
    return await _resolve_model_info(client, await _require_model_row(client, model_id))


@router.post("/models/{model_id}/sync", response_model=ModelSyncJobAcceptedResponse, status_code=202)
async def sync_model(model_id: str):
    """Start a background model sync job."""
    model_id = model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="Model ID is required")
    user_id = require_user_id()
    auth_session = get_supabase_session()

    client = await get_supabase_async_client()
    rows = (
        await client.table("models").select("id,status").eq("id", model_id).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    if rows[0].get("status") != "active":
        raise HTTPException(status_code=400, detail="Model is not active")

    jobs = get_model_sync_jobs_service()
    accepted = jobs.create(user_id=user_id, model_id=model_id, auth_session=auth_session)
    jobs.ensure_worker()
    return accepted


@router.get("/model-sync/jobs", response_model=ModelSyncJobListResponse)
async def list_model_sync_jobs(include_terminal: bool = Query(False, description="Include completed jobs")):
    user_id = require_user_id()
    jobs = get_model_sync_jobs_service()
    return jobs.list(user_id=user_id, include_terminal=include_terminal)


@router.get("/model-sync/jobs/{job_id}", response_model=ModelSyncJobStatus)
async def get_model_sync_job(job_id: str):
    user_id = require_user_id()
    jobs = get_model_sync_jobs_service()
    return jobs.get(user_id=user_id, job_id=job_id)


@router.post("/model-sync/jobs/{job_id}/cancel", response_model=ModelSyncJobCancelResponse)
async def cancel_model_sync_job(job_id: str):
    user_id = require_user_id()
    jobs = get_model_sync_jobs_service()
    return jobs.cancel(
        user_id=user_id,
        job_id=job_id,
    )


@router.delete("/models/{model_id}", response_model=ArchiveResponse)
async def archive_model(model_id: str):
    """Archive (soft delete) a model."""
    client = await get_supabase_async_client()
    existing = (
        await client.table("models").select("id").eq("id", model_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    await client.table("models").update({"status": "archived"}).eq("id", model_id).execute()
    return ArchiveResponse(id=model_id, success=True, message="Model archived", status="archived")


@router.post("/bulk/models/sync", response_model=BulkActionResponse, status_code=202)
async def bulk_sync_models(request: BulkActionRequest):
    user_id = require_user_id()
    results: list[BulkActionResult] = []
    for model_id in request.ids:
        results.append(await sync_model_for_bulk(user_id=user_id, model_id=model_id))
    return _build_bulk_action_response(results, requested=len(request.ids))


@router.post("/bulk/models/archive", response_model=BulkActionResponse)
async def bulk_archive_models(request: BulkActionRequest):
    user_id = require_user_id()
    results: list[BulkActionResult] = []
    for model_id in request.ids:
        results.append(await archive_model_for_bulk(user_id=user_id, model_id=model_id))
    return _build_bulk_action_response(results, requested=len(request.ids))


@router.post("/models/{model_id}/restore", response_model=ArchiveResponse)
async def restore_model(model_id: str):
    """Restore model from archive."""
    client = await get_supabase_async_client()
    existing = (
        await client.table("models").select("id").eq("id", model_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    await client.table("models").update({"status": "active"}).eq("id", model_id).execute()
    return ArchiveResponse(id=model_id, success=True, message="Model restored", status="active")


@router.get("/usage", response_model=StorageUsageResponse)
async def get_storage_usage():
    """Get storage usage statistics from DB."""
    client = await get_supabase_async_client()
    datasets = (await client.table("datasets").select("size_bytes,status").execute()).data or []
    models = (await client.table("models").select("size_bytes,status").execute()).data or []

    datasets_size = sum(d.get("size_bytes") or 0 for d in datasets if d.get("status") == "active")
    models_size = sum(m.get("size_bytes") or 0 for m in models if m.get("status") == "active")
    archive_size = sum(d.get("size_bytes") or 0 for d in datasets if d.get("status") == "archived")
    archive_size += sum(m.get("size_bytes") or 0 for m in models if m.get("status") == "archived")

    return StorageUsageResponse(
        datasets_count=sum(1 for d in datasets if d.get("status") == "active"),
        datasets_size_bytes=datasets_size,
        models_count=sum(1 for m in models if m.get("status") == "active"),
        models_size_bytes=models_size,
        archive_count=sum(1 for d in datasets if d.get("status") == "archived")
        + sum(1 for m in models if m.get("status") == "archived"),
        archive_size_bytes=archive_size,
        total_size_bytes=datasets_size + models_size + archive_size,
    )


@router.get("/archive", response_model=ArchiveListResponse)
async def list_archived():
    """List archived datasets and models."""
    client = await get_supabase_async_client()
    datasets = (
        await client.table("datasets").select("*").eq("status", "archived").execute()
    ).data or []
    models = (
        await client.table("models").select("*").eq("status", "archived").execute()
    ).data or []
    dataset_infos = [_dataset_row_to_info(d) for d in datasets]
    model_infos = [_model_row_to_info(m) for m in models]
    return ArchiveListResponse(
        datasets=dataset_infos,
        models=model_infos,
        total=len(dataset_infos) + len(model_infos),
    )


@router.delete("/archive/datasets/{dataset_id:path}", response_model=ArchiveResponse)
async def delete_archived_dataset(dataset_id: str):
    """Permanently delete an archived dataset."""
    client = await get_supabase_async_client()
    existing = (
        await client.table("datasets").select("id,status").eq("id", dataset_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    if existing[0].get("status") != "archived":
        raise HTTPException(status_code=400, detail="Dataset is not archived")

    await _detach_dataset_references(client, dataset_id)
    sync_service = R2DBSyncService()
    sync_service.delete_dataset_remote(dataset_id)
    _delete_local_dataset(dataset_id)
    await client.table("datasets").delete().eq("id", dataset_id).execute()
    return ArchiveResponse(id=dataset_id, success=True, message="Dataset deleted", status="deleted")


@router.delete("/archive/models/{model_id}", response_model=ArchiveResponse)
async def delete_archived_model(model_id: str):
    """Permanently delete an archived model."""
    client = await get_supabase_async_client()
    existing = (
        await client.table("models").select("id,status").eq("id", model_id).execute()
    ).data or []
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    if existing[0].get("status") != "archived":
        raise HTTPException(status_code=400, detail="Model is not archived")

    sync_service = R2DBSyncService()
    sync_service.delete_model_remote(model_id)
    _delete_local_model(model_id)
    await client.table("training_jobs").update({"model_id": None}).eq("model_id", model_id).execute()
    await client.table("models").delete().eq("id", model_id).execute()
    return ArchiveResponse(id=model_id, success=True, message="Model deleted", status="deleted")


@router.post("/archive/restore", response_model=ArchiveBulkResponse)
async def restore_archived_items(request: ArchiveBulkRequest):
    """Bulk restore archived datasets/models."""
    client = await get_supabase_async_client()
    restored: list[str] = []
    errors: list[str] = []

    for dataset_id in request.dataset_ids:
        existing = (
            await client.table("datasets").select("id,status").eq("id", dataset_id).execute()
        ).data or []
        if not existing:
            errors.append(f"Dataset not found: {dataset_id}")
            continue
        await client.table("datasets").update({"status": "active"}).eq("id", dataset_id).execute()
        restored.append(dataset_id)

    for model_id in request.model_ids:
        existing = (
            await client.table("models").select("id,status").eq("id", model_id).execute()
        ).data or []
        if not existing:
            errors.append(f"Model not found: {model_id}")
            continue
        await client.table("models").update({"status": "active"}).eq("id", model_id).execute()
        restored.append(model_id)

    return ArchiveBulkResponse(
        success=len(errors) == 0,
        restored=restored,
        deleted=[],
        errors=errors,
    )


@router.post("/archive/delete", response_model=ArchiveBulkResponse)
async def delete_archived_items(request: ArchiveBulkRequest):
    """Bulk delete archived datasets/models."""
    client = await get_supabase_async_client()
    sync_service = R2DBSyncService()
    deleted: list[str] = []
    errors: list[str] = []

    for dataset_id in request.dataset_ids:
        existing = (
            await client.table("datasets").select("id,status").eq("id", dataset_id).execute()
        ).data or []
        if not existing:
            errors.append(f"Dataset not found: {dataset_id}")
            continue
        if existing[0].get("status") != "archived":
            errors.append(f"Dataset is not archived: {dataset_id}")
            continue
        await _detach_dataset_references(client, dataset_id)
        sync_service.delete_dataset_remote(dataset_id)
        _delete_local_dataset(dataset_id)
        await client.table("datasets").delete().eq("id", dataset_id).execute()
        deleted.append(dataset_id)

    for model_id in request.model_ids:
        existing = (
            await client.table("models").select("id,status").eq("id", model_id).execute()
        ).data or []
        if not existing:
            errors.append(f"Model not found: {model_id}")
            continue
        if existing[0].get("status") != "archived":
            errors.append(f"Model is not archived: {model_id}")
            continue
        sync_service.delete_model_remote(model_id)
        _delete_local_model(model_id)
        await client.table("training_jobs").update({"model_id": None}).eq("model_id", model_id).execute()
        await client.table("models").delete().eq("id", model_id).execute()
        deleted.append(model_id)

    return ArchiveBulkResponse(
        success=len(errors) == 0,
        restored=[],
        deleted=deleted,
        errors=errors,
    )


async def _upsert_dataset_from_hf(
    dataset_id: str,
    name: str,
    profile_snapshot: Optional[dict],
) -> None:
    payload = {
        "id": dataset_id,
        "name": name,
        "profile_name": extract_profile_name(profile_snapshot),
        "profile_snapshot": profile_snapshot,
        "dataset_type": "huggingface",
        "source": "huggingface",
        "status": "active",
    }
    await upsert_with_owner("datasets", "id", payload)


async def _upsert_model_from_hf(
    model_id: str,
    name: str,
    dataset_id: Optional[str],
    profile_snapshot: Optional[dict],
    policy_type: Optional[str],
) -> None:
    payload = {
        "id": model_id,
        "name": name,
        "dataset_id": dataset_id,
        "profile_name": extract_profile_name(profile_snapshot),
        "profile_snapshot": profile_snapshot,
        "policy_type": policy_type,
        "model_type": "huggingface",
        "source": "huggingface",
        "status": "active",
    }
    await upsert_with_owner("models", "id", payload)


def _report_upload_progress(
    message: dict,
    report: Optional[Callable[[dict], None]],
) -> None:
    if report is None:
        return
    msg_type = message.get("type")
    if not msg_type:
        return
    type_map = {
        "start": "upload_start",
        "uploading": "uploading",
        "progress": "upload_progress",
        "uploaded": "upload_file_complete",
        "complete": "upload_complete",
    }
    report({**message, "type": type_map.get(msg_type, msg_type), "step": "upload"})


async def _import_dataset_from_huggingface(
    request: HuggingFaceDatasetImportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    hf_token = _require_hf_token_for_current_user()
    dataset_id = request.dataset_id or generate_dataset_id()
    local_path = get_datasets_dir() / dataset_id
    if local_path.exists():
        if request.force:
            shutil.rmtree(local_path)
        else:
            raise HTTPException(status_code=409, detail=f"Dataset already exists: {dataset_id}")

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "hf_download",
            "message": f"Downloading {request.repo_id}",
        })
    local_path.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=request.repo_id,
        repo_type="dataset",
        local_dir=str(local_path),
        local_dir_use_symlinks=False,
        token=hf_token,
    )
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "hf_download",
            "message": "Download complete",
        })

    name = request.dataset_name or request.name or request.repo_id.split("/")[-1]
    profile_name = request.profile_name.strip() if request.profile_name else None
    profile_snapshot = resolve_profile_spec(profile_name).snapshot if profile_name else None
    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "db_upsert",
            "message": "Registering dataset",
        })
    await _upsert_dataset_from_hf(dataset_id, name, profile_snapshot)
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "db_upsert",
            "message": "Dataset registered",
        })

    sync_service = R2DBSyncService()
    ok, error = await sync_service.upload_dataset_with_progress(
        dataset_id,
        lambda message: _report_upload_progress(message, progress_callback),
    )
    if not ok:
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {error}")

    return HuggingFaceTransferResponse(
        success=True,
        message="Dataset imported from HuggingFace",
        item_id=dataset_id,
        repo_url=f"https://huggingface.co/datasets/{request.repo_id}",
    )


async def _import_model_from_huggingface(
    request: HuggingFaceModelImportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    hf_token = _require_hf_token_for_current_user()
    model_id = request.model_id or str(uuid.uuid4())
    local_path = get_models_dir() / model_id
    if local_path.exists():
        if request.force:
            shutil.rmtree(local_path)
        else:
            raise HTTPException(status_code=409, detail=f"Model already exists: {model_id}")

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "hf_download",
            "message": f"Downloading {request.repo_id}",
        })
    download_model(
        repo_id=request.repo_id,
        output_dir=local_path,
        force=request.force,
        token=hf_token,
    )
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "hf_download",
            "message": "Download complete",
        })
    local_info = get_local_model_info(local_path)
    policy_type = local_info.policy_type if local_info else None
    name = request.model_name or model_id
    profile_name = request.profile_name.strip() if request.profile_name else None
    profile_snapshot = resolve_profile_spec(profile_name).snapshot if profile_name else None

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "db_upsert",
            "message": "Registering model",
        })
    await _upsert_model_from_hf(
        model_id,
        name,
        request.dataset_id,
        profile_snapshot,
        policy_type,
    )
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "db_upsert",
            "message": "Model registered",
        })

    sync_service = R2DBSyncService()
    result = await sync_service.upload_model(model_id)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"R2 upload failed: {result.message}")

    return HuggingFaceTransferResponse(
        success=True,
        message="Model imported from HuggingFace",
        item_id=model_id,
        repo_url=f"https://huggingface.co/{request.repo_id}",
    )


async def _export_dataset_to_huggingface(
    dataset_id: str,
    request: HuggingFaceExportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    hf_token = _require_hf_token_for_current_user()
    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "ensure_local",
            "message": "Checking local dataset cache",
        })
    sync_service = R2DBSyncService()
    result = await sync_service.ensure_dataset_local(dataset_id, auto_download=True)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"Dataset download failed: {result.message}")
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "ensure_local",
            "message": result.message,
        })

    local_path = get_datasets_dir() / dataset_id
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "hf_upload",
            "message": f"Uploading to {request.repo_id}",
        })
    api = HfApi(token=hf_token)
    api.create_repo(
        repo_id=request.repo_id,
        repo_type="dataset",
        exist_ok=True,
        private=request.private,
    )
    commit_message = request.commit_message or f"Upload dataset: {dataset_id}"
    upload_folder(
        folder_path=str(local_path),
        repo_id=request.repo_id,
        repo_type="dataset",
        commit_message=commit_message,
        token=hf_token,
    )
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "hf_upload",
            "message": "Upload complete",
        })

    return HuggingFaceTransferResponse(
        success=True,
        message="Dataset exported to HuggingFace",
        item_id=dataset_id,
        repo_url=f"https://huggingface.co/datasets/{request.repo_id}",
    )


async def _export_model_to_huggingface(
    model_id: str,
    request: HuggingFaceExportRequest,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> HuggingFaceTransferResponse:
    hf_token = _require_hf_token_for_current_user()
    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "ensure_local",
            "message": "Checking local model cache",
        })
    sync_service = R2DBSyncService()
    result = await sync_service.ensure_model_local(model_id, auto_download=True)
    if not result.success:
        raise HTTPException(status_code=500, detail=f"Model download failed: {result.message}")
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "ensure_local",
            "message": result.message,
        })

    local_path = get_models_dir() / model_id
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

    if progress_callback:
        progress_callback({
            "type": "start",
            "step": "hf_upload",
            "message": f"Uploading to {request.repo_id}",
        })
    repo_url = upload_model(
        local_path=local_path,
        repo_id=request.repo_id,
        private=request.private,
        commit_message=request.commit_message,
        token=hf_token,
    )
    if progress_callback:
        progress_callback({
            "type": "step_complete",
            "step": "hf_upload",
            "message": "Upload complete",
        })

    return HuggingFaceTransferResponse(
        success=True,
        message="Model exported to HuggingFace",
        item_id=model_id,
        repo_url=repo_url,
    )


@router.post("/huggingface/datasets/import", response_model=HuggingFaceTransferResponse)
async def import_dataset_from_huggingface(request: HuggingFaceDatasetImportRequest):
    return await _import_dataset_from_huggingface(request)


@router.post("/huggingface/models/import", response_model=HuggingFaceTransferResponse)
async def import_model_from_huggingface(request: HuggingFaceModelImportRequest):
    return await _import_model_from_huggingface(request)


@router.post("/huggingface/datasets/{dataset_id:path}/export", response_model=HuggingFaceTransferResponse)
async def export_dataset_to_huggingface(dataset_id: str, request: HuggingFaceExportRequest):
    return await _export_dataset_to_huggingface(dataset_id, request)


@router.post("/huggingface/models/{model_id}/export", response_model=HuggingFaceTransferResponse)
async def export_model_to_huggingface(model_id: str, request: HuggingFaceExportRequest):
    return await _export_model_to_huggingface(model_id, request)

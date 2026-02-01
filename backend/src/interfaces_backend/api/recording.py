"""Recording API router (lerobot_recorder WebAPI bridge)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from percus_ai.db import get_current_user_id, get_supabase_client, upsert_with_owner
from percus_ai.profiles.models import ProfileInstance
from percus_ai.storage.naming import generate_dataset_id, validate_dataset_name
from percus_ai.storage.paths import get_datasets_dir, get_user_config_path
from percus_ai.storage.r2_db_sync import R2DBSyncService
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recording", tags=["recording"])

_RECORDER_URL = os.environ.get("LEROBOT_RECORDER_URL", "http://127.0.0.1:8082")
_sync_service: Optional[R2DBSyncService] = None


class RecordingSessionStartRequest(BaseModel):
    profile_instance_id: Optional[str] = Field(None, description="Profile instance ID")
    dataset_name: str = Field(..., description="Dataset display name")
    task: str = Field(..., description="Task description")
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RecordingSessionStopRequest(BaseModel):
    dataset_id: Optional[str] = Field(None, description="Dataset ID (UUID)")
    tags_append: List[str] = Field(default_factory=list)
    metadata_append: Dict[str, Any] = Field(default_factory=dict)


class RecordingSessionActionResponse(BaseModel):
    success: bool
    message: str
    dataset_id: Optional[str] = None
    status: Optional[Dict[str, Any]] = None


class RecordingSessionStatusResponse(BaseModel):
    dataset_id: Optional[str] = None
    status: Dict[str, Any]


class RecordingInfo(BaseModel):
    recording_id: str
    dataset_name: str
    profile_instance_id: Optional[str] = None
    created_at: Optional[str] = None
    episode_count: int = 0
    size_bytes: int = 0


class RecordingListResponse(BaseModel):
    recordings: List[RecordingInfo]
    total: int


class RecordingValidateResponse(BaseModel):
    recording_id: str
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _get_sync_service() -> R2DBSyncService:
    global _sync_service
    if _sync_service is None:
        _sync_service = R2DBSyncService()
    return _sync_service


def _load_user_config() -> dict:
    path = get_user_config_path()
    if not path.exists():
        return {"auto_upload_after_recording": True}
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    sync = raw.get("sync", {})
    return {
        "auto_upload_after_recording": sync.get("auto_upload_after_recording", True),
    }


def _call_recorder(path: str, payload: Optional[dict] = None) -> dict:
    url = f"{_RECORDER_URL}{path}"
    data = None
    headers = {}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=503, detail=f"Recorder unreachable: {exc}") from exc
    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {"raw": body}


def _row_to_profile_instance(row: dict) -> ProfileInstance:
    return ProfileInstance(
        id=row.get("id"),
        class_id=row.get("class_id"),
        class_version=row.get("class_version") or 1,
        name=row.get("name") or "active",
        variables=row.get("variables") or {},
        metadata=row.get("metadata") or {},
        thumbnail_key=row.get("thumbnail_key"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _resolve_profile_instance(profile_instance_id: Optional[str]) -> ProfileInstance:
    client = get_supabase_client()
    if profile_instance_id:
        rows = (
            client.table("profile_instances")
            .select("*")
            .eq("id", profile_instance_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    else:
        rows = (
            client.table("profile_instances")
            .select("*")
            .eq("is_active", True)
            .limit(1)
            .execute()
            .data
            or []
        )
    if not rows:
        raise HTTPException(status_code=404, detail="Profile instance not found")
    return _row_to_profile_instance(rows[0])


def _upsert_dataset_record(
    dataset_id: str,
    dataset_name: str,
    task: str,
    profile_instance: ProfileInstance,
    status: str,
) -> None:
    payload = {
        "id": dataset_id,
        "name": dataset_name,
        "dataset_type": "recorded",
        "source": "local",
        "status": status,
        "task_detail": task,
        "profile_instance_id": profile_instance.id,
        "profile_snapshot": profile_instance.snapshot(),
    }
    upsert_with_owner("datasets", "id", payload)


def _update_dataset_stats(dataset_id: str) -> None:
    dataset_root = get_datasets_dir() / dataset_id
    if not dataset_root.exists():
        return
    meta = LeRobotDatasetMetadata(dataset_id, root=dataset_root)
    size_bytes = sum(p.stat().st_size for p in dataset_root.rglob("*") if p.is_file())
    payload = {
        "id": dataset_id,
        "episode_count": meta.total_episodes,
        "size_bytes": size_bytes,
        "status": "active",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    upsert_with_owner("datasets", "id", payload)


@router.post("/session/start", response_model=RecordingSessionActionResponse)
async def start_session(request: RecordingSessionStartRequest):
    _require_user_id()

    is_valid, errors = validate_dataset_name(request.dataset_name)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid dataset name: {'; '.join(errors)}")

    dataset_id = generate_dataset_id()
    profile_instance = _resolve_profile_instance(request.profile_instance_id)

    payload = {
        "task": request.task,
        "dataset_name": dataset_id,
        "tags": request.tags,
        "metadata": request.metadata,
    }

    result = _call_recorder("/api/episode/start", payload)
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder start failed")

    _upsert_dataset_record(dataset_id, request.dataset_name, request.task, profile_instance, "recording")

    return RecordingSessionActionResponse(
        success=True,
        message="Recording session started",
        dataset_id=dataset_id,
        status=result,
    )


@router.post("/session/stop", response_model=RecordingSessionActionResponse)
async def stop_session(request: RecordingSessionStopRequest):
    _require_user_id()
    result = _call_recorder(
        "/api/episode/stop",
        {"tags_append": request.tags_append, "metadata_append": request.metadata_append},
    )
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder stop failed")

    dataset_id = request.dataset_id or result.get("dataset_name")
    if dataset_id:
        _update_dataset_stats(dataset_id)

        user_config = _load_user_config()
        if user_config.get("auto_upload_after_recording", True):
            try:
                sync_service = _get_sync_service()
                sync_service.upload_dataset_with_progress(dataset_id, None)
            except Exception as exc:
                logger.error("Auto-upload failed for %s: %s", dataset_id, exc)

    return RecordingSessionActionResponse(
        success=True,
        message="Recording session stopped",
        dataset_id=dataset_id,
        status=result,
    )


@router.post("/session/pause", response_model=RecordingSessionActionResponse)
async def pause_session():
    _require_user_id()
    result = _call_recorder("/api/episode/pause", {})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder pause failed")
    return RecordingSessionActionResponse(success=True, message="Recording paused", status=result)


@router.post("/session/resume", response_model=RecordingSessionActionResponse)
async def resume_session():
    _require_user_id()
    result = _call_recorder("/api/episode/resume", {})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder resume failed")
    return RecordingSessionActionResponse(success=True, message="Recording resumed", status=result)


@router.post("/session/cancel", response_model=RecordingSessionActionResponse)
async def cancel_session(dataset_id: Optional[str] = None):
    _require_user_id()
    result = _call_recorder("/api/episode/cancel", {})
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder cancel failed")

    if dataset_id:
        client = get_supabase_client()
        client.table("datasets").update({"status": "archived"}).eq("id", dataset_id).execute()

    return RecordingSessionActionResponse(success=True, message="Recording cancelled", dataset_id=dataset_id, status=result)


@router.get("/session/status", response_model=RecordingSessionStatusResponse)
async def get_session_status():
    _require_user_id()
    status = _call_recorder("/api/status")
    dataset_id = status.get("dataset_name")
    return RecordingSessionStatusResponse(dataset_id=dataset_id, status=status)


def _list_recordings() -> List[dict]:
    client = get_supabase_client()
    rows = (
        client.table("datasets")
        .select("id,name,profile_instance_id,episode_count,size_bytes,created_at,dataset_type,status")
        .eq("dataset_type", "recorded")
        .execute()
        .data
        or []
    )
    return [row for row in rows if row.get("status") != "archived"]


@router.get("/recordings", response_model=RecordingListResponse)
async def list_recordings():
    recordings_data = _list_recordings()
    recordings = [
        RecordingInfo(
            recording_id=r.get("id"),
            dataset_name=r.get("name"),
            profile_instance_id=r.get("profile_instance_id"),
            created_at=r.get("created_at"),
            episode_count=r.get("episode_count") or 0,
            size_bytes=r.get("size_bytes") or 0,
        )
        for r in recordings_data
        if r.get("id")
    ]
    return RecordingListResponse(recordings=recordings, total=len(recordings))


@router.get("/recordings/{recording_id:path}", response_model=RecordingInfo)
async def get_recording(recording_id: str):
    client = get_supabase_client()
    rows = (
        client.table("datasets")
        .select("id,name,profile_instance_id,episode_count,size_bytes,created_at")
        .eq("id", recording_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")
    row = rows[0]
    return RecordingInfo(
        recording_id=row.get("id"),
        dataset_name=row.get("name"),
        profile_instance_id=row.get("profile_instance_id"),
        created_at=row.get("created_at"),
        episode_count=row.get("episode_count") or 0,
        size_bytes=row.get("size_bytes") or 0,
    )


@router.get("/recordings/{recording_id:path}/validate", response_model=RecordingValidateResponse)
async def validate_recording(recording_id: str):
    recording_path = get_datasets_dir() / recording_id
    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")

    errors = []
    meta_file = recording_path / "meta" / "info.json"
    if not meta_file.exists():
        errors.append("meta/info.json missing")

    data_dir = recording_path / "data"
    if not data_dir.exists():
        errors.append("data directory missing")

    return RecordingValidateResponse(
        recording_id=recording_id,
        is_valid=len(errors) == 0,
        errors=errors,
    )


@router.delete("/recordings/{recording_id:path}")
async def delete_recording(recording_id: str):
    recording_path = get_datasets_dir() / recording_id
    if recording_path.exists():
        for _ in range(3):
            try:
                for child in recording_path.iterdir():
                    if child.is_dir():
                        for sub in child.rglob("*"):
                            if sub.is_file():
                                sub.unlink(missing_ok=True)
                        child.rmdir()
                    else:
                        child.unlink(missing_ok=True)
                recording_path.rmdir()
                break
            except Exception:
                continue
    client = get_supabase_client()
    client.table("datasets").delete().eq("id", recording_id).execute()
    return {"recording_id": recording_id, "message": "Recording deleted"}

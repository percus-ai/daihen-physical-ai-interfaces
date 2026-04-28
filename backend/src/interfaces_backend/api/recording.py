"""Recording API router (lerobot_session_recorder WebAPI bridge)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from interfaces_backend.services.recorder_bridge import get_recorder_bridge
from interfaces_backend.services.dataset_lifecycle import get_dataset_lifecycle
from interfaces_backend.services.inference_session import get_inference_session_manager
from interfaces_backend.services.recording_session import get_recording_session_manager
from interfaces_backend.services.session_manager import SessionProgressCallback, require_user_id
from interfaces_backend.services.storage_bulk_actions import (
    archive_dataset_for_bulk,
    reupload_dataset_for_bulk,
)
from interfaces_backend.services.startup_operations import get_startup_operations_service
from interfaces_backend.services.user_directory import resolve_user_directory_entries
from interfaces_backend.models.storage import BulkActionRequest, BulkActionResponse, BulkActionResult
from interfaces_backend.models.startup import StartupOperationAcceptedResponse
from interfaces_backend.models.realtime_payloads import RecordingUploadStatusResponse
from percus_ai.db import get_supabase_async_client
from percus_ai.storage.naming import validate_dataset_name
from percus_ai.storage.paths import get_datasets_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recording", tags=["recording"])
_RECORDING_MUTABLE_STATES = {"warming", "recording", "paused", "resetting", "resetting_paused"}


async def _emit_recording_control_event(
    *,
    action: str,
    phase: str,
    session_id: str | None = None,
    operation_id: str | None = None,
    success: bool | None = None,
    message: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    return None


def _recorder_error_detail(result: dict[str, Any], fallback: str) -> str:
    detail = result.get("error") or result.get("message")
    if isinstance(detail, str):
        detail = detail.strip()
        if detail:
            return detail
    return fallback


def _ensure_recorder_not_reserved_by_inference() -> None:
    status = get_inference_session_manager().get_active_recording_status()
    if (
        bool(status.get("recording_prepared"))
        or bool(status.get("recording_active"))
        or bool(str(status.get("recording_dataset_id") or "").strip())
    ):
        raise HTTPException(
            status_code=409,
            detail="Recorder is reserved by an active inference session",
        )


def _reject_inference_owned_recorder(status: dict[str, Any]) -> None:
    if str(status.get("session_kind") or "").strip() != "inference":
        return
    raise HTTPException(
        status_code=409,
        detail="Recorder is controlled by an active inference session",
    )


# -- Request / Response models ------------------------------------------------


class RecordingSessionCreateRequest(BaseModel):
    dataset_name: str = Field(..., description="Dataset display name")
    task: str = Field(..., description="Task description")
    profile: Optional[str] = Field(None, description="Optional VLAbor profile name")
    num_episodes: int = Field(1, ge=1, description="Number of episodes")
    episode_time_s: float = Field(60.0, gt=0, description="Episode length in seconds")
    reset_time_s: float = Field(10.0, ge=0, description="Reset wait time in seconds")
    continue_from_dataset_id: Optional[str] = Field(
        None,
        description="Continue recording from an existing dataset ID",
    )


class RecordingSessionStartRequest(BaseModel):
    dataset_id: str = Field(..., description="Dataset ID (UUID)")


class RecordingSessionStopRequest(BaseModel):
    dataset_id: Optional[str] = Field(None, description="Dataset ID (UUID)")
    save_current: bool = Field(True, description="Save current episode before stopping")


class RecordingSessionActionResponse(BaseModel):
    success: bool
    message: str
    dataset_id: Optional[str] = None
    status: Optional[Dict[str, Any]] = None


class RecordingSessionStatusResponse(BaseModel):
    dataset_id: Optional[str] = None
    status: Dict[str, Any]


class RecordingSessionUpdateRequest(BaseModel):
    dataset_id: Optional[str] = None
    task: Optional[str] = None
    episode_time_s: Optional[float] = Field(None, gt=0)
    reset_time_s: Optional[float] = Field(None, ge=0)
    num_episodes: Optional[int] = Field(None, ge=1)


class RecordingInfo(BaseModel):
    recording_id: str
    dataset_name: str
    task: str = ""
    profile_name: Optional[str] = None
    owner_user_id: Optional[str] = None
    owner_email: Optional[str] = None
    owner_name: Optional[str] = None
    created_at: Optional[str] = None
    episode_count: int = 0
    target_total_episodes: int = 0
    remaining_episodes: int = 0
    episode_time_s: float = 0.0
    reset_time_s: float = 0.0
    continuable: bool = False
    continue_block_reason: Optional[str] = None
    size_bytes: int = 0
    is_local: bool = False
    is_uploaded: bool = False


class RecordingListResponse(BaseModel):
    recordings: List[RecordingInfo]
    total: int
    owner_options: List["RecordingOwnerFilterOption"] = Field(default_factory=list)
    profile_options: List["RecordingValueFilterOption"] = Field(default_factory=list)
    upload_status_options: List["RecordingValueFilterOption"] = Field(default_factory=list)


class RecordingOwnerFilterOption(BaseModel):
    user_id: str
    label: str
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None
    total_count: int = 0
    available_count: int = 0


class RecordingValueFilterOption(BaseModel):
    value: str
    label: str
    total_count: int = 0
    available_count: int = 0


class RecordingValidateResponse(BaseModel):
    recording_id: str
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []


class RecordingContinuePlanResponse(BaseModel):
    recording_id: str
    dataset_name: str
    task: str
    profile_name: Optional[str] = None
    episode_count: int = 0
    target_total_episodes: int = 0
    remaining_episodes: int = 0
    episode_time_s: float = 0.0
    reset_time_s: float = 0.0
    continuable: bool = False
    reason: Optional[str] = None


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


# -- helpers ------------------------------------------------------------------


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_query_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _parse_filter_datetime(value: str | None) -> datetime | None:
    normalized = _normalize_optional_text(value)
    if not normalized:
        return None
    try:
        if len(normalized) == 10:
            return datetime.fromisoformat(f"{normalized}T00:00:00+00:00")
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalize_datetime_filter_start(value: str | None) -> str | None:
    parsed = _parse_filter_datetime(value)
    return parsed.isoformat() if parsed else None


def _normalize_datetime_filter_end(value: str | None) -> str | None:
    parsed = _parse_filter_datetime(value)
    if parsed is None:
        return None
    if len(str(value or "").strip()) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed.isoformat()


def _matches_datetime_range(value: Any, start: datetime | None, end: datetime | None) -> bool:
    if start is None and end is None:
        return True
    normalized = _normalize_optional_text(value)
    if not normalized:
        return False
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    if start and parsed < start:
        return False
    if end and parsed > end:
        return False
    return True


def _matches_int_range(value: Any, minimum: int | None, maximum: int | None) -> bool:
    if minimum is None and maximum is None:
        return True
    parsed = _to_int(value, default=0)
    if minimum is not None and parsed < minimum:
        return False
    if maximum is not None and parsed > maximum:
        return False
    return True


def _normalize_upload_filter_value(status_snapshot: dict[str, Any], is_uploaded: bool) -> str:
    normalized_status = _normalize_query_text(status_snapshot.get("status"))
    if normalized_status == "running":
        return "running"
    if normalized_status == "failed":
        return "failed"
    return "uploaded" if is_uploaded else "idle"


def _upload_filter_label(value: str) -> str:
    return {
        "running": "送信中",
        "failed": "失敗",
        "uploaded": "送信済",
        "idle": "未送信",
    }.get(value, value)


def _build_recording_value_filter_options(
    all_records: list[dict],
    available_records: list[dict],
    *,
    value_getter,
    label_getter=None,
) -> list[RecordingValueFilterOption]:
    total_counts: dict[str, int] = {}
    available_counts: dict[str, int] = {}

    for record in all_records:
        value = _normalize_optional_text(value_getter(record))
        if not value:
            continue
        total_counts[value] = total_counts.get(value, 0) + 1

    for record in available_records:
        value = _normalize_optional_text(value_getter(record))
        if not value:
            continue
        available_counts[value] = available_counts.get(value, 0) + 1

    options = [
        RecordingValueFilterOption(
            value=value,
            label=label_getter(value) if label_getter else value,
            total_count=total_count,
            available_count=available_counts.get(value, 0),
        )
        for value, total_count in total_counts.items()
    ]
    options.sort(key=lambda option: (option.label.lower(), option.value))
    return options


def _build_continue_plan_from_row(row: dict) -> RecordingContinuePlanResponse:
    recording_id = str(row.get("id") or "").strip()
    dataset_name = str(row.get("name") or "").strip()
    task = str(row.get("task_detail") or "").strip()
    profile_name = str(row.get("profile_name") or "").strip() or None
    episode_count = max(_to_int(row.get("episode_count"), default=0), 0)
    target_total_episodes = max(_to_int(row.get("target_total_episodes"), default=0), 0)
    episode_time_s = _to_float(row.get("episode_time_s"), default=0.0)
    reset_time_s = _to_float(row.get("reset_time_s"), default=0.0)
    remaining_episodes = max(target_total_episodes - episode_count, 0)

    continuable = True
    reason: str | None = None

    if str(row.get("dataset_type") or "") != "recorded":
        continuable = False
        reason = "recorded データセットのみ継続できます"
    elif str(row.get("status") or "").lower() == "archived":
        continuable = False
        reason = "アーカイブ済みデータセットです"
    elif target_total_episodes <= 0:
        continuable = False
        reason = "目標エピソード総数が設定されていません"
    elif remaining_episodes <= 0:
        continuable = False
        reason = "残りエピソードがありません"
    elif episode_time_s <= 0:
        continuable = False
        reason = "エピソード秒数が設定されていません"
    elif reset_time_s < 0:
        continuable = False
        reason = "リセット待機秒数の設定が不正です"
    elif not (get_datasets_dir() / recording_id).exists():
        continuable = False
        reason = "ローカルデータセットが見つかりません"

    return RecordingContinuePlanResponse(
        recording_id=recording_id,
        dataset_name=dataset_name,
        task=task,
        profile_name=profile_name,
        episode_count=episode_count,
        target_total_episodes=target_total_episodes,
        remaining_episodes=remaining_episodes,
        episode_time_s=episode_time_s,
        reset_time_s=reset_time_s,
        continuable=continuable,
        reason=reason,
    )


async def _fetch_recording_row(recording_id: str) -> dict:
    client = await get_supabase_async_client()
    rows = (
        await client.table("datasets")
        .select(
            "id,name,task_detail,profile_name,episode_count,target_total_episodes,episode_time_s,reset_time_s,size_bytes,created_at,dataset_type,status,content_hash"
        )
        .eq("id", recording_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")
    return rows[0]


def _build_recording_session_snapshot(
    *,
    session_id: str,
    active_dataset_id: str,
    session_state: Any | None,
    recording_row: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "state": "inactive",
        "dataset_id": session_id,
        "active_dataset_id": active_dataset_id or None,
    }

    if recording_row is not None:
        plan = _build_continue_plan_from_row(recording_row)
        snapshot.update(
            {
                "task": plan.task,
                "episode_count": plan.episode_count,
                "num_episodes": plan.target_total_episodes,
                "episode_time_s": plan.episode_time_s,
                "reset_time_s": plan.reset_time_s,
            }
        )

    if session_state is None:
        return snapshot

    recorder_payload = session_state.extras.get("recorder_payload")
    if not isinstance(recorder_payload, dict):
        recorder_payload = {}
    metadata = recorder_payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    episode_count = snapshot.get("episode_count")
    target_total_episodes = session_state.extras.get("target_total_episodes")
    if target_total_episodes is None:
        target_total_episodes = metadata.get("target_total_episodes")
    if target_total_episodes is None:
        recorder_num_episodes = recorder_payload.get("num_episodes")
        if recording_row is not None:
            target_total_episodes = _to_int(recorder_num_episodes, default=0) + _to_int(episode_count, default=0)
        else:
            target_total_episodes = recorder_num_episodes

    snapshot.update(
        {
            "state": str(session_state.status or snapshot["state"]).strip() or snapshot["state"],
            "task": str(
                session_state.extras.get("task")
                or recorder_payload.get("task")
                or snapshot.get("task")
                or ""
            ).strip(),
            "episode_count": _to_int(episode_count, default=0),
            "num_episodes": max(_to_int(target_total_episodes, default=0), 0),
            "episode_time_s": _to_float(
                recorder_payload.get("episode_time_s", metadata.get("episode_time_s", snapshot.get("episode_time_s"))),
                default=0.0,
            ),
            "reset_time_s": _to_float(
                recorder_payload.get("reset_time_s", metadata.get("reset_time_s", snapshot.get("reset_time_s"))),
                default=0.0,
            ),
        }
    )
    return snapshot


def _apply_recording_session_updates(
    *,
    session_state: Any | None,
    payload: dict[str, Any],
    recording_row: dict[str, Any] | None,
) -> None:
    if session_state is None:
        return

    recorder_payload = session_state.extras.get("recorder_payload")
    if not isinstance(recorder_payload, dict):
        recorder_payload = {}
        session_state.extras["recorder_payload"] = recorder_payload

    metadata = recorder_payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        recorder_payload["metadata"] = metadata

    if "task" in payload:
        session_state.extras["task"] = payload["task"]
        recorder_payload["task"] = payload["task"]

    if "episode_time_s" in payload:
        recorder_payload["episode_time_s"] = payload["episode_time_s"]
        metadata["episode_time_s"] = payload["episode_time_s"]

    if "reset_time_s" in payload:
        recorder_payload["reset_time_s"] = payload["reset_time_s"]
        metadata["reset_time_s"] = payload["reset_time_s"]

    if "num_episodes" in payload:
        target_total_episodes = int(payload["num_episodes"])
        recorded_episode_count = _to_int((recording_row or {}).get("episode_count"), default=0)
        remaining_episodes = max(target_total_episodes - recorded_episode_count, 0)
        session_state.extras["target_total_episodes"] = target_total_episodes
        recorder_payload["num_episodes"] = remaining_episodes if recording_row is not None else target_total_episodes
        metadata["num_episodes"] = recorder_payload["num_episodes"]
        metadata["target_total_episodes"] = target_total_episodes


# -- Session endpoints --------------------------------------------------------


async def _run_recording_create_operation(
    operation_id: str,
    request: RecordingSessionCreateRequest,
) -> None:
    operations = get_startup_operations_service()
    progress_callback = operations.build_progress_callback(operation_id)
    manager = get_recording_session_manager()
    try:
        if request.continue_from_dataset_id:
            state = await _create_continue_session(
                manager=manager,
                recording_id=request.continue_from_dataset_id,
                episode_time_s=request.episode_time_s,
                reset_time_s=request.reset_time_s,
                progress_callback=progress_callback,
            )
        else:
            state = await manager.create(
                profile=request.profile,
                dataset_name=request.dataset_name,
                task=request.task,
                num_episodes=request.num_episodes,
                target_total_episodes=request.num_episodes,
                episode_time_s=request.episode_time_s,
                reset_time_s=request.reset_time_s,
                progress_callback=progress_callback,
            )
        operations.complete(
            operation_id=operation_id,
            target_session_id=state.id,
            message="録画セッションの準備が完了しました。",
        )
    except HTTPException as exc:
        operations.fail(
            operation_id=operation_id,
            message="録画セッションの準備に失敗しました。",
            error=str(exc.detail),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to UI
        logger.exception("recording startup operation failed: %s", operation_id)
        operations.fail(
            operation_id=operation_id,
            message="録画セッションの準備に失敗しました。",
            error=str(exc),
        )


async def _create_continue_session(
    *,
    manager,
    recording_id: str,
    episode_time_s: float | None = None,
    reset_time_s: float | None = None,
    progress_callback: SessionProgressCallback,
):
    row = await _fetch_recording_row(recording_id)
    plan = _build_continue_plan_from_row(row)
    if not plan.continuable:
        raise HTTPException(status_code=400, detail=plan.reason or "Recording cannot continue")
    return await manager.create(
        session_id=plan.recording_id,
        profile=plan.profile_name,
        dataset_name=plan.dataset_name,
        task=plan.task,
        num_episodes=plan.remaining_episodes,
        target_total_episodes=plan.target_total_episodes,
        episode_time_s=plan.episode_time_s if episode_time_s is None else episode_time_s,
        reset_time_s=plan.reset_time_s if reset_time_s is None else reset_time_s,
        progress_callback=progress_callback,
    )


@router.post(
    "/session/create",
    response_model=StartupOperationAcceptedResponse,
    status_code=202,
)
async def create_session(request: RecordingSessionCreateRequest):
    user_id = require_user_id()
    _ensure_recorder_not_reserved_by_inference()

    if request.continue_from_dataset_id:
        row = await _fetch_recording_row(request.continue_from_dataset_id)
        plan = _build_continue_plan_from_row(row)
        if not plan.continuable:
            raise HTTPException(status_code=400, detail=plan.reason or "Recording cannot continue")
    else:
        is_valid, errors = validate_dataset_name(request.dataset_name)
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Invalid dataset name: {'; '.join(errors)}")
    operation = get_startup_operations_service().create(
        user_id=user_id,
        kind="recording_create",
    )
    asyncio.create_task(_run_recording_create_operation(operation.operation_id, request))
    await _emit_recording_control_event(
        action="session_create",
        phase="accepted",
        session_id=request.continue_from_dataset_id or "global",
        operation_id=operation.operation_id,
        success=True,
        message="Recording session create operation accepted.",
        details={
            "dataset_name": request.dataset_name,
            "continue_from_dataset_id": request.continue_from_dataset_id,
        },
    )
    return operation


@router.post("/session/start", response_model=RecordingSessionActionResponse)
async def start_session(request: RecordingSessionStartRequest):
    require_user_id()
    _ensure_recorder_not_reserved_by_inference()
    mgr = get_recording_session_manager()
    if mgr.status(request.dataset_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Recording session is not prepared: {request.dataset_id}",
        )

    state = await mgr.start(request.dataset_id)
    response = RecordingSessionActionResponse(
        success=True,
        message="Recording session started",
        dataset_id=state.id,
        status=state.extras.get("recorder_result"),
    )
    await _emit_recording_control_event(
        action="session_start",
        phase="completed",
        session_id=state.id,
        success=True,
        message=response.message,
    )
    return response


@router.post("/session/stop", response_model=RecordingSessionActionResponse)
async def stop_session(request: RecordingSessionStopRequest):
    require_user_id()
    mgr = get_recording_session_manager()

    dataset_id = request.dataset_id
    if not dataset_id:
        active = mgr.any_active()
        if active:
            dataset_id = active.id
        else:
            raise HTTPException(status_code=404, detail="Session not found")
    elif mgr.status(dataset_id) is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {dataset_id}")

    recorder_status = get_recorder_bridge().status()
    _reject_inference_owned_recorder(recorder_status)
    state = await mgr.stop(dataset_id, save_current=request.save_current, recorder_status=recorder_status)
    response = RecordingSessionActionResponse(
        success=True,
        message="Recording session stopped",
        dataset_id=state.id,
        status=state.extras.get("recorder_result"),
    )
    await _emit_recording_control_event(
        action="session_stop",
        phase="completed",
        session_id=state.id,
        success=True,
        message=response.message,
        details={"save_current": request.save_current},
    )
    return response


@router.post("/session/pause", response_model=RecordingSessionActionResponse)
async def pause_session():
    require_user_id()
    recorder = get_recorder_bridge()
    _reject_inference_owned_recorder(recorder.status())
    result = recorder.pause()
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder pause failed")
    dataset_id = str(result.get("dataset_id") or "").strip() or "global"
    response = RecordingSessionActionResponse(success=True, message="Recording paused", status=result)
    await _emit_recording_control_event(
        action="session_pause",
        phase="completed",
        session_id=dataset_id,
        success=True,
        message=response.message,
    )
    return response


@router.post("/session/resume", response_model=RecordingSessionActionResponse)
async def resume_session():
    require_user_id()
    recorder = get_recorder_bridge()
    _reject_inference_owned_recorder(recorder.status())
    result = recorder.resume()
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder resume failed")
    dataset_id = str(result.get("dataset_id") or "").strip() or "global"
    response = RecordingSessionActionResponse(success=True, message="Recording resumed", status=result)
    await _emit_recording_control_event(
        action="session_resume",
        phase="completed",
        session_id=dataset_id,
        success=True,
        message=response.message,
    )
    return response


@router.post("/session/update", response_model=RecordingSessionActionResponse)
async def update_session(request: RecordingSessionUpdateRequest):
    require_user_id()
    payload: dict[str, Any] = {}
    target_dataset_id = (request.dataset_id or "").strip()
    if request.dataset_id is not None and not target_dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id must not be empty")
    if request.task is not None:
        task = request.task.strip()
        if not task:
            raise HTTPException(status_code=400, detail="task must not be empty")
        payload["task"] = task
    if request.episode_time_s is not None:
        payload["episode_time_s"] = float(request.episode_time_s)
    if request.reset_time_s is not None:
        payload["reset_time_s"] = float(request.reset_time_s)
    if request.num_episodes is not None:
        payload["num_episodes"] = int(request.num_episodes)
    if not payload:
        raise HTTPException(status_code=400, detail="No update fields provided")

    recorder = get_recorder_bridge()
    manager = get_recording_session_manager()
    recording_row: dict[str, Any] | None = None
    active_dataset_id = ""
    active_state = ""
    result: dict[str, Any] = {}

    if target_dataset_id:
        recording_row = await _fetch_recording_row(target_dataset_id)
        status = recorder.status()
        _reject_inference_owned_recorder(status)
        active_dataset_id = str(status.get("dataset_id") or "").strip()
        active_state = str(status.get("state") or "").strip().lower()
        is_active_target = active_dataset_id == target_dataset_id and active_state in _RECORDING_MUTABLE_STATES
        is_active_other = active_dataset_id != target_dataset_id and active_state in _RECORDING_MUTABLE_STATES
        if is_active_other:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Requested dataset is not the active recording session "
                    f"(requested={target_dataset_id}, active={active_dataset_id or 'none'})"
                ),
            )
        if is_active_target:
            result = recorder.update(payload)
            if not result.get("success", False):
                raise HTTPException(
                    status_code=500,
                    detail=result.get("error") or result.get("message") or "Recorder update failed",
                )
        else:
            result = {
                "success": True,
                "message": "Recording session settings updated",
                "dataset_id": target_dataset_id,
            }
    else:
        status = recorder.status()
        _reject_inference_owned_recorder(status)
        result = recorder.update(payload)
        if not result.get("success", False):
            raise HTTPException(
                status_code=500,
                detail=result.get("error") or result.get("message") or "Recorder update failed",
            )
        active_dataset_id = str(result.get("dataset_id") or "").strip()

    dataset_id = str(result.get("dataset_id") or target_dataset_id or active_dataset_id).strip() or None
    if dataset_id:
        session_state = manager.status(dataset_id)
        if recording_row is None:
            try:
                recording_row = await _fetch_recording_row(dataset_id)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                recording_row = None
        _apply_recording_session_updates(session_state=session_state, payload=payload, recording_row=recording_row)
        db_updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if "task" in payload:
            db_updates["task_detail"] = payload["task"]
        if "episode_time_s" in payload:
            db_updates["episode_time_s"] = payload["episode_time_s"]
        if "reset_time_s" in payload:
            db_updates["reset_time_s"] = payload["reset_time_s"]
        if "num_episodes" in payload:
            db_updates["target_total_episodes"] = payload["num_episodes"]
        try:
            client = await get_supabase_async_client()
            await client.table("datasets").update(db_updates).eq("id", dataset_id).execute()
        except Exception as exc:
            logger.warning("Failed to persist recording settings update: %s", exc)
        if not result.get("status") and target_dataset_id:
            next_row = dict(recording_row or {})
            if "task_detail" in db_updates:
                next_row["task_detail"] = db_updates["task_detail"]
            if "episode_time_s" in db_updates:
                next_row["episode_time_s"] = db_updates["episode_time_s"]
            if "reset_time_s" in db_updates:
                next_row["reset_time_s"] = db_updates["reset_time_s"]
            if "target_total_episodes" in db_updates:
                next_row["target_total_episodes"] = db_updates["target_total_episodes"]
            result["status"] = _build_recording_session_snapshot(
                session_id=dataset_id,
                active_dataset_id=active_dataset_id,
                session_state=session_state,
                recording_row=next_row or None,
            )

    response = RecordingSessionActionResponse(
        success=True,
        message=str(result.get("message") or "Recording session updated"),
        dataset_id=dataset_id,
        status=result.get("status") if isinstance(result.get("status"), dict) else result,
    )
    await _emit_recording_control_event(
        action="session_update",
        phase="completed",
        session_id=dataset_id or "global",
        success=True,
        message=response.message,
        details=payload,
    )
    return response


@router.post("/episode/retake-previous", response_model=RecordingSessionActionResponse)
async def retake_previous_episode():
    require_user_id()
    recorder = get_recorder_bridge()
    status = recorder.status()
    _reject_inference_owned_recorder(status)
    dataset_id = status.get("dataset_id")
    if not dataset_id:
        raise HTTPException(status_code=400, detail="No active session")

    result = recorder.retake_previous_episode()
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=_recorder_error_detail(result, "Recorder retake failed"))

    response = RecordingSessionActionResponse(
        success=True,
        message="Previous episode will be re-recorded",
        dataset_id=dataset_id,
        status=result,
    )
    await _emit_recording_control_event(
        action="episode_retake_previous",
        phase="completed",
        session_id=str(dataset_id or "").strip() or "global",
        success=True,
        message=response.message,
    )
    return response


@router.post("/episode/cancel", response_model=RecordingSessionActionResponse)
async def cancel_episode():
    require_user_id()
    recorder = get_recorder_bridge()
    _reject_inference_owned_recorder(recorder.status())
    result = recorder.cancel_episode()
    if not result.get("success", False):
        raise HTTPException(status_code=500, detail=result.get("error") or "Recorder episode cancel failed")
    dataset_id = str(result.get("dataset_id") or "").strip() or "global"
    response = RecordingSessionActionResponse(success=True, message="Episode cancelled", status=result)
    await _emit_recording_control_event(
        action="episode_cancel",
        phase="completed",
        session_id=dataset_id,
        success=True,
        message=response.message,
    )
    return response


@router.post(
    "/episode/next",
    response_model=RecordingSessionActionResponse,
    status_code=202,
)
async def next_episode():
    require_user_id()
    recorder = get_recorder_bridge()
    _reject_inference_owned_recorder(recorder.status())
    result = recorder.next_episode()
    if not result.get("success", False):
        raise HTTPException(
            status_code=500,
            detail=result.get("error") or "Recorder next episode failed",
        )
    response = RecordingSessionActionResponse(
        success=True,
        message=str(result.get("message") or "Episode transition accepted"),
        dataset_id=result.get("dataset_id"),
        status=result,
    )
    await _emit_recording_control_event(
        action="episode_next",
        phase="completed",
        session_id=str(result.get("dataset_id") or "").strip() or "global",
        success=True,
        message=response.message,
    )
    return response


@router.post("/session/cancel", response_model=RecordingSessionActionResponse)
async def cancel_session(dataset_id: Optional[str] = None):
    require_user_id()
    mgr = get_recording_session_manager()
    recorder = get_recorder_bridge()
    _reject_inference_owned_recorder(recorder.status())
    result: dict = {}

    if dataset_id:
        session = mgr.status(dataset_id)
        if session:
            state = await mgr.stop(dataset_id, save_current=False, cancel=True)
            result = state.extras.get("recorder_result", {})
        else:
            # Not tracked — check recorder directly
            try:
                rec_status = recorder.status()
                active_id = rec_status.get("dataset_id")
                active_state = rec_status.get("state")
                if active_id == dataset_id and active_state not in ("idle", "completed"):
                    result = recorder.stop(save_current=False)
                    if not result.get("success", False):
                        raise HTTPException(
                            status_code=500, detail=result.get("error") or "Recorder cancel failed"
                        )
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
        client = await get_supabase_async_client()
        await client.table("datasets").update({"status": "archived"}).eq("id", dataset_id).execute()
    else:
        result = recorder.stop(save_current=False)
        if not result.get("success", False):
            raise HTTPException(status_code=500, detail=result.get("error") or "Recorder cancel failed")

    response = RecordingSessionActionResponse(
        success=True,
        message="Recording cancelled",
        dataset_id=dataset_id,
        status=result,
    )
    await _emit_recording_control_event(
        action="session_cancel",
        phase="completed",
        session_id=(dataset_id or "").strip() or "global",
        success=True,
        message=response.message,
    )
    return response


@router.get("/sessions/{session_id}/status", response_model=RecordingSessionStatusResponse)
async def get_session_status(session_id: str):
    require_user_id()
    recorder = get_recorder_bridge()
    manager = get_recording_session_manager()
    status = recorder.status()
    active_id = str(status.get("dataset_id") or "").strip()
    session_state = manager.status(session_id)
    recording_row: dict[str, Any] | None = None
    try:
        recording_row = await _fetch_recording_row(session_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    snapshot = _build_recording_session_snapshot(
        session_id=session_id,
        active_dataset_id=active_id,
        session_state=session_state,
        recording_row=recording_row,
    )
    if active_id and active_id == session_id:
        return RecordingSessionStatusResponse(dataset_id=active_id, status={**snapshot, **status})
    return RecordingSessionStatusResponse(dataset_id=session_id, status=snapshot)


@router.get(
    "/sessions/{session_id}/upload-status",
    response_model=RecordingUploadStatusResponse,
)
async def get_session_upload_status(session_id: str):
    require_user_id()
    lifecycle = get_dataset_lifecycle()
    status = lifecycle.get_dataset_upload_status(session_id)
    return RecordingUploadStatusResponse(**status)


# -- Recording management endpoints (DB / filesystem) ------------------------


RecordingListSortBy = Literal["created_at", "dataset_name", "owner_name", "profile_name", "episode_count", "size_bytes", "upload_status"]
SortOrder = Literal["asc", "desc"]

_RECORDING_LIST_COLUMNS = (
    "id,name,task_detail,profile_name,episode_count,target_total_episodes,"
    "episode_time_s,reset_time_s,size_bytes,created_at,dataset_type,status,"
    "owner_user_id,content_hash"
)
_RECORDING_FILTER_OPTION_COLUMNS = (
    "id,name,profile_name,episode_count,size_bytes,created_at,dataset_type,"
    "status,owner_user_id,content_hash"
)
_RECORDING_DB_SORT_COLUMNS: dict[str, str] = {
    "created_at": "created_at",
    "dataset_name": "name",
    "profile_name": "profile_name",
    "episode_count": "episode_count",
    "size_bytes": "size_bytes",
}
_RECORDING_UPLOAD_STATUS_SORT_RANK = {
    "idle": 0,
    "uploaded": 1,
    "running": 2,
    "failed": 3,
}
_UNBOUNDED_RECORDING_RANGE_END = 1_000_000_000


def _build_recording_owner_filter_options(
    all_rows: list[dict[str, Any]],
    available_rows: list[dict[str, Any]],
    owner_directory,
) -> list[RecordingOwnerFilterOption]:
    total_counts: dict[str, int] = {}
    available_counts: dict[str, int] = {}

    for row in all_rows:
        owner_id = str(row.get("owner_user_id") or "").strip()
        if not owner_id:
            continue
        total_counts[owner_id] = total_counts.get(owner_id, 0) + 1

    for row in available_rows:
        owner_id = str(row.get("owner_user_id") or "").strip()
        if not owner_id:
            continue
        available_counts[owner_id] = available_counts.get(owner_id, 0) + 1

    options: list[RecordingOwnerFilterOption] = []
    for owner_id, total_count in total_counts.items():
        owner_entry = owner_directory.get(owner_id)
        label = ((owner_entry.name or "").strip() if owner_entry else "") or ((owner_entry.email or "").strip() if owner_entry else "") or owner_id
        options.append(
            RecordingOwnerFilterOption(
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


def _apply_recording_base_filters(query):
    return query.eq("dataset_type", "recorded").neq("status", "archived")


def _apply_recording_db_filters(
    query,
    *,
    owner_user_id: str | None = None,
    profile_name: str | None = None,
    search: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    episode_count_min: int | None = None,
    episode_count_max: int | None = None,
):
    query = _apply_recording_base_filters(query)
    normalized_owner_user_id = _normalize_optional_text(owner_user_id)
    normalized_profile_name = _normalize_optional_text(profile_name)
    normalized_search = _normalize_optional_text(search)
    normalized_created_from = _normalize_datetime_filter_start(created_from)
    normalized_created_to = _normalize_datetime_filter_end(created_to)

    if normalized_owner_user_id:
        query = query.eq("owner_user_id", normalized_owner_user_id)
    if normalized_profile_name:
        query = query.eq("profile_name", normalized_profile_name)
    if normalized_search:
        escaped_search = normalized_search.replace(",", "\\,")
        query = query.ilike("name", f"%{escaped_search}%")
    if normalized_created_from:
        query = query.gte("created_at", normalized_created_from)
    if normalized_created_to:
        query = query.lte("created_at", normalized_created_to)
    if size_min is not None:
        query = query.gte("size_bytes", size_min)
    if size_max is not None:
        query = query.lte("size_bytes", size_max)
    if episode_count_min is not None:
        query = query.gte("episode_count", episode_count_min)
    if episode_count_max is not None:
        query = query.lte("episode_count", episode_count_max)
    return query


def _apply_recording_db_sort(query, *, sort_by: RecordingListSortBy, sort_order: SortOrder):
    sort_column = _RECORDING_DB_SORT_COLUMNS.get(sort_by)
    if not sort_column:
        return query
    descending = sort_order == "desc"
    query = query.order(sort_column, desc=descending)
    if sort_column != "id":
        query = query.order("id", desc=descending)
    return query


def _apply_recording_db_range(query, *, limit: int | None, offset: int):
    if limit is not None:
        return query.range(offset, offset + limit - 1)
    if offset > 0:
        return query.range(offset, _UNBOUNDED_RECORDING_RANGE_END)
    return query


def _recording_python_sort_key(row: dict[str, Any], sort_by: RecordingListSortBy) -> tuple[object, str]:
    if sort_by == "dataset_name":
        primary: object = _normalize_query_text(row.get("name") or row.get("id"))
    elif sort_by == "owner_name":
        primary = _normalize_query_text(row.get("owner_name") or row.get("owner_email") or row.get("owner_user_id"))
    elif sort_by == "profile_name":
        primary = _normalize_query_text(row.get("profile_name"))
    elif sort_by == "episode_count":
        primary = _to_int(row.get("episode_count"), default=0)
    elif sort_by == "size_bytes":
        primary = _to_int(row.get("size_bytes"), default=0)
    elif sort_by == "upload_status":
        primary = _RECORDING_UPLOAD_STATUS_SORT_RANK.get(
            _normalize_query_text(row.get("upload_filter_value")),
            -1,
        )
    else:
        primary = str(row.get("created_at") or "")
    return primary, str(row.get("id") or "")


def _attach_recording_owner_info(rows: list[dict[str, Any]], owner_directory) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        owner_user_id = str(row.get("owner_user_id") or "").strip()
        owner_entry = owner_directory.get(owner_user_id)
        enriched_row = dict(row)
        enriched_row["owner_email"] = owner_entry.email or None if owner_entry else None
        enriched_row["owner_name"] = owner_entry.name or None if owner_entry else None
        enriched.append(enriched_row)
    return enriched


def _attach_recording_upload_filter_values(rows: list[dict[str, Any]], lifecycle) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        enriched_row = dict(row)
        upload_snapshot = lifecycle.get_dataset_upload_status(str(row.get("id") or ""))
        enriched_row["upload_filter_value"] = _normalize_upload_filter_value(
            upload_snapshot,
            bool(str(row.get("content_hash") or "").strip()),
        )
        enriched.append(enriched_row)
    return enriched


def _recording_row_matches_filters(
    row: dict[str, Any],
    *,
    owner_user_id: str | None = None,
    profile_name: str | None = None,
    upload_status: str | None = None,
    search: str | None = None,
    created_from_dt: datetime | None = None,
    created_to_dt: datetime | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    episode_count_min: int | None = None,
    episode_count_max: int | None = None,
    skip_owner: bool = False,
    skip_profile: bool = False,
    skip_upload: bool = False,
) -> bool:
    normalized_search = _normalize_query_text(search)
    normalized_profile_name = _normalize_optional_text(profile_name)
    normalized_upload_status = _normalize_optional_text(upload_status)
    normalized_owner_user_id = _normalize_optional_text(owner_user_id)

    if normalized_search and normalized_search not in _normalize_query_text(row.get("name")):
        return False
    if not skip_profile and normalized_profile_name and _normalize_optional_text(row.get("profile_name")) != normalized_profile_name:
        return False
    if not skip_upload and normalized_upload_status and _normalize_optional_text(row.get("upload_filter_value")) != normalized_upload_status:
        return False
    if not skip_owner and normalized_owner_user_id and _normalize_optional_text(row.get("owner_user_id")) != normalized_owner_user_id:
        return False
    if not _matches_datetime_range(row.get("created_at"), created_from_dt, created_to_dt):
        return False
    if not _matches_int_range(row.get("size_bytes"), size_min, size_max):
        return False
    if not _matches_int_range(row.get("episode_count"), episode_count_min, episode_count_max):
        return False
    return True


async def _load_recording_option_rows(client, lifecycle) -> list[dict[str, Any]]:
    rows = (
        await _apply_recording_base_filters(
            client.table("datasets").select(_RECORDING_FILTER_OPTION_COLUMNS)
        ).execute()
    ).data or []
    return _attach_recording_upload_filter_values(rows, lifecycle)


async def _load_recording_db_page_rows(
    client,
    *,
    owner_user_id: str | None = None,
    profile_name: str | None = None,
    search: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    episode_count_min: int | None = None,
    episode_count_max: int | None = None,
    sort_by: RecordingListSortBy = "created_at",
    sort_order: SortOrder = "desc",
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    query = client.table("datasets").select(_RECORDING_LIST_COLUMNS, count="exact")
    query = _apply_recording_db_filters(
        query,
        owner_user_id=owner_user_id,
        profile_name=profile_name,
        search=search,
        created_from=created_from,
        created_to=created_to,
        size_min=size_min,
        size_max=size_max,
        episode_count_min=episode_count_min,
        episode_count_max=episode_count_max,
    )
    query = _apply_recording_db_sort(query, sort_by=sort_by, sort_order=sort_order)
    query = _apply_recording_db_range(query, limit=limit, offset=offset)
    result = await query.execute()
    rows = result.data or []
    total = int(getattr(result, "count", len(rows)) or 0)
    return rows, total


async def _load_recording_candidate_rows(
    client,
    *,
    owner_user_id: str | None = None,
    profile_name: str | None = None,
    search: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    episode_count_min: int | None = None,
    episode_count_max: int | None = None,
    sort_by: RecordingListSortBy = "created_at",
    sort_order: SortOrder = "desc",
) -> list[dict[str, Any]]:
    query = client.table("datasets").select(_RECORDING_LIST_COLUMNS)
    query = _apply_recording_db_filters(
        query,
        owner_user_id=owner_user_id,
        profile_name=profile_name,
        search=search,
        created_from=created_from,
        created_to=created_to,
        size_min=size_min,
        size_max=size_max,
        episode_count_min=episode_count_min,
        episode_count_max=episode_count_max,
    )
    query = _apply_recording_db_sort(query, sort_by=sort_by, sort_order=sort_order)
    return (await query.execute()).data or []


async def _list_recordings(
    *,
    owner_user_id: str | None = None,
    profile_name: str | None = None,
    upload_status: str | None = None,
    search: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    episode_count_min: int | None = None,
    episode_count_max: int | None = None,
    sort_by: RecordingListSortBy = "created_at",
    sort_order: SortOrder = "desc",
    limit: int | None = None,
    offset: int = 0,
) -> tuple[
    list[dict],
    int,
    list[RecordingOwnerFilterOption],
    list[RecordingValueFilterOption],
    list[RecordingValueFilterOption],
]:
    client = await get_supabase_async_client()
    lifecycle = get_dataset_lifecycle()
    option_rows = await _load_recording_option_rows(client, lifecycle)
    owner_directory = await resolve_user_directory_entries(
        [str(row.get("owner_user_id") or "").strip() for row in option_rows]
    )

    normalized_upload_status = _normalize_optional_text(upload_status)
    created_from_dt = _parse_filter_datetime(created_from)
    created_to_dt = _parse_filter_datetime(created_to)
    if created_to_dt and len(str(created_to or "").strip()) == 10:
        created_to_dt = created_to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    owner_available_records = [
        row
        for row in option_rows
        if _recording_row_matches_filters(
            row,
            owner_user_id=owner_user_id,
            profile_name=profile_name,
            upload_status=upload_status,
            search=search,
            created_from_dt=created_from_dt,
            created_to_dt=created_to_dt,
            size_min=size_min,
            size_max=size_max,
            episode_count_min=episode_count_min,
            episode_count_max=episode_count_max,
            skip_owner=True,
        )
    ]
    profile_available_records = [
        row
        for row in option_rows
        if _recording_row_matches_filters(
            row,
            owner_user_id=owner_user_id,
            profile_name=profile_name,
            upload_status=upload_status,
            search=search,
            created_from_dt=created_from_dt,
            created_to_dt=created_to_dt,
            size_min=size_min,
            size_max=size_max,
            episode_count_min=episode_count_min,
            episode_count_max=episode_count_max,
            skip_profile=True,
        )
    ]
    upload_available_records = [
        row
        for row in option_rows
        if _recording_row_matches_filters(
            row,
            owner_user_id=owner_user_id,
            profile_name=profile_name,
            upload_status=upload_status,
            search=search,
            created_from_dt=created_from_dt,
            created_to_dt=created_to_dt,
            size_min=size_min,
            size_max=size_max,
            episode_count_min=episode_count_min,
            episode_count_max=episode_count_max,
            skip_upload=True,
        )
    ]

    owner_options = _build_recording_owner_filter_options(option_rows, owner_available_records, owner_directory)
    profile_options = _build_recording_value_filter_options(
        option_rows,
        profile_available_records,
        value_getter=lambda record: record.get("profile_name"),
    )
    upload_status_options = _build_recording_value_filter_options(
        option_rows,
        upload_available_records,
        value_getter=lambda record: record.get("upload_filter_value"),
        label_getter=_upload_filter_label,
    )

    requires_python_paging = normalized_upload_status is not None or sort_by in {"owner_name", "upload_status"}
    if requires_python_paging:
        records = await _load_recording_candidate_rows(
            client,
            owner_user_id=owner_user_id,
            profile_name=profile_name,
            search=search,
            created_from=created_from,
            created_to=created_to,
            size_min=size_min,
            size_max=size_max,
            episode_count_min=episode_count_min,
            episode_count_max=episode_count_max,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        if normalized_upload_status is not None or sort_by == "upload_status":
            records = _attach_recording_upload_filter_values(records, lifecycle)
        if normalized_upload_status is not None:
            records = [
                row
                for row in records
                if _normalize_optional_text(row.get("upload_filter_value")) == normalized_upload_status
            ]
        if sort_by == "owner_name":
            records = _attach_recording_owner_info(records, owner_directory)
        if sort_by in {"owner_name", "upload_status"}:
            records.sort(key=lambda row: _recording_python_sort_key(row, sort_by), reverse=sort_order == "desc")
        total = len(records)
        records = records[offset:]
        if limit is not None:
            records = records[:limit]
    else:
        records, total = await _load_recording_db_page_rows(
            client,
            owner_user_id=owner_user_id,
            profile_name=profile_name,
            search=search,
            created_from=created_from,
            created_to=created_to,
            size_min=size_min,
            size_max=size_max,
            episode_count_min=episode_count_min,
            episode_count_max=episode_count_max,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )
    records = _attach_recording_owner_info(records, owner_directory)
    return records, total, owner_options, profile_options, upload_status_options


@router.get("/recordings", response_model=RecordingListResponse)
async def list_recordings(
    owner_user_id: Optional[str] = Query(None, description="Filter by owner user id"),
    profile_name: Optional[str] = Query(None, description="Filter by profile name"),
    upload_status: Optional[str] = Query(None, description="Filter by upload status"),
    search: Optional[str] = Query(None, description="Search recording name"),
    created_from: Optional[str] = Query(None, description="Created-at lower bound"),
    created_to: Optional[str] = Query(None, description="Created-at upper bound"),
    size_min: Optional[int] = Query(None, ge=0, description="Minimum size in bytes"),
    size_max: Optional[int] = Query(None, ge=0, description="Maximum size in bytes"),
    episode_count_min: Optional[int] = Query(None, ge=0, description="Minimum episode count"),
    episode_count_max: Optional[int] = Query(None, ge=0, description="Maximum episode count"),
    sort_by: RecordingListSortBy = Query("created_at", description="Sort field"),
    sort_order: SortOrder = Query("desc", description="Sort direction"),
    limit: Optional[int] = Query(None, ge=1, le=500, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    recordings_data, total, owner_options, profile_options, upload_status_options = await _list_recordings(
        owner_user_id=owner_user_id,
        profile_name=profile_name,
        upload_status=upload_status,
        search=search,
        created_from=created_from,
        created_to=created_to,
        size_min=size_min,
        size_max=size_max,
        episode_count_min=episode_count_min,
        episode_count_max=episode_count_max,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    recordings: list[RecordingInfo] = []
    for row in recordings_data:
        if not row.get("id"):
            continue
        plan = _build_continue_plan_from_row(row)
        recordings.append(
            RecordingInfo(
                recording_id=str(row.get("id")),
                dataset_name=str(row.get("name") or row.get("id")),
                task=str(row.get("task_detail") or ""),
                profile_name=str(row.get("profile_name") or "").strip() or None,
                owner_user_id=row.get("owner_user_id"),
                owner_email=row.get("owner_email"),
                owner_name=row.get("owner_name"),
                created_at=row.get("created_at"),
                episode_count=row.get("episode_count") or 0,
                target_total_episodes=plan.target_total_episodes,
                remaining_episodes=plan.remaining_episodes,
                episode_time_s=plan.episode_time_s,
                reset_time_s=plan.reset_time_s,
                continuable=plan.continuable,
                continue_block_reason=plan.reason,
                size_bytes=row.get("size_bytes") or 0,
                is_local=(get_datasets_dir() / str(row.get("id"))).exists(),
                is_uploaded=bool(str(row.get("content_hash") or "").strip()),
            )
        )
    return RecordingListResponse(
        recordings=recordings,
        total=total,
        owner_options=owner_options,
        profile_options=profile_options,
        upload_status_options=upload_status_options,
    )


@router.get(
    "/recordings/{recording_id:path}/continue-plan",
    response_model=RecordingContinuePlanResponse,
)
async def get_recording_continue_plan(recording_id: str):
    row = await _fetch_recording_row(recording_id)
    return _build_continue_plan_from_row(row)


@router.get("/recordings/{recording_id:path}", response_model=RecordingInfo)
async def get_recording(recording_id: str):
    row = await _fetch_recording_row(recording_id)
    owner_user_id = str(row.get("owner_user_id") or "").strip()
    owner_directory = await resolve_user_directory_entries([owner_user_id])
    owner_entry = owner_directory.get(owner_user_id)
    plan = _build_continue_plan_from_row(row)
    return RecordingInfo(
        recording_id=str(row.get("id")),
        dataset_name=str(row.get("name") or row.get("id")),
        task=str(row.get("task_detail") or ""),
        profile_name=str(row.get("profile_name") or "").strip() or None,
        owner_user_id=row.get("owner_user_id"),
        owner_email=owner_entry.email or None if owner_entry else None,
        owner_name=owner_entry.name or None if owner_entry else None,
        created_at=row.get("created_at"),
        episode_count=row.get("episode_count") or 0,
        target_total_episodes=plan.target_total_episodes,
        remaining_episodes=plan.remaining_episodes,
        episode_time_s=plan.episode_time_s,
        reset_time_s=plan.reset_time_s,
        continuable=plan.continuable,
        continue_block_reason=plan.reason,
        size_bytes=row.get("size_bytes") or 0,
        is_local=(get_datasets_dir() / str(row.get("id"))).exists(),
        is_uploaded=bool(str(row.get("content_hash") or "").strip()),
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


@router.post("/recordings/bulk/archive", response_model=BulkActionResponse)
async def bulk_archive_recordings(request: BulkActionRequest):
    require_user_id()
    results: list[BulkActionResult] = []
    for recording_id in request.ids:
        results.append(await archive_dataset_for_bulk(recording_id))
    return _build_bulk_action_response(results, requested=len(request.ids))


@router.post("/recordings/bulk/reupload", response_model=BulkActionResponse)
async def bulk_reupload_recordings(request: BulkActionRequest):
    require_user_id()
    results: list[BulkActionResult] = []
    for recording_id in request.ids:
        results.append(await reupload_dataset_for_bulk(recording_id))
    return _build_bulk_action_response(results, requested=len(request.ids))


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
    client = await get_supabase_async_client()
    await client.table("datasets").delete().eq("id", recording_id).execute()
    return {"recording_id": recording_id, "message": "Recording deleted"}

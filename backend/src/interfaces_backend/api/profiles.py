"""VLAbor profile selection API."""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from interfaces_backend.models.profile import (
    ProfileDeviceStatusArm,
    ProfileDeviceStatusCamera,
    VlaborActiveProfileResponse,
    VlaborActiveProfileStatusResponse,
    VlaborOperationAcceptedResponse,
    VlaborOperationAction,
    VlaborOperationState,
    VlaborOperationStatus,
    VlaborProfileSelectRequest,
    VlaborProfilesResponse,
    VlaborProfileSummary,
    VlaborStatusResponse,
)
from interfaces_backend.services.vlabor_profiles import (
    extract_status_arm_specs,
    extract_status_camera_specs,
    get_active_profile_spec,
    list_vlabor_profiles,
    set_active_profile_spec,
)
from interfaces_backend.services.vlabor_runtime import stream_vlabor_script
from interfaces_backend.services.realtime_runtime import Broadcast, UserID, get_realtime_runtime
from interfaces_backend.services.system_status_monitor import get_system_status_monitor
from interfaces_backend.utils.docker_compose import get_vlabor_compose_file
from interfaces_backend.utils.docker_services import get_docker_service_summary
from percus_ai.db import get_current_user_id

router = APIRouter(prefix="/api/profiles", tags=["profiles"])
MAX_OPERATION_LOG_LINES = 50
_vlabor_operation_lock = threading.Lock()


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _get_vlabor_status() -> dict:
    compose_file = get_vlabor_compose_file()
    if not compose_file.exists():
        return {"status": "unknown", "service": "vlabor"}
    entry = get_docker_service_summary("vlabor")
    if not entry:
        return {"status": "unknown", "service": "vlabor"}

    state_raw = str(entry.get("state") or "").lower()
    status_value = "unknown"
    if "restarting" in state_raw:
        status_value = "restarting"
    elif "running" in state_raw:
        status_value = "running"
    elif "exited" in state_raw or "stopped" in state_raw:
        status_value = "stopped"
    hostname = socket.gethostname()
    dashboard_url = f"http://{hostname}.local:8888"

    return {
        "status": status_value,
        "service": "vlabor",
        "state": entry.get("state"),
        "status_detail": entry.get("status_detail"),
        "running_for": entry.get("running_for"),
        "created_at": entry.get("created_at"),
        "container_id": entry.get("container_id"),
        "dashboard_url": dashboard_url,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _begin_vlabor_operation() -> None:
    if not _vlabor_operation_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Another VLAbor operation is already running")


def _end_vlabor_operation() -> None:
    if _vlabor_operation_lock.locked():
        _vlabor_operation_lock.release()


def _commit_vlabor_operation(user_id: str, status: VlaborOperationStatus) -> None:
    get_realtime_runtime().track(
        scope=UserID(user_id),
        kind="profiles.vlabor.operation",
        key=status.operation_id,
    ).replace(status.model_dump(mode="json"))


def _vlabor_operation_status(
    *,
    operation_id: str,
    action: VlaborOperationAction,
    state: VlaborOperationState,
    profile_name: str | None,
    previous_profile_name: str | None = None,
    message: str = "",
    logs: list[str] | None = None,
    error: str | None = None,
    exit_code: str | None = None,
) -> VlaborOperationStatus:
    return VlaborOperationStatus(
        operation_id=operation_id,
        action=action,
        state=state,
        profile_name=profile_name,
        previous_profile_name=previous_profile_name,
        message=message,
        logs=list(logs or [])[-MAX_OPERATION_LOG_LINES:],
        error=error,
        exit_code=exit_code,
        updated_at=_now_iso(),
    )


async def _run_vlabor_script_events(
    *,
    script_name: str,
    args: list[str],
    timeout: int,
    on_event: Callable[[dict[str, str]], None],
) -> tuple[bool, str | None, str | None]:
    queue: asyncio.Queue[dict[str, str] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _run() -> None:
        try:
            for event in stream_vlabor_script(script_name, args, timeout=timeout):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:  # noqa: BLE001 - surface operation failure to realtime track
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": str(exc)},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    future = loop.run_in_executor(None, _run)

    saw_complete = False
    exit_code: str | None = None
    error_message: str | None = None
    while True:
        event = await queue.get()
        if event is None:
            break
        on_event(event)
        event_type = str(event.get("type") or "").strip().lower()
        if event_type == "complete":
            saw_complete = True
            exit_code = str(event.get("exit_code") or "").strip()
        elif event_type == "error":
            error_message = str(event.get("message") or "Unknown error").strip()

    await future
    if error_message:
        return False, error_message, exit_code
    if not saw_complete:
        return False, "VLAbor script finished without completion status", exit_code
    if exit_code != "0":
        return False, f"exit code={exit_code or 'unknown'}", exit_code
    return True, None, exit_code


async def _run_vlabor_restart_operation(
    *,
    user_id: str,
    operation_id: str,
    action: VlaborOperationAction,
    profile_name: str | None,
    previous_profile_name: str | None = None,
    logs: list[str] | None = None,
    commit_terminal_success: bool = True,
) -> tuple[bool, str | None]:
    operation_logs = list(logs or [])

    def commit(
        state: VlaborOperationState,
        message: str,
        *,
        error: str | None = None,
        exit_code: str | None = None,
    ) -> None:
        _commit_vlabor_operation(
            user_id,
            _vlabor_operation_status(
                operation_id=operation_id,
                action=action,
                state=state,
                profile_name=profile_name,
                previous_profile_name=previous_profile_name,
                message=message,
                logs=operation_logs,
                error=error,
                exit_code=exit_code,
            ),
        )

    commit("running", f"Restarting VLAbor with profile: {profile_name or 'default'}")

    def on_event(event: dict[str, str]) -> None:
        event_type = str(event.get("type") or "").strip().lower()
        if event_type == "log":
            line = str(event.get("line") or "").strip()
            if line:
                operation_logs.append(line)
                commit("running", line)
            return
        if event_type == "error":
            message = str(event.get("message") or "VLAbor restart failed").strip()
            operation_logs.append(message)
            commit("failed", message, error=message)

    args = [profile_name] if profile_name else []
    ok, detail, exit_code = await _run_vlabor_script_events(
        script_name="restart",
        args=args,
        timeout=300,
        on_event=on_event,
    )
    if ok:
        if commit_terminal_success:
            commit("completed", "VLAbor restart completed", exit_code=exit_code)
        else:
            commit("running", "VLAbor rollback restart completed", exit_code=exit_code)
        await get_vlabor_status()
        return True, None

    message = detail or "VLAbor restart failed"
    operation_logs.append(message)
    commit("failed", message, error=message, exit_code=exit_code)
    await get_vlabor_status()
    return False, message


async def _run_vlabor_switch_operation(
    *,
    user_id: str,
    operation_id: str,
    profile_name: str,
    previous_profile_name: str,
) -> None:
    logs = [f"Switching active profile: {previous_profile_name} -> {profile_name}"]
    switched, switch_detail = await _run_vlabor_restart_operation(
        user_id=user_id,
        operation_id=operation_id,
        action="switch_profile",
        profile_name=profile_name,
        previous_profile_name=previous_profile_name,
        logs=logs,
    )
    if switched:
        return

    logs.append(
        f"Switch failed ({switch_detail or 'unknown'}). Rolling back to profile: {previous_profile_name}"
    )
    _commit_vlabor_operation(
        user_id,
        _vlabor_operation_status(
            operation_id=operation_id,
            action="switch_profile",
            state="running",
            profile_name=profile_name,
            previous_profile_name=previous_profile_name,
            message="Rolling back active profile",
            logs=logs,
        ),
    )
    try:
        await set_active_profile_spec(previous_profile_name)
        logs.append(f"Active profile reverted to: {previous_profile_name}")
    except Exception as exc:  # noqa: BLE001 - precise rollback detail
        message = f"Failed to revert active profile: {exc}"
        logs.append(message)
        _commit_vlabor_operation(
            user_id,
            _vlabor_operation_status(
                operation_id=operation_id,
                action="switch_profile",
                state="failed",
                profile_name=profile_name,
                previous_profile_name=previous_profile_name,
                message=message,
                logs=logs,
                error=message,
            ),
        )
        return

    rollback_ok, rollback_detail = await _run_vlabor_restart_operation(
        user_id=user_id,
        operation_id=operation_id,
        action="switch_profile",
        profile_name=previous_profile_name,
        previous_profile_name=previous_profile_name,
        logs=logs,
        commit_terminal_success=False,
    )
    message = f"Failed to switch profile to {profile_name}: {switch_detail or 'unknown'}"
    if not rollback_ok:
        message = f"{message}; rollback restart failed: {rollback_detail or 'unknown'}"
    logs.append(message)
    _commit_vlabor_operation(
        user_id,
        _vlabor_operation_status(
            operation_id=operation_id,
            action="switch_profile",
            state="failed",
            profile_name=profile_name,
            previous_profile_name=previous_profile_name,
            message=message,
            logs=logs,
            error=message,
        ),
    )


async def _run_vlabor_restart_operation_task(**kwargs) -> None:
    try:
        await _run_vlabor_restart_operation(**kwargs)
    finally:
        _end_vlabor_operation()


async def _run_vlabor_switch_operation_task(**kwargs) -> None:
    try:
        await _run_vlabor_switch_operation(**kwargs)
    finally:
        _end_vlabor_operation()


@router.get("", response_model=VlaborProfilesResponse)
async def list_profiles():
    _require_user_id()
    profiles = list_vlabor_profiles()
    active = await get_active_profile_spec()
    items = [
        VlaborProfileSummary(
            name=profile.name,
            description=profile.description,
            updated_at=profile.updated_at,
            source_path=profile.source_path,
        )
        for profile in profiles
    ]
    return VlaborProfilesResponse(
        profiles=items,
        active_profile_name=active.name if active else None,
        total=len(items),
    )


@router.get("/active", response_model=VlaborActiveProfileResponse)
async def get_active_profile():
    _require_user_id()
    active = await get_active_profile_spec()
    return VlaborActiveProfileResponse(
        profile_name=active.name,
        profile_snapshot=active.snapshot,
    )


@router.put("/active", response_model=VlaborOperationAcceptedResponse)
async def set_active_profile(request: VlaborProfileSelectRequest, background_tasks: BackgroundTasks):
    user_id = _require_user_id()
    _begin_vlabor_operation()
    requested_profile = request.profile_name.strip()
    try:
        available = {profile.name for profile in list_vlabor_profiles()}
        if requested_profile not in available:
            raise HTTPException(status_code=404, detail=f"VLAbor profile not found: {requested_profile}")

        previous = await get_active_profile_spec()
        active = await set_active_profile_spec(requested_profile)
        operation_id = uuid4().hex
        _commit_vlabor_operation(
            user_id,
            _vlabor_operation_status(
                operation_id=operation_id,
                action="switch_profile",
                state="queued",
                profile_name=active.name,
                previous_profile_name=previous.name,
                message=f"Switching active profile: {previous.name} -> {active.name}",
                logs=[f"Switching active profile: {previous.name} -> {active.name}"],
            ),
        )
        background_tasks.add_task(
            _run_vlabor_switch_operation_task,
            user_id=user_id,
            operation_id=operation_id,
            profile_name=active.name,
            previous_profile_name=previous.name,
        )
        return VlaborOperationAcceptedResponse(
            operation_id=operation_id,
            action="switch_profile",
            profile_name=active.name,
            previous_profile_name=previous.name,
        )
    except Exception:
        _end_vlabor_operation()
        raise


@router.get("/active/status", response_model=VlaborActiveProfileStatusResponse)
async def get_active_profile_status():
    _require_user_id()
    active = await get_active_profile_spec()
    monitor = get_system_status_monitor()
    monitor.ensure_started()
    topics = monitor.get_cached_ros2_topics()
    topic_set = set(topics)

    cameras = []
    for spec in extract_status_camera_specs(active.snapshot):
        name = str(spec.get("name") or "").strip()
        if not name:
            continue
        # Skip disabled cameras to avoid clutter in device status UI
        if not spec.get("enabled", True):
            continue
        expected_topics = [str(item).strip() for item in (spec.get("topics") or []) if str(item).strip()]
        if not expected_topics:
            expected_topics = [f"/{name}/image_raw", f"/{name}/image_raw/compressed"]
        connected_topic = next((item for item in expected_topics if item in topic_set), None)
        cameras.append(
            ProfileDeviceStatusCamera(
                name=name,
                label=str(spec.get("label") or "").strip() or name,
                enabled=bool(spec.get("enabled", True)),
                connected=bool(connected_topic),
                connected_topic=connected_topic,
                topics=expected_topics,
            )
        )

    arms = []
    for spec in extract_status_arm_specs(active.snapshot):
        namespace = str(spec.get("name") or "").strip()
        if not namespace:
            continue
        expected_topics = [str(item).strip() for item in (spec.get("topics") or []) if str(item).strip()]
        if not expected_topics:
            expected_topics = [f"/{namespace}/joint_states", f"/{namespace}/joint_states_single"]
        connected_topic = next((item for item in expected_topics if item in topic_set), None)
        arms.append(
            ProfileDeviceStatusArm(
                name=namespace,
                label=str(spec.get("label") or "").strip() or namespace,
                role=str(spec.get("role") or "").strip() or None,
                enabled=bool(spec.get("enabled", True)),
                connected=bool(connected_topic),
                connected_topic=connected_topic,
                topics=expected_topics,
            )
        )

    response = VlaborActiveProfileStatusResponse(
        profile_name=active.name,
        profile_snapshot=active.snapshot,
        cameras=cameras,
        arms=arms,
        topics=topics,
    )
    get_realtime_runtime().track(
        scope=Broadcast(),
        kind="profiles.active",
        key="active",
    ).replace(response.model_dump(mode="json"))
    return response


@router.get("/vlabor/status", response_model=VlaborStatusResponse)
async def get_vlabor_status():
    response = VlaborStatusResponse(**(await asyncio.to_thread(_get_vlabor_status)))
    get_realtime_runtime().track(
        scope=Broadcast(),
        kind="profiles.vlabor",
        key="vlabor",
    ).replace(response.model_dump(mode="json"))
    return response


@router.post("/vlabor/restart", response_model=VlaborOperationAcceptedResponse)
async def restart_vlabor_endpoint(
    background_tasks: BackgroundTasks,
    profile: str | None = Query(default=None),
):
    user_id = _require_user_id()
    _begin_vlabor_operation()
    try:
        requested_profile = str(profile or "").strip()
        if requested_profile:
            available = {item.name for item in list_vlabor_profiles()}
            if requested_profile not in available:
                raise HTTPException(status_code=404, detail=f"VLAbor profile not found: {requested_profile}")
            profile_name = requested_profile
        else:
            active = await get_active_profile_spec()
            profile_name = active.name

        operation_id = uuid4().hex
        _commit_vlabor_operation(
            user_id,
            _vlabor_operation_status(
                operation_id=operation_id,
                action="restart",
                state="queued",
                profile_name=profile_name,
                message=f"Restarting VLAbor with profile: {profile_name}",
                logs=[],
            ),
        )
        background_tasks.add_task(
            _run_vlabor_restart_operation_task,
            user_id=user_id,
            operation_id=operation_id,
            action="restart",
            profile_name=profile_name,
        )
        return VlaborOperationAcceptedResponse(
            operation_id=operation_id,
            action="restart",
            profile_name=profile_name,
        )
    except Exception:
        _end_vlabor_operation()
        raise

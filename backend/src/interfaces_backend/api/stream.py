"""SSE endpoints for WebUI state streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from interfaces_backend.core.request_auth import (
    is_session_expired,
    refresh_session_from_refresh_token,
)
from interfaces_backend.api.inference import get_inference_runner_status
from interfaces_backend.api.operate import get_operate_status
from interfaces_backend.api.profiles import get_active_profile_status, get_vlabor_status
from interfaces_backend.api.training import (
    RUNNING_STATUSES,
    _get_setup_log_file_path,
    _get_ssh_connection_for_job,
    _get_training_log_file_path,
    _load_job,
    get_job,
    get_job_metrics,
    get_job_provision_operation,
)
from interfaces_backend.services.dataset_lifecycle import UPLOAD_TOPIC, get_dataset_lifecycle
from interfaces_backend.services.dataset_sync_jobs import (
    DATASET_SYNC_JOB_TOPIC,
    get_dataset_sync_jobs_service,
)
from interfaces_backend.services.dataset_merge_jobs import (
    DATASET_MERGE_JOB_TOPIC,
    get_dataset_merge_jobs_service,
)
from interfaces_backend.services.model_sync_jobs import (
    MODEL_SYNC_JOB_TOPIC,
    get_model_sync_jobs_service,
)
from interfaces_backend.services.realtime_events import get_realtime_event_bus
from interfaces_backend.services.realtime_producers import (
    ProducerBuilder,
    get_realtime_producer_hub,
)
from interfaces_backend.services.recorder_status_stream import (
    RECORDING_STATUS_TOPIC,
    get_recorder_status_stream,
)
from interfaces_backend.services.session_control_events import (
    SESSION_CONTROL_TOPIC,
    normalize_session_kind,
    session_control_channel_key,
)
from interfaces_backend.services.startup_operations import (
    STARTUP_OPERATION_TOPIC,
    get_startup_operations_service,
)
from interfaces_backend.services.system_status_monitor import (
    SYSTEM_STATUS_KEY,
    SYSTEM_STATUS_TOPIC,
    get_system_status_monitor,
)
from interfaces_backend.services.bundled_torch_build_service import (
    BUNDLED_TORCH_KEY,
    BUNDLED_TORCH_TOPIC,
    get_bundled_torch_build_service,
)
from interfaces_backend.services.runtime_env_service import (
    RUNTIME_ENV_KEY,
    RUNTIME_ENV_TOPIC,
    get_runtime_env_service,
)
from interfaces_backend.services.training_provision_operations import (
    TRAINING_PROVISION_OPERATION_TOPIC,
    get_training_provision_operations_service,
)
from interfaces_backend.utils.sse import sse_queue_response
from percus_ai.db import get_current_user_id, get_supabase_session, set_request_session

router = APIRouter(prefix="/api/stream", tags=["stream"])
logger = logging.getLogger(__name__)

PROFILE_ACTIVE_TOPIC = "profiles.active"
PROFILE_VLABOR_TOPIC = "profiles.vlabor"
OPERATE_STATUS_TOPIC = "operate.status"
TRAINING_JOB_TOPIC = "training.job"


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _refresh_stream_session_if_needed() -> None:
    session = get_supabase_session()
    if not session or not is_session_expired(session):
        return
    refreshed_session = refresh_session_from_refresh_token(session.get("refresh_token"))
    if refreshed_session is None:
        return
    set_request_session(refreshed_session)


async def _stream_with_shared_producer(
    request: Request,
    *,
    topic: str,
    key: str,
    build_payload: ProducerBuilder,
    interval: float,
    idle_ttl: float = 30.0,
):
    bus = get_realtime_event_bus()
    hub = get_realtime_producer_hub()
    subscription = bus.subscribe(topic, key)

    async def build_payload_with_fresh_session() -> dict:
        _refresh_stream_session_if_needed()
        return await build_payload()

    await hub.publish_once(topic=topic, key=key, build_payload=build_payload_with_fresh_session)
    hub.ensure_polling(
        topic=topic,
        key=key,
        build_payload=build_payload_with_fresh_session,
        interval=interval,
        idle_ttl=idle_ttl,
    )
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/profiles/active")
async def stream_active_profile(request: Request):
    _require_user_id()

    async def build_payload() -> dict:
        status = await get_active_profile_status()
        return status.model_dump(mode="json")

    return await _stream_with_shared_producer(
        request,
        topic=PROFILE_ACTIVE_TOPIC,
        key="global",
        build_payload=build_payload,
        interval=5.0,
        idle_ttl=45.0,
    )


@router.get("/profiles/vlabor")
async def stream_vlabor_status(request: Request):
    _require_user_id()

    async def build_payload() -> dict:
        status = await get_vlabor_status()
        return status.model_dump(mode="json")

    return await _stream_with_shared_producer(
        request,
        topic=PROFILE_VLABOR_TOPIC,
        key="global",
        build_payload=build_payload,
        interval=2.0,
        idle_ttl=45.0,
    )


@router.get("/recording/sessions/{session_id}")
async def stream_recording_session(request: Request, session_id: str):
    _require_user_id()
    recorder_stream = get_recorder_status_stream()
    recorder_stream.ensure_started()
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(RECORDING_STATUS_TOPIC, session_id)
    await bus.publish(
        RECORDING_STATUS_TOPIC,
        session_id,
        await recorder_stream.build_session_snapshot(session_id),
    )
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/recording/sessions/{session_id}/upload-status")
async def stream_recording_upload_status(request: Request, session_id: str):
    _require_user_id()
    bus = get_realtime_event_bus()
    lifecycle = get_dataset_lifecycle()
    subscription = bus.subscribe(UPLOAD_TOPIC, session_id)
    await bus.publish(UPLOAD_TOPIC, session_id, lifecycle.get_dataset_upload_status(session_id))
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/operate/status")
async def stream_operate_status(request: Request):
    _require_user_id()

    async def build_payload() -> dict:
        vlabor_status = await get_vlabor_status()
        inference_runner_status = await get_inference_runner_status()
        operate_status = await get_operate_status()

        return {
            "vlabor_status": vlabor_status.model_dump(mode="json"),
            "inference_runner_status": inference_runner_status.model_dump(mode="json"),
            "operate_status": operate_status.model_dump(mode="json"),
        }

    return await _stream_with_shared_producer(
        request,
        topic=OPERATE_STATUS_TOPIC,
        key="global",
        build_payload=build_payload,
        interval=2.0,
        idle_ttl=45.0,
    )


@router.get("/system/status")
async def stream_system_status(request: Request):
    _require_user_id()
    monitor = get_system_status_monitor()
    monitor.ensure_started()
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(SYSTEM_STATUS_TOPIC, SYSTEM_STATUS_KEY)
    await monitor.publish_snapshot()
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/system/bundled-torch")
async def stream_bundled_torch_status(request: Request):
    _require_user_id()
    service = get_bundled_torch_build_service()
    await service.refresh_snapshot()
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(BUNDLED_TORCH_TOPIC, BUNDLED_TORCH_KEY)
    await service.publish_snapshot()
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/system/runtime-envs")
async def stream_runtime_env_status(request: Request):
    _require_user_id()
    service = get_runtime_env_service()
    await service.refresh_snapshot()
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(RUNTIME_ENV_TOPIC, RUNTIME_ENV_KEY)
    await service.publish_snapshot()
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/startup/operations/{operation_id}")
async def stream_startup_operation(request: Request, operation_id: str):
    user_id = _require_user_id()
    operations = get_startup_operations_service()
    snapshot = operations.get(user_id=user_id, operation_id=operation_id)
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(STARTUP_OPERATION_TOPIC, operation_id)
    await bus.publish(STARTUP_OPERATION_TOPIC, operation_id, snapshot.model_dump(mode="json"))
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/training/provision-operations/{operation_id}")
async def stream_training_provision_operation(request: Request, operation_id: str):
    user_id = _require_user_id()
    operations = get_training_provision_operations_service()
    snapshot = await operations.get(user_id=user_id, operation_id=operation_id)
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(TRAINING_PROVISION_OPERATION_TOPIC, operation_id)
    await bus.publish(
        TRAINING_PROVISION_OPERATION_TOPIC,
        operation_id,
        snapshot.model_dump(mode="json"),
    )
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/training/jobs/{job_id}/logs")
async def stream_training_job_logs(
    request: Request,
    job_id: str,
    log_type: str = "training",
):
    _require_user_id()
    if log_type not in {"training", "setup"}:
        raise HTTPException(status_code=400, detail=f"Invalid log_type: {log_type}")

    _refresh_stream_session_if_needed()

    async def event_stream():
        ssh_conn = None
        channel = None
        last_status_poll = 0.0

        def encode(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n\n"

        try:
            job_data = await _load_job(job_id)
            if not job_data:
                yield encode({"type": "error", "error": f"Job not found: {job_id}"})
                return

            ip = job_data.get("ip")
            if not ip:
                yield encode({"type": "error", "error": "Job has no IP address"})
                return

            loop = asyncio.get_running_loop()
            ssh_conn = await loop.run_in_executor(
                None,
                lambda: _get_ssh_connection_for_job(job_data, timeout=30),
            )
            if not ssh_conn:
                yield encode({"type": "error", "error": "SSH接続に失敗しました"})
                return

            yield encode({"type": "connected", "message": "SSH接続完了"})

            log_file = (
                _get_setup_log_file_path(job_data)
                if log_type == "setup"
                else _get_training_log_file_path(job_data)
            )
            transport = ssh_conn.client.get_transport()
            channel = transport.open_session()
            channel.exec_command(f"tail -f {log_file} 2>/dev/null")
            channel.setblocking(0)

            while True:
                if await request.is_disconnected():
                    break

                emitted = False
                try:
                    if channel.recv_ready():
                        data = channel.recv(4096)
                        if data:
                            lines = data.decode("utf-8", errors="replace").split("\n")
                            for line in lines:
                                if line.strip():
                                    yield encode({"type": "log", "line": line})
                                    emitted = True

                    if channel.exit_status_ready():
                        yield encode(
                            {
                                "type": "status",
                                "status": "stream_ended",
                                "message": "ログストリーム終了",
                            }
                        )
                        break
                except Exception as exc:  # noqa: BLE001
                    logger.debug("SSH recv error for %s: %s", job_id, exc)

                now = asyncio.get_running_loop().time()
                if now - last_status_poll >= 5.0:
                    last_status_poll = now
                    current_job = await _load_job(job_id, include_deleted=True)
                    if current_job is None:
                        yield encode(
                            {
                                "type": "status",
                                "status": "deleted",
                                "message": "ジョブが見つかりません。",
                            }
                        )
                        break

                    current_status = str(current_job.get("status") or "").strip()
                    if current_status and current_status not in RUNNING_STATUSES:
                        yield encode(
                            {
                                "type": "status",
                                "status": current_status,
                                "message": f"ジョブ状態: {current_status}",
                            }
                        )
                        break

                if not emitted:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("SSE log stream error for job %s: %s", job_id, exc)
            yield encode({"type": "error", "error": str(exc)})
        finally:
            try:
                if channel is not None:
                    channel.close()
            except Exception:
                pass
            if ssh_conn:
                try:
                    ssh_conn.disconnect()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/training/jobs/{job_id}/provision-operation")
async def stream_training_job_provision_operation(request: Request, job_id: str):
    _require_user_id()
    snapshot = await get_job_provision_operation(job_id)
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(TRAINING_PROVISION_OPERATION_TOPIC, snapshot.operation_id)
    await bus.publish(
        TRAINING_PROVISION_OPERATION_TOPIC,
        snapshot.operation_id,
        snapshot.model_dump(mode="json"),
    )
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/storage/model-sync/jobs/{job_id}")
async def stream_model_sync_job(request: Request, job_id: str):
    user_id = _require_user_id()
    jobs = get_model_sync_jobs_service()
    snapshot = jobs.get(user_id=user_id, job_id=job_id)
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(MODEL_SYNC_JOB_TOPIC, job_id)
    await bus.publish(MODEL_SYNC_JOB_TOPIC, job_id, snapshot.model_dump(mode="json"))
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/storage/dataset-sync/jobs/{job_id}")
async def stream_dataset_sync_job(request: Request, job_id: str):
    user_id = _require_user_id()
    jobs = get_dataset_sync_jobs_service()
    snapshot = jobs.get(user_id=user_id, job_id=job_id)
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(DATASET_SYNC_JOB_TOPIC, job_id)
    await bus.publish(DATASET_SYNC_JOB_TOPIC, job_id, snapshot.model_dump(mode="json"))
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/storage/dataset-merge/jobs/{job_id}")
async def stream_dataset_merge_job(request: Request, job_id: str):
    user_id = _require_user_id()
    jobs = get_dataset_merge_jobs_service()
    snapshot = jobs.get(user_id=user_id, job_id=job_id)
    bus = get_realtime_event_bus()
    subscription = bus.subscribe(DATASET_MERGE_JOB_TOPIC, job_id)
    await bus.publish(DATASET_MERGE_JOB_TOPIC, job_id, snapshot.model_dump(mode="json"))
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/sessions/{session_kind}/{session_id}/events")
async def stream_session_control_events(request: Request, session_kind: str, session_id: str):
    _require_user_id()
    try:
        normalized_kind = normalize_session_kind(session_kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized_session_id = session_id.strip() or "global"

    bus = get_realtime_event_bus()
    subscription = bus.subscribe(
        SESSION_CONTROL_TOPIC,
        session_control_channel_key(
            session_kind=normalized_kind,
            session_id=normalized_session_id,
        ),
    )
    return sse_queue_response(
        request,
        subscription.queue,
        on_close=subscription.close,
    )


@router.get("/training/jobs/{job_id}")
async def stream_training_job(request: Request, job_id: str, limit: int = 2000):
    _require_user_id()

    async def build_payload() -> dict:
        job_detail = await get_job(job_id)
        metrics = await get_job_metrics(job_id=job_id, response=Response(), limit=limit)
        return {
            "job_detail": job_detail.model_dump(mode="json"),
            "metrics": metrics.model_dump(mode="json"),
        }

    return await _stream_with_shared_producer(
        request,
        topic=TRAINING_JOB_TOPIC,
        key=job_id,
        build_payload=build_payload,
        interval=5.0,
        idle_ttl=60.0,
    )

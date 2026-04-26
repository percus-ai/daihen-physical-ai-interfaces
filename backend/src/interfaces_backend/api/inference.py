"""Inference control API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from interfaces_backend.models.inference import (
    InferenceNumericOption,
    InferenceRecordingDecisionRequest,
    InferenceRecordingDecisionResponse,
    InferenceModelInfo,
    InferenceModelsResponse,
    InferenceOwnerOption,
    InferenceRuntimeTargetsResponse,
    InferenceValueOption,
    InferenceRunnerStartRequest,
    InferenceRunnerControlResponse,
    InferenceRunnerSettingsApplyRequest,
    InferenceRunnerSettingsApplyResponse,
    InferenceRunnerStatusResponse,
    InferenceRunnerStopRequest,
    InferenceRunnerStopResponse,
    InferenceSetTaskRequest,
    InferenceSetTaskResponse,
)
from interfaces_backend.models.startup import StartupOperationAcceptedResponse
from interfaces_backend.services.inference_runtime import get_inference_runtime_manager
from interfaces_backend.services.inference_runtime_targets import (
    get_inference_runtime_targets_service,
)
from interfaces_backend.services.inference_session import get_inference_session_manager
from interfaces_backend.services.session_manager import require_user_id
from interfaces_backend.services.startup_operations import (
    get_startup_operations_service,
)
from interfaces_backend.services.dataset_lifecycle import get_dataset_lifecycle
from interfaces_backend.services.user_directory import resolve_user_directory_entries
from percus_ai.db import get_supabase_async_client
from percus_ai.storage.paths import get_datasets_dir, get_models_dir
from lerobot.datasets.utils import load_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inference", tags=["inference"])

_MODEL_LIST_COLUMNS = (
    "id,name,created_at,owner_user_id,profile_name,policy_type,"
    "training_steps,batch_size,size_bytes,source,dataset_id"
)
_TRAINING_JOB_DATASET_COLUMNS = "model_id,dataset_id,updated_at,deleted_at"
_DATASET_TASK_COLUMNS = "id,task_detail,status,dataset_type"
_DATASET_SOURCE_SNAPSHOT_COLUMNS = "id,source_datasets"
_DEFAULT_MODEL_LIST_LIMIT = 200
_MAX_MODEL_LIST_LIMIT = 500


async def _emit_inference_control_event(
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


def _to_size_mb(size_bytes: object) -> float:
    try:
        value = float(size_bytes or 0)
    except (TypeError, ValueError):
        value = 0.0
    return round(max(value, 0.0) / (1024 * 1024), 2)


def _normalize_task_detail(task_detail: object) -> str | None:
    if not isinstance(task_detail, str):
        return None
    normalized = task_detail.strip()
    return normalized if normalized else None


def _merge_task_candidates(*candidate_groups: Sequence[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in candidate_groups:
        for item in group:
            normalized = _normalize_task_detail(item)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _task_candidates_from_source_snapshots(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    candidates: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        task_detail = _normalize_task_detail(item.get("task_detail"))
        if task_detail is not None:
            candidates.append(task_detail)
    return _merge_task_candidates(candidates)


def _load_local_dataset_task_candidates(dataset_id: str) -> list[str]:
    dataset_root = get_datasets_dir() / dataset_id
    if not dataset_root.exists():
        return []

    try:
        tasks = load_tasks(dataset_root)
    except Exception as exc:
        logger.warning("Failed to load local dataset tasks for %s: %s", dataset_id, exc)
        return []

    try:
        task_names = [str(task_name) for task_name in tasks.index.tolist()]
    except Exception as exc:
        logger.warning(
            "Failed to normalize local dataset tasks for %s: %s", dataset_id, exc
        )
        return []
    return _merge_task_candidates(task_names)


async def _load_task_candidates_by_model(
    client,
    model_rows: Sequence[dict],
) -> dict[str, list[str]]:
    model_ids: list[str] = []
    model_dataset_ids: dict[str, list[str]] = {}

    for row in model_rows:
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        if model_id not in model_dataset_ids:
            model_ids.append(model_id)
            model_dataset_ids[model_id] = []
        dataset_id = str(row.get("dataset_id") or "").strip()
        if dataset_id and dataset_id not in model_dataset_ids[model_id]:
            model_dataset_ids[model_id].append(dataset_id)

    if not model_ids:
        return {}

    try:
        job_rows = (
            await client.table("training_jobs")
            .select(_TRAINING_JOB_DATASET_COLUMNS)
            .in_("model_id", model_ids)
            .order("updated_at", desc=True)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("Failed to load training_jobs for task candidates: %s", exc)
        return {model_id: [] for model_id in model_ids}

    for row in job_rows:
        if row.get("deleted_at"):
            continue
        model_id = str(row.get("model_id") or "").strip()
        dataset_id = str(row.get("dataset_id") or "").strip()
        if not model_id or not dataset_id:
            continue
        if model_id not in model_dataset_ids:
            continue
        if dataset_id not in model_dataset_ids[model_id]:
            model_dataset_ids[model_id].append(dataset_id)

    all_dataset_ids: list[str] = []
    seen_dataset_ids: set[str] = set()
    for model_id in model_ids:
        for dataset_id in model_dataset_ids.get(model_id, []):
            if dataset_id in seen_dataset_ids:
                continue
            seen_dataset_ids.add(dataset_id)
            all_dataset_ids.append(dataset_id)

    if not all_dataset_ids:
        return {model_id: [] for model_id in model_ids}

    try:
        dataset_rows = (
            await client.table("datasets")
            .select(_DATASET_TASK_COLUMNS)
            .in_("id", all_dataset_ids)
            .eq("status", "active")
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("Failed to load datasets for task candidates: %s", exc)
        return {model_id: [] for model_id in model_ids}

    task_candidates_by_dataset_id: dict[str, list[str]] = {}
    merged_ids_needing_snapshots: list[str] = []
    merged_task_detail_fallbacks: dict[str, list[str]] = {}
    for row in dataset_rows:
        dataset_id = str(row.get("id") or "").strip()
        if not dataset_id:
            continue

        dataset_type = str(row.get("dataset_type") or "").strip().lower()
        if dataset_type == "merged":
            local_candidates = _load_local_dataset_task_candidates(dataset_id)
            if local_candidates:
                task_candidates_by_dataset_id[dataset_id] = local_candidates
                continue
            task_detail = _normalize_task_detail(row.get("task_detail"))
            merged_task_detail_fallbacks[dataset_id] = (
                [task_detail] if task_detail is not None else []
            )
            merged_ids_needing_snapshots.append(dataset_id)
            continue

        task_detail = _normalize_task_detail(row.get("task_detail"))
        task_candidates_by_dataset_id[dataset_id] = (
            [task_detail] if task_detail is not None else []
        )

    if merged_ids_needing_snapshots:
        snapshot_candidates = await _load_merged_dataset_source_snapshot_candidates(
            client,
            merged_ids_needing_snapshots,
        )
        for dataset_id in merged_ids_needing_snapshots:
            task_candidates_by_dataset_id[dataset_id] = snapshot_candidates.get(
                dataset_id
            ) or merged_task_detail_fallbacks.get(dataset_id, [])

    candidates_by_model: dict[str, list[str]] = {}
    for model_id in model_ids:
        ordered_candidate_groups = [
            task_candidates_by_dataset_id[dataset_id]
            for dataset_id in model_dataset_ids.get(model_id, [])
            if dataset_id in task_candidates_by_dataset_id
        ]
        candidates_by_model[model_id] = _merge_task_candidates(
            *ordered_candidate_groups
        )
    return candidates_by_model


async def _load_merged_dataset_source_snapshot_candidates(
    client,
    dataset_ids: Sequence[str],
) -> dict[str, list[str]]:
    if not dataset_ids:
        return {}

    try:
        rows = (
            await client.table("datasets")
            .select(_DATASET_SOURCE_SNAPSHOT_COLUMNS)
            .in_("id", list(dataset_ids))
            .eq("status", "active")
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("Failed to load merged dataset source snapshots: %s", exc)
        return {}

    candidates_by_dataset_id: dict[str, list[str]] = {}
    for row in rows:
        dataset_id = str(row.get("id") or "").strip()
        if not dataset_id:
            continue
        candidates_by_dataset_id[dataset_id] = _task_candidates_from_source_snapshots(
            row.get("source_datasets")
        )
    return candidates_by_dataset_id


async def _list_db_models(
    *,
    owner_user_id: str | None = None,
    profile_name: str | None = None,
    policy_type: str | None = None,
    training_steps: int | None = None,
    batch_size: int | None = None,
    limit: int = _DEFAULT_MODEL_LIST_LIMIT,
    offset: int = 0,
) -> list[InferenceModelInfo]:
    try:
        client = await get_supabase_async_client()
        query = (
            client.table("models").select(_MODEL_LIST_COLUMNS).eq("status", "active")
        )
        if owner_user_id:
            query = query.eq("owner_user_id", owner_user_id)
        if profile_name:
            query = query.eq("profile_name", profile_name)
        if policy_type:
            query = query.eq("policy_type", policy_type)
        if training_steps is not None:
            query = query.eq("training_steps", training_steps)
        if batch_size is not None:
            query = query.eq("batch_size", batch_size)
        rows = (
            await query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("Failed to load models from DB: %s", exc)
        return []

    task_candidates_by_model = await _load_task_candidates_by_model(client, rows)
    owner_directory = await resolve_user_directory_entries(
        [str(row.get("owner_user_id") or "").strip() for row in rows]
    )
    models_dir = get_models_dir()
    db_models: list[InferenceModelInfo] = []
    for row in rows:
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        local_exists = (models_dir / model_id).exists()
        name = str(row.get("name") or model_id).strip() or model_id
        owner_user_id = str(row.get("owner_user_id") or "").strip() or None
        owner_entry = owner_directory.get(owner_user_id or "")
        policy_type = row.get("policy_type")
        source = (
            str(row.get("source") or ("local" if local_exists else "r2")).strip()
            or "r2"
        )
        db_models.append(
            InferenceModelInfo(
                model_id=model_id,
                name=name,
                created_at=str(row.get("created_at") or "").strip() or None,
                owner_user_id=owner_user_id,
                owner_name=owner_entry.name or None if owner_entry else None,
                profile_name=str(row.get("profile_name") or "").strip() or None,
                policy_type=policy_type
                if isinstance(policy_type, str) and policy_type
                else None,
                training_steps=int(row.get("training_steps"))
                if row.get("training_steps") is not None
                else None,
                batch_size=int(row.get("batch_size"))
                if row.get("batch_size") is not None
                else None,
                source=source,
                size_mb=_to_size_mb(row.get("size_bytes")),
                is_loaded=False,
                is_local=local_exists,
                task_candidates=task_candidates_by_model.get(model_id, []),
            )
        )
    return db_models


def _model_matches_filters(
    model: InferenceModelInfo,
    *,
    owner_user_id: str | None,
    profile_name: str | None,
    policy_type: str | None,
    training_steps: int | None,
    batch_size: int | None,
) -> bool:
    if owner_user_id and model.owner_user_id != owner_user_id:
        return False
    if profile_name and model.profile_name != profile_name:
        return False
    if policy_type and model.policy_type != policy_type:
        return False
    if training_steps is not None and model.training_steps != training_steps:
        return False
    if batch_size is not None and model.batch_size != batch_size:
        return False
    return True


def _merge_models(
    db_models: Sequence[InferenceModelInfo],
    runtime_models: Sequence[InferenceModelInfo],
) -> list[InferenceModelInfo]:
    merged: dict[str, InferenceModelInfo] = {item.model_id: item for item in db_models}
    for local in runtime_models:
        existing = merged.get(local.model_id)
        if existing is None:
            merged[local.model_id] = local
            continue
        merged[local.model_id] = InferenceModelInfo(
            model_id=existing.model_id,
            name=existing.name or local.name,
            created_at=existing.created_at or local.created_at,
            owner_user_id=existing.owner_user_id or local.owner_user_id,
            owner_name=existing.owner_name or local.owner_name,
            profile_name=existing.profile_name or local.profile_name,
            policy_type=local.policy_type or existing.policy_type,
            training_steps=existing.training_steps or local.training_steps,
            batch_size=existing.batch_size or local.batch_size,
            source=existing.source or local.source,
            size_mb=local.size_mb if local.size_mb > 0 else existing.size_mb,
            is_loaded=bool(existing.is_loaded or local.is_loaded),
            is_local=bool(existing.is_local or local.is_local),
            task_candidates=_merge_task_candidates(
                existing.task_candidates,
                local.task_candidates,
            ),
        )

    ordered_models = sorted(
        merged.values(),
        key=lambda item: (item.name or item.model_id).lower(),
    )
    ordered_models.sort(key=lambda item: item.created_at or "", reverse=True)
    return ordered_models


def _build_owner_options(
    models: Sequence[InferenceModelInfo],
) -> list[InferenceOwnerOption]:
    counts: dict[tuple[str, str], int] = {}
    for model in models:
        user_id = str(model.owner_user_id or "").strip()
        if not user_id:
            continue
        label = str(model.owner_name or user_id).strip() or user_id
        key = (user_id, label)
        counts[key] = counts.get(key, 0) + 1
    return [
        InferenceOwnerOption(user_id=user_id, label=label, total_count=total_count)
        for (user_id, label), total_count in sorted(
            counts.items(), key=lambda item: item[0][1].lower()
        )
    ]


def _build_value_options(
    models: Sequence[InferenceModelInfo],
    *,
    value_getter,
) -> list[InferenceValueOption]:
    counts: dict[str, int] = {}
    for model in models:
        value = str(value_getter(model) or "").strip()
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return [
        InferenceValueOption(value=value, label=value, total_count=counts[value])
        for value in sorted(counts.keys(), key=str.lower)
    ]


def _build_numeric_options(
    models: Sequence[InferenceModelInfo],
    *,
    value_getter,
) -> list[InferenceNumericOption]:
    counts: dict[int, int] = {}
    for model in models:
        raw_value = value_getter(model)
        if raw_value is None:
            continue
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if value < 0:
            continue
        counts[value] = counts.get(value, 0) + 1
    return [
        InferenceNumericOption(value=value, label=str(value), total_count=counts[value])
        for value in sorted(counts.keys())
    ]


@router.get("/models", response_model=InferenceModelsResponse)
async def list_models(
    owner_user_id: str | None = None,
    profile_name: str | None = None,
    policy_type: str | None = None,
    training_steps: Annotated[int | None, Query(ge=0)] = None,
    batch_size: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[
        int, Query(ge=1, le=_MAX_MODEL_LIST_LIMIT)
    ] = _DEFAULT_MODEL_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    runtime_models = get_inference_runtime_manager().list_models()
    db_models = await _list_db_models(
        owner_user_id=owner_user_id,
        profile_name=profile_name,
        policy_type=policy_type,
        training_steps=training_steps,
        batch_size=batch_size,
        limit=limit,
        offset=offset,
    )
    models = _merge_models(db_models, runtime_models)
    models = [
        model
        for model in models
        if _model_matches_filters(
            model,
            owner_user_id=owner_user_id,
            profile_name=profile_name,
            policy_type=policy_type,
            training_steps=training_steps,
            batch_size=batch_size,
        )
    ]
    return InferenceModelsResponse(
        models=models,
        owner_options=_build_owner_options(models),
        profile_options=_build_value_options(
            models,
            value_getter=lambda model: model.profile_name,
        ),
        training_steps_options=_build_numeric_options(
            models,
            value_getter=lambda model: model.training_steps,
        ),
        batch_size_options=_build_numeric_options(
            models,
            value_getter=lambda model: model.batch_size,
        ),
    )


@router.get("/runtime-targets", response_model=InferenceRuntimeTargetsResponse)
async def get_runtime_targets(policy_type: str | None = None):
    return get_inference_runtime_targets_service().list_targets(policy_type=policy_type)


@router.get("/runner/status", response_model=InferenceRunnerStatusResponse)
async def get_inference_runner_status():
    manager = get_inference_session_manager()
    runtime_status = get_inference_runtime_manager().get_status()
    recording_status = manager.get_active_recording_status()
    runner_status = runtime_status.runner_status.model_copy(
        update=recording_status,
    )
    model_sync = get_dataset_lifecycle().get_model_sync_status()
    return InferenceRunnerStatusResponse(
        runner_status=runner_status,
        gpu_host_status=runtime_status.gpu_host_status,
        model_sync=model_sync,
    )


@router.get("/runner/diagnostics")
async def get_inference_runner_diagnostics():
    return get_inference_runtime_manager().get_diagnostics()


async def _run_inference_start_operation(
    operation_id: str,
    *,
    model_id: str,
    runtime_target_id: str | None,
    profile: str | None,
    task: str | None,
    num_episodes: int | None,
    policy_options: dict[str, object] | None,
) -> None:
    operations = get_startup_operations_service()
    progress_callback = operations.build_progress_callback(operation_id)
    manager = get_inference_session_manager()
    try:
        state = await manager.create(
            model_id=model_id,
            runtime_target_id=runtime_target_id,
            profile=profile,
            task=task,
            num_episodes=num_episodes,
            policy_options=policy_options,
            progress_callback=progress_callback,
        )
        operations.complete(
            operation_id=operation_id,
            target_session_id=state.extras["worker_session_id"],
            message="推論セッションの準備が完了しました。",
        )
    except HTTPException as exc:
        operations.fail(
            operation_id=operation_id,
            message="推論セッションの準備に失敗しました。",
            error=str(exc.detail),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to UI
        logger.exception("inference startup operation failed: %s", operation_id)
        operations.fail(
            operation_id=operation_id,
            message="推論セッションの準備に失敗しました。",
            error=str(exc),
        )


@router.post(
    "/runner/start",
    response_model=StartupOperationAcceptedResponse,
    status_code=202,
)
async def start_inference_runner(request: InferenceRunnerStartRequest):
    user_id = require_user_id()
    operation = get_startup_operations_service().create(
        user_id=user_id,
        kind="inference_start",
    )
    asyncio.create_task(
        _run_inference_start_operation(
            operation.operation_id,
            model_id=request.model_id,
            runtime_target_id=request.runtime_target_id,
            profile=request.profile,
            task=request.task,
            num_episodes=request.num_episodes,
            policy_options=(
                request.policy_options.model_dump(mode="python", exclude_none=True)
                if request.policy_options
                else None
            ),
        )
    )
    await _emit_inference_control_event(
        action="runner_start",
        phase="accepted",
        session_id="global",
        operation_id=operation.operation_id,
        success=True,
        message="Inference start operation accepted.",
        details={
            "model_id": request.model_id,
            "runtime_target_id": request.runtime_target_id,
            "profile": request.profile,
            "num_episodes": request.num_episodes,
        },
    )
    return operation


@router.post("/runner/stop", response_model=InferenceRunnerStopResponse)
async def stop_inference_runner(request: InferenceRunnerStopRequest):
    mgr = get_inference_session_manager()
    active = mgr.any_active()
    target_session_id = active.id if active else (request.session_id or "")

    if active:
        state = await mgr.stop(active.id)
        stopped = state.extras.get("stopped", False)
    else:
        # Fallback: stop runtime directly (e.g., after server restart)
        runtime = get_inference_runtime_manager()
        try:
            stopped = runtime.stop(session_id=request.session_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to stop inference worker: {exc}"
            ) from exc

    response = InferenceRunnerStopResponse(
        success=True,
        session_id=request.session_id,
        message="inference worker stopped"
        if stopped
        else "inference worker already stopped",
    )
    await _emit_inference_control_event(
        action="runner_stop",
        phase="completed",
        session_id=target_session_id or "global",
        success=True,
        message=response.message,
        details={"stopped": bool(stopped)},
    )
    return response


@router.post(
    "/runner/settings/apply",
    response_model=InferenceRunnerSettingsApplyResponse,
)
async def apply_inference_runner_settings(request: InferenceRunnerSettingsApplyRequest):
    require_user_id()
    if (
        request.task is None
        and request.episode_time_s is None
        and request.reset_time_s is None
        and request.denoising_steps is None
    ):
        raise HTTPException(status_code=400, detail="No settings provided")

    manager = get_inference_session_manager()
    active = manager.any_active()
    active_session_id = active.id if active else "global"
    try:
        settings = await manager.apply_active_settings(
            task=request.task,
            episode_time_s=request.episode_time_s,
            reset_time_s=request.reset_time_s,
            denoising_steps=request.denoising_steps,
        )
    except HTTPException as exc:
        await _emit_inference_control_event(
            action="runner_settings_apply",
            phase="failed",
            session_id=active_session_id,
            success=False,
            message=str(exc.detail),
        )
        raise
    except Exception as exc:
        await _emit_inference_control_event(
            action="runner_settings_apply",
            phase="failed",
            session_id=active_session_id,
            success=False,
            message=str(exc),
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to apply settings: {exc}"
        ) from exc

    response = InferenceRunnerSettingsApplyResponse(
        success=True,
        message="Inference settings applied",
        task=settings.get("task"),
        episode_time_s=settings.get("episode_time_s"),
        reset_time_s=settings.get("reset_time_s"),
        denoising_steps=settings.get("denoising_steps"),
    )
    await _emit_inference_control_event(
        action="runner_settings_apply",
        phase="completed",
        session_id=active_session_id,
        success=True,
        message=response.message,
        details={
            "task": response.task,
            "episode_time_s": response.episode_time_s,
            "reset_time_s": response.reset_time_s,
            "denoising_steps": response.denoising_steps,
        },
    )
    return response


@router.post(
    "/runner/recording/decision",
    response_model=InferenceRecordingDecisionResponse,
)
async def decide_inference_recording(request: InferenceRecordingDecisionRequest):
    require_user_id()
    manager = get_inference_session_manager()
    active = manager.any_active()
    active_session_id = active.id if active else "global"
    if not request.continue_recording and request.stop_reason is None:
        raise HTTPException(
            status_code=400,
            detail="stop_reason is required when continue_recording is false",
        )
    stop_reason = request.stop_reason if not request.continue_recording else None

    if request.continue_recording:
        try:
            decision = await manager.decide_active_recording_continue(
                continue_recording=True
            )
        except HTTPException as exc:
            await _emit_inference_control_event(
                action="recording_decision",
                phase="failed",
                session_id=active_session_id,
                success=False,
                message=str(exc.detail),
                details={"continue_recording": True},
            )
            raise
        except Exception as exc:
            await _emit_inference_control_event(
                action="recording_decision",
                phase="failed",
                session_id=active_session_id,
                success=False,
                message=str(exc),
                details={"continue_recording": True},
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to continue inference recording: {exc}",
            ) from exc
        response = InferenceRecordingDecisionResponse(
            success=True,
            message="Additional recording batch started.",
            recording_dataset_id=decision.get("recording_dataset_id"),
            awaiting_continue_confirmation=bool(
                decision.get("awaiting_continue_confirmation", False)
            ),
            stop_reason=None,
        )
        await _emit_inference_control_event(
            action="recording_decision",
            phase="completed",
            session_id=active_session_id,
            success=True,
            message=response.message,
            details={
                "continue_recording": True,
                "recording_dataset_id": response.recording_dataset_id,
            },
        )
        return response

    if active:
        await manager.stop(active.id)
    response = InferenceRecordingDecisionResponse(
        success=True,
        message="Inference and recording stopped.",
        recording_dataset_id=None,
        awaiting_continue_confirmation=False,
        stop_reason=stop_reason,
    )
    await _emit_inference_control_event(
        action="recording_decision",
        phase="completed",
        session_id=active_session_id,
        success=True,
        message=response.message,
        details={"continue_recording": False, "stop_reason": stop_reason},
    )
    return response


@router.post("/runner/pause", response_model=InferenceRunnerControlResponse)
async def pause_inference_runner():
    require_user_id()
    manager = get_inference_session_manager()
    active = manager.any_active()
    active_session_id = active.id if active else "global"
    try:
        result = await manager.pause_active_recording_and_inference()
    except HTTPException as exc:
        await _emit_inference_control_event(
            action="runner_pause",
            phase="failed",
            session_id=active_session_id,
            success=False,
            message=str(exc.detail),
        )
        raise
    except Exception as exc:
        await _emit_inference_control_event(
            action="runner_pause",
            phase="failed",
            session_id=active_session_id,
            success=False,
            message=str(exc),
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to pause inference runner: {exc}"
        ) from exc
    response = InferenceRunnerControlResponse(
        success=True,
        message="Inference and recording paused.",
        paused=bool(result.get("paused", False)),
        teleop_enabled=bool(result.get("teleop_enabled", False)),
        recorder_state=str(result.get("recorder_state") or "") or None,
    )
    await _emit_inference_control_event(
        action="runner_pause",
        phase="completed",
        session_id=active_session_id,
        success=True,
        message=response.message,
        details={
            "paused": response.paused,
            "teleop_enabled": response.teleop_enabled,
            "recorder_state": response.recorder_state,
        },
    )
    return response


@router.post("/runner/resume", response_model=InferenceRunnerControlResponse)
async def resume_inference_runner():
    require_user_id()
    manager = get_inference_session_manager()
    active = manager.any_active()
    active_session_id = active.id if active else "global"
    try:
        result = await manager.resume_active_recording_and_inference()
    except HTTPException as exc:
        await _emit_inference_control_event(
            action="runner_resume",
            phase="failed",
            session_id=active_session_id,
            success=False,
            message=str(exc.detail),
        )
        raise
    except Exception as exc:
        await _emit_inference_control_event(
            action="runner_resume",
            phase="failed",
            session_id=active_session_id,
            success=False,
            message=str(exc),
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to resume inference runner: {exc}"
        ) from exc
    started = bool(result.get("started", False))
    response = InferenceRunnerControlResponse(
        success=True,
        message="Inference and recording started."
        if started
        else "Inference and recording resumed.",
        paused=bool(result.get("paused", False)),
        teleop_enabled=bool(result.get("teleop_enabled", False)),
        recorder_state=str(result.get("recorder_state") or "") or None,
    )
    await _emit_inference_control_event(
        action="runner_resume",
        phase="completed",
        session_id=active_session_id,
        success=True,
        message=response.message,
        details={
            "paused": response.paused,
            "teleop_enabled": response.teleop_enabled,
            "recorder_state": response.recorder_state,
        },
    )
    return response


@router.post("/runner/task", response_model=InferenceSetTaskResponse)
async def set_inference_task(request: InferenceSetTaskRequest):
    task = request.task.strip()
    if not task:
        raise HTTPException(status_code=400, detail="task must not be empty")

    try:
        applied_from_step = get_inference_runtime_manager().set_task(
            session_id=request.session_id, task=task
        )
    except RuntimeError as exc:
        await _emit_inference_control_event(
            action="runner_task_set",
            phase="failed",
            session_id=request.session_id,
            success=False,
            message=str(exc),
            details={"task": task},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await _emit_inference_control_event(
            action="runner_task_set",
            phase="failed",
            session_id=request.session_id,
            success=False,
            message=str(exc),
            details={"task": task},
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to update task: {exc}"
        ) from exc

    response = InferenceSetTaskResponse(
        success=True,
        session_id=request.session_id,
        task=task,
        applied_from_step=applied_from_step,
    )
    await _emit_inference_control_event(
        action="runner_task_set",
        phase="completed",
        session_id=request.session_id,
        success=True,
        message="Inference task updated.",
        details={"task": task, "applied_from_step": applied_from_step},
    )
    return response

"""Persistent training provision operation tracking."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException
from supabase._async.client import AsyncClient

from interfaces_backend.models.training import (
    JobCreateRequest,
    TrainingProvisionOperationCompletedEvent,
    TrainingProvisionOperationEvent,
    TrainingProvisionOperationFailedEvent,
    TrainingProvisionOperationProgressEvent,
    TrainingProvisionOperationAcceptedResponse,
    TrainingProvisionOperationStatusResponse,
)
from interfaces_backend.models.realtime_payloads import TrainingJobProvisionRealtimeDetail
from interfaces_backend.services.realtime_runtime import UserID, get_realtime_runtime
from percus_ai.db import get_supabase_async_client, get_supabase_service_client_required
from percus_ai.training.providers.vast import destroy_instance
from percus_ai.training.providers.verda import VerdaProvider

logger = logging.getLogger(__name__)

TRAINING_PROVISION_OPERATION_TABLE = "training_provision_operations"
_ACTIVE_STATES = {"queued", "running"}
_TERMINAL_STATES = {"completed", "failed", "cancelled"}
_STALE_TIMEOUT_MINUTES = int(os.environ.get("TRAINING_PROVISION_STALE_TIMEOUT_MINUTES", "15"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _step_from_provision_progress_type(progress_type: str) -> str:
    mapping = {
        "start": "validate",
        "validating": "validate",
        "validated": "validate",
        "selecting_instance": "select_candidate",
        "instance_selected": "select_candidate",
        "finding_location": "select_candidate",
        "location_found": "select_candidate",
        "creating_instance": "create_instance",
        "instance_created": "create_instance",
        "waiting_ip": "wait_ip",
        "ip_assigned": "wait_ip",
        "waiting_running": "wait_ip",
        "instance_running": "wait_ip",
        "connecting_ssh": "connect_ssh",
        "ssh_ready": "connect_ssh",
        "deploying": "deploy_files",
        "setting_up": "setup_env",
        "starting_training": "start_training",
        "cleaning_up": "cleanup",
        "job_created": "job_created",
    }
    return mapping.get(progress_type, progress_type or "running")


def _identity_patch_from_event(
    event: TrainingProvisionOperationEvent,
) -> dict[str, str | None]:
    patch: dict[str, str | None] = {}
    if event.instance_id is not None:
        patch["instance_id"] = str(event.instance_id or "").strip() or None
    if event.job_id is not None:
        patch["job_id"] = str(event.job_id or "").strip() or None
    return patch


def cleanup_provision_instance(provider: str, instance_id: str) -> tuple[bool, str]:
    try:
        if provider == "vast":
            destroy_instance(instance_id)
            return True, "Vast instance deleted"
        if provider == "verda":
            VerdaProvider().delete_instance(instance_id)
            return True, "Verda instance deleted"
        return False, f"Unknown provider: {provider}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to cleanup stale provision instance %s/%s: %s", provider, instance_id, exc)
        return False, str(exc)


class TrainingProvisionOperationsService:
    async def create(
        self,
        *,
        user_id: str,
        request: JobCreateRequest,
    ) -> TrainingProvisionOperationAcceptedResponse:
        operation_id = uuid4().hex
        now = _utcnow_iso()
        payload = request.model_dump(mode="python")
        record = {
            "operation_id": operation_id,
            "owner_user_id": user_id,
            "state": "queued",
            "step": "queued",
            "message": "学習インスタンス作成を受け付けました。",
            "failure_reason": None,
            "provider": request.cloud.provider,
            "request_payload": payload,
            "instance_id": None,
            "job_id": None,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        await self._upsert(record)
        snapshot = self._row_to_response(record)
        detail = snapshot.model_dump(mode="json")
        runtime = get_realtime_runtime()
        runtime.track(
            scope=UserID(user_id),
            kind="training.provision-operation",
            key=snapshot.operation_id,
        ).replace(detail)
        if snapshot.job_id:
            runtime.track(
                scope=UserID(user_id),
                kind="training.job.provision",
                key=snapshot.job_id,
            ).replace(
                TrainingJobProvisionRealtimeDetail(provision_operation=snapshot).model_dump(mode="json")
            )
        return TrainingProvisionOperationAcceptedResponse(
            accepted=True,
            operation_id=operation_id,
            state="queued",
            message="accepted",
        )

    async def get(
        self,
        *,
        user_id: str,
        operation_id: str,
    ) -> TrainingProvisionOperationStatusResponse:
        row = await self._load(operation_id, owner_user_id=user_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Provision operation not found: {operation_id}")
        return self._row_to_response(row)

    async def get_system(self, *, operation_id: str) -> Optional[TrainingProvisionOperationStatusResponse]:
        row = await self._load(operation_id, owner_user_id=None)
        if row is None:
            return None
        return self._row_to_response(row)

    async def get_for_job_system(
        self,
        *,
        job_id: str,
    ) -> Optional[TrainingProvisionOperationStatusResponse]:
        row = await self._load_by_job_id(job_id, owner_user_id=None)
        if row is None:
            return None
        return self._row_to_response(row)

    async def set_running(
        self,
        *,
        operation_id: str,
        step: str,
        message: str,
    ) -> None:
        await self._update(
            operation_id=operation_id,
            state="running",
            step=step,
            message=message,
            started_at=_utcnow_iso(),
            failure_reason=None,
        )

    async def complete(
        self,
        *,
        operation_id: str,
        message: str = "学習開始までの初期化が完了しました。",
    ) -> None:
        await self._update(
            operation_id=operation_id,
            state="completed",
            step="completed",
            message=message,
            finished_at=_utcnow_iso(),
        )

    async def fail(
        self,
        *,
        operation_id: str,
        message: str,
        failure_reason: str,
    ) -> None:
        await self._update(
            operation_id=operation_id,
            state="failed",
            step="failed",
            message=message,
            failure_reason=failure_reason,
            finished_at=_utcnow_iso(),
        )

    async def update_from_event(self, *, operation_id: str, event: TrainingProvisionOperationEvent) -> None:
        if isinstance(event, TrainingProvisionOperationProgressEvent):
            await self._update_from_progress_event(operation_id=operation_id, event=event)
            return
        if isinstance(event, TrainingProvisionOperationCompletedEvent):
            await self._update_from_completed_event(operation_id=operation_id, event=event)
            return
        if isinstance(event, TrainingProvisionOperationFailedEvent):
            await self._update_from_failed_event(operation_id=operation_id, event=event)
            return
        raise TypeError(f"Unsupported training provision operation event: {type(event).__name__}")

    async def _update_from_progress_event(
        self,
        *,
        operation_id: str,
        event: TrainingProvisionOperationProgressEvent,
    ) -> None:
        progress_type = str(event.type or "").strip()
        if not progress_type:
            return

        patch: dict[str, Any] = {
            "step": _step_from_provision_progress_type(progress_type),
            "message": str(event.message or event.error or "").strip() or None,
            "state": "running",
            "failure_reason": None,
        }
        patch.update(_identity_patch_from_event(event))

        if progress_type == "job_created":
            patch["step"] = "job_created"
            patch["message"] = patch["message"] or "学習ジョブを作成しました。"

        await self._update(operation_id=operation_id, **patch)

    async def _update_from_completed_event(
        self,
        *,
        operation_id: str,
        event: TrainingProvisionOperationCompletedEvent,
    ) -> None:
        patch: dict[str, Any] = {
            "state": "completed",
            "step": "completed",
            "message": str(event.message or "").strip() or None,
            "finished_at": _utcnow_iso(),
        }
        patch.update(_identity_patch_from_event(event))
        await self._update(operation_id=operation_id, **patch)

    async def _update_from_failed_event(
        self,
        *,
        operation_id: str,
        event: TrainingProvisionOperationFailedEvent,
    ) -> None:
        error = str(event.error or "").strip() or "provision_failed"
        patch: dict[str, Any] = {
            "state": "failed",
            "step": "failed",
            "message": str(event.message or error).strip() or None,
            "failure_reason": error,
            "finished_at": _utcnow_iso(),
        }
        patch.update(_identity_patch_from_event(event))
        await self._update(operation_id=operation_id, **patch)

    async def _load(self, operation_id: str, *, owner_user_id: str | None) -> Optional[dict[str, Any]]:
        async def _fetch_with(client: AsyncClient) -> list[dict[str, Any]]:
            query = client.table(TRAINING_PROVISION_OPERATION_TABLE).select("*").eq("operation_id", operation_id)
            if owner_user_id:
                query = query.eq("owner_user_id", owner_user_id)
            response = await query.execute()
            return response.data or []

        client = (
            await get_supabase_async_client()
            if owner_user_id
            else await get_supabase_service_client_required()
        )
        rows = await _fetch_with(client)
        return rows[0] if rows else None

    async def _load_by_job_id(self, job_id: str, *, owner_user_id: str | None) -> Optional[dict[str, Any]]:
        async def _fetch_with(client: AsyncClient) -> list[dict[str, Any]]:
            query = client.table(TRAINING_PROVISION_OPERATION_TABLE).select("*").eq("job_id", job_id)
            if owner_user_id:
                query = query.eq("owner_user_id", owner_user_id)
            response = await query.execute()
            return response.data or []

        client = (
            await get_supabase_async_client()
            if owner_user_id
            else await get_supabase_service_client_required()
        )
        rows = await _fetch_with(client)
        return rows[0] if rows else None

    async def _upsert(self, record: dict[str, Any]) -> None:
        operation_id = str(record.get("operation_id") or "").strip()
        if not operation_id:
            raise ValueError("operation_id is required")

        async def _upsert_with(client: AsyncClient) -> None:
            existing = (
                await client.table(TRAINING_PROVISION_OPERATION_TABLE)
                .select("operation_id")
                .eq("operation_id", operation_id)
                .execute()
            ).data or []
            if existing:
                update_record = {
                    key: value
                    for key, value in record.items()
                    if key not in {"operation_id", "owner_user_id"}
                }
                if update_record:
                    await client.table(TRAINING_PROVISION_OPERATION_TABLE).update(update_record).eq(
                        "operation_id", operation_id
                    ).execute()
                return
            await client.table(TRAINING_PROVISION_OPERATION_TABLE).insert(record).execute()

        await _upsert_with(await get_supabase_service_client_required())

    async def _update(self, *, operation_id: str, **patch: Any) -> None:
        await self._update_with_client(
            await get_supabase_service_client_required(),
            operation_id=operation_id,
            patch=patch,
        )
        row = await self._load(operation_id, owner_user_id=None)
        if row is None:
            return
        user_id = str(row.get("owner_user_id") or "").strip()
        if not user_id:
            return
        snapshot = self._row_to_response(row)
        detail = snapshot.model_dump(mode="json")
        runtime = get_realtime_runtime()
        runtime.track(
            scope=UserID(user_id),
            kind="training.provision-operation",
            key=snapshot.operation_id,
        ).replace(detail)
        if snapshot.job_id:
            runtime.track(
                scope=UserID(user_id),
                kind="training.job.provision",
                key=snapshot.job_id,
            ).replace(
                TrainingJobProvisionRealtimeDetail(provision_operation=snapshot).model_dump(mode="json")
            )

    @staticmethod
    async def _update_with_client(
        client: AsyncClient,
        *,
        operation_id: str,
        patch: dict[str, Any],
    ) -> None:
        row_patch = {key: value for key, value in patch.items() if value is not None or key in patch}
        row_patch["updated_at"] = _utcnow_iso()
        await client.table(TRAINING_PROVISION_OPERATION_TABLE).update(row_patch).eq(
            "operation_id", operation_id
        ).execute()

    @staticmethod
    def _row_to_response(row: dict[str, Any]) -> TrainingProvisionOperationStatusResponse:
        return TrainingProvisionOperationStatusResponse(
            operation_id=str(row.get("operation_id") or ""),
            state=str(row.get("state") or "queued"),
            step=str(row.get("step") or "queued"),
            message=row.get("message"),
            failure_reason=row.get("failure_reason"),
            provider=str(row.get("provider") or "verda"),
            instance_id=row.get("instance_id"),
            job_id=row.get("job_id"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        )

_service: TrainingProvisionOperationsService | None = None


def get_training_provision_operations_service() -> TrainingProvisionOperationsService:
    global _service
    if _service is None:
        _service = TrainingProvisionOperationsService()
    return _service


def reset_training_provision_operations_service() -> None:
    global _service
    _service = None

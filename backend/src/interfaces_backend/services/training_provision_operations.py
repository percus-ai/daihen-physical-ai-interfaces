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
    TrainingProvisionOperationAcceptedResponse,
    TrainingProvisionOperationStatusResponse,
)
from percus_ai.db import get_supabase_async_client
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


def _cleanup_step_from_progress(progress_type: str) -> str:
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
        "job_created": "job_created",
        "complete": "completed",
        "error": "failed",
    }
    return mapping.get(progress_type, progress_type or "running")


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

    async def get_for_job(
        self,
        *,
        user_id: str,
        job_id: str,
    ) -> Optional[TrainingProvisionOperationStatusResponse]:
        row = await self._load_by_job_id(job_id, owner_user_id=user_id)
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

    async def update_from_progress(self, *, operation_id: str, progress: dict[str, Any]) -> None:
        progress_type = str(progress.get("type") or "").strip()
        if not progress_type:
            return

        patch: dict[str, Any] = {
            "step": _cleanup_step_from_progress(progress_type),
            "message": str(progress.get("message") or progress.get("error") or "").strip() or None,
        }

        if progress_type == "error":
            patch["state"] = "failed"
            patch["failure_reason"] = str(progress.get("error") or "provision_failed")
            patch["finished_at"] = _utcnow_iso()
        elif progress_type == "complete":
            patch["state"] = "completed"
            patch["step"] = "completed"
            patch["finished_at"] = _utcnow_iso()
        else:
            patch["state"] = "running"
            patch["failure_reason"] = None

        if progress.get("instance_id") is not None:
            patch["instance_id"] = str(progress.get("instance_id") or "").strip() or None
        if progress.get("job_id") is not None:
            patch["job_id"] = str(progress.get("job_id") or "").strip() or None
        if progress_type == "job_created":
            patch["job_id"] = str(progress.get("job_id") or "").strip() or patch.get("job_id")
            patch["step"] = "job_created"
            patch["message"] = patch["message"] or "学習ジョブを作成しました。"

        await self._update(operation_id=operation_id, **patch)

    async def _load(self, operation_id: str, *, owner_user_id: str | None) -> Optional[dict[str, Any]]:
        async def _fetch_with(client: AsyncClient) -> list[dict[str, Any]]:
            query = client.table(TRAINING_PROVISION_OPERATION_TABLE).select("*").eq("operation_id", operation_id)
            if owner_user_id:
                query = query.eq("owner_user_id", owner_user_id)
            response = await query.execute()
            return response.data or []

        rows = await _fetch_with(await get_supabase_async_client())
        return rows[0] if rows else None

    async def _load_by_job_id(self, job_id: str, *, owner_user_id: str | None) -> Optional[dict[str, Any]]:
        async def _fetch_with(client: AsyncClient) -> list[dict[str, Any]]:
            query = client.table(TRAINING_PROVISION_OPERATION_TABLE).select("*").eq("job_id", job_id)
            if owner_user_id:
                query = query.eq("owner_user_id", owner_user_id)
            response = await query.execute()
            return response.data or []

        rows = await _fetch_with(await get_supabase_async_client())
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

        await _upsert_with(await get_supabase_async_client())

    async def _update(self, *, operation_id: str, **patch: Any) -> None:
        await self._update_with_client(
            await get_supabase_async_client(),
            operation_id=operation_id,
            patch=patch,
        )
        snapshot = await self.get_system(operation_id=operation_id)
        if snapshot is None:
            return None
        await self._publish(snapshot)

    async def _publish(self, snapshot: TrainingProvisionOperationStatusResponse) -> None:
        del snapshot
        return None

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

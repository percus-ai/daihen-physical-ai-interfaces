"""Background recovery for stale training provision operations."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import timedelta
from typing import Any

from percus_ai.db import get_supabase_service_client
from interfaces_backend.services.training_provision_operations import (
    _ACTIVE_STATES,
    _STALE_TIMEOUT_MINUTES,
    _utcnow,
    _utcnow_iso,
    TRAINING_PROVISION_OPERATION_TABLE,
    TrainingProvisionOperationsService,
    cleanup_provision_instance,
    get_training_provision_operations_service,
)

logger = logging.getLogger(__name__)

_DISABLE_RECOVERY_ENV = "PHI_DISABLE_TRAINING_PROVISION_RECOVERY"
_RECOVERY_RETRY_SECONDS_ENV = "TRAINING_PROVISION_RECOVERY_RETRY_SECONDS"
_PUBLISH_RETRY_COUNT_ENV = "TRAINING_PROVISION_RECOVERY_PUBLISH_RETRY_COUNT"


async def _get_recovery_db_client():
    return await get_supabase_service_client()


def _recovery_disabled() -> bool:
    raw = str(os.environ.get(_DISABLE_RECOVERY_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _recovery_retry_seconds() -> float:
    raw = str(os.environ.get(_RECOVERY_RETRY_SECONDS_ENV) or "").strip()
    if not raw:
        return 30.0
    try:
        return max(float(raw), 0.0)
    except ValueError:
        logger.warning("Invalid %s=%r; fallback to 30s", _RECOVERY_RETRY_SECONDS_ENV, raw)
        return 30.0


def _publish_retry_count() -> int:
    raw = str(os.environ.get(_PUBLISH_RETRY_COUNT_ENV) or "").strip()
    if not raw:
        return 3
    try:
        return max(int(raw), 1)
    except ValueError:
        logger.warning("Invalid %s=%r; fallback to 3", _PUBLISH_RETRY_COUNT_ENV, raw)
        return 3


class TrainingProvisionRecoveryService:
    def __init__(self, operations_service: TrainingProvisionOperationsService | None = None) -> None:
        self._operations_service = operations_service or get_training_provision_operations_service()
        self._lock = threading.RLock()
        self._task: asyncio.Task[None] | None = None

    def ensure_started(self) -> None:
        if _recovery_disabled():
            logger.info("Training provision recovery disabled via %s", _DISABLE_RECOVERY_ENV)
            return
        with self._lock:
            if self._task is not None and not self._task.done():
                return
            self._task = asyncio.create_task(
                self._run_until_stable(),
                name="training-provision-recovery",
            )

    async def shutdown(self) -> None:
        with self._lock:
            task = self._task
            self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run_until_stable(self) -> None:
        while True:
            should_retry = await self._run_recovery_pass()
            if not should_retry:
                return
            await asyncio.sleep(_recovery_retry_seconds())

    async def _run_recovery_pass(self) -> bool:
        try:
            service_client = await _get_recovery_db_client()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to initialize training provision recovery client")
            return True
        if service_client is None:
            logger.warning("SUPABASE_SECRET_KEY is not configured; skip stale training provision recovery")
            return False

        rows = await self._load_stale_rows(service_client)
        if rows is None:
            return True

        should_retry = False
        for row in rows:
            recovered = await self._recover_row(service_client, row)
            should_retry = should_retry or not recovered
        return should_retry

    async def _load_stale_rows(self, service_client) -> list[dict[str, Any]] | None:
        cutoff = (_utcnow() - timedelta(minutes=_STALE_TIMEOUT_MINUTES)).isoformat()
        try:
            response = await (
                service_client.table(TRAINING_PROVISION_OPERATION_TABLE)
                .select("*")
                .in_("state", list(_ACTIVE_STATES))
                .lt("updated_at", cutoff)
                .execute()
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to fetch stale training provision operations")
            return None
        return response.data or []

    async def _recover_row(self, service_client, row: dict[str, Any]) -> bool:
        operation_id = str(row.get("operation_id") or "").strip()
        if not operation_id:
            return True

        try:
            patch = await self._build_failure_patch(row)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Training provision recovery failed while preparing cleanup for operation_id=%s",
                operation_id,
            )
            return False

        try:
            await self._operations_service._update_with_client(
                service_client,
                operation_id=operation_id,
                patch=patch,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Training provision recovery failed while updating operation_id=%s",
                operation_id,
            )
            return False

        snapshot_row = dict(row)
        snapshot_row.update(patch)
        snapshot_row["updated_at"] = _utcnow_iso()
        snapshot = self._operations_service._row_to_response(snapshot_row)
        if not await self._publish_with_retry(snapshot):
            logger.warning(
                "Training provision recovery could not publish operation_id=%s after retries",
                operation_id,
            )

        logger.warning(
            "Recovered stale training provision operation on backend startup: operation_id=%s",
            operation_id,
        )
        return True

    async def _build_failure_patch(self, row: dict[str, Any]) -> dict[str, Any]:
        provider = str(row.get("provider") or "").strip().lower()
        instance_id = str(row.get("instance_id") or "").strip()
        job_id = str(row.get("job_id") or "").strip()
        message = "バックエンド再起動によりプロビジョニングが中断されました。"

        if instance_id and not job_id:
            deleted, detail = cleanup_provision_instance(provider, instance_id)
            if deleted:
                message = "バックエンド再起動により中断されたため、作成中インスタンスをクリーンアップしました。"
            else:
                message = (
                    "バックエンド再起動により中断され、作成中インスタンスのクリーンアップに失敗しました。 "
                    f"({detail})"
                )
        elif job_id:
            message = (
                "バックエンド再起動により作成進行の追跡が中断されました。"
                " ジョブ詳細画面から状態を確認してください。"
            )

        return {
            "state": "failed",
            "step": "failed",
            "message": message,
            "failure_reason": "backend_restart_cleanup",
            "finished_at": _utcnow_iso(),
        }

    async def _publish_with_retry(self, snapshot) -> bool:
        attempts = _publish_retry_count()
        for attempt in range(1, attempts + 1):
            try:
                await self._operations_service._publish(snapshot)
                return True
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Training provision recovery publish failed for operation_id=%s (attempt %d/%d)",
                    snapshot.operation_id,
                    attempt,
                    attempts,
                )
                if attempt < attempts:
                    await asyncio.sleep(_recovery_retry_seconds())
        return False


_service: TrainingProvisionRecoveryService | None = None


def get_training_provision_recovery_service() -> TrainingProvisionRecoveryService:
    global _service
    if _service is None:
        _service = TrainingProvisionRecoveryService()
    return _service


def reset_training_provision_recovery_service() -> None:
    global _service
    _service = None

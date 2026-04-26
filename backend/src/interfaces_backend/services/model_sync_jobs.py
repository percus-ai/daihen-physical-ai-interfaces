"""In-memory model sync job tracking for storage sync operations.

This service allows enqueueing multiple model sync jobs while running them
sequentially in a single background worker per backend environment.
"""

from __future__ import annotations

import asyncio
from collections import deque
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException

from percus_ai.storage.r2_db_sync import R2DBSyncService, StorageSyncCancelledError

from interfaces_backend.models.storage import (
    ModelSyncJobAcceptedResponse,
    ModelSyncJobCancelResponse,
    ModelSyncJobDetail,
    ModelSyncJobListResponse,
    ModelSyncJobState,
    ModelSyncJobStatus,
)
from interfaces_backend.services.realtime_runtime import UserID, get_realtime_runtime
_ACTIVE_STATES: set[ModelSyncJobState] = {"queued", "running"}
_TERMINAL_STATES: set[ModelSyncJobState] = {"completed", "failed", "cancelled"}
_DEFAULT_TTL_SECONDS = 1800

ProgressCallback = Callable[[dict[str, Any]], None]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _JobRecord:
    job_id: str
    user_id: str
    model_id: str
    state: ModelSyncJobState = "queued"
    progress_percent: float = 0.0
    message: str | None = None
    error: str | None = None
    detail: ModelSyncJobDetail = field(default_factory=ModelSyncJobDetail)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_response(self) -> ModelSyncJobStatus:
        return ModelSyncJobStatus(
            job_id=self.job_id,
            model_id=self.model_id,
            state=self.state,
            progress_percent=self.progress_percent,
            message=self.message,
            error=self.error,
            detail=self.detail.model_copy(deep=True),
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
        )


class ModelSyncJobsService:
    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._jobs: dict[str, _JobRecord] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._pending: deque[str] = deque()
        self._worker_task: asyncio.Task[None] | None = None
        self._pending_event: asyncio.Event | None = None

    def create(
        self,
        *,
        user_id: str,
        model_id: str,
    ) -> ModelSyncJobAcceptedResponse:
        snapshot: ModelSyncJobStatus
        with self._lock:
            self._cleanup_locked()
            for job in self._jobs.values():
                if (
                    job.user_id == user_id
                    and job.model_id == model_id
                    and job.state in _ACTIVE_STATES
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="A model sync job is already in progress",
                    )

            job_id = uuid4().hex
            now = _utcnow()
            record = _JobRecord(
                job_id=job_id,
                user_id=user_id,
                model_id=model_id,
                state="queued",
                message="モデル同期ジョブを受け付けました。",
                created_at=now,
                updated_at=now,
            )
            self._jobs[job_id] = record
            self._cancel_events[job_id] = threading.Event()
            self._pending.append(job_id)
            if self._pending_event is not None:
                self._pending_event.set()
            snapshot = record.to_response()
        get_realtime_runtime().track(
            scope=UserID(user_id),
            kind="storage.model-sync",
            key=snapshot.job_id,
        ).replace(snapshot.model_dump(mode="json"))
        return ModelSyncJobAcceptedResponse(
            job_id=job_id,
            model_id=model_id,
            state="queued",
            message="accepted",
        )

    def ensure_worker(self) -> None:
        """Ensure the background worker is running (best-effort).

        Must be called from within an active asyncio event loop.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        with self._lock:
            if self._worker_task is not None and not self._worker_task.done():
                return
            if self._pending_event is None:
                self._pending_event = asyncio.Event()
            self._worker_task = loop.create_task(self._worker_loop(), name="model-sync-worker")

    def list(self, *, user_id: str, include_terminal: bool = False) -> ModelSyncJobListResponse:
        with self._lock:
            self._cleanup_locked()
            jobs = []
            for job in self._jobs.values():
                if job.user_id != user_id:
                    continue
                if not include_terminal and job.state in _TERMINAL_STATES:
                    continue
                jobs.append(job.to_response())
        jobs.sort(key=lambda job: str(job.updated_at or ""), reverse=True)
        return ModelSyncJobListResponse(jobs=jobs)

    def get(self, *, user_id: str, job_id: str) -> ModelSyncJobStatus:
        with self._lock:
            self._cleanup_locked()
            return self._get_for_user_locked(user_id=user_id, job_id=job_id).to_response()

    def cancel(self, *, user_id: str, job_id: str) -> ModelSyncJobCancelResponse:
        snapshot: ModelSyncJobStatus | None = None
        with self._lock:
            self._cleanup_locked()
            record = self._get_for_user_locked(user_id=user_id, job_id=job_id)
            if record.state in _TERMINAL_STATES:
                return ModelSyncJobCancelResponse(
                    job_id=record.job_id,
                    accepted=False,
                    state=record.state,
                    message="Job is already finished.",
                )
            cancel_event = self._cancel_events.get(job_id)
            if cancel_event is None:
                cancel_event = threading.Event()
                self._cancel_events[job_id] = cancel_event
            cancel_event.set()
            if record.state == "queued":
                record.state = "cancelled"
                record.progress_percent = 0.0
                record.message = "モデル同期を中断しました。"
                record.error = None
            else:
                record.message = "モデル同期の中断を要求しました。"
            record.updated_at = _utcnow()
            snapshot = record.to_response()
        if snapshot is not None:
            get_realtime_runtime().track(
                scope=UserID(user_id),
                kind="storage.model-sync",
                key=snapshot.job_id,
            ).replace(snapshot.model_dump(mode="json"))
        return ModelSyncJobCancelResponse(
            job_id=snapshot.job_id,
            accepted=True,
            state=snapshot.state,
            message=snapshot.message or "Cancel requested.",
        )

    async def _worker_loop(self) -> None:
        """Process queued jobs sequentially."""
        while True:
            job_id: str | None = None
            pending_event: asyncio.Event | None = None
            with self._lock:
                self._cleanup_locked()
                while self._pending:
                    candidate = self._pending.popleft()
                    record = self._jobs.get(candidate)
                    if record is None:
                        continue
                    if record.state in _TERMINAL_STATES:
                        continue
                    job_id = candidate
                    break
                if job_id is None:
                    pending_event = self._pending_event

            if job_id is None:
                if pending_event is None:
                    await asyncio.sleep(0.5)
                    continue
                await pending_event.wait()
                pending_event.clear()
                continue

            await self._run_job(job_id)

    async def _run_job(self, job_id: str) -> None:
        jobs = self
        record: _JobRecord | None = None
        cancel_event: threading.Event | None = None
        with self._lock:
            record = self._jobs.get(job_id)
            cancel_event = self._cancel_events.get(job_id)

        if record is None:
            return
        if record.state in _TERMINAL_STATES:
            return

        sync_service = R2DBSyncService()
        progress_callback = jobs.build_progress_callback(job_id=job_id)

        # Mark as running (progress callback will update it further).
        jobs.set_running(job_id=job_id, progress_percent=0.0, message="モデル同期を開始しました。")

        try:
            result = await sync_service.ensure_model_local(
                record.model_id,
                auto_download=True,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )
        except StorageSyncCancelledError:
            jobs.cancelled(job_id=job_id)
            return
        except Exception as exc:
            jobs.fail(
                job_id=job_id,
                message="モデル同期に失敗しました。",
                error=str(exc),
            )
            return

        if result.success:
            jobs.complete(
                job_id=job_id,
                message="ローカルキャッシュを利用しました。" if result.skipped else "モデル同期が完了しました。",
            )
            return
        if result.cancelled:
            jobs.cancelled(job_id=job_id)
            return
        jobs.fail(
            job_id=job_id,
            message="モデル同期に失敗しました。",
            error=result.message,
        )

    def set_running(
        self,
        *,
        job_id: str,
        progress_percent: float,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._update(
            job_id=job_id,
            state="running",
            progress_percent=progress_percent,
            message=message,
            error=None,
            detail=detail,
        )

    def complete(self, *, job_id: str, message: str) -> None:
        self._update(
            job_id=job_id,
            state="completed",
            progress_percent=100.0,
            message=message,
            error=None,
        )

    def fail(self, *, job_id: str, message: str, error: str) -> None:
        self._update(
            job_id=job_id,
            state="failed",
            progress_percent=100.0,
            message=message,
            error=error,
        )

    def cancelled(self, *, job_id: str, message: str = "モデル同期を中断しました。") -> None:
        self._update(
            job_id=job_id,
            state="cancelled",
            message=message,
            error=None,
        )

    def build_progress_callback(self, *, job_id: str) -> ProgressCallback:
        def _callback(progress: dict[str, Any]) -> None:
            event_type = str(progress.get("type") or "")
            if event_type == "cancelled":
                self.cancelled(job_id=job_id, message=str(progress.get("message") or "モデル同期を中断しました。"))
                return
            if event_type == "complete":
                self.complete(job_id=job_id, message=str(progress.get("message") or "モデル同期が完了しました。"))
                return
            if event_type == "error":
                self.fail(
                    job_id=job_id,
                    message=str(progress.get("message") or "モデル同期に失敗しました。"),
                    error=str(progress.get("error") or "unknown error"),
                )
                return
            message = str(progress.get("message") or "モデルを同期中です...")
            progress_percent = self._to_float(progress.get("progress_percent"))
            detail = {
                "files_done": self._to_int(progress.get("files_done")),
                "total_files": self._to_int(progress.get("total_files")),
                "transferred_bytes": self._to_int(
                    progress.get("bytes_done_total", progress.get("bytes_transferred"))
                ),
                "total_bytes": self._to_int(progress.get("total_size")),
                "current_file": str(progress.get("current_file")) if progress.get("current_file") else None,
            }
            if progress_percent is None:
                progress_percent = self._compute_progress_percent(
                    total_files=detail["total_files"],
                    files_done=detail["files_done"],
                    total_bytes=detail["total_bytes"],
                    transferred_bytes=detail["transferred_bytes"],
                )
            self.set_running(
                job_id=job_id,
                progress_percent=progress_percent,
                message=message,
                detail=detail,
            )

        return _callback

    def _update(
        self,
        *,
        job_id: str,
        state: ModelSyncJobState | None = None,
        progress_percent: float | None = None,
        message: str | None = None,
        error: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        snapshot: ModelSyncJobStatus | None = None
        user_id: str | None = None
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            if record.state in _TERMINAL_STATES:
                return
            user_id = record.user_id
            if state is not None:
                record.state = state
            if progress_percent is not None:
                record.progress_percent = self._clamp_progress(progress_percent)
            if message is not None:
                record.message = message
            record.error = error
            if detail:
                payload = record.detail.model_dump(mode="python")
                payload.update(detail)
                record.detail = ModelSyncJobDetail.model_validate(payload)
            record.updated_at = _utcnow()
            snapshot = record.to_response()
            if record.state in _TERMINAL_STATES:
                self._cancel_events.pop(job_id, None)
        if snapshot is not None and user_id:
            get_realtime_runtime().track(
                scope=UserID(user_id),
                kind="storage.model-sync",
                key=snapshot.job_id,
            ).replace(snapshot.model_dump(mode="json"))

    def _cleanup_locked(self) -> None:
        cutoff = _utcnow() - timedelta(seconds=self._ttl_seconds)
        stale_job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.state in _TERMINAL_STATES and job.updated_at < cutoff
        ]
        for job_id in stale_job_ids:
            self._jobs.pop(job_id, None)
            self._cancel_events.pop(job_id, None)

    def _get_for_user_locked(self, *, user_id: str, job_id: str) -> _JobRecord:
        record = self._jobs.get(job_id)
        if record is None or record.user_id != user_id:
            raise HTTPException(status_code=404, detail=f"Model sync job not found: {job_id}")
        return record

    @staticmethod
    def _clamp_progress(value: float) -> float:
        return min(max(float(value), 0.0), 100.0)

    @staticmethod
    def _to_int(value: object) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _compute_progress_percent(
        cls,
        *,
        total_files: int,
        files_done: int,
        total_bytes: int,
        transferred_bytes: int,
    ) -> float:
        if total_bytes > 0:
            ratio = transferred_bytes / total_bytes
        elif total_files > 0:
            ratio = files_done / total_files
        else:
            ratio = 0.0
        return round(cls._clamp_progress(ratio * 100.0), 2)


_service: ModelSyncJobsService | None = None


def get_model_sync_jobs_service() -> ModelSyncJobsService:
    global _service
    if _service is None:
        _service = ModelSyncJobsService()
    return _service


def reset_model_sync_jobs_service() -> None:
    global _service
    _service = None

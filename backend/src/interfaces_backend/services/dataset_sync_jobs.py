"""In-memory dataset sync job tracking for storage sync operations.

This service allows enqueueing multiple dataset sync jobs while running them
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

from interfaces_backend.core.request_auth import is_session_expired, refresh_session_from_refresh_token
from percus_ai.storage.r2_db_sync import R2DBSyncService, StorageSyncCancelledError
from percus_ai.db import reset_request_session, set_request_session

from interfaces_backend.models.storage import (
    DatasetSyncJobAcceptedResponse,
    DatasetSyncJobCancelResponse,
    DatasetSyncJobDetail,
    DatasetSyncJobListResponse,
    DatasetSyncJobState,
    DatasetSyncJobStatus,
)

_ACTIVE_STATES: set[DatasetSyncJobState] = {"queued", "running"}
_TERMINAL_STATES: set[DatasetSyncJobState] = {"completed", "failed", "cancelled"}
_DEFAULT_TTL_SECONDS = 1800

ProgressCallback = Callable[[dict[str, Any]], None]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _JobRecord:
    job_id: str
    user_id: str
    dataset_id: str
    auth_session: dict[str, Any] | None = None
    state: DatasetSyncJobState = "queued"
    progress_percent: float = 0.0
    message: str | None = None
    error: str | None = None
    detail: DatasetSyncJobDetail = field(default_factory=DatasetSyncJobDetail)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_response(self) -> DatasetSyncJobStatus:
        return DatasetSyncJobStatus(
            job_id=self.job_id,
            dataset_id=self.dataset_id,
            state=self.state,
            progress_percent=self.progress_percent,
            message=self.message,
            error=self.error,
            detail=self.detail.model_copy(deep=True),
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
        )


class DatasetSyncJobsService:
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
        dataset_id: str,
        auth_session: dict[str, Any] | None = None,
    ) -> DatasetSyncJobAcceptedResponse:
        with self._lock:
            self._cleanup_locked()
            for job in self._jobs.values():
                if (
                    job.user_id == user_id
                    and job.dataset_id == dataset_id
                    and job.state in _ACTIVE_STATES
                ):
                    raise HTTPException(status_code=409, detail="A dataset sync job is already in progress")

            job_id = uuid4().hex
            now = _utcnow()
            self._jobs[job_id] = _JobRecord(
                job_id=job_id,
                user_id=user_id,
                dataset_id=dataset_id,
                auth_session=dict(auth_session) if auth_session else None,
                state="queued",
                message="データセット同期ジョブを受け付けました。",
                created_at=now,
                updated_at=now,
            )
            self._cancel_events[job_id] = threading.Event()
            self._pending.append(job_id)
            if self._pending_event is not None:
                self._pending_event.set()
        return DatasetSyncJobAcceptedResponse(
            accepted=True,
            job_id=job_id,
            dataset_id=dataset_id,
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
            self._worker_task = loop.create_task(self._worker_loop(), name="dataset-sync-worker")

    def list(self, *, user_id: str, include_terminal: bool = False) -> DatasetSyncJobListResponse:
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
        return DatasetSyncJobListResponse(jobs=jobs)

    def get(self, *, user_id: str, job_id: str) -> DatasetSyncJobStatus:
        with self._lock:
            self._cleanup_locked()
            return self._get_for_user_locked(user_id=user_id, job_id=job_id).to_response()

    def get_cancel_event(self, *, job_id: str) -> threading.Event | None:
        with self._lock:
            return self._cancel_events.get(job_id)

    def cancel(self, *, user_id: str, job_id: str) -> DatasetSyncJobCancelResponse:
        with self._lock:
            self._cleanup_locked()
            record = self._get_for_user_locked(user_id=user_id, job_id=job_id)
            if record.state in _TERMINAL_STATES:
                return DatasetSyncJobCancelResponse(
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
                record.message = "データセット同期を中断しました。"
                record.error = None
            else:
                record.message = "データセット同期の中断を要求しました。"
            record.updated_at = _utcnow()
            snapshot = record.to_response()
        return DatasetSyncJobCancelResponse(
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
        progress_callback = self.build_progress_callback(job_id=job_id)
        request_session = self._resolve_job_session(record.auth_session)

        self.set_running(job_id=job_id, progress_percent=0.0, message="データセット同期を開始しました。")

        session_token = set_request_session(request_session)
        try:
            result = await sync_service.ensure_dataset_local(
                record.dataset_id,
                auto_download=True,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )
        except StorageSyncCancelledError:
            self.cancelled(job_id=job_id)
            return
        except Exception as exc:
            self.fail(
                job_id=job_id,
                message="データセット同期に失敗しました。",
                error=str(exc),
            )
            return
        finally:
            reset_request_session(session_token)

        if result.success:
            self.complete(
                job_id=job_id,
                message="ローカルキャッシュを利用しました。" if result.skipped else "データセット同期が完了しました。",
            )
            return
        if result.cancelled:
            self.cancelled(job_id=job_id)
            return
        self.fail(
            job_id=job_id,
            message="データセット同期に失敗しました。",
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

    def cancelled(self, *, job_id: str, message: str = "データセット同期を中断しました。") -> None:
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
                self.cancelled(job_id=job_id, message=str(progress.get("message") or "データセット同期を中断しました。"))
                return
            if event_type == "complete":
                self.complete(job_id=job_id, message=str(progress.get("message") or "データセット同期が完了しました。"))
                return
            if event_type == "error":
                self.fail(
                    job_id=job_id,
                    message=str(progress.get("message") or "データセット同期に失敗しました。"),
                    error=str(progress.get("error") or "unknown error"),
                )
                return

            message = str(progress.get("message") or "データセットを同期中です...")
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
        state: DatasetSyncJobState | None = None,
        progress_percent: float | None = None,
        message: str | None = None,
        error: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        snapshot: DatasetSyncJobStatus | None = None
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            if record.state in _TERMINAL_STATES:
                return
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
                record.detail = DatasetSyncJobDetail.model_validate(payload)
            record.updated_at = _utcnow()
            snapshot = record.to_response()
            if record.state in _TERMINAL_STATES:
                self._cancel_events.pop(job_id, None)
        if snapshot is not None:
            return None

    @staticmethod
    def _resolve_job_session(auth_session: dict[str, Any] | None) -> dict[str, Any] | None:
        if not auth_session:
            return None
        refresh_token = str(auth_session.get("refresh_token") or "").strip()
        if refresh_token:
            refreshed_session = refresh_session_from_refresh_token(refresh_token)
            if refreshed_session:
                return refreshed_session
        if is_session_expired(auth_session):
            return None
        return dict(auth_session)

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
            raise HTTPException(status_code=404, detail=f"Dataset sync job not found: {job_id}")
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


_service: DatasetSyncJobsService | None = None


def get_dataset_sync_jobs_service() -> DatasetSyncJobsService:
    global _service
    if _service is None:
        _service = DatasetSyncJobsService()
    return _service


def reset_dataset_sync_jobs_service() -> None:
    global _service
    _service = None

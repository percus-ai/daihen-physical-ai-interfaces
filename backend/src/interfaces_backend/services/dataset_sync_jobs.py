"""In-memory dataset sync job tracking for storage sync operations."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from interfaces_backend.models.storage import (
    DatasetSyncJobAcceptedResponse,
    DatasetSyncJobCancelResponse,
    DatasetSyncJobDetail,
    DatasetSyncJobListResponse,
    DatasetSyncJobState,
    DatasetSyncJobStatus,
)
from interfaces_backend.services.realtime_events import get_realtime_event_bus

DATASET_SYNC_JOB_TOPIC = "storage.dataset_sync.job"
_ACTIVE_STATES: set[DatasetSyncJobState] = {"queued", "running"}
_TERMINAL_STATES: set[DatasetSyncJobState] = {"completed", "failed", "cancelled"}
_DEFAULT_TTL_SECONDS = 1800


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _JobRecord:
    job_id: str
    user_id: str
    dataset_id: str
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
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def create(self, *, user_id: str, dataset_id: str) -> DatasetSyncJobAcceptedResponse:
        with self._lock:
            self._cleanup_locked()
            for job in self._jobs.values():
                if job.user_id == user_id and job.state in _ACTIVE_STATES:
                    raise HTTPException(status_code=409, detail="A dataset sync job is already in progress")

            job_id = uuid4().hex
            now = _utcnow()
            self._jobs[job_id] = _JobRecord(
                job_id=job_id,
                user_id=user_id,
                dataset_id=dataset_id,
                state="queued",
                message="データセット同期ジョブを受け付けました。",
                created_at=now,
                updated_at=now,
            )
            snapshot = self._jobs[job_id].to_response()
        self._publish(snapshot)
        return DatasetSyncJobAcceptedResponse(
            accepted=True,
            job_id=job_id,
            dataset_id=dataset_id,
            state="queued",
            message="accepted",
        )

    def attach_task(self, *, user_id: str, job_id: str, task: asyncio.Task[None]) -> None:
        with self._lock:
            record = self._get_for_user_locked(user_id=user_id, job_id=job_id)
            if record.state in _TERMINAL_STATES:
                return
            self._tasks[job_id] = task

    def release_runtime_handles(self, *, job_id: str) -> None:
        with self._lock:
            self._tasks.pop(job_id, None)

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
            if record.state == "running":
                return DatasetSyncJobCancelResponse(
                    job_id=record.job_id,
                    accepted=False,
                    state=record.state,
                    message="Running dataset sync cannot be cancelled.",
                )
            record.state = "cancelled"
            record.progress_percent = 0.0
            record.message = "データセット同期を中断しました。"
            record.error = None
            record.updated_at = _utcnow()
            snapshot = record.to_response()
            self._tasks.pop(job_id, None)
        self._publish(snapshot)
        return DatasetSyncJobCancelResponse(
            job_id=snapshot.job_id,
            accepted=True,
            state=snapshot.state,
            message=snapshot.message or "Cancel requested.",
        )

    def set_running(
        self,
        *,
        job_id: str,
        progress_percent: float,
        message: str,
        detail: dict | None = None,
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

    def _update(
        self,
        *,
        job_id: str,
        state: DatasetSyncJobState | None = None,
        progress_percent: float | None = None,
        message: str | None = None,
        error: str | None = None,
        detail: dict | None = None,
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
                self._tasks.pop(job_id, None)
        if snapshot is not None:
            self._publish(snapshot)

    def _publish(self, snapshot: DatasetSyncJobStatus) -> None:
        get_realtime_event_bus().publish_threadsafe(
            DATASET_SYNC_JOB_TOPIC,
            snapshot.job_id,
            snapshot.model_dump(mode="json"),
        )

    def _cleanup_locked(self) -> None:
        cutoff = _utcnow() - timedelta(seconds=self._ttl_seconds)
        stale_job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.state in _TERMINAL_STATES and job.updated_at < cutoff
        ]
        for job_id in stale_job_ids:
            self._jobs.pop(job_id, None)
            self._tasks.pop(job_id, None)

    def _get_for_user_locked(self, *, user_id: str, job_id: str) -> _JobRecord:
        record = self._jobs.get(job_id)
        if record is None or record.user_id != user_id:
            raise HTTPException(status_code=404, detail=f"Dataset sync job not found: {job_id}")
        return record

    @staticmethod
    def _clamp_progress(value: float) -> float:
        return min(max(float(value), 0.0), 100.0)


_service: DatasetSyncJobsService | None = None


def get_dataset_sync_jobs_service() -> DatasetSyncJobsService:
    global _service
    if _service is None:
        _service = DatasetSyncJobsService()
    return _service


def reset_dataset_sync_jobs_service() -> None:
    global _service
    _service = None

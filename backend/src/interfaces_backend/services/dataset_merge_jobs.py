"""In-memory dataset merge job tracking."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from interfaces_backend.models.storage import (
    DatasetMergeJobAcceptedResponse,
    DatasetMergeJobDetail,
    DatasetMergeJobState,
    DatasetMergeJobStatus,
    DatasetMergeRequest,
    DatasetMergeResponse,
)
_ACTIVE_STATES: set[DatasetMergeJobState] = {"queued", "running"}
_TERMINAL_STATES: set[DatasetMergeJobState] = {"completed", "failed"}
_DEFAULT_TTL_SECONDS = 1800


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _JobRecord:
    job_id: str
    user_id: str
    state: DatasetMergeJobState = "queued"
    progress_percent: float = 0.0
    message: str | None = None
    error: str | None = None
    detail: DatasetMergeJobDetail = field(default_factory=DatasetMergeJobDetail)
    result_dataset_id: str | None = None
    result_size_bytes: int = 0
    result_episode_count: int = 0
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_response(self) -> DatasetMergeJobStatus:
        return DatasetMergeJobStatus(
            job_id=self.job_id,
            state=self.state,
            progress_percent=self.progress_percent,
            message=self.message,
            error=self.error,
            detail=self.detail.model_copy(deep=True),
            result_dataset_id=self.result_dataset_id,
            result_size_bytes=self.result_size_bytes,
            result_episode_count=self.result_episode_count,
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
        )


class DatasetMergeJobsService:
    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._jobs: dict[str, _JobRecord] = {}

    def create(self, *, user_id: str, request: DatasetMergeRequest) -> DatasetMergeJobAcceptedResponse:
        with self._lock:
            self._cleanup_locked()
            for job in self._jobs.values():
                if job.user_id == user_id and job.state in _ACTIVE_STATES:
                    raise HTTPException(status_code=409, detail="A dataset merge job is already in progress")

            job_id = uuid4().hex
            now = _utcnow()
            record = _JobRecord(
                job_id=job_id,
                user_id=user_id,
                state="queued",
                progress_percent=0.0,
                message="データセットマージを受け付けました。",
                created_at=now,
                updated_at=now,
            )
            record.detail = DatasetMergeJobDetail(
                dataset_name=request.dataset_name,
                source_dataset_ids=list(dict.fromkeys(request.source_dataset_ids)),
                step="queued",
            )
            self._jobs[job_id] = record
        return DatasetMergeJobAcceptedResponse(
            accepted=True,
            job_id=job_id,
            state="queued",
            message="accepted",
        )

    def get(self, *, user_id: str, job_id: str) -> DatasetMergeJobStatus:
        with self._lock:
            self._cleanup_locked()
            return self._get_for_user_locked(user_id=user_id, job_id=job_id).to_response()

    def set_running(self, *, job_id: str, progress_percent: float, message: str, step: str) -> None:
        self._update(
            job_id=job_id,
            state="running",
            progress_percent=progress_percent,
            message=message,
            error=None,
            detail={"step": step},
        )

    def fail(self, *, job_id: str, message: str, error: str) -> None:
        self._update(
            job_id=job_id,
            state="failed",
            progress_percent=100.0,
            message=message,
            error=error,
        )

    def complete(self, *, job_id: str, result: DatasetMergeResponse) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or record.state in _TERMINAL_STATES:
                return
            record.state = "completed"
            record.progress_percent = 100.0
            record.message = result.message
            record.error = None
            record.result_dataset_id = result.dataset_id
            record.result_size_bytes = int(result.size_bytes or 0)
            record.result_episode_count = int(result.episode_count or 0)
            record.detail.step = "completed"
            record.updated_at = _utcnow()
            record.to_response()

    def update_from_progress(self, *, job_id: str, progress: dict) -> None:
        """Translate merge/upload progress callbacks into a single job snapshot."""
        msg_type = str(progress.get("type") or "").strip()
        step = str(progress.get("step") or "").strip()
        message = str(progress.get("message") or "").strip() or None

        current_dataset_id = progress.get("dataset_id")
        current_file = progress.get("current_file")
        files_done = progress.get("files_done")
        total_files = progress.get("total_files")
        total_size = progress.get("total_size")
        bytes_transferred = progress.get("bytes_transferred")
        file_size = progress.get("file_size")
        error = progress.get("error")

        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            update_detail: dict = {}
            if step:
                update_detail["step"] = step
            if current_dataset_id:
                update_detail["current_dataset_id"] = str(current_dataset_id)
                downloaded = list(record.detail.downloaded_dataset_ids)
                if str(current_dataset_id) not in downloaded:
                    downloaded.append(str(current_dataset_id))
                update_detail["downloaded_dataset_ids"] = downloaded
            if current_file:
                update_detail["current_file"] = str(current_file)
            if isinstance(files_done, int):
                update_detail["files_done"] = files_done
            if isinstance(total_files, int):
                update_detail["total_files"] = total_files
            if isinstance(total_size, int):
                update_detail["total_size"] = total_size
            if isinstance(bytes_transferred, int):
                update_detail["transferred_bytes"] = bytes_transferred

            progress_percent = self._progress_from_event(
                record=record,
                msg_type=msg_type,
                step=step,
                detail=update_detail,
                raw={
                    "file_size": file_size,
                    "bytes_transferred": bytes_transferred,
                },
            )

        if msg_type == "error":
            self._update(
                job_id=job_id,
                state="failed",
                progress_percent=100.0,
                message=message or "マージに失敗しました。",
                error=str(error or "unknown error"),
                detail=update_detail,
            )
            return

        # Keep the job in running state until the worker marks it completed.
        self._update(
            job_id=job_id,
            state="running",
            progress_percent=progress_percent,
            message=message,
            error=None,
            detail=update_detail,
        )

    def _progress_from_event(
        self,
        *,
        record: _JobRecord,
        msg_type: str,
        step: str,
        detail: dict,
        raw: dict | None = None,
    ) -> float:
        """Map step-local progress into a smooth 0-100% bar."""
        # validate: 0-10, download: 10-30, aggregate: 30-55, upload: 55-100
        if step == "validate":
            if msg_type == "step_complete":
                return 10.0
            return 5.0
        if step == "download":
            total = len(record.detail.source_dataset_ids)
            current_done = len(record.detail.downloaded_dataset_ids)
            ratio = (current_done / total) if total > 0 else 0.0
            return 10.0 + (20.0 * min(max(ratio, 0.0), 1.0))
        if step == "aggregate":
            if msg_type == "step_complete":
                return 55.0
            return 40.0
        if step == "upload":
            files_done = int(detail.get("files_done") or 0)
            total_files = int(detail.get("total_files") or 0)
            partial = 0.0
            if raw:
                try:
                    current_size = float(raw.get("file_size") or 0.0)
                    current_bytes = float(raw.get("bytes_transferred") or 0.0)
                except (TypeError, ValueError):
                    current_size = 0.0
                    current_bytes = 0.0
                if current_size > 0 and current_bytes > 0:
                    partial = min(max(current_bytes / current_size, 0.0), 1.0)
            ratio = ((files_done + partial) / total_files) if total_files > 0 else 0.0
            return 55.0 + (45.0 * min(max(ratio, 0.0), 1.0))
        # Default: keep last progress if present.
        return float(record.progress_percent)

    def _update(
        self,
        *,
        job_id: str,
        state: DatasetMergeJobState | None = None,
        progress_percent: float | None = None,
        message: str | None = None,
        error: str | None = None,
        detail: dict | None = None,
    ) -> None:
        snapshot: DatasetMergeJobStatus | None = None
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
                record.detail = DatasetMergeJobDetail.model_validate(payload)
            record.updated_at = _utcnow()
            snapshot = record.to_response()
        if snapshot is not None:
            return None

    def _cleanup_locked(self) -> None:
        cutoff = _utcnow() - timedelta(seconds=self._ttl_seconds)
        stale_job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.state in _TERMINAL_STATES and job.updated_at < cutoff
        ]
        for job_id in stale_job_ids:
            self._jobs.pop(job_id, None)

    def _get_for_user_locked(self, *, user_id: str, job_id: str) -> _JobRecord:
        record = self._jobs.get(job_id)
        if record is None or record.user_id != user_id:
            raise HTTPException(status_code=404, detail=f"Dataset merge job not found: {job_id}")
        return record

    @staticmethod
    def _clamp_progress(value: float) -> float:
        return min(max(float(value), 0.0), 100.0)


_service: DatasetMergeJobsService | None = None
_service_lock = threading.Lock()


def get_dataset_merge_jobs_service() -> DatasetMergeJobsService:
    global _service
    with _service_lock:
        if _service is None:
            _service = DatasetMergeJobsService()
    return _service

"""In-memory training job operation tracking."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from interfaces_backend.models.training import (
    TrainingJobOperationAcceptedResponse,
    TrainingJobOperationKind,
    TrainingJobOperationState,
    TrainingJobOperationStatusResponse,
)

_ACTIVE_STATES: set[TrainingJobOperationState] = {"queued", "running"}
_TERMINAL_STATES: set[TrainingJobOperationState] = {"completed", "failed", "cancelled"}
_DEFAULT_TTL_SECONDS = 1800


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


@dataclass
class _OperationRecord:
    operation_id: str
    user_id: str
    job_id: str
    kind: TrainingJobOperationKind
    state: TrainingJobOperationState = "queued"
    phase: str = "queued"
    progress_percent: float = 0.0
    message: str | None = None
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_response(self) -> TrainingJobOperationStatusResponse:
        return TrainingJobOperationStatusResponse(
            operation_id=self.operation_id,
            job_id=self.job_id,
            kind=self.kind,
            state=self.state,
            phase=self.phase,
            progress_percent=self.progress_percent,
            message=self.message,
            error=self.error,
            detail=dict(self.detail),
            result=dict(self.result) if isinstance(self.result, dict) else self.result,
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
            started_at=self.started_at.isoformat() if self.started_at else None,
            finished_at=self.finished_at.isoformat() if self.finished_at else None,
        )


class TrainingJobOperationsService:
    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._operations: dict[str, _OperationRecord] = {}

    def create(
        self,
        *,
        user_id: str,
        job_id: str,
        kind: TrainingJobOperationKind,
        message: str,
    ) -> TrainingJobOperationAcceptedResponse:
        with self._lock:
            self._cleanup_locked()
            existing = self._find_active_locked(user_id=user_id, job_id=job_id, kind=kind)
            if existing is not None:
                return TrainingJobOperationAcceptedResponse(
                    accepted=True,
                    operation_id=existing.operation_id,
                    job_id=job_id,
                    kind=kind,
                    state=existing.state,
                    message=existing.message or "already_running",
                    reused=True,
                )

            operation_id = uuid4().hex
            now = _utcnow()
            self._operations[operation_id] = _OperationRecord(
                operation_id=operation_id,
                user_id=user_id,
                job_id=job_id,
                kind=kind,
                message=message,
                created_at=now,
                updated_at=now,
            )
            return TrainingJobOperationAcceptedResponse(
                accepted=True,
                operation_id=operation_id,
                job_id=job_id,
                kind=kind,
                state="queued",
                message="accepted",
                reused=False,
            )

    def get(self, *, user_id: str, operation_id: str) -> TrainingJobOperationStatusResponse:
        with self._lock:
            self._cleanup_locked()
            record = self._operations.get(operation_id)
            if record is None or record.user_id != user_id:
                raise HTTPException(status_code=404, detail=f"Training operation not found: {operation_id}")
            return record.to_response()

    def list_for_job(
        self,
        *,
        user_id: str,
        job_id: str,
    ) -> list[TrainingJobOperationStatusResponse]:
        with self._lock:
            self._cleanup_locked()
            responses = [
                record.to_response()
                for record in self._operations.values()
                if record.user_id == user_id and record.job_id == job_id
            ]
        responses.sort(key=lambda item: item.updated_at or "", reverse=True)
        return responses

    def update_from_progress(self, *, operation_id: str, progress: dict[str, Any]) -> None:
        event_type = str(progress.get("type") or "").strip()
        phase = str(progress.get("phase") or event_type or "running").strip() or "running"
        message = str(progress.get("message") or progress.get("error") or "").strip() or None
        progress_percent = self._to_progress_percent(progress.get("progress_percent"))
        detail = {
            key: value
            for key, value in progress.items()
            if key not in {"type", "phase", "progress_percent", "message", "error", "result"}
            and value is not None
        }

        state: TrainingJobOperationState = "running"
        if event_type == "error" or phase == "failed":
            state = "failed"
        elif event_type == "complete" or phase == "completed":
            state = "completed"

        self._update(
            operation_id=operation_id,
            state=state,
            phase=phase,
            progress_percent=progress_percent,
            message=message,
            error=str(progress.get("error") or "").strip() or None,
            detail=detail,
            started=True,
            finished=state in _TERMINAL_STATES,
        )

    def complete(
        self,
        *,
        operation_id: str,
        message: str,
        result: dict[str, Any],
    ) -> None:
        self._update(
            operation_id=operation_id,
            state="completed",
            phase="completed",
            progress_percent=100.0,
            message=message,
            error=None,
            result=result,
            started=True,
            finished=True,
        )

    def fail(
        self,
        *,
        operation_id: str,
        message: str,
        error: str,
    ) -> None:
        self._update(
            operation_id=operation_id,
            state="failed",
            phase="failed",
            progress_percent=100.0,
            message=message,
            error=error,
            started=True,
            finished=True,
        )

    def _update(
        self,
        *,
        operation_id: str,
        state: TrainingJobOperationState | None = None,
        phase: str | None = None,
        progress_percent: float | None = None,
        message: str | None = None,
        error: str | None = None,
        detail: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        with self._lock:
            record = self._operations.get(operation_id)
            if record is None:
                return
            if state is not None:
                record.state = state
            if phase is not None:
                record.phase = phase
            if progress_percent is not None:
                record.progress_percent = progress_percent
            if message is not None:
                record.message = message
            record.error = error
            if detail:
                record.detail.update(detail)
            if result is not None:
                record.result = dict(result)
            if started and record.started_at is None:
                record.started_at = _utcnow()
            if finished:
                record.finished_at = _utcnow()
            record.updated_at = _utcnow()

    def _find_active_locked(
        self,
        *,
        user_id: str,
        job_id: str,
        kind: TrainingJobOperationKind,
    ) -> _OperationRecord | None:
        matches = [
            record
            for record in self._operations.values()
            if record.user_id == user_id
            and record.job_id == job_id
            and record.kind == kind
            and record.state in _ACTIVE_STATES
        ]
        if not matches:
            return None
        matches.sort(key=lambda record: record.updated_at, reverse=True)
        return matches[0]

    def _cleanup_locked(self) -> None:
        cutoff = _utcnow() - timedelta(seconds=self._ttl_seconds)
        stale_ids = [
            operation_id
            for operation_id, record in self._operations.items()
            if record.state in _TERMINAL_STATES and record.updated_at < cutoff
        ]
        for operation_id in stale_ids:
            self._operations.pop(operation_id, None)

    @staticmethod
    def _to_progress_percent(value: Any) -> float:
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return 0.0


_service: TrainingJobOperationsService | None = None


def get_training_job_operations_service() -> TrainingJobOperationsService:
    global _service
    if _service is None:
        _service = TrainingJobOperationsService()
    return _service


def reset_training_job_operations_service() -> None:
    global _service
    _service = None

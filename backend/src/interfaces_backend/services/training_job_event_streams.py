"""Backend-owned active training job event stream registry."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
import threading
from typing import Literal, cast


TrainingJobLogType = Literal["setup", "training"]


class TrainingJobEventStreamRegistry:
    """Tracks process-local training jobs that are currently producing events."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_job_ids: set[str] = set()
        self._log_lines: dict[tuple[str, TrainingJobLogType], deque[str]] = defaultdict(
            lambda: deque(maxlen=200)
        )

    def open(self, *, job_id: str) -> None:
        normalized_job_id = self._normalize_job_id(job_id)
        with self._lock:
            self._active_job_ids.add(normalized_job_id)
            self._log_lines.pop((normalized_job_id, "setup"), None)
            self._log_lines.pop((normalized_job_id, "training"), None)

    def is_active(self, *, job_id: str) -> bool:
        with self._lock:
            return self._normalize_job_id(job_id) in self._active_job_ids

    def close(self, *, job_id: str) -> None:
        with self._lock:
            self._active_job_ids.discard(self._normalize_job_id(job_id))

    def append_log_lines(
        self,
        *,
        job_id: str,
        log_type: TrainingJobLogType,
        lines: Iterable[str],
    ) -> None:
        normalized_job_id = self._normalize_job_id(job_id)
        normalized_log_type = self._normalize_log_type(log_type)
        normalized_lines = [
            clean
            for line in lines
            if (clean := str(line or "").rstrip("\r\n"))
        ]
        if not normalized_lines:
            return
        with self._lock:
            self._log_lines[(normalized_job_id, normalized_log_type)].extend(normalized_lines)

    def get_log_lines(
        self,
        *,
        job_id: str,
        log_type: TrainingJobLogType,
        limit: int,
    ) -> list[str]:
        normalized_job_id = self._normalize_job_id(job_id)
        normalized_log_type = self._normalize_log_type(log_type)
        safe_limit = max(1, min(int(limit), 10000))
        with self._lock:
            lines = list(self._log_lines.get((normalized_job_id, normalized_log_type), ()))
        return lines[-safe_limit:]

    def clear(self) -> None:
        with self._lock:
            self._active_job_ids.clear()
            self._log_lines.clear()

    @staticmethod
    def _normalize_job_id(job_id: str) -> str:
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        return normalized

    @staticmethod
    def _normalize_log_type(log_type: TrainingJobLogType) -> TrainingJobLogType:
        normalized = str(log_type or "").strip()
        if normalized not in ("setup", "training"):
            raise ValueError("log_type must be setup or training")
        return cast(TrainingJobLogType, normalized)


_registry = TrainingJobEventStreamRegistry()


def get_training_job_event_stream_registry() -> TrainingJobEventStreamRegistry:
    return _registry

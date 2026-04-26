"""Backend-owned active training job event stream registry."""

from __future__ import annotations

import threading


class TrainingJobEventStreamRegistry:
    """Tracks process-local training jobs that are currently producing events."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_job_ids: set[str] = set()

    def open(self, *, job_id: str) -> None:
        with self._lock:
            self._active_job_ids.add(self._normalize_job_id(job_id))

    def is_active(self, *, job_id: str) -> bool:
        with self._lock:
            return self._normalize_job_id(job_id) in self._active_job_ids

    def close(self, *, job_id: str) -> None:
        with self._lock:
            self._active_job_ids.discard(self._normalize_job_id(job_id))

    def clear(self) -> None:
        with self._lock:
            self._active_job_ids.clear()

    @staticmethod
    def _normalize_job_id(job_id: str) -> str:
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        return normalized


_registry = TrainingJobEventStreamRegistry()


def get_training_job_event_stream_registry() -> TrainingJobEventStreamRegistry:
    return _registry

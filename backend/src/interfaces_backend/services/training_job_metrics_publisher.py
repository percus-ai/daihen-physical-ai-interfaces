"""Realtime publisher for training job metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading

from supabase._async.client import AsyncClient

from interfaces_backend.models.training import JobMetricsResponse
from interfaces_backend.services.realtime_runtime import UserID, get_realtime_runtime
from percus_ai.db import get_supabase_service_client_required

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"completed", "failed", "stopped", "terminated", "deleted"}
_DEFAULT_INTERVAL_SECONDS = float(os.environ.get("TRAINING_METRICS_PUBLISH_INTERVAL_SECONDS") or "2.0")


class TrainingJobMetricsPublisherService:
    """Publishes DB-backed training metrics onto the tab realtime track."""

    def __init__(self, *, interval_seconds: float = _DEFAULT_INTERVAL_SECONDS) -> None:
        self._interval_seconds = max(0.01, float(interval_seconds))
        self._lock = threading.RLock()
        self._tasks: dict[tuple[str, str], asyncio.Task[None]] = {}

    def publish_snapshot(self, *, user_id: str, job_id: str, snapshot: JobMetricsResponse) -> None:
        normalized_user_id = str(user_id or "").strip()
        normalized_job_id = str(job_id or "").strip()
        if not normalized_user_id or not normalized_job_id:
            return
        get_realtime_runtime().track(
            scope=UserID(normalized_user_id),
            kind="training.job.metrics",
            key=normalized_job_id,
        ).replace(snapshot.model_dump(mode="json"))

    def ensure_running(self, *, user_id: str, job_id: str, limit: int) -> None:
        normalized_user_id = str(user_id or "").strip()
        normalized_job_id = str(job_id or "").strip()
        if not normalized_user_id or not normalized_job_id:
            return
        key = (normalized_user_id, normalized_job_id)
        with self._lock:
            existing = self._tasks.get(key)
            if existing is not None and not existing.done():
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("training metrics publisher requires a running event loop")
                return
            task = loop.create_task(
                self._run(user_id=normalized_user_id, job_id=normalized_job_id, limit=limit),
                name=f"training-metrics-{normalized_job_id[:8]}",
            )
            self._tasks[key] = task
            task.add_done_callback(lambda done, task_key=key: self._forget_task(task_key, done))

    def shutdown(self) -> None:
        with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            task.cancel()

    def _forget_task(self, key: tuple[str, str], task: asyncio.Task[None]) -> None:
        with self._lock:
            if self._tasks.get(key) is task:
                self._tasks.pop(key, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning("training metrics publisher failed for %s: %s", key[1], exc)

    async def _run(self, *, user_id: str, job_id: str, limit: int) -> None:
        last_payload = ""
        while True:
            snapshot = await self._fetch_snapshot(job_id=job_id, limit=limit)
            payload = self._encode_snapshot(snapshot)
            if payload != last_payload:
                self.publish_snapshot(user_id=user_id, job_id=job_id, snapshot=snapshot)
                last_payload = payload

            status = await self._fetch_job_status(job_id)
            if status is None or status in _TERMINAL_STATUSES:
                return
            await asyncio.sleep(self._interval_seconds)

    async def _fetch_snapshot(self, *, job_id: str, limit: int) -> JobMetricsResponse:
        client = await get_supabase_service_client_required()
        train, val = await asyncio.gather(
            self._fetch_metrics_series(client=client, job_id=job_id, split="train", limit=limit),
            self._fetch_metrics_series(client=client, job_id=job_id, split="val", limit=limit),
        )
        return JobMetricsResponse(job_id=job_id, train=train, val=val)

    async def _fetch_metrics_series(
        self,
        *,
        client: AsyncClient,
        job_id: str,
        split: str,
        limit: int,
    ) -> list[dict]:
        response = (
            await client.table("training_job_metrics")
            .select("step,loss,ts")
            .eq("job_id", job_id)
            .eq("split", split)
            .order("step", desc=False)
            .limit(limit)
            .execute()
        )
        return response.data or []

    async def _fetch_job_status(self, job_id: str) -> str | None:
        client = await get_supabase_service_client_required()
        response = (
            await client.table("training_jobs")
            .select("status,deleted_at")
            .eq("job_id", job_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        row = rows[0]
        if row.get("deleted_at"):
            return "deleted"
        return str(row.get("status") or "").strip().lower() or None

    @staticmethod
    def _encode_snapshot(snapshot: JobMetricsResponse) -> str:
        return json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


_training_job_metrics_publisher: TrainingJobMetricsPublisherService | None = None
_training_job_metrics_publisher_lock = threading.Lock()


def get_training_job_metrics_publisher_service() -> TrainingJobMetricsPublisherService:
    global _training_job_metrics_publisher
    with _training_job_metrics_publisher_lock:
        if _training_job_metrics_publisher is None:
            _training_job_metrics_publisher = TrainingJobMetricsPublisherService()
    return _training_job_metrics_publisher


def reset_training_job_metrics_publisher_service() -> None:
    global _training_job_metrics_publisher
    with _training_job_metrics_publisher_lock:
        if _training_job_metrics_publisher is not None:
            _training_job_metrics_publisher.shutdown()
        _training_job_metrics_publisher = None

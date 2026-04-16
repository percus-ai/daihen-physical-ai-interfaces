"""Async build job execution for the new environment architecture."""

from __future__ import annotations

import asyncio
from collections import deque
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from interfaces_backend.models.build_management import (
    BuildJobCancelResponse,
    BuildJobSummaryModel,
    BuildRunAcceptedResponse,
)
from percus_ai.environment.build import BuildStore, generate_build_id
from percus_ai.environment.build.build_metadata import EnvBuildMetadataModel, SharedBuildMetadataModel
from percus_ai.environment.config import EnvironmentConfigLoader
from percus_ai.environment.config.config_models import EnvironmentDefinitionModel, SharedPackageVariantModel
from percus_ai.environment.operations import (
    BuildEnvironmentOperation,
    BuildSharedPackageOperation,
)

_ACTIVE_STATES = {"queued", "running"}
_TERMINAL_STATES = {"completed", "failed"}
_LOG_BUFFER_MAX_EVENTS = 2000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _BuildJobRecord:
    job_id: str
    build_id: str
    kind: str
    setting_id: str
    state: str = "queued"
    current_step_name: str | None = None
    current_step_index: int = 0
    total_steps: int = 0
    progress_percent: float = 0.0
    message: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    env_name: str | None = None
    config_id: str | None = None
    package: str | None = None
    variant: str | None = None

    def to_response(self) -> BuildJobSummaryModel:
        return BuildJobSummaryModel(
            job_id=self.job_id,
            build_id=self.build_id,
            kind=self.kind,  # type: ignore[arg-type]
            setting_id=self.setting_id,
            state=self.state,  # type: ignore[arg-type]
            current_step_name=self.current_step_name,
            current_step_index=self.current_step_index,
            total_steps=self.total_steps,
            progress_percent=self.progress_percent,
            message=self.message,
            error=self.error,
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
            started_at=self.started_at.isoformat() if self.started_at else None,
            finished_at=self.finished_at.isoformat() if self.finished_at else None,
        )


class BuildJobsService:
    def __init__(
        self,
        *,
        config_loader: EnvironmentConfigLoader | None = None,
        build_store: BuildStore | None = None,
        environment_build_operation: BuildEnvironmentOperation | None = None,
        shared_build_operation: BuildSharedPackageOperation | None = None,
    ) -> None:
        self._config_loader = config_loader or EnvironmentConfigLoader()
        self._build_store = build_store or BuildStore()
        self._environment_build_operation = environment_build_operation or BuildEnvironmentOperation(store=self._build_store)
        self._shared_build_operation = shared_build_operation or BuildSharedPackageOperation(store=self._build_store)
        self._lock = threading.RLock()
        self._jobs: dict[str, _BuildJobRecord] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._log_events: deque[dict[str, Any]] = deque(maxlen=_LOG_BUFFER_MAX_EVENTS)
        self._next_log_seq = 0

    def list_active_jobs(self) -> list[BuildJobSummaryModel]:
        with self._lock:
            items = [record.to_response() for record in self._jobs.values() if record.state in _ACTIVE_STATES]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def get_job(self, *, job_id: str) -> BuildJobSummaryModel:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"Build job not found: {job_id}")
            return record.to_response()

    def poll_log_events(self, *, after_seq: int | None = None) -> tuple[int | None, list[dict[str, Any]]]:
        with self._lock:
            events = [
                dict(item)
                for item in self._log_events
                if after_seq is None or int(item["seq"]) > after_seq
            ]
        next_cursor = int(events[-1]["seq"]) if events else after_seq
        return next_cursor, events

    def start_env_build(self, *, config_id: str, env_name: str) -> BuildRunAcceptedResponse:
        config = self._config_loader.load_env_config(config_id)
        if env_name not in config.envs:
            raise HTTPException(status_code=404, detail=f"Environment definition not found: {config_id}:{env_name}")
        setting_id = f"{config_id}:{env_name}"
        with self._lock:
            self._ensure_no_active_job_locked(setting_id)
            record = _BuildJobRecord(
                job_id=uuid4().hex,
                build_id=generate_build_id(),
                kind="env",
                setting_id=setting_id,
                env_name=env_name,
                config_id=config_id,
                total_steps=self._count_env_steps_from_definition(config.envs[env_name]),
                current_step_name="queued",
                message="環境構築ジョブを受け付けました。",
            )
            self._jobs[record.job_id] = record
            self._cancel_events[record.job_id] = threading.Event()
            loop = asyncio.get_running_loop()
            self._tasks[record.job_id] = loop.create_task(self._run_env_job(record.job_id), name=f"build-env-{setting_id}")
            response = record.to_response()
        return BuildRunAcceptedResponse(job=response)

    def start_shared_build(self, *, package: str, variant: str) -> BuildRunAcceptedResponse:
        definition = self._config_loader.load_shared_package_definition(package)
        if variant not in definition.variants:
            raise HTTPException(status_code=404, detail=f"Shared package variant not found: {package}:{variant}")
        setting_id = f"{package}:{variant}"
        with self._lock:
            self._ensure_no_active_job_locked(setting_id)
            record = _BuildJobRecord(
                job_id=uuid4().hex,
                build_id=generate_build_id(),
                kind="shared",
                setting_id=setting_id,
                package=package,
                variant=variant,
                total_steps=self._count_shared_steps(definition.variants[variant]),
                current_step_name="queued",
                message="共有パッケージ構築ジョブを受け付けました。",
            )
            self._jobs[record.job_id] = record
            self._cancel_events[record.job_id] = threading.Event()
            loop = asyncio.get_running_loop()
            self._tasks[record.job_id] = loop.create_task(
                self._run_shared_job(record.job_id),
                name=f"build-shared-{setting_id}",
            )
            response = record.to_response()
        return BuildRunAcceptedResponse(job=response)

    def cancel(self, *, job_id: str) -> BuildJobCancelResponse:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"Build job not found: {job_id}")
            cancel_event = self._cancel_events.get(job_id)
            if record.state in _TERMINAL_STATES:
                return BuildJobCancelResponse(accepted=False, job=record.to_response())
            if cancel_event is not None:
                cancel_event.set()
            record.message = "構築の中止を要求しました。"
            record.updated_at = _utcnow()
            return BuildJobCancelResponse(accepted=True, job=record.to_response())

    async def shutdown(self) -> None:
        tasks: list[asyncio.Task[None]]
        with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
            cancel_events = list(self._cancel_events.values())
            self._cancel_events.clear()
        for event in cancel_events:
            event.set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _ensure_no_active_job_locked(self, setting_id: str) -> None:
        for record in self._jobs.values():
            if record.setting_id == setting_id and record.state in _ACTIVE_STATES:
                raise HTTPException(status_code=409, detail=f"Build already in progress: {setting_id}")

    async def _run_env_job(self, job_id: str) -> None:
        record = self._get_record(job_id)
        if record is None or record.config_id is None or record.env_name is None:
            return
        self._mark_running(job_id, message="環境構築を開始しました。")
        monitor = asyncio.create_task(
            self._monitor_env_metadata(job_id=job_id, env_name=record.env_name, build_id=record.build_id),
            name=f"build-env-monitor-{job_id}",
        )
        try:
            cancel_event = self._cancel_events.get(job_id)
            await asyncio.to_thread(
                self._environment_build_operation.execute,
                config_id=record.config_id,
                env_name=record.env_name,
                build_id=record.build_id,
                cancel_event=cancel_event,
                output_callback=self._build_output_callback(job_id),
            )
            self._mark_completed(job_id, message="環境構築が完了しました。")
        except Exception as exc:  # noqa: BLE001
            if self._is_cancel_requested(job_id):
                self._mark_failed(job_id, error="cancelled", message="環境構築を中止しました。")
            else:
                self._mark_failed(job_id, error=str(exc), message="環境構築に失敗しました。")
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            with self._lock:
                self._tasks.pop(job_id, None)
                self._cancel_events.pop(job_id, None)

    async def _run_shared_job(self, job_id: str) -> None:
        record = self._get_record(job_id)
        if record is None or record.package is None or record.variant is None:
            return
        self._mark_running(job_id, message="共有パッケージ構築を開始しました。")
        monitor = asyncio.create_task(
            self._monitor_shared_metadata(job_id=job_id, package=record.package, build_id=record.build_id),
            name=f"build-shared-monitor-{job_id}",
        )
        try:
            cancel_event = self._cancel_events.get(job_id)
            await asyncio.to_thread(
                self._shared_build_operation.execute,
                package=record.package,
                variant=record.variant,
                build_id=record.build_id,
                cancel_event=cancel_event,
                output_callback=self._build_output_callback(job_id),
            )
            self._mark_completed(job_id, message="共有パッケージ構築が完了しました。")
        except Exception as exc:  # noqa: BLE001
            if self._is_cancel_requested(job_id):
                self._mark_failed(job_id, error="cancelled", message="共有パッケージ構築を中止しました。")
            else:
                self._mark_failed(job_id, error=str(exc), message="共有パッケージ構築に失敗しました。")
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            with self._lock:
                self._tasks.pop(job_id, None)
                self._cancel_events.pop(job_id, None)

    async def _monitor_env_metadata(self, *, job_id: str, env_name: str, build_id: str) -> None:
        while True:
            metadata = self._safe_load_env_metadata(env_name=env_name, build_id=build_id)
            if metadata is not None:
                self._update_from_metadata(job_id, metadata)
            await asyncio.sleep(0.5)

    async def _monitor_shared_metadata(self, *, job_id: str, package: str, build_id: str) -> None:
        while True:
            metadata = self._safe_load_shared_metadata(package=package, build_id=build_id)
            if metadata is not None:
                self._update_from_metadata(job_id, metadata)
            await asyncio.sleep(0.5)

    def _update_from_metadata(self, job_id: str, metadata: EnvBuildMetadataModel | SharedBuildMetadataModel) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None or record.state not in _ACTIVE_STATES:
                return
            record.current_step_index = len(metadata.steps)
            record.current_step_name = metadata.steps[-1].step if metadata.steps else "prepare"
            if record.total_steps > 0:
                record.progress_percent = min(99.0, (record.current_step_index / record.total_steps) * 100.0)
            record.updated_at = _utcnow()

    def _mark_running(self, job_id: str, *, message: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.state = "running"
            record.message = message
            record.started_at = _utcnow()
            record.updated_at = record.started_at
            record.current_step_name = "prepare"
            record.progress_percent = 0.0

    def _mark_completed(self, job_id: str, *, message: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.state = "completed"
            record.message = message
            record.error = None
            record.current_step_index = max(record.current_step_index, record.total_steps)
            record.progress_percent = 100.0
            record.finished_at = _utcnow()
            record.updated_at = record.finished_at

    def _mark_failed(self, job_id: str, *, error: str, message: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            record.state = "failed"
            record.message = message
            record.error = error
            record.finished_at = _utcnow()
            record.updated_at = record.finished_at

    def _build_output_callback(self, job_id: str):
        def _callback(step: str, stream: str, line: str) -> None:
            with self._lock:
                record = self._jobs.get(job_id)
                if record is None:
                    return
                self._next_log_seq += 1
                self._log_events.append(
                    {
                        "seq": self._next_log_seq,
                        "job_id": record.job_id,
                        "build_id": record.build_id,
                        "kind": record.kind,
                        "setting_id": record.setting_id,
                        "step": step,
                        "stream": stream,
                        "line": line,
                        "emitted_at": _utcnow().isoformat(),
                    }
                )

        return _callback

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            cancel_event = self._cancel_events.get(job_id)
            return bool(cancel_event and cancel_event.is_set())

    def _get_record(self, job_id: str) -> _BuildJobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _safe_load_env_metadata(self, *, env_name: str, build_id: str) -> EnvBuildMetadataModel | None:
        try:
            return self._build_store.load_env_metadata(env_name, build_id)
        except FileNotFoundError:
            return None

    def _safe_load_shared_metadata(self, *, package: str, build_id: str) -> SharedBuildMetadataModel | None:
        try:
            return self._build_store.load_shared_metadata(package, build_id)
        except FileNotFoundError:
            return None

    def _count_env_steps_from_definition(self, definition: EnvironmentDefinitionModel) -> int:
        count = 1  # create venv
        has_shared_refs = False
        for step in definition.installs:
            count += len(step.preflight_checks)
            if step.source.type == "shared-packages":
                has_shared_refs = True
            else:
                count += 1
            count += len(step.post_install_checks)
        if has_shared_refs:
            count += 1
        count += len(definition.checks)
        return count

    def _count_shared_steps(self, variant: SharedPackageVariantModel) -> int:
        count = 1  # create build venv
        if variant.build_env is not None:
            for step in variant.build_env.installs:
                count += len(step.preflight_checks)
                count += 1
                count += len(step.post_install_checks)
        build_source = variant.build.source.type
        if build_source == "path":
            count += 1
        elif build_source == "git":
            count += 2
        if build_source != "index" or variant.build.packages:
            count += len(variant.build.preflight_checks)
            count += 1
            count += len(variant.build.post_install_checks)
        count += 1  # collect outputs
        count += len(variant.checks)
        return count


_build_jobs_service: BuildJobsService | None = None


def get_build_jobs_service() -> BuildJobsService:
    global _build_jobs_service
    if _build_jobs_service is None:
        _build_jobs_service = BuildJobsService()
    return _build_jobs_service


def reset_build_jobs_service() -> None:
    global _build_jobs_service
    _build_jobs_service = None

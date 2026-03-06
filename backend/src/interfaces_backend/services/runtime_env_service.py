"""Runtime environment orchestration with latest-state SSE snapshots."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from interfaces_backend.models.runtime_env import (
    RuntimeEnvLogEntry,
    RuntimeEnvSnapshot,
    RuntimeEnvStatusSnapshot,
)
from interfaces_backend.services.realtime_events import get_realtime_event_bus
from percus_ai.environment import EnvironmentManager

RUNTIME_ENV_TOPIC = "system.runtime_envs"
RUNTIME_ENV_KEY = "global"
_LOG_LIMIT = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _estimate_progress_from_step(step: str | None, *, state: str) -> int | None:
    if state == "completed":
        return 100
    if state == "failed":
        return None
    mapping = {
        "prepare": 5,
        "create_venv": 15,
        "install_torch_runtime": 28,
        "install_packages": 40,
        "install_packages_stage_1": 55,
        "install_packages_stage_2": 70,
        "install_packages_stage_3": 80,
        "reinstall_torch_runtime": 78,
        "verify_torch_runtime": 96,
        "create_bundled_torch_metadata": 90,
        "save_packages_hash": 94,
        "verify_flash_attn": 98,
        "delete": 100 if state == "deleting" else 10,
        "complete": 100,
    }
    return mapping.get(step or "")


class RuntimeEnvService:
    def __init__(self, root_dir: Path | None = None) -> None:
        self._bus = get_realtime_event_bus()
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="runtime-env")
        self._env_manager = EnvironmentManager(root_dir=root_dir)
        self._active_task: asyncio.Task[None] | None = None
        self._closed = False
        self._snapshot = self._build_initial_snapshot()
        self._last_published_payload = ""

    def get_snapshot(self) -> RuntimeEnvSnapshot:
        with self._lock:
            return self._snapshot.model_copy(deep=True)

    async def refresh_snapshot(self) -> RuntimeEnvSnapshot:
        with self._lock:
            if self._active_task is not None and not self._active_task.done():
                return self._snapshot.model_copy(deep=True)
        snapshot = await asyncio.to_thread(self._snapshot_with_current_envs)
        self._replace_snapshot(snapshot)
        await self.publish_snapshot()
        return self.get_snapshot()

    async def publish_snapshot(self) -> None:
        payload = self.get_snapshot().model_dump(mode="json")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            if encoded == self._last_published_payload:
                return
            self._last_published_payload = encoded
        await self._bus.publish(RUNTIME_ENV_TOPIC, RUNTIME_ENV_KEY, payload)

    async def start_build(self, env_name: str, *, force: bool = False) -> RuntimeEnvSnapshot:
        normalized = self._normalize_known_env(env_name)
        with self._lock:
            if self._active_task is not None and not self._active_task.done():
                raise HTTPException(status_code=409, detail="Runtime environment operation already in progress")
            snapshot = self._snapshot.model_copy(deep=True)
            target = self._find_env(snapshot, normalized)
            target.state = "building"
            target.current_step = "prepare"
            target.progress_percent = 0
            target.message = (
                f"Rebuilding environment '{normalized}'..."
                if force
                else f"Building environment '{normalized}'..."
            )
            target.started_at = _now_iso()
            target.updated_at = target.started_at
            target.finished_at = None
            target.last_error = None
            target.logs = []
            snapshot.active_env_name = normalized
            snapshot.updated_at = target.updated_at
            self._snapshot = self._with_capabilities(snapshot)
            self._active_task = asyncio.create_task(
                self._run_build(normalized, force=force),
                name=f"runtime-env-build-{normalized}",
            )
        await self.publish_snapshot()
        return self.get_snapshot()

    async def start_delete(self, env_name: str) -> RuntimeEnvSnapshot:
        normalized = self._normalize_known_env(env_name)
        with self._lock:
            if self._active_task is not None and not self._active_task.done():
                raise HTTPException(status_code=409, detail="Runtime environment operation already in progress")
            snapshot = self._snapshot.model_copy(deep=True)
            target = self._find_env(snapshot, normalized)
            target.state = "deleting"
            target.current_step = "delete"
            target.progress_percent = 10
            target.message = f"Deleting environment '{normalized}'..."
            target.started_at = _now_iso()
            target.updated_at = target.started_at
            target.finished_at = None
            target.last_error = None
            target.logs = []
            snapshot.active_env_name = normalized
            snapshot.updated_at = target.updated_at
            self._snapshot = self._with_capabilities(snapshot)
            self._active_task = asyncio.create_task(
                self._run_delete(normalized),
                name=f"runtime-env-delete-{normalized}",
            )
        await self.publish_snapshot()
        return self.get_snapshot()

    async def shutdown(self) -> None:
        with self._lock:
            task = self._active_task
            self._active_task = None
            self._closed = True
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._executor.shutdown(wait=False, cancel_futures=False)

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    async def _run_build(self, env_name: str, *, force: bool) -> None:
        loop = asyncio.get_running_loop()

        def callback(event: dict[str, object]) -> None:
            self._record_event(env_name, event, final_operation="build")

        try:
            def run() -> None:
                if force:
                    if not self._env_manager.delete_env(env_name, silent=True, callback=callback):
                        raise RuntimeError(f"Failed to delete environment '{env_name}' before rebuild")
                if not self._env_manager.ensure_env(env_name, silent=True, callback=callback):
                    raise RuntimeError(f"Failed to build environment '{env_name}'")

            await loop.run_in_executor(self._executor, run)
            snapshot = await asyncio.to_thread(self._snapshot_with_current_envs)
            env_snapshot = self._find_env(snapshot, env_name)
            current = self._find_env(self.get_snapshot(), env_name)
            env_snapshot.state = "completed"
            env_snapshot.current_step = "complete"
            env_snapshot.progress_percent = 100
            env_snapshot.message = f"Environment '{env_name}' is ready"
            env_snapshot.started_at = current.started_at
            env_snapshot.finished_at = _now_iso()
            env_snapshot.updated_at = env_snapshot.finished_at
            env_snapshot.last_error = None
            env_snapshot.logs = current.logs
            snapshot.active_env_name = None
            snapshot.updated_at = env_snapshot.updated_at
            self._replace_snapshot(snapshot)
            await self.publish_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._record_failure(env_name, str(exc))
        finally:
            with self._lock:
                self._active_task = None

    async def _run_delete(self, env_name: str) -> None:
        loop = asyncio.get_running_loop()

        def callback(event: dict[str, object]) -> None:
            self._record_event(env_name, event, final_operation="delete")

        try:
            def run() -> None:
                if not self._env_manager.delete_env(env_name, silent=True, callback=callback):
                    raise RuntimeError(f"Failed to delete environment '{env_name}'")

            await loop.run_in_executor(self._executor, run)
            snapshot = await asyncio.to_thread(self._snapshot_with_current_envs)
            env_snapshot = self._find_env(snapshot, env_name)
            current = self._find_env(self.get_snapshot(), env_name)
            env_snapshot.state = "completed"
            env_snapshot.current_step = "complete"
            env_snapshot.progress_percent = 100
            env_snapshot.message = f"Environment '{env_name}' deleted"
            env_snapshot.started_at = current.started_at
            env_snapshot.finished_at = _now_iso()
            env_snapshot.updated_at = env_snapshot.finished_at
            env_snapshot.last_error = None
            env_snapshot.logs = current.logs
            snapshot.active_env_name = None
            snapshot.updated_at = env_snapshot.updated_at
            self._replace_snapshot(snapshot)
            await self.publish_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._record_failure(env_name, str(exc))
        finally:
            with self._lock:
                self._active_task = None

    def _record_event(self, env_name: str, event: dict[str, object], *, final_operation: str) -> None:
        now = _now_iso()
        event_type = str(event.get("type") or "progress")
        step = str(event.get("step") or "") or None
        log_entry = RuntimeEnvLogEntry(
            at=now,
            type=event_type,
            step=step,
            message=str(event.get("message") or "") or None,
            error=str(event.get("error") or "") or None,
            percent=int(event["percent"]) if isinstance(event.get("percent"), int) else None,
        )
        with self._lock:
            snapshot = self._snapshot.model_copy(deep=True)
            env_snapshot = self._find_env(snapshot, env_name)
            snapshot.active_env_name = env_name
            snapshot.updated_at = now
            env_snapshot.updated_at = now
            if step == "delete" and final_operation == "delete":
                env_snapshot.state = "deleting"
            elif step == "delete" and final_operation == "build":
                env_snapshot.state = "deleting"
            else:
                env_snapshot.state = "building"
            env_snapshot.current_step = step or env_snapshot.current_step
            if log_entry.message:
                env_snapshot.message = log_entry.message
            if log_entry.error:
                env_snapshot.last_error = log_entry.error
            env_snapshot.progress_percent = (
                log_entry.percent
                if log_entry.percent is not None
                else _estimate_progress_from_step(env_snapshot.current_step, state=env_snapshot.state)
            )
            if event_type == "error":
                env_snapshot.state = "failed"
                env_snapshot.message = log_entry.error or log_entry.message or "Runtime environment operation failed"
                env_snapshot.last_error = env_snapshot.message
                env_snapshot.finished_at = now
                env_snapshot.progress_percent = None
            env_snapshot.logs.append(log_entry)
            if len(env_snapshot.logs) > _LOG_LIMIT:
                env_snapshot.logs = env_snapshot.logs[-_LOG_LIMIT:]
            self._snapshot = self._with_capabilities(snapshot)
            payload = self._snapshot.model_dump(mode="json")
            self._last_published_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self._bus.publish_threadsafe(RUNTIME_ENV_TOPIC, RUNTIME_ENV_KEY, payload)

    def _record_failure(self, env_name: str, error: str) -> None:
        now = _now_iso()
        with self._lock:
            snapshot = self._snapshot.model_copy(deep=True)
            env_snapshot = self._find_env(snapshot, env_name)
            env_snapshot.state = "failed"
            env_snapshot.current_step = "failed"
            env_snapshot.progress_percent = None
            env_snapshot.message = error
            env_snapshot.last_error = error
            env_snapshot.finished_at = now
            env_snapshot.updated_at = now
            env_snapshot.logs.append(
                RuntimeEnvLogEntry(at=now, type="error", step="failed", message=error, error=error)
            )
            if len(env_snapshot.logs) > _LOG_LIMIT:
                env_snapshot.logs = env_snapshot.logs[-_LOG_LIMIT:]
            snapshot.active_env_name = None
            snapshot.updated_at = now
            self._snapshot = self._with_capabilities(snapshot)
            payload = self._snapshot.model_dump(mode="json")
            self._last_published_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self._bus.publish_threadsafe(RUNTIME_ENV_TOPIC, RUNTIME_ENV_KEY, payload)

    def _replace_snapshot(self, snapshot: RuntimeEnvSnapshot) -> None:
        with self._lock:
            previous = {item.env_name: item for item in self._snapshot.envs}
            for env_snapshot in snapshot.envs:
                prev = previous.get(env_snapshot.env_name)
                if prev is None:
                    continue
                env_snapshot.logs = list(prev.logs or env_snapshot.logs)
                if not env_snapshot.message and prev.state in {"completed", "failed"}:
                    env_snapshot.state = prev.state
                    env_snapshot.current_step = prev.current_step
                    env_snapshot.progress_percent = prev.progress_percent
                    env_snapshot.message = prev.message
                    env_snapshot.started_at = prev.started_at
                    env_snapshot.finished_at = prev.finished_at
                    env_snapshot.last_error = prev.last_error
            self._snapshot = self._with_capabilities(snapshot)

    def _snapshot_with_current_envs(self) -> RuntimeEnvSnapshot:
        current_snapshot = getattr(self, "_snapshot", None)
        previous = {item.env_name: item for item in current_snapshot.envs} if current_snapshot else {}
        envs: list[RuntimeEnvStatusSnapshot] = []
        for item in self._env_manager.get_runtime_environments():
            env_name = str(item["venv"])
            venv_path = self._env_manager._get_venv_path(env_name)
            python_path = venv_path / "bin" / "python"
            packages_hash_path = venv_path / ".packages_hash"
            previous_item = previous.get(env_name)
            env_snapshot = RuntimeEnvStatusSnapshot(
                env_name=env_name,
                description=str(item.get("description") or "") or None,
                policies=list(item.get("policies") or []),
                exists=bool(item.get("exists")),
                gpu_required=bool(item.get("gpu_required")),
                python_path=str(python_path) if python_path.exists() else None,
                packages_hash=packages_hash_path.read_text().strip() if packages_hash_path.exists() else None,
                state=previous_item.state if previous_item and previous_item.state in {"completed", "failed"} else "idle",
                current_step=previous_item.current_step if previous_item and previous_item.state in {"completed", "failed"} else None,
                progress_percent=previous_item.progress_percent if previous_item and previous_item.state in {"completed", "failed"} else None,
                message=previous_item.message if previous_item and previous_item.state in {"completed", "failed"} else None,
                started_at=previous_item.started_at if previous_item and previous_item.state in {"completed", "failed"} else None,
                updated_at=_now_iso(),
                finished_at=previous_item.finished_at if previous_item and previous_item.state in {"completed", "failed"} else None,
                last_error=previous_item.last_error if previous_item and previous_item.state == "failed" else None,
                logs=list(previous_item.logs) if previous_item else [],
            )
            envs.append(env_snapshot)
        return self._with_capabilities(
            RuntimeEnvSnapshot(
                updated_at=_now_iso(),
                active_env_name=None,
                envs=envs,
            )
        )

    def _build_initial_snapshot(self) -> RuntimeEnvSnapshot:
        return self._snapshot_with_current_envs()

    def _normalize_known_env(self, env_name: str) -> str:
        normalized = self._env_manager._normalize_env_short_name(env_name)
        available = {str(item["venv"]) for item in self._env_manager.get_runtime_environments()}
        if normalized not in available:
            raise HTTPException(status_code=404, detail=f"Unknown runtime environment: {env_name}")
        return normalized

    @staticmethod
    def _find_env(snapshot: RuntimeEnvSnapshot, env_name: str) -> RuntimeEnvStatusSnapshot:
        for item in snapshot.envs:
            if item.env_name == env_name:
                return item
        raise HTTPException(status_code=404, detail=f"Unknown runtime environment: {env_name}")

    @staticmethod
    def _with_capabilities(snapshot: RuntimeEnvSnapshot) -> RuntimeEnvSnapshot:
        busy = any(item.state in {"building", "deleting"} for item in snapshot.envs)
        for item in snapshot.envs:
            item.can_build = not busy
            item.can_rebuild = item.exists and not busy
            item.can_delete = item.exists and not busy
            if item.state == "completed":
                item.progress_percent = 100
                item.current_step = item.current_step or "complete"
            elif item.state == "idle" and item.progress_percent is None:
                item.progress_percent = 0
        return snapshot


_runtime_env_service: RuntimeEnvService | None = None
_runtime_env_service_lock = threading.Lock()


def get_runtime_env_service() -> RuntimeEnvService:
    global _runtime_env_service
    with _runtime_env_service_lock:
        if _runtime_env_service is None or _runtime_env_service.closed:
            _runtime_env_service = RuntimeEnvService()
    return _runtime_env_service

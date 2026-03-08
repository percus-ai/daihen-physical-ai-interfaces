"""Bundled-torch build orchestration with in-memory snapshots."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import HTTPException

from interfaces_backend.models.build import (
    BundledTorchBuildSnapshot,
    BundledTorchInstallStatus,
    BundledTorchLogEntry,
    BundledTorchPlatformInfo,
)
from percus_ai.environment import Platform, TorchBuilder

_LOG_LIMIT = 400


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BundledTorchBuildService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bundled-torch")
        self._active_task: asyncio.Task[None] | None = None
        self._closed = False
        snapshot = self._build_initial_snapshot()
        self._snapshot = snapshot
        self._last_published_payload = ""

    async def refresh_snapshot(self) -> BundledTorchBuildSnapshot:
        with self._lock:
            if self._snapshot.state in {"building", "cleaning"}:
                return self._snapshot.model_copy(deep=True)

        builder = TorchBuilder()
        install = await asyncio.to_thread(self._install_status, builder)
        platform = await asyncio.to_thread(
            self._detect_platform_for_install_status,
            install,
            current_state=self.get_snapshot().state,
        )
        with self._lock:
            snapshot = self._snapshot.model_copy(deep=True)
            snapshot.platform = self._platform_info(platform)
            snapshot.install = install
            snapshot.updated_at = _now_iso()
            self._snapshot = self._with_capabilities(self._with_install_warning(snapshot))
        await self.publish_snapshot()
        return self.get_snapshot()

    def get_snapshot(self) -> BundledTorchBuildSnapshot:
        with self._lock:
            return self._snapshot.model_copy(deep=True)

    async def publish_snapshot(self) -> None:
        payload = self.get_snapshot().model_dump(mode="json")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            if encoded == self._last_published_payload:
                return
            self._last_published_payload = encoded
        return None

    async def start_build(
        self,
        *,
        pytorch_version: str | None = None,
        torchvision_version: str | None = None,
        force: bool = False,
    ) -> BundledTorchBuildSnapshot:
        platform = await asyncio.to_thread(Platform.detect, False)
        if not platform.pytorch_build_required:
            raise HTTPException(status_code=400, detail="Bundled-torch build is not required on this platform")

        with self._lock:
            if self._active_task is not None and not self._active_task.done():
                raise HTTPException(status_code=409, detail="Bundled-torch operation already in progress")

            snapshot = self._snapshot.model_copy(deep=True)
            snapshot.platform = self._platform_info(platform)
            snapshot.state = "building"
            snapshot.current_action = "rebuild" if force else "build"
            snapshot.current_step = "clean" if force else "clone_pytorch"
            snapshot.message = "Starting bundled-torch build..."
            snapshot.started_at = _now_iso()
            snapshot.updated_at = snapshot.started_at
            snapshot.finished_at = None
            snapshot.requested_pytorch_version = pytorch_version
            snapshot.requested_torchvision_version = torchvision_version
            snapshot.last_error = None
            snapshot.logs = []
            self._snapshot = self._with_capabilities(snapshot)
            self._active_task = asyncio.create_task(
                self._run_build(
                    pytorch_version=pytorch_version,
                    torchvision_version=torchvision_version,
                    force=force,
                ),
                name="bundled-torch-build",
            )
        await self.publish_snapshot()
        return self.get_snapshot()

    async def start_clean(self) -> BundledTorchBuildSnapshot:
        platform = await asyncio.to_thread(Platform.detect, False)
        if not platform.pytorch_build_required:
            raise HTTPException(status_code=400, detail="Bundled-torch clean is not required on this platform")

        with self._lock:
            if self._active_task is not None and not self._active_task.done():
                raise HTTPException(status_code=409, detail="Bundled-torch operation already in progress")

            snapshot = self._snapshot.model_copy(deep=True)
            snapshot.platform = self._platform_info(platform)
            snapshot.state = "cleaning"
            snapshot.current_action = "clean"
            snapshot.current_step = "clean"
            snapshot.message = "Cleaning bundled-torch..."
            snapshot.started_at = _now_iso()
            snapshot.updated_at = snapshot.started_at
            snapshot.finished_at = None
            snapshot.last_error = None
            snapshot.logs = []
            self._snapshot = self._with_capabilities(snapshot)
            self._active_task = asyncio.create_task(self._run_clean(), name="bundled-torch-clean")
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

    async def _run_build(
        self,
        *,
        pytorch_version: str | None,
        torchvision_version: str | None,
        force: bool,
    ) -> None:
        builder = TorchBuilder()
        loop = asyncio.get_running_loop()

        def clean_callback(event: dict[str, object]) -> None:
            normalized = dict(event)
            if normalized.get("type") == "complete":
                normalized["type"] = "step_complete"
                normalized["step"] = "clean"
            normalized.setdefault("step", "clean")
            self._record_event(normalized, final_operation=None)

        def build_callback(event: dict[str, object]) -> None:
            self._record_event(event, final_operation="build")

        try:
            def run() -> None:
                if force:
                    builder.clean(callback=clean_callback)
                builder.build_all(
                    pytorch_version=pytorch_version,
                    torchvision_version=torchvision_version,
                    callback=build_callback,
                )

            await loop.run_in_executor(self._executor, run)
            snapshot = await asyncio.to_thread(self._snapshot_with_current_install)
            snapshot.state = "completed"
            snapshot.current_action = None
            snapshot.message = "Bundled-torch build completed"
            snapshot.current_step = "complete"
            snapshot.started_at = self.get_snapshot().started_at
            snapshot.finished_at = _now_iso()
            snapshot.updated_at = snapshot.finished_at
            snapshot.requested_pytorch_version = pytorch_version
            snapshot.requested_torchvision_version = torchvision_version
            snapshot.logs = self.get_snapshot().logs
            self._replace_snapshot(snapshot)
            await self.publish_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._record_failure(str(exc))
        finally:
            with self._lock:
                self._active_task = None

    async def _run_clean(self) -> None:
        builder = TorchBuilder()
        loop = asyncio.get_running_loop()

        def clean_callback(event: dict[str, object]) -> None:
            self._record_event(event, final_operation="clean")

        try:
            await loop.run_in_executor(self._executor, lambda: builder.clean(callback=clean_callback))
            snapshot = await asyncio.to_thread(self._snapshot_with_current_install)
            snapshot.state = "completed"
            snapshot.current_action = None
            snapshot.message = "Bundled-torch clean completed"
            snapshot.current_step = "complete"
            snapshot.started_at = self.get_snapshot().started_at
            snapshot.finished_at = _now_iso()
            snapshot.updated_at = snapshot.finished_at
            snapshot.logs = self.get_snapshot().logs
            self._replace_snapshot(snapshot)
            await self.publish_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._record_failure(str(exc))
        finally:
            with self._lock:
                self._active_task = None

    def _record_event(self, event: dict[str, object], *, final_operation: str | None) -> None:
        now = _now_iso()
        log_entry = BundledTorchLogEntry(
            at=now,
            type=str(event.get("type") or "progress"),
            step=str(event.get("step") or "") or None,
            message=str(event.get("message") or "") or None,
            line=str(event.get("line") or "") or None,
            percent=int(event["percent"]) if isinstance(event.get("percent"), int) else None,
        )

        with self._lock:
            snapshot = self._snapshot.model_copy(deep=True)
            snapshot.updated_at = now
            snapshot.current_step = log_entry.step or snapshot.current_step
            if log_entry.message:
                snapshot.message = log_entry.message
            if log_entry.type == "error":
                snapshot.state = "failed"
                snapshot.current_action = None
                snapshot.last_error = str(event.get("error") or log_entry.message or "Bundled-torch operation failed")
                snapshot.finished_at = now
            elif log_entry.type == "complete" and final_operation == "build":
                snapshot.state = "completed"
                snapshot.current_action = None
                snapshot.finished_at = now
            elif log_entry.type == "complete" and final_operation == "clean":
                snapshot.state = "completed"
                snapshot.current_action = None
                snapshot.finished_at = now
            snapshot.logs.append(log_entry)
            if len(snapshot.logs) > _LOG_LIMIT:
                snapshot.logs = snapshot.logs[-_LOG_LIMIT:]
            self._snapshot = self._with_capabilities(snapshot)
            payload = self._snapshot.model_dump(mode="json")
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            self._last_published_payload = encoded
        return None

    def _record_failure(self, error: str) -> None:
        now = _now_iso()
        with self._lock:
            snapshot = self._snapshot.model_copy(deep=True)
            snapshot.state = "failed"
            snapshot.current_action = None
            snapshot.message = error
            snapshot.last_error = error
            snapshot.finished_at = now
            snapshot.updated_at = now
            snapshot.logs.append(BundledTorchLogEntry(at=now, type="error", message=error))
            if len(snapshot.logs) > _LOG_LIMIT:
                snapshot.logs = snapshot.logs[-_LOG_LIMIT:]
            self._snapshot = self._with_capabilities(snapshot)
            payload = self._snapshot.model_dump(mode="json")
            self._last_published_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return None

    def _replace_snapshot(self, snapshot: BundledTorchBuildSnapshot) -> None:
        with self._lock:
            snapshot.logs = list(snapshot.logs or self._snapshot.logs)
            snapshot.updated_at = snapshot.updated_at or _now_iso()
            self._snapshot = self._with_capabilities(self._with_install_warning(snapshot))

    def _snapshot_with_current_install(self) -> BundledTorchBuildSnapshot:
        builder = TorchBuilder()
        install = self._install_status(builder)
        platform = self._detect_platform_for_install_status(install, current_state="idle")
        return BundledTorchBuildSnapshot(
            platform=self._platform_info(platform),
            install=install,
            state="idle",
            updated_at=_now_iso(),
        )

    def _build_initial_snapshot(self) -> BundledTorchBuildSnapshot:
        return self._with_capabilities(self._with_install_warning(self._snapshot_with_current_install()))

    @staticmethod
    def _detect_platform_for_install_status(
        install: BundledTorchInstallStatus,
        *,
        current_state: str,
    ) -> Platform:
        use_cache = not (
            current_state in {"building", "cleaning"}
            or not install.exists
            or not install.is_valid
        )
        return Platform.detect(use_cache=use_cache)

    @staticmethod
    def _with_install_warning(snapshot: BundledTorchBuildSnapshot) -> BundledTorchBuildSnapshot:
        if snapshot.state in {"building", "cleaning", "failed"}:
            return snapshot
        if snapshot.install.exists and not snapshot.install.is_valid:
            snapshot.message = "bundled-torch exists but is invalid. rebuild or clean before retrying."
        elif snapshot.message == "bundled-torch exists but is invalid. rebuild or clean before retrying.":
            snapshot.message = None
        return snapshot

    @staticmethod
    def _install_status(builder: TorchBuilder) -> BundledTorchInstallStatus:
        status = builder.get_status()
        return BundledTorchInstallStatus(**asdict(status))

    @staticmethod
    def _platform_info(platform: Platform) -> BundledTorchPlatformInfo:
        platform_name = platform.jetson_model if platform.is_jetson and platform.jetson_model else platform.arch
        return BundledTorchPlatformInfo(
            platform_name=platform_name,
            is_jetson=platform.is_jetson,
            pytorch_build_required=platform.pytorch_build_required,
            supported=platform.pytorch_build_required,
            gpu_name=platform.gpu_name,
            cuda_version=platform.cuda_version,
        )

    @staticmethod
    def _with_capabilities(snapshot: BundledTorchBuildSnapshot) -> BundledTorchBuildSnapshot:
        busy = snapshot.state in {"building", "cleaning"}
        required = snapshot.platform.pytorch_build_required and snapshot.platform.supported
        snapshot.can_build = required and not busy
        snapshot.can_rebuild = required and not busy
        snapshot.can_clean = required and not busy
        return snapshot


_bundled_torch_build_service: BundledTorchBuildService | None = None
_bundled_torch_build_service_lock = threading.Lock()


def get_bundled_torch_build_service() -> BundledTorchBuildService:
    global _bundled_torch_build_service
    with _bundled_torch_build_service_lock:
        if _bundled_torch_build_service is None or _bundled_torch_build_service.closed:
            _bundled_torch_build_service = BundledTorchBuildService()
    return _bundled_torch_build_service

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from interfaces_backend.models.build import BundledTorchInstallStatus
from interfaces_backend.services.bundled_torch_build_service import BundledTorchBuildService


@pytest.fixture
def anyio_backend():
    return "asyncio"


@dataclass
class _FakeBuildStatus:
    exists: bool = False
    pytorch_version: str | None = None
    torchvision_version: str | None = None
    numpy_version: str | None = None
    pytorch_path: str | None = None
    torchvision_path: str | None = None
    is_valid: bool = False


class _FakePlatform:
    def __init__(self, *, required: bool) -> None:
        self.arch = "aarch64" if required else "x86_64"
        self.is_jetson = required
        self.jetson_model = "AGX Thor" if required else None
        self.pytorch_build_required = required
        self.gpu_name = "Fake GPU"
        self.cuda_version = "12.8"


class _FakeBuilder:
    built = False

    def get_status(self):
        if self.__class__.built:
            return _FakeBuildStatus(
                exists=True,
                pytorch_version="v2.8.0",
                torchvision_version="v0.23.0",
                numpy_version="2.1.0",
                pytorch_path="/tmp/pytorch",
                torchvision_path="/tmp/vision",
                is_valid=True,
            )
        return _FakeBuildStatus()

    def build_all(self, pytorch_version=None, torchvision_version=None, callback=None):
        if callback:
            callback({"type": "progress", "step": "clone_pytorch", "message": "cloning"})
            callback({"type": "log", "step": "build_pytorch", "line": "building..."})
        self.__class__.built = True
        if callback:
            callback({"type": "complete", "step": "build_torchvision", "message": "done"})

    def clean(self, callback=None):
        self.__class__.built = False
        if callback:
            callback({"type": "complete", "step": "clean", "message": "cleaned"})


class _InvalidBuilder:
    def get_status(self):
        return _FakeBuildStatus(
            exists=True,
            pytorch_version="v2.8.0",
            torchvision_version="v0.23.0",
            is_valid=False,
        )


@pytest.mark.anyio
async def test_start_build_rejects_unsupported_platform(monkeypatch):
    monkeypatch.setattr(
        "interfaces_backend.services.bundled_torch_build_service.Platform.detect",
        lambda *args, **kwargs: _FakePlatform(required=False),
    )

    service = BundledTorchBuildService()

    with pytest.raises(HTTPException) as exc_info:
        await service.start_build()

    assert exc_info.value.status_code == 400
    await service.shutdown()


@pytest.mark.anyio
async def test_start_build_rejects_conflict(monkeypatch):
    monkeypatch.setattr(
        "interfaces_backend.services.bundled_torch_build_service.Platform.detect",
        lambda *args, **kwargs: _FakePlatform(required=True),
    )

    service = BundledTorchBuildService()

    async def fake_run_build(**kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(service, "_run_build", fake_run_build)

    await service.start_build()

    try:
        with pytest.raises(HTTPException) as exc_info:
            await service.start_build()
        assert exc_info.value.status_code == 409
    finally:
        task = service._active_task
        assert task is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await service.shutdown()


@pytest.mark.anyio
async def test_start_build_updates_completed_snapshot(monkeypatch):
    _FakeBuilder.built = False
    monkeypatch.setattr(
        "interfaces_backend.services.bundled_torch_build_service.Platform.detect",
        lambda *args, **kwargs: _FakePlatform(required=True),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.bundled_torch_build_service.TorchBuilder",
        _FakeBuilder,
    )

    service = BundledTorchBuildService()
    await service.start_build(pytorch_version="v2.8.0", torchvision_version="v0.23.0")

    task = service._active_task
    assert task is not None
    await task

    snapshot = service.get_snapshot()
    assert snapshot.state == "completed"
    assert snapshot.install.exists is True
    assert snapshot.install.is_valid is True
    assert snapshot.requested_pytorch_version == "v2.8.0"
    assert snapshot.requested_torchvision_version == "v0.23.0"
    assert snapshot.can_build is True
    assert snapshot.can_clean is True
    assert any(entry.type == "log" for entry in snapshot.logs)
    await service.shutdown()


def test_detect_platform_uses_fresh_probe_for_missing_or_invalid_install():
    _FakeBuilder.built = False
    calls: list[bool] = []

    def fake_detect(*, use_cache=True, **kwargs):
        calls.append(use_cache)
        return _FakePlatform(required=True)

    service = BundledTorchBuildService()
    try:
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            "interfaces_backend.services.bundled_torch_build_service.Platform.detect",
            fake_detect,
        )

        service._detect_platform_for_install_status(
            service._install_status(_FakeBuilder()),
            current_state="idle",
        )
        service._detect_platform_for_install_status(
            service._install_status(_InvalidBuilder()),
            current_state="idle",
        )
        service._detect_platform_for_install_status(
            BundledTorchInstallStatus(exists=False, is_valid=False),
            current_state="idle",
        )
        service._detect_platform_for_install_status(
            BundledTorchInstallStatus(exists=True, is_valid=True),
            current_state="building",
        )
        service._detect_platform_for_install_status(
            BundledTorchInstallStatus(exists=True, is_valid=True),
            current_state="completed",
        )
    finally:
        monkeypatch.undo()

    assert calls == [False, False, False, False, True]


def test_invalid_install_sets_warning_message():
    service = BundledTorchBuildService()
    snapshot = BundledTorchBuildService._with_install_warning(  # type: ignore[attr-defined]
        service.get_snapshot().model_copy(
            update={
                "install": BundledTorchInstallStatus(
                    exists=True,
                    pytorch_version="v2.8.0",
                    torchvision_version="v0.23.0",
                    is_valid=False,
                ),
                "state": "idle",
                "message": None,
            }
        )
    )
    assert snapshot.message == "bundled-torch exists but is invalid. rebuild or clean before retrying."
    asyncio.run(service.shutdown())


def test_capabilities_allow_rebuild_and_clean_without_existing_install():
    service = BundledTorchBuildService()
    snapshot = BundledTorchBuildService._with_capabilities(  # type: ignore[attr-defined]
        service.get_snapshot().model_copy(
            update={
                "platform": service.get_snapshot().platform.model_copy(
                    update={
                        "pytorch_build_required": True,
                        "supported": True,
                    }
                ),
                "install": BundledTorchInstallStatus(exists=False, is_valid=False),
                "state": "idle",
            }
        )
    )

    assert snapshot.can_build is True
    assert snapshot.can_rebuild is True
    assert snapshot.can_clean is True
    asyncio.run(service.shutdown())

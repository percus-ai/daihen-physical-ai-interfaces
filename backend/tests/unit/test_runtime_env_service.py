from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException

from interfaces_backend.services.runtime_env_service import RuntimeEnvService


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeEnvironmentManager:
    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = Path(root_dir or ".")
        self._venv_dir = self.root_dir / "envs"
        self._venv_dir.mkdir(parents=True, exist_ok=True)
        self._exists = {"act": False, "pi0": True}
        self._sync_files()

    @staticmethod
    def _normalize_env_short_name(env_name: str) -> str:
        return env_name.replace(".venv-", "").strip()

    def _sync_files(self) -> None:
        for env_name, exists in self._exists.items():
            env_path = self._venv_dir / env_name
            if exists:
                (env_path / "bin").mkdir(parents=True, exist_ok=True)
                (env_path / "bin" / "python").write_text("")
                (env_path / ".packages_hash").write_text(f"hash-{env_name}")
            elif env_path.exists():
                shutil.rmtree(env_path)

    def get_available_environments(self):
        self._sync_files()
        return [
            {
                "name": "framework",
                "venv": "framework",
                "description": "Framework runtime",
                "policies": [],
                "exists": False,
                "gpu_required": False,
            },
            {
                "name": "act",
                "venv": "act",
                "description": "ACT runtime",
                "policies": ["act"],
                "exists": self._exists["act"],
                "gpu_required": False,
            },
            {
                "name": "pi0",
                "venv": "pi0",
                "description": "Pi0 runtime",
                "policies": ["pi0"],
                "exists": self._exists["pi0"],
                "gpu_required": False,
            },
        ]

    def get_runtime_environments(self):
        return [item for item in self.get_available_environments() if item["policies"]]

    def _get_venv_path(self, env_name: str) -> Path:
        return self._venv_dir / env_name

    def ensure_env(self, env_name: str, silent: bool = False, callback=None) -> bool:
        if callback:
            callback({"type": "progress", "step": "create_venv", "message": f"creating {env_name}", "percent": 15})
            callback({"type": "progress", "step": "install_packages", "message": f"installing {env_name}", "percent": 60})
        self._exists[env_name] = True
        self._sync_files()
        if callback:
            callback({"type": "complete", "step": "complete", "message": f"{env_name} ready", "percent": 100})
        return True

    def delete_env(self, env_name: str, silent: bool = False, callback=None) -> bool:
        if callback:
            callback({"type": "progress", "step": "delete", "message": f"deleting {env_name}", "percent": 10})
        self._exists[env_name] = False
        self._sync_files()
        if callback:
            callback({"type": "complete", "step": "delete", "message": f"{env_name} deleted", "percent": 100})
        return True


@pytest.mark.anyio
async def test_runtime_env_build_updates_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "interfaces_backend.services.runtime_env_service.EnvironmentManager",
        lambda root_dir=None: _FakeEnvironmentManager(tmp_path),
    )
    service = RuntimeEnvService(root_dir=tmp_path)

    await service.start_build("act")
    task = service._active_task
    assert task is not None
    await task

    snapshot = service.get_snapshot()
    act = next(item for item in snapshot.envs if item.env_name == "act")
    assert act.exists is True
    assert act.state == "completed"
    assert act.current_step == "complete"
    assert act.progress_percent == 100
    assert act.can_delete is True
    assert any((entry.step or "") == "create_venv" for entry in act.logs)
    assert any(entry.percent is not None for entry in act.logs)
    await service.shutdown()


@pytest.mark.anyio
async def test_runtime_env_delete_updates_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "interfaces_backend.services.runtime_env_service.EnvironmentManager",
        lambda root_dir=None: _FakeEnvironmentManager(tmp_path),
    )
    service = RuntimeEnvService(root_dir=tmp_path)

    await service.start_delete("pi0")
    task = service._active_task
    assert task is not None
    await task

    snapshot = service.get_snapshot()
    pi0 = next(item for item in snapshot.envs if item.env_name == "pi0")
    assert pi0.exists is False
    assert pi0.state == "completed"
    assert pi0.current_step == "complete"
    assert pi0.progress_percent == 100
    assert pi0.can_delete is False
    await service.shutdown()


@pytest.mark.anyio
async def test_runtime_env_rejects_conflict(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "interfaces_backend.services.runtime_env_service.EnvironmentManager",
        lambda root_dir=None: _FakeEnvironmentManager(tmp_path),
    )
    service = RuntimeEnvService(root_dir=tmp_path)

    async def fake_run_build(env_name: str, *, force: bool) -> None:
        await asyncio.sleep(60)

    monkeypatch.setattr(service, "_run_build", fake_run_build)
    await service.start_build("act")

    try:
        with pytest.raises(HTTPException) as exc_info:
            await service.start_delete("pi0")
        assert exc_info.value.status_code == 409
    finally:
        task = service._active_task
        assert task is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await service.shutdown()

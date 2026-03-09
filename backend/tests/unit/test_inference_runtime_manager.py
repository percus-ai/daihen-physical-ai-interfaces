from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.services.inference_runtime as inference_runtime
from interfaces_backend.models.inference import (
    InferenceDeviceCompatibilityResponse,
    InferenceDeviceInfo,
)
from interfaces_backend.services.inference_runtime import InferenceRuntimeManager


class _FakeEnvironmentManager:
    def __init__(self, _root_dir):
        pass

    def get_env_for_policy(self, policy_type: str) -> str:
        return f".venv-{policy_type}"


class _FakeProc:
    def __init__(self):
        self.pid = 4321
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        _ = timeout
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_start_times_out_only_on_worker_control_socket(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    models_dir = tmp_path / "models"
    repo_root.mkdir()
    models_dir.mkdir()
    run_in_env = repo_root / "features" / "percus_ai" / "environment"
    run_in_env.mkdir(parents=True)
    (run_in_env / "run_in_env.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    model_dir = models_dir / "model-1"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        json.dumps({"type": "act"}),
        encoding="utf-8",
    )

    popen_env: dict[str, str] = {}

    def fake_popen(*args, **kwargs):
        _ = args
        popen_env.update(kwargs.get("env") or {})
        return _FakeProc()

    manager = InferenceRuntimeManager()

    monkeypatch.setattr(inference_runtime, "get_project_root", lambda: repo_root)
    monkeypatch.setattr(inference_runtime, "get_models_dir", lambda: models_dir)
    monkeypatch.setattr(inference_runtime, "EnvironmentManager", _FakeEnvironmentManager)
    monkeypatch.setattr(inference_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(inference_runtime, "_STARTUP_TIMEOUT_S", 0.0)
    monkeypatch.setattr(manager, "_connect_ctrl_socket_locked", lambda: None)
    monkeypatch.setattr(manager, "_start_event_listener_locked", lambda: None)
    monkeypatch.setattr(
        manager,
        "_send_ctrl_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("not ready")),
    )
    monkeypatch.setattr(
        manager,
        "get_device_compatibility",
        lambda: InferenceDeviceCompatibilityResponse(
            devices=[InferenceDeviceInfo(device="cpu", available=True)],
            recommended="cpu",
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        manager.start(
            model_id="model-1",
            device="cpu",
            task="pick",
        )

    assert str(exc_info.value) == "Timed out waiting for worker control socket"
    assert manager.get_status().runner_status.last_error == "Timed out waiting for worker control socket"
    assert popen_env["PERCUS_AI_SKIP_ENV_ENSURE"] == "1"

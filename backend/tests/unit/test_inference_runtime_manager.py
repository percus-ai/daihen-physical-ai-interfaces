from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.services.inference_runtime as inference_runtime
from interfaces_backend.services.inference_runtime_targets import ResolvedInferenceRuntimeTarget
from interfaces_backend.services.inference_runtime import InferenceRuntimeManager


class _FakeRuntimeTargetsService:
    def resolve_target(self, *, policy_type: str | None, target_id: str | None):
        assert policy_type == "act"
        assert target_id == "cpu"
        return ResolvedInferenceRuntimeTarget(
            target_id="cpu",
            kind="cpu",
            device="cpu",
            python_executable="/usr/bin/python3",
            config_id="default",
            env_name="act",
            build_id="build-1",
        )


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
    monkeypatch.setattr(inference_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(inference_runtime, "_STARTUP_TIMEOUT_S", 0.0)
    monkeypatch.setattr(manager, "_connect_ctrl_socket_locked", lambda: None)
    monkeypatch.setattr(manager, "_start_event_listener_locked", lambda: None)
    monkeypatch.setattr(
        manager,
        "_send_ctrl_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("not ready")),
    )
    monkeypatch.setattr(manager, "_runtime_targets_service", _FakeRuntimeTargetsService())

    with pytest.raises(RuntimeError) as exc_info:
        manager.start(
            model_id="model-1",
            runtime_target_id="cpu",
            task="pick",
        )

    assert str(exc_info.value) == "Timed out waiting for worker control socket"
    assert manager.get_status().runner_status.last_error == "Timed out waiting for worker control socket"

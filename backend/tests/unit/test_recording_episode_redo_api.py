import asyncio
import importlib.util
import os
from pathlib import Path
import sys

from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _load_recording_api_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "interfaces_backend"
        / "api"
        / "recording.py"
    )
    spec = importlib.util.spec_from_file_location("interfaces_backend_api_recording_retake_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


recording_api = _load_recording_api_module()


def test_retake_previous_episode_surfaces_recorder_message(monkeypatch):
    class _FakeRecorder:
        def status(self):
            return {"state": "recording", "dataset_id": "dataset-1"}

        def retake_previous_episode(self):
            return {"success": False, "message": "retake output missing meta/info.json"}

    monkeypatch.setattr(recording_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(recording_api, "get_recorder_bridge", lambda: _FakeRecorder())

    try:
        asyncio.run(recording_api.retake_previous_episode())
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "retake output missing meta/info.json"


def test_retake_previous_episode_surfaces_cancel_message(monkeypatch):
    class _FakeRecorder:
        def status(self):
            return {"state": "recording", "dataset_id": "dataset-1"}

        def retake_previous_episode(self):
            return {"success": False, "message": "not recording"}

    monkeypatch.setattr(recording_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(recording_api, "get_recorder_bridge", lambda: _FakeRecorder())

    try:
        asyncio.run(recording_api.retake_previous_episode())
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "not recording"


def test_retake_previous_episode_surfaces_retake_message(monkeypatch):
    class _FakeRecorder:
        def status(self):
            return {"state": "resetting", "dataset_id": "dataset-1"}

        def retake_previous_episode(self):
            return {"success": False, "message": "retake output missing meta/info.json"}

    monkeypatch.setattr(recording_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(recording_api, "get_recorder_bridge", lambda: _FakeRecorder())

    try:
        asyncio.run(recording_api.retake_previous_episode())
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "retake output missing meta/info.json"

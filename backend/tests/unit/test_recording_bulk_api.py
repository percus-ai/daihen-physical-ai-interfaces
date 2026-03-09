import asyncio
import importlib.util
import os
from pathlib import Path
import sys

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _load_recording_api_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "interfaces_backend"
        / "api"
        / "recording.py"
    )
    spec = importlib.util.spec_from_file_location("interfaces_backend_api_recording_bulk_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


recording_api = _load_recording_api_module()


def test_bulk_reupload_recordings_returns_summary(monkeypatch):
    monkeypatch.setattr(recording_api, "require_user_id", lambda: "user-1")

    async def _fake_reupload(recording_id: str):
        if recording_id == "dataset-1":
            return recording_api.BulkActionResult(id=recording_id, status="succeeded", message="ok")
        return recording_api.BulkActionResult(id=recording_id, status="failed", message="missing")

    monkeypatch.setattr(recording_api, "reupload_dataset_for_bulk", _fake_reupload)

    response = asyncio.run(
        recording_api.bulk_reupload_recordings(recording_api.BulkActionRequest(ids=["dataset-1", "dataset-2"]))
    )

    assert response.requested == 2
    assert response.succeeded == 1
    assert response.failed == 1


def test_bulk_archive_recordings_returns_summary(monkeypatch):
    monkeypatch.setattr(recording_api, "require_user_id", lambda: "user-1")

    async def _fake_archive(recording_id: str):
        return recording_api.BulkActionResult(id=recording_id, status="succeeded", message="archived")

    monkeypatch.setattr(recording_api, "archive_dataset_for_bulk", _fake_archive)

    response = asyncio.run(
        recording_api.bulk_archive_recordings(recording_api.BulkActionRequest(ids=["dataset-1"]))
    )

    assert response.requested == 1
    assert response.succeeded == 1
    assert response.failed == 0

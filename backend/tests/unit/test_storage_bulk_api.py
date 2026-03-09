import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _install_lerobot_stubs() -> None:
    lerobot_module = sys.modules.setdefault("lerobot", ModuleType("lerobot"))
    datasets_module = sys.modules.setdefault("lerobot.datasets", ModuleType("lerobot.datasets"))
    aggregate_module = sys.modules.setdefault(
        "lerobot.datasets.aggregate",
        ModuleType("lerobot.datasets.aggregate"),
    )
    lerobot_dataset_module = sys.modules.setdefault(
        "lerobot.datasets.lerobot_dataset",
        ModuleType("lerobot.datasets.lerobot_dataset"),
    )

    setattr(aggregate_module, "aggregate_datasets", lambda **kwargs: None)

    class _DummyLeRobotDatasetMetadata:
        def __init__(self, *_args, **_kwargs):
            self.total_episodes = 0

    setattr(lerobot_dataset_module, "LeRobotDatasetMetadata", _DummyLeRobotDatasetMetadata)
    setattr(datasets_module, "aggregate", aggregate_module)
    setattr(datasets_module, "lerobot_dataset", lerobot_dataset_module)
    setattr(lerobot_module, "datasets", datasets_module)


def _load_storage_api_module():
    module_path = Path(__file__).resolve().parents[2] / "src" / "interfaces_backend" / "api" / "storage.py"
    spec = importlib.util.spec_from_file_location("storage_api_bulk_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_install_lerobot_stubs()
storage_api = _load_storage_api_module()


def test_bulk_archive_datasets_returns_summary(monkeypatch):
    monkeypatch.setattr(storage_api, "require_user_id", lambda: "user-1")

    async def _fake_archive(dataset_id: str):
        mapping = {
            "dataset-1": storage_api.BulkActionResult(id=dataset_id, status="succeeded", message="ok"),
            "dataset-2": storage_api.BulkActionResult(id=dataset_id, status="skipped", message="skip"),
        }
        return mapping[dataset_id]

    monkeypatch.setattr(storage_api, "archive_dataset_for_bulk", _fake_archive)

    response = asyncio.run(
        storage_api.bulk_archive_datasets(storage_api.BulkActionRequest(ids=["dataset-1", "dataset-2"]))
    )

    assert response.requested == 2
    assert response.succeeded == 1
    assert response.skipped == 1
    assert response.failed == 0


def test_bulk_sync_models_returns_summary(monkeypatch):
    monkeypatch.setattr(storage_api, "require_user_id", lambda: "user-1")

    async def _fake_sync(*, user_id: str, model_id: str):
        assert user_id == "user-1"
        if model_id == "model-1":
            return storage_api.BulkActionResult(id=model_id, status="succeeded", message="ok", job_id="job-1")
        return storage_api.BulkActionResult(id=model_id, status="failed", message="nope")

    monkeypatch.setattr(storage_api, "sync_model_for_bulk", _fake_sync)

    response = asyncio.run(
        storage_api.bulk_sync_models(storage_api.BulkActionRequest(ids=["model-1", "model-2"]))
    )

    assert response.requested == 2
    assert response.succeeded == 1
    assert response.failed == 1
    assert response.results[0].job_id == "job-1"

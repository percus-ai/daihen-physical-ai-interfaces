import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


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
    repo_root = _find_repo_root(Path(__file__).resolve())
    module_path = repo_root / "interfaces" / "backend" / "src" / "interfaces_backend" / "api" / "storage.py"
    spec = importlib.util.spec_from_file_location("storage_api_rename_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load storage module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_install_lerobot_stubs()
storage_api = _load_storage_api_module()


class _FakeTableQuery:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table_name = table_name
        self._filters: list[tuple[str, str]] = []
        self._update_payload: dict | None = None

    def select(self, *_fields):
        return self

    def eq(self, key: str, value: str):
        self._filters.append((key, value))
        return self

    def update(self, payload: dict):
        self._update_payload = payload
        return self

    async def execute(self):
        rows = self._client.rows_by_table.setdefault(self._table_name, [])
        matched_rows = [row for row in rows if all(str(row.get(key)) == str(value) for key, value in self._filters)]
        if self._update_payload is not None:
            for row in matched_rows:
                row.update(self._update_payload)
        return SimpleNamespace(data=[dict(row) for row in matched_rows])


class _FakeStorageDbClient:
    def __init__(self):
        self.rows_by_table: dict[str, list[dict]] = {
            "datasets": [],
            "models": [],
        }

    def table(self, table_name: str):
        return _FakeTableQuery(self, table_name)


def _install_db_client(monkeypatch: pytest.MonkeyPatch, client: _FakeStorageDbClient) -> None:
    async def _fake_get_supabase():
        return client

    monkeypatch.setattr(storage_api, "get_supabase_async_client", _fake_get_supabase)


def test_rename_dataset_updates_display_name(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeStorageDbClient()
    fake_client.rows_by_table["datasets"] = [
        {"id": "dataset-1", "name": "old_name", "status": "archived"},
    ]
    _install_db_client(monkeypatch, fake_client)
    monkeypatch.setattr(storage_api, "require_user_id", lambda: "user-1")

    response = asyncio.run(
        storage_api.rename_dataset(
            "dataset-1",
            storage_api.StorageRenameRequest(name="  new_dataset_name  "),
        )
    )

    assert response.id == "dataset-1"
    assert response.name == "new_dataset_name"
    assert fake_client.rows_by_table["datasets"][0]["name"] == "new_dataset_name"


def test_rename_dataset_rejects_invalid_name(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeStorageDbClient()
    fake_client.rows_by_table["datasets"] = [{"id": "dataset-1", "name": "old_name", "status": "active"}]
    _install_db_client(monkeypatch, fake_client)
    monkeypatch.setattr(storage_api, "require_user_id", lambda: "user-1")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            storage_api.rename_dataset(
                "dataset-1",
                storage_api.StorageRenameRequest(name="bad/name"),
            )
        )

    assert exc_info.value.status_code == 400
    assert "path separators" in str(exc_info.value.detail)


def test_rename_model_updates_name_and_keeps_owner_metadata(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeStorageDbClient()
    fake_client.rows_by_table["models"] = [
        {
            "id": "model-1",
            "name": "old_model",
            "status": "archived",
            "owner_user_id": "user-1",
        },
    ]
    _install_db_client(monkeypatch, fake_client)
    monkeypatch.setattr(storage_api, "require_user_id", lambda: "user-1")

    async def _fake_resolve_user_directory_entries(_ids):
        return {"user-1": SimpleNamespace(email="user@example.com", name="User One")}

    monkeypatch.setattr(storage_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)

    response = asyncio.run(
        storage_api.rename_model(
            "model-1",
            storage_api.StorageRenameRequest(name="renamed_model"),
        )
    )

    assert response.id == "model-1"
    assert response.name == "renamed_model"
    assert response.owner_email == "user@example.com"
    assert response.owner_name == "User One"
    assert fake_client.rows_by_table["models"][0]["name"] == "renamed_model"


def test_rename_model_raises_not_found(monkeypatch: pytest.MonkeyPatch):
    fake_client = _FakeStorageDbClient()
    _install_db_client(monkeypatch, fake_client)
    monkeypatch.setattr(storage_api, "require_user_id", lambda: "user-1")

    async def _fake_resolve_user_directory_entries(_ids):
        return {}

    monkeypatch.setattr(storage_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            storage_api.rename_model(
                "missing-model",
                storage_api.StorageRenameRequest(name="model_name"),
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Model not found: missing-model"

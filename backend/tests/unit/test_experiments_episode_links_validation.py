from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


def _load_experiments_api_module():
    repo_root = _find_repo_root(Path(__file__).resolve())
    module_path = repo_root / "interfaces" / "backend" / "src" / "interfaces_backend" / "api" / "experiments.py"
    spec = importlib.util.spec_from_file_location("experiments_api_for_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load experiments module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

experiments_api = _load_experiments_api_module()


class _FakeTableQuery:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table_name = table_name
        self._op = "select"
        self._in_filters: list[tuple[str, list[str]]] = []

    def select(self, _fields: str):
        self._op = "select"
        return self

    def in_(self, key: str, values: list[str]):
        self._in_filters.append((key, values))
        return self

    async def execute(self):
        if self._table_name == "datasets" and self._op == "select":
            dataset_ids: list[str] = []
            for key, values in self._in_filters:
                if key == "id":
                    dataset_ids = list(values)
                    break
            rows = [self._client.dataset_rows[dataset_id] for dataset_id in dataset_ids if dataset_id in self._client.dataset_rows]
            return SimpleNamespace(data=rows)
        return SimpleNamespace(data=[])


class _FakeDbClient:
    def __init__(self):
        self.dataset_rows: dict[str, dict] = {}

    def table(self, table_name: str):
        return _FakeTableQuery(self, table_name)


def _item_with_link(*, dataset_id: str, episode_index: int):
    return SimpleNamespace(
        value="ok",
        episode_links=[
            SimpleNamespace(
                dataset_id=dataset_id,
                episode_index=episode_index,
                sort_order=0,
            )
        ],
    )


def test_validate_episode_links_accepts_existing_dataset_and_episode_index() -> None:
    client = _FakeDbClient()
    client.dataset_rows["dataset-a"] = {"id": "dataset-a", "episode_count": 3}
    items = [_item_with_link(dataset_id="dataset-a", episode_index=2)]

    asyncio.run(experiments_api._validate_episode_links(client, items))


def test_validate_episode_links_rejects_unknown_dataset_id() -> None:
    client = _FakeDbClient()
    items = [_item_with_link(dataset_id="dataset-missing", episode_index=0)]

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(experiments_api._validate_episode_links(client, items))

    assert exc_info.value.status_code == 400
    assert "Invalid dataset_id in episode_links" in str(exc_info.value.detail)
    assert "dataset-missing" in str(exc_info.value.detail)


def test_validate_episode_links_rejects_out_of_range_episode_index() -> None:
    client = _FakeDbClient()
    client.dataset_rows["dataset-a"] = {"id": "dataset-a", "episode_count": 2}
    items = [_item_with_link(dataset_id="dataset-a", episode_index=2)]

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(experiments_api._validate_episode_links(client, items))

    assert exc_info.value.status_code == 400
    assert "Invalid episode_index in episode_links" in str(exc_info.value.detail)
    assert "dataset-a:2 (total=2)" in str(exc_info.value.detail)

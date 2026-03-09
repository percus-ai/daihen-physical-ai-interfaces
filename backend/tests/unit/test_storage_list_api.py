import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

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
    spec = importlib.util.spec_from_file_location("storage_api_list_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_install_lerobot_stubs()
storage_api = _load_storage_api_module()


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._eq_filters: list[tuple[str, object]] = []
        self._order_key: str | None = None
        self._order_desc = False
        self._limit: int | None = None
        self._offset = 0
        self._or_filters: list[tuple[str, str]] = []
        self._count_method: str | None = None

    def select(self, *_columns, count=None, head=None):
        self._count_method = count
        return self

    def eq(self, key, value):
        self._eq_filters.append((key, value))
        return self

    def order(self, key, *, desc=False, nullsfirst=None, foreign_table=None):
        self._order_key = key
        self._order_desc = desc
        return self

    def limit(self, size):
        self._limit = size
        return self

    def offset(self, size):
        self._offset = size
        return self

    def or_(self, filters, reference_table=None):
        for clause in filters.split(","):
            parts = clause.split(".")
            if len(parts) < 3:
                continue
            field = parts[0]
            operator = parts[1]
            term = ".".join(parts[2:])
            if operator != "ilike":
                continue
            self._or_filters.append((field, term.strip("%").lower()))
        return self

    async def execute(self):
        rows = list(self._rows)
        for key, value in self._eq_filters:
            rows = [row for row in rows if row.get(key) == value]
        if self._or_filters:
            rows = [
                row
                for row in rows
                if any(term in str(row.get(field) or "").lower() for field, term in self._or_filters)
            ]
        if self._order_key:
            rows.sort(key=lambda row: row.get(self._order_key) or "", reverse=self._order_desc)
        total = len(rows)
        if self._offset:
            rows = rows[self._offset :]
        if self._limit is not None:
            rows = rows[: self._limit]
        count = total if self._count_method == "exact" else None
        return SimpleNamespace(data=rows, count=count)


class _FakeClient:
    def __init__(self, rows_by_table):
        self._rows_by_table = rows_by_table

    def table(self, name):
        return _FakeQuery(self._rows_by_table.get(name, []))


def test_list_datasets_supports_search_sort_and_limit(monkeypatch, tmp_path: Path):
    rows = [
        {
            "id": "dataset-old",
            "name": "Dataset old",
            "status": "active",
            "dataset_type": "recorded",
            "episode_count": 2,
            "size_bytes": 10,
            "created_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": "dataset-new",
            "name": "Dataset new",
            "status": "active",
            "dataset_type": "recorded",
            "episode_count": 3,
            "size_bytes": 20,
            "created_at": "2026-02-01T00:00:00Z",
        },
        {
            "id": "dataset-archived",
            "name": "Dataset archived",
            "status": "archived",
            "dataset_type": "recorded",
            "episode_count": 1,
            "size_bytes": 5,
            "created_at": "2026-03-01T00:00:00Z",
        },
    ]

    async def _fake_get_supabase():
        return _FakeClient({"datasets": rows})

    async def _fake_resolve_user_directory_entries(_ids):
        return {}

    monkeypatch.setattr(storage_api, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(storage_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)
    monkeypatch.setattr(storage_api, "get_datasets_dir", lambda: tmp_path / "datasets")

    response = asyncio.run(
        storage_api._list_datasets(
            storage_api.DatasetListQuery(
                search="dataset",
                limit=1,
                sort_by="created_at",
                sort_order="desc",
            )
        )
    )

    assert response.total == 2
    assert [dataset.id for dataset in response.datasets] == ["dataset-new"]


def test_list_models_supports_column_filters(monkeypatch, tmp_path: Path):
    rows = [
        {
            "id": "model-a",
            "name": "Model A",
            "status": "active",
            "policy_type": "pi0",
            "dataset_id": "dataset-1",
            "created_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": "model-b",
            "name": "Model B",
            "status": "active",
            "policy_type": "pi05",
            "dataset_id": "dataset-1",
            "created_at": "2026-02-01T00:00:00Z",
        },
        {
            "id": "model-c",
            "name": "Model C",
            "status": "archived",
            "policy_type": "pi05",
            "dataset_id": "dataset-2",
            "created_at": "2026-03-01T00:00:00Z",
        },
    ]

    async def _fake_get_supabase():
        return _FakeClient({"models": rows})

    async def _fake_resolve_user_directory_entries(_ids):
        return {}

    monkeypatch.setattr(storage_api, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(storage_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)
    monkeypatch.setattr(storage_api, "get_models_dir", lambda: tmp_path / "models")

    response = asyncio.run(
        storage_api._list_models(
            storage_api.ModelListQuery(
                dataset_id="dataset-1",
                policy_type="pi05",
                sort_by="created_at",
                sort_order="desc",
            )
        )
    )

    assert response.total == 1
    assert [model.id for model in response.models] == ["model-b"]


def test_list_models_profile_filter_applies_before_pagination(monkeypatch, tmp_path: Path):
    rows = [
        {
            "id": "model-1",
            "name": "Model 1",
            "status": "active",
            "profile_name": "profile-a",
            "created_at": "2026-03-03T00:00:00Z",
        },
        {
            "id": "model-2",
            "name": "Model 2",
            "status": "active",
            "profile_name": "profile-a",
            "created_at": "2026-03-02T00:00:00Z",
        },
        {
            "id": "model-3",
            "name": "Model 3",
            "status": "active",
            "profile_name": "profile-b",
            "created_at": "2026-03-01T00:00:00Z",
        },
    ]

    async def _fake_get_supabase():
        return _FakeClient({"models": rows})

    async def _fake_resolve_user_directory_entries(_ids):
        return {}

    monkeypatch.setattr(storage_api, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(storage_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)
    monkeypatch.setattr(storage_api, "get_models_dir", lambda: tmp_path / "models")

    response = asyncio.run(
        storage_api._list_models(
            storage_api.ModelListQuery(
                profile_name="profile-a",
                limit=1,
                offset=1,
                sort_by="created_at",
                sort_order="desc",
            )
        )
    )

    assert response.total == 2
    assert [model.id for model in response.models] == ["model-2"]

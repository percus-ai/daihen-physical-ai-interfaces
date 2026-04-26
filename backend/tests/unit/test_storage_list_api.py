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
    def __init__(self, table_name, rows):
        self.table_name = table_name
        self._rows = rows
        self._eq_filters: list[tuple[str, object]] = []
        self._gte_filters: list[tuple[str, object]] = []
        self._lte_filters: list[tuple[str, object]] = []
        self._ilike_filters: list[tuple[str, str]] = []
        self._order_key: str | None = None
        self._order_desc = False
        self._limit: int | None = None
        self._offset = 0
        self._range: tuple[int, int] | None = None
        self._or_filters: list[tuple[str, str]] = []
        self._count_method: str | None = None
        self.selected_columns: str | None = None

    def select(self, columns="*", count=None, head=None):
        self.selected_columns = columns
        self._count_method = count
        return self

    def eq(self, key, value):
        self._eq_filters.append((key, value))
        return self

    def gte(self, key, value):
        self._gte_filters.append((key, value))
        return self

    def lte(self, key, value):
        self._lte_filters.append((key, value))
        return self

    def ilike(self, key, pattern):
        self._ilike_filters.append((key, pattern))
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

    def range(self, start, end):
        self._range = (start, end)
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
        for key, value in self._gte_filters:
            rows = [row for row in rows if (row.get(key) is not None and row.get(key) >= value)]
        for key, value in self._lte_filters:
            rows = [row for row in rows if (row.get(key) is not None and row.get(key) <= value)]
        for key, pattern in self._ilike_filters:
            term = pattern.strip("%").replace("\\,", ",").lower()
            rows = [row for row in rows if term in str(row.get(key) or "").lower()]
        if self._or_filters:
            rows = [
                row
                for row in rows
                if any(term in str(row.get(field) or "").lower() for field, term in self._or_filters)
            ]
        if self._order_key:
            rows.sort(key=lambda row: row.get(self._order_key) or "", reverse=self._order_desc)
        total = len(rows)
        if self._range is not None:
            start, end = self._range
            rows = rows[start : end + 1]
        elif self._offset:
            rows = rows[self._offset :]
        if self._range is None and self._limit is not None:
            rows = rows[: self._limit]
        count = total if self._count_method == "exact" else None
        return SimpleNamespace(data=rows, count=count)


class _FakeClient:
    def __init__(self, rows_by_table):
        self._rows_by_table = rows_by_table
        self.queries: list[_FakeQuery] = []

    def table(self, name):
        query = _FakeQuery(name, self._rows_by_table.get(name, []))
        self.queries.append(query)
        return query

    def queries_for(self, table_name):
        return [query for query in self.queries if query.table_name == table_name]


def _assert_profile_snapshot_not_selected(client: _FakeClient, table_name: str):
    for query in client.queries_for(table_name):
        assert query.selected_columns is not None
        selected = {column.strip() for column in query.selected_columns.split(",")}
        assert "profile_snapshot" not in selected
        assert "source_datasets" not in selected
        assert "archived_at" not in selected
        assert "*" not in selected


def _patch_storage_list_dependencies(monkeypatch, tmp_path: Path, rows_by_table) -> _FakeClient:
    client = _FakeClient(rows_by_table)

    async def _fake_get_supabase():
        return client

    async def _fake_resolve_user_directory_entries(_ids):
        return {}

    empty_jobs_service = SimpleNamespace(list=lambda **_kwargs: SimpleNamespace(jobs=[]))

    monkeypatch.setattr(storage_api, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(storage_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)
    monkeypatch.setattr(storage_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(storage_api, "get_dataset_sync_jobs_service", lambda: empty_jobs_service)
    monkeypatch.setattr(storage_api, "get_model_sync_jobs_service", lambda: empty_jobs_service)
    monkeypatch.setattr(storage_api, "get_datasets_dir", lambda: tmp_path / "datasets")
    monkeypatch.setattr(storage_api, "get_models_dir", lambda: tmp_path / "models")
    return client


def test_list_datasets_supports_search_sort_and_limit_in_db(monkeypatch, tmp_path: Path):
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

    client = _patch_storage_list_dependencies(monkeypatch, tmp_path, {"datasets": rows})

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
    list_query = next(query for query in client.queries_for("datasets") if query._range == (0, 0))
    assert ("status", "active") in list_query._eq_filters
    assert list_query._ilike_filters == [("name", "%dataset%")]
    assert list_query._order_key == "created_at"
    assert list_query._order_desc is True
    assert list_query._range == (0, 0)
    _assert_profile_snapshot_not_selected(client, "datasets")


def test_list_models_supports_column_filters_sort_and_limit_in_db(monkeypatch, tmp_path: Path):
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

    client = _patch_storage_list_dependencies(monkeypatch, tmp_path, {"models": rows})

    response = asyncio.run(
        storage_api._list_models(
            storage_api.ModelListQuery(
                dataset_id="dataset-1",
                policy_type="pi05",
                limit=1,
                sort_by="created_at",
                sort_order="desc",
            )
        )
    )

    assert response.total == 1
    assert [model.id for model in response.models] == ["model-b"]
    list_query = next(query for query in client.queries_for("models") if query._range == (0, 0))
    assert ("status", "active") in list_query._eq_filters
    assert ("policy_type", "pi05") in list_query._eq_filters
    assert list_query._ilike_filters == [("dataset_id", "%dataset-1%")]
    assert list_query._order_key == "created_at"
    assert list_query._order_desc is True
    assert list_query._range == (0, 0)
    _assert_profile_snapshot_not_selected(client, "models")


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

    client = _patch_storage_list_dependencies(monkeypatch, tmp_path, {"models": rows})

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
    list_query = next(query for query in client.queries_for("models") if query._range == (1, 1))
    assert ("profile_name", "profile-a") in list_query._eq_filters
    assert list_query._order_key == "created_at"
    assert list_query._order_desc is True
    _assert_profile_snapshot_not_selected(client, "models")


def test_list_datasets_checks_local_path_only_for_paged_rows(monkeypatch, tmp_path: Path):
    rows = [
        {
            "id": "dataset-1",
            "name": "Dataset 1",
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": "dataset-2",
            "name": "Dataset 2",
            "status": "active",
            "created_at": "2026-01-02T00:00:00Z",
        },
    ]
    client = _patch_storage_list_dependencies(monkeypatch, tmp_path, {"datasets": rows})
    datasets_dir = tmp_path / "datasets"
    (datasets_dir / "dataset-2").mkdir(parents=True)

    response = asyncio.run(
        storage_api._list_datasets(
            storage_api.DatasetListQuery(
                limit=1,
                sort_by="created_at",
                sort_order="desc",
            )
        )
    )

    assert response.total == 2
    assert [(dataset.id, dataset.is_local) for dataset in response.datasets] == [("dataset-2", True)]
    assert next(query for query in client.queries_for("datasets") if query._range == (0, 0))
    _assert_profile_snapshot_not_selected(client, "datasets")


def test_list_archive_uses_lightweight_columns(monkeypatch, tmp_path: Path):
    rows_by_table = {
        "datasets": [
            {
                "id": "dataset-archived",
                "name": "Dataset archived",
                "status": "archived",
                "created_at": "2026-01-01T00:00:00Z",
            }
        ],
        "models": [
            {
                "id": "model-archived",
                "name": "Model archived",
                "status": "archived",
                "created_at": "2026-01-01T00:00:00Z",
            }
        ],
    }
    client = _patch_storage_list_dependencies(monkeypatch, tmp_path, rows_by_table)

    response = asyncio.run(storage_api.list_archived())

    assert response.total == 2
    assert [dataset.id for dataset in response.datasets] == ["dataset-archived"]
    assert [model.id for model in response.models] == ["model-archived"]
    assert client.queries_for("datasets")[0]._eq_filters == [("status", "archived")]
    assert client.queries_for("models")[0]._eq_filters == [("status", "archived")]
    _assert_profile_snapshot_not_selected(client, "datasets")
    _assert_profile_snapshot_not_selected(client, "models")


def test_storage_usage_selects_only_size_and_status(monkeypatch, tmp_path: Path):
    rows_by_table = {
        "datasets": [
            {"size_bytes": 10, "status": "active"},
            {"size_bytes": 5, "status": "archived"},
        ],
        "models": [
            {"size_bytes": 20, "status": "active"},
            {"size_bytes": 7, "status": "archived"},
        ],
    }
    client = _patch_storage_list_dependencies(monkeypatch, tmp_path, rows_by_table)

    response = asyncio.run(storage_api.get_storage_usage())

    assert response.datasets_count == 1
    assert response.datasets_size_bytes == 10
    assert response.models_count == 1
    assert response.models_size_bytes == 20
    assert response.archive_count == 2
    assert response.archive_size_bytes == 12
    assert response.total_size_bytes == 42
    assert [query.selected_columns for query in client.queries_for("datasets")] == ["size_bytes,status"]
    assert [query.selected_columns for query in client.queries_for("models")] == ["size_bytes,status"]

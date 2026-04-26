from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


def _load_experiments_api_module():
    repo_root = _find_repo_root(Path(__file__).resolve())
    module_path = (
        repo_root
        / "interfaces"
        / "backend"
        / "src"
        / "interfaces_backend"
        / "api"
        / "experiments.py"
    )
    spec = importlib.util.spec_from_file_location(
        "experiments_list_api_for_test", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load experiments module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


experiments_api = _load_experiments_api_module()


class _FakeTableQuery:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.select_fields: str | None = None
        self.select_count: str | None = None
        self.eq_filters: list[tuple[str, object]] = []
        self.gte_filters: list[tuple[str, object]] = []
        self.lte_filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, list[object]]] = []
        self.orders: list[tuple[str, bool]] = []
        self.ranges: list[tuple[int, int]] = []

    def select(self, fields: str, count: str | None = None):
        self.select_fields = fields
        self.select_count = count
        return self

    def eq(self, key: str, value: object):
        self.eq_filters.append((key, value))
        return self

    def gte(self, key: str, value: object):
        self.gte_filters.append((key, value))
        return self

    def lte(self, key: str, value: object):
        self.lte_filters.append((key, value))
        return self

    def in_(self, key: str, values: list[object]):
        self.in_filters.append((key, values))
        return self

    def order(self, key: str, desc: bool = False):
        self.orders.append((key, desc))
        return self

    def range(self, start: int, end: int):
        self.ranges.append((start, end))
        return self

    async def execute(self):
        rows = list(self._rows)
        for key, value in self.eq_filters:
            rows = [row for row in rows if row.get(key) == value]
        for key, value in self.gte_filters:
            rows = [row for row in rows if str(row.get(key) or "") >= str(value)]
        for key, value in self.lte_filters:
            rows = [row for row in rows if str(row.get(key) or "") <= str(value)]
        for key, values in self.in_filters:
            values_set = set(values)
            rows = [row for row in rows if row.get(key) in values_set]
        for key, desc in reversed(self.orders):
            rows.sort(key=lambda row: row.get(key) or "", reverse=desc)
        total = len(rows)
        for start, end in self.ranges:
            rows = rows[start : end + 1]
        return SimpleNamespace(data=rows, count=total)


class _FakeDbClient:
    def __init__(self):
        self.queries_by_table: dict[str, list[_FakeTableQuery]] = {}
        self.rows_by_table = {
            "experiments": [
                {
                    "id": "exp-new",
                    "model_id": "model-a",
                    "profile_instance_id": "profile-a",
                    "name": "New",
                    "evaluation_count": 5,
                    "metric": "binary",
                    "metric_options": ["ok", "ng"],
                    "updated_at": "2026-01-20T00:00:00+00:00",
                    "notes": "detail-only",
                    "result_image_files": ["heavy.png"],
                },
                {
                    "id": "exp-old",
                    "model_id": "model-a",
                    "profile_instance_id": "profile-a",
                    "name": "Old",
                    "evaluation_count": 2,
                    "metric": "binary",
                    "metric_options": ["ok", "ng"],
                    "updated_at": "2026-01-10T00:00:00+00:00",
                    "notes": "detail-only",
                    "result_image_files": ["heavy.png"],
                },
                {
                    "id": "exp-other",
                    "model_id": "model-b",
                    "profile_instance_id": "profile-a",
                    "name": "Other",
                    "evaluation_count": 2,
                    "metric": "binary",
                    "metric_options": ["ok", "ng"],
                    "updated_at": "2026-01-15T00:00:00+00:00",
                },
            ],
            "experiment_evaluations": [
                {"experiment_id": "exp-old", "value": "ok"},
                {"experiment_id": "exp-old", "value": "ng"},
                {"experiment_id": "exp-new", "value": "ok"},
            ],
            "experiment_analyses": [
                {"experiment_id": "exp-old"},
                {"experiment_id": "exp-old"},
                {"experiment_id": "exp-new"},
            ],
        }

    def table(self, table_name: str):
        query = _FakeTableQuery(self.rows_by_table.get(table_name, []))
        self.queries_by_table.setdefault(table_name, []).append(query)
        return query

    def queries_for(self, table_name: str) -> list[_FakeTableQuery]:
        return self.queries_by_table.get(table_name, [])


def test_list_experiments_selects_summary_columns_and_applies_db_pagination(
    monkeypatch,
):
    fake_client = _FakeDbClient()

    async def _get_client():
        return fake_client

    monkeypatch.setattr(experiments_api, "get_supabase_async_client", _get_client)

    response = asyncio.run(
        experiments_api.list_experiments(
            model_id="model-a",
            profile_instance_id="profile-a",
            updated_from="2026-01-01",
            updated_to="2026-01-31",
            evaluation_count_min=1,
            evaluation_count_max=5,
            limit=1,
            offset=1,
        )
    )

    query = fake_client.queries_for("experiments")[0]
    assert query.select_fields == experiments_api._EXPERIMENT_LIST_COLUMNS
    assert "*" not in query.select_fields
    assert "notes" not in query.select_fields
    assert "result_image_files" not in query.select_fields
    assert query.select_count == "exact"
    assert query.orders == [("updated_at", True)]
    assert query.ranges == [(1, 1)]
    assert ("model_id", "model-a") in query.eq_filters
    assert ("profile_instance_id", "profile-a") in query.eq_filters
    assert ("updated_at", "2026-01-01") in query.gte_filters
    assert ("updated_at", "2026-01-31T23:59:59.999999+00:00") in query.lte_filters
    assert ("evaluation_count", 1) in query.gte_filters
    assert ("evaluation_count", 5) in query.lte_filters
    assert response.total == 2
    assert [experiment.id for experiment in response.experiments] == ["exp-old"]
    assert response.experiments[0].evaluation_summary is not None
    assert response.experiments[0].evaluation_summary.total == 2
    assert response.experiments[0].evaluation_summary.counts == {"ok": 1, "ng": 1}
    assert response.experiments[0].analysis_count == 2
    assert fake_client.queries_for("experiment_evaluations")[0].select_fields == "experiment_id,value"
    assert fake_client.queries_for("experiment_analyses")[0].select_fields == "experiment_id"


def test_list_experiments_rejects_invalid_pagination_bounds():
    app = FastAPI()
    app.include_router(experiments_api.router)

    with TestClient(app) as client:
        assert client.get("/api/experiments?limit=0").status_code == 422
        assert client.get("/api/experiments?limit=501").status_code == 422
        assert client.get("/api/experiments?offset=-1").status_code == 422

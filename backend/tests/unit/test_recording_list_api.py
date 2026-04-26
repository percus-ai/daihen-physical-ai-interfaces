import asyncio
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _load_recording_api_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "interfaces_backend"
        / "api"
        / "recording.py"
    )
    spec = importlib.util.spec_from_file_location("interfaces_backend_api_recording_list_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


recording_api = _load_recording_api_module()


def _recording_rows() -> list[dict]:
    return [
        {
            "id": "rec-old",
            "name": "pick old",
            "task_detail": "pick",
            "profile_name": "profile-a",
            "profile_snapshot": {"name": "profile-a"},
            "episode_count": 2,
            "target_total_episodes": 5,
            "episode_time_s": 30.0,
            "reset_time_s": 5.0,
            "size_bytes": 100,
            "created_at": "2026-01-01T00:00:00+00:00",
            "dataset_type": "recorded",
            "status": "active",
            "owner_user_id": "user-1",
            "content_hash": "",
        },
        {
            "id": "rec-new",
            "name": "pick new",
            "task_detail": "pick",
            "profile_name": "profile-a",
            "profile_snapshot": {"name": "profile-a"},
            "episode_count": 5,
            "target_total_episodes": 9,
            "episode_time_s": 30.0,
            "reset_time_s": 5.0,
            "size_bytes": 300,
            "created_at": "2026-02-01T00:00:00+00:00",
            "dataset_type": "recorded",
            "status": "active",
            "owner_user_id": "user-1",
            "content_hash": "hash-new",
        },
        {
            "id": "rec-other-owner",
            "name": "pick other",
            "task_detail": "pick",
            "profile_name": "profile-a",
            "profile_snapshot": {"name": "profile-a"},
            "episode_count": 4,
            "target_total_episodes": 6,
            "episode_time_s": 30.0,
            "reset_time_s": 5.0,
            "size_bytes": 250,
            "created_at": "2026-02-15T00:00:00+00:00",
            "dataset_type": "recorded",
            "status": "active",
            "owner_user_id": "user-2",
            "content_hash": "",
        },
        {
            "id": "rec-archived",
            "name": "pick archived",
            "task_detail": "pick",
            "profile_name": "profile-a",
            "profile_snapshot": {"name": "profile-a"},
            "episode_count": 6,
            "target_total_episodes": 8,
            "episode_time_s": 30.0,
            "reset_time_s": 5.0,
            "size_bytes": 400,
            "created_at": "2026-03-01T00:00:00+00:00",
            "dataset_type": "recorded",
            "status": "archived",
            "owner_user_id": "user-1",
            "content_hash": "",
        },
    ]


class _FakeQuery:
    def __init__(self, rows: list[dict], queries: list["_FakeQuery"]):
        self._rows = rows
        self._queries = queries
        self.selected_columns: str | None = None
        self.count: str | None = None
        self.filters: list[tuple[str, str, object]] = []
        self.orders: list[tuple[str, bool]] = []
        self.range_call: tuple[int, int] | None = None
        self.limit_call: int | None = None
        queries.append(self)

    def select(self, columns: str, count=None, head=None):
        self.selected_columns = columns
        self.count = count
        return self

    def eq(self, field: str, value: object):
        self.filters.append(("eq", field, value))
        return self

    def neq(self, field: str, value: object):
        self.filters.append(("neq", field, value))
        return self

    def ilike(self, field: str, pattern: str):
        self.filters.append(("ilike", field, pattern))
        return self

    def gte(self, field: str, value: object):
        self.filters.append(("gte", field, value))
        return self

    def lte(self, field: str, value: object):
        self.filters.append(("lte", field, value))
        return self

    def order(self, field: str, *, desc=False, nullsfirst=None, foreign_table=None):
        self.orders.append((field, bool(desc)))
        return self

    def range(self, start: int, end: int):
        self.range_call = (start, end)
        return self

    def limit(self, size: int):
        self.limit_call = size
        return self

    async def execute(self):
        rows = list(self._rows)
        for operator, field, value in self.filters:
            if operator == "eq":
                rows = [row for row in rows if row.get(field) == value]
            elif operator == "neq":
                rows = [row for row in rows if row.get(field) != value]
            elif operator == "ilike":
                term = str(value).strip("%").replace("\\,", ",").lower()
                rows = [row for row in rows if term in str(row.get(field) or "").lower()]
            elif operator == "gte":
                rows = [row for row in rows if row.get(field) is not None and row.get(field) >= value]
            elif operator == "lte":
                rows = [row for row in rows if row.get(field) is not None and row.get(field) <= value]
        for field, desc in reversed(self.orders):
            rows.sort(key=lambda row: row.get(field) or "", reverse=desc)
        total = len(rows)
        if self.range_call is not None:
            start, end = self.range_call
            rows = rows[start : end + 1]
        if self.limit_call is not None:
            rows = rows[: self.limit_call]
        return SimpleNamespace(data=rows, count=total if self.count == "exact" else None)


class _FakeClient:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.queries: list[_FakeQuery] = []

    def table(self, table_name: str):
        assert table_name == "datasets"
        return _FakeQuery(self.rows, self.queries)


class _FakeLifecycle:
    def __init__(self):
        self.status_calls: list[str] = []

    def get_dataset_upload_status(self, dataset_id: str):
        self.status_calls.append(dataset_id)
        return {"status": "idle"}


async def _fake_resolve_user_directory_entries(user_ids):
    return {
        user_id: SimpleNamespace(name=f"Owner {user_id}", email=f"{user_id}@example.com")
        for user_id in user_ids
        if user_id
    }


def test_list_recordings_uses_db_filters_order_range_without_profile_snapshot(monkeypatch):
    fake_client = _FakeClient(_recording_rows())

    async def _fake_get_supabase():
        return fake_client

    monkeypatch.setattr(recording_api, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(recording_api, "get_dataset_lifecycle", lambda: _FakeLifecycle())
    monkeypatch.setattr(recording_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)

    rows, total, _owner_options, _profile_options, _upload_options = asyncio.run(
        recording_api._list_recordings(
            owner_user_id="user-1",
            profile_name="profile-a",
            search="pick",
            created_from="2026-01-01",
            created_to="2026-02-28",
            size_min=100,
            size_max=500,
            episode_count_min=2,
            episode_count_max=10,
            sort_by="created_at",
            sort_order="desc",
            limit=1,
            offset=0,
        )
    )

    main_query = next(query for query in fake_client.queries if query.count == "exact")
    assert [row["id"] for row in rows] == ["rec-new"]
    assert total == 2
    assert main_query.range_call == (0, 0)
    assert main_query.orders == [("created_at", True), ("id", True)]
    assert ("eq", "dataset_type", "recorded") in main_query.filters
    assert ("neq", "status", "archived") in main_query.filters
    assert ("eq", "owner_user_id", "user-1") in main_query.filters
    assert ("eq", "profile_name", "profile-a") in main_query.filters
    assert ("ilike", "name", "%pick%") in main_query.filters
    assert ("gte", "created_at", "2026-01-01T00:00:00+00:00") in main_query.filters
    assert ("lte", "created_at", "2026-02-28T23:59:59.999999+00:00") in main_query.filters
    assert ("gte", "size_bytes", 100) in main_query.filters
    assert ("lte", "size_bytes", 500) in main_query.filters
    assert ("gte", "episode_count", 2) in main_query.filters
    assert ("lte", "episode_count", 10) in main_query.filters
    assert all("profile_snapshot" not in str(query.selected_columns) for query in fake_client.queries)


class _FakeDatasetPath:
    def __init__(self, dataset_id: str, exists_calls: list[str]):
        self.dataset_id = dataset_id
        self.exists_calls = exists_calls

    def exists(self):
        self.exists_calls.append(self.dataset_id)
        return True


class _FakeDatasetRoot:
    def __init__(self):
        self.exists_calls: list[str] = []

    def __truediv__(self, dataset_id: str):
        return _FakeDatasetPath(dataset_id, self.exists_calls)


def test_list_recordings_checks_continue_plan_and_exists_only_for_page_rows(monkeypatch):
    rows = [
        {
            **row,
            "id": f"rec-{index}",
            "created_at": f"2026-01-0{index}T00:00:00+00:00",
            "episode_count": index,
            "target_total_episodes": index + 5,
        }
        for index, row in enumerate(_recording_rows()[:3], start=1)
    ]
    fake_client = _FakeClient(rows)
    fake_root = _FakeDatasetRoot()
    plan_ids: list[str] = []
    original_build_continue_plan = recording_api._build_continue_plan_from_row

    async def _fake_get_supabase():
        return fake_client

    def _tracking_build_continue_plan(row: dict):
        plan_ids.append(str(row.get("id")))
        return original_build_continue_plan(row)

    monkeypatch.setattr(recording_api, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(recording_api, "get_dataset_lifecycle", lambda: _FakeLifecycle())
    monkeypatch.setattr(recording_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)
    monkeypatch.setattr(recording_api, "get_datasets_dir", lambda: fake_root)
    monkeypatch.setattr(recording_api, "_build_continue_plan_from_row", _tracking_build_continue_plan)

    response = asyncio.run(
        recording_api.list_recordings(
            owner_user_id=None,
            profile_name=None,
            upload_status=None,
            search=None,
            created_from=None,
            created_to=None,
            size_min=None,
            size_max=None,
            episode_count_min=None,
            episode_count_max=None,
            sort_by="created_at",
            sort_order="desc",
            limit=1,
            offset=1,
        )
    )

    assert response.total == 3
    assert [recording.recording_id for recording in response.recordings] == ["rec-2"]
    assert plan_ids == ["rec-2"]
    assert fake_root.exists_calls == ["rec-2", "rec-2"]

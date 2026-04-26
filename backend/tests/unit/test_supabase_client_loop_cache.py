import asyncio
import pytest

import percus_ai.db as percus_db


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, client, table: str):
        self.client = client
        self.table = table
        self.operation = ""
        self.payload = None
        self.filters: dict[str, object] = {}

    def select(self, _fields: str):
        self.operation = "select"
        return self

    def update(self, payload: dict):
        self.operation = "update"
        self.payload = payload
        return self

    def insert(self, payload: dict):
        self.operation = "insert"
        self.payload = payload
        return self

    def eq(self, field: str, value: object):
        self.filters[field] = value
        return self

    async def execute(self):
        self.client.operations.append(
            {
                "table": self.table,
                "operation": self.operation,
                "payload": self.payload,
                "filters": dict(self.filters),
            }
        )
        if self.operation == "select":
            return _FakeResponse(self.client.existing_rows)
        return _FakeResponse([])


class _FakeDbClient:
    def __init__(self, existing_rows: list[dict] | None = None):
        self.existing_rows = existing_rows or []
        self.operations: list[dict] = []

    def table(self, table: str):
        return _FakeTable(self, table)


def test_get_supabase_service_client_reuses_client_within_same_loop(monkeypatch):
    created_clients: list[object] = []

    async def fake_create_async_client(_url: str, _key: str):
        client = object()
        created_clients.append(client)
        return client

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "service-key")
    monkeypatch.setattr(percus_db, "create_async_client", fake_create_async_client)
    percus_db.reset_supabase_async_client_cache()

    async def run_once():
        first = await percus_db.get_supabase_service_client()
        second = await percus_db.get_supabase_service_client()
        return first, second

    first, second = asyncio.run(run_once())

    assert first is second
    assert created_clients == [first]


def test_get_supabase_service_client_creates_new_client_for_new_loop(monkeypatch):
    created_clients: list[object] = []

    async def fake_create_async_client(_url: str, _key: str):
        client = object()
        created_clients.append(client)
        return client

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "service-key")
    monkeypatch.setattr(percus_db, "create_async_client", fake_create_async_client)
    percus_db.reset_supabase_async_client_cache()

    first = asyncio.run(percus_db.get_supabase_service_client())
    second = asyncio.run(percus_db.get_supabase_service_client())

    assert first is not second
    assert created_clients == [first, second]


def test_get_supabase_async_client_creates_new_client_for_new_loop_without_session(monkeypatch):
    created_clients: list[object] = []

    async def fake_create_async_client(_url: str, _key: str):
        client = object()
        created_clients.append(client)
        return client

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setattr(percus_db, "create_async_client", fake_create_async_client)
    percus_db.clear_supabase_session()
    percus_db.reset_supabase_async_client_cache()

    first = asyncio.run(percus_db.get_supabase_async_client())
    second = asyncio.run(percus_db.get_supabase_async_client())

    assert first is not second
    assert created_clients == [first, second]


def test_get_supabase_service_client_required_raises_without_service_key(monkeypatch):
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    percus_db.reset_supabase_async_client_cache()

    with pytest.raises(RuntimeError, match="SUPABASE_URL and SUPABASE_SECRET_KEY"):
        asyncio.run(percus_db.get_supabase_service_client_required())


def test_upsert_with_explicit_owner_inserts_with_owner(monkeypatch):
    client = _FakeDbClient()

    async def fake_get_supabase_service_client_required():
        return client

    monkeypatch.setattr(
        percus_db,
        "get_supabase_service_client_required",
        fake_get_supabase_service_client_required,
    )

    asyncio.run(
        percus_db.upsert_with_explicit_owner(
            "training_jobs",
            "job_id",
            {"job_id": "job-1", "status": "running"},
            owner_user_id="user-1",
        )
    )

    assert client.operations[0]["operation"] == "select"
    assert client.operations[1] == {
        "table": "training_jobs",
        "operation": "insert",
        "payload": {
            "job_id": "job-1",
            "status": "running",
            "owner_user_id": "user-1",
        },
        "filters": {},
    }


def test_upsert_with_explicit_owner_updates_without_owner_or_key(monkeypatch):
    client = _FakeDbClient(existing_rows=[{"job_id": "job-1"}])

    async def fake_get_supabase_service_client_required():
        return client

    monkeypatch.setattr(
        percus_db,
        "get_supabase_service_client_required",
        fake_get_supabase_service_client_required,
    )

    asyncio.run(
        percus_db.upsert_with_explicit_owner(
            "training_jobs",
            "job_id",
            {
                "job_id": "job-1",
                "owner_user_id": "user-1",
                "status": "running",
            },
        )
    )

    assert client.operations[1] == {
        "table": "training_jobs",
        "operation": "update",
        "payload": {"status": "running"},
        "filters": {"job_id": "job-1"},
    }

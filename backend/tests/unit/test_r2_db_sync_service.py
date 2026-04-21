import asyncio

from percus_ai.storage.r2_db_sync import R2DBSyncService
import percus_ai.storage.r2_db_sync as r2_db_sync


def test_get_db_hash_uses_service_client_when_available(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class _Query:
        def select(self, columns: str):
            calls.append(("select", columns))
            return self

        def eq(self, key: str, value: str):
            calls.append(("eq", (key, value)))
            return self

        def limit(self, value: int):
            calls.append(("limit", value))
            return self

        async def execute(self):
            calls.append(("execute", None))
            return type("Result", (), {"data": [{"content_hash": "hash-1"}]})()

    class _Client:
        def table(self, name: str):
            calls.append(("table", name))
            return _Query()

    async def _fake_get_service_client():
        return _Client()

    async def _fake_get_async_client():
        raise AssertionError("anon/auth client should not be used when service client is available")

    monkeypatch.setattr(r2_db_sync, "get_supabase_service_client", _fake_get_service_client)
    monkeypatch.setattr(r2_db_sync, "get_supabase_async_client", _fake_get_async_client)

    service = R2DBSyncService()
    value = asyncio.run(service._get_db_hash("models", "model-1"))

    assert value == "hash-1"
    assert ("table", "models") in calls
    assert ("limit", 1) in calls


def test_update_db_hash_uses_service_client_when_available(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class _Query:
        def update(self, payload: dict):
            calls.append(("update", payload))
            return self

        def eq(self, key: str, value: str):
            calls.append(("eq", (key, value)))
            return self

        async def execute(self):
            calls.append(("execute", None))
            return type("Result", (), {"data": []})()

    class _Client:
        def table(self, name: str):
            calls.append(("table", name))
            return _Query()

    async def _fake_get_service_client():
        return _Client()

    async def _fake_get_async_client():
        raise AssertionError("anon/auth client should not be used when service client is available")

    monkeypatch.setattr(r2_db_sync, "get_supabase_service_client", _fake_get_service_client)
    monkeypatch.setattr(r2_db_sync, "get_supabase_async_client", _fake_get_async_client)

    service = R2DBSyncService()
    asyncio.run(service._update_db_hash("models", "model-1", "hash-2", 1234))

    assert ("table", "models") in calls
    assert ("update", {"content_hash": "hash-2", "size_bytes": 1234}) in calls
    assert ("eq", ("id", "model-1")) in calls

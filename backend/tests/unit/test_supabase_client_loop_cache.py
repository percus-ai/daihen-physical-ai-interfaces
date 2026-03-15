import asyncio

import percus_ai.db as percus_db


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

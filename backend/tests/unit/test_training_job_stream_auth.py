from __future__ import annotations

import asyncio


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeMetricsQuery:
    def __init__(self, client):
        self._client = client

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    async def execute(self):
        self._client.calls += 1
        if self._client.error is not None:
            raise self._client.error
        return _FakeResponse(self._client.data)


class _FakeMetricsClient:
    def __init__(self, *, data, error: Exception | None = None):
        self.data = data
        self.error = error
        self.calls = 0

    def table(self, _name: str):
        return _FakeMetricsQuery(self)


def test_get_latest_metric_propagates_jwt_expiry_without_service_key(monkeypatch):
    import interfaces_backend.api.training as training_api

    jwt_error = Exception("JWT expired")
    expired_client = _FakeMetricsClient(data=[], error=jwt_error)

    async def fake_get_supabase_async_client():
        return expired_client

    monkeypatch.setattr(training_api, "get_supabase_async_client", fake_get_supabase_async_client)

    try:
        asyncio.run(training_api._get_latest_metric("job-1", "train"))
    except Exception as exc:
        assert exc is jwt_error
    else:
        raise AssertionError("JWT expiry should be propagated")
    assert expired_client.calls == 1

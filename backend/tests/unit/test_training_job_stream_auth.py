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


def test_get_latest_metric_retries_with_service_key_after_jwt_expiry(monkeypatch):
    import interfaces_backend.api.training as training_api

    expired_client = _FakeMetricsClient(data=[], error=Exception("JWT expired"))
    service_client = _FakeMetricsClient(
        data=[{"step": 12, "loss": 0.34, "ts": "2026-03-07T23:16:12Z", "metrics": {"lr": 1e-4}}]
    )

    async def fake_get_supabase_async_client():
        return expired_client

    async def fake_get_service_db_client():
        return service_client

    monkeypatch.setattr(training_api, "get_supabase_async_client", fake_get_supabase_async_client)
    monkeypatch.setattr(training_api, "_get_service_db_client", fake_get_service_db_client)

    result = asyncio.run(training_api._get_latest_metric("job-1", "train"))

    assert result == {
        "step": 12,
        "loss": 0.34,
        "ts": "2026-03-07T23:16:12Z",
        "metrics": {"lr": 1e-4},
    }
    assert expired_client.calls == 1
    assert service_client.calls == 1

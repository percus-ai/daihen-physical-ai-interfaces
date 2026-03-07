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


def test_stream_shared_producer_refreshes_expired_session_before_build(monkeypatch):
    import interfaces_backend.api.stream as stream_api

    current_session = {
        "access_token": "expired-token",
        "refresh_token": "refresh-token",
        "expires_at": 1,
        "user_id": "user-1",
    }
    refreshed_session = {
        "access_token": "fresh-token",
        "refresh_token": "refresh-token",
        "expires_at": 9999999999,
        "user_id": "user-1",
    }
    captured: dict[str, object] = {}

    class _FakeSubscription:
        def __init__(self):
            self.queue = asyncio.Queue()

        def close(self):
            return None

    class _FakeBus:
        def subscribe(self, topic: str, key: str):
            captured["topic"] = topic
            captured["key"] = key
            return _FakeSubscription()

    class _FakeHub:
        async def publish_once(self, *, topic: str, key: str, build_payload):
            captured["publish_topic"] = topic
            captured["publish_key"] = key
            captured["payload"] = await build_payload()

        def ensure_polling(self, *, build_payload, **kwargs):
            captured["polling_kwargs"] = kwargs
            captured["polling_build_payload"] = build_payload

    def fake_get_supabase_session():
        return current_session

    def fake_set_request_session(session):
        nonlocal current_session
        current_session = session
        captured["updated_session"] = session
        return None

    monkeypatch.setattr(stream_api, "get_realtime_event_bus", lambda: _FakeBus())
    monkeypatch.setattr(stream_api, "get_realtime_producer_hub", lambda: _FakeHub())
    monkeypatch.setattr(stream_api, "get_supabase_session", fake_get_supabase_session)
    monkeypatch.setattr(stream_api, "set_request_session", fake_set_request_session)
    monkeypatch.setattr(
        stream_api,
        "is_session_expired",
        lambda session: session["access_token"] == "expired-token",
    )
    monkeypatch.setattr(
        stream_api,
        "refresh_session_from_refresh_token",
        lambda refresh_token: refreshed_session if refresh_token == "refresh-token" else None,
    )
    monkeypatch.setattr(
        stream_api,
        "sse_queue_response",
        lambda request, queue, on_close: {"queue": queue, "on_close": on_close},
    )

    async def build_payload() -> dict:
        return {"access_token": current_session["access_token"]}

    response = asyncio.run(
        stream_api._stream_with_shared_producer(
            request=object(),
            topic="training.job",
            key="job-1",
            build_payload=build_payload,
            interval=5.0,
            idle_ttl=60.0,
        )
    )
    captured["polling_payload"] = asyncio.run(captured["polling_build_payload"]())

    assert captured["updated_session"] == refreshed_session
    assert captured["payload"] == {"access_token": "fresh-token"}
    assert captured["polling_payload"] == {"access_token": "fresh-token"}
    assert response["queue"] is not None

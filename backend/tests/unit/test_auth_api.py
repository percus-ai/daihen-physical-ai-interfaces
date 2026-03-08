from types import SimpleNamespace

import interfaces_backend.api.auth as auth_api


def test_status_uses_middleware_session_without_reresolving(monkeypatch):
    request = SimpleNamespace(
        state=SimpleNamespace(
            supabase_session={
                "access_token": "token",
                "refresh_token": "refresh",
                "user_id": "user-1",
                "expires_at": 1234567890,
            },
            supabase_session_refreshed=True,
        )
    )
    response = SimpleNamespace()

    monkeypatch.setattr(
        auth_api,
        "resolve_session_from_request",
        lambda _request: (_ for _ in ()).throw(AssertionError("should not re-resolve")),
    )
    monkeypatch.setattr(auth_api, "compute_session_expires_at", lambda issued_at: issued_at + 100)
    monkeypatch.setattr(auth_api.time, "time", lambda: 1000)
    monkeypatch.setattr(
        auth_api,
        "set_session_cookies",
        lambda _response, _session: (_ for _ in ()).throw(AssertionError("should not reset cookies")),
    )

    status = auth_api.status(request, response)

    assert status.authenticated is True
    assert status.user_id == "user-1"
    assert status.session_expires_at == 1100


def test_token_uses_middleware_session_without_reresolving(monkeypatch):
    request = SimpleNamespace(
        state=SimpleNamespace(
            supabase_session={
                "access_token": "token",
                "refresh_token": "refresh",
                "user_id": "user-1",
                "expires_at": 1234567890,
            },
            supabase_session_refreshed=True,
        )
    )
    response = SimpleNamespace()

    monkeypatch.setattr(
        auth_api,
        "resolve_session_from_request",
        lambda _request: (_ for _ in ()).throw(AssertionError("should not re-resolve")),
    )
    monkeypatch.setattr(auth_api, "compute_session_expires_at", lambda issued_at: issued_at + 100)
    monkeypatch.setattr(auth_api.time, "time", lambda: 1000)
    monkeypatch.setattr(
        auth_api,
        "set_session_cookies",
        lambda _response, _session: (_ for _ in ()).throw(AssertionError("should not reset cookies")),
    )

    token = auth_api.token(request, response)

    assert token.access_token == "token"
    assert token.user_id == "user-1"
    assert token.session_expires_at == 1100


def test_status_updates_cookies_when_cached_session_needs_extension(monkeypatch):
    request = SimpleNamespace(
        state=SimpleNamespace(
            supabase_session={
                "access_token": "token",
                "refresh_token": "refresh",
                "user_id": "user-1",
                "expires_at": 1234567890,
            },
            supabase_session_refreshed=False,
        )
    )
    response = SimpleNamespace()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        auth_api,
        "resolve_session_from_request",
        lambda _request: (_ for _ in ()).throw(AssertionError("should not re-resolve")),
    )
    monkeypatch.setattr(auth_api, "needs_session_cookie_update", lambda _request: True)
    monkeypatch.setattr(auth_api, "compute_session_expires_at", lambda issued_at: issued_at + 100)
    monkeypatch.setattr(auth_api.time, "time", lambda: 1000)
    monkeypatch.setattr(
        auth_api,
        "set_session_cookies",
        lambda _response, session: captured.setdefault("session", session),
    )

    status = auth_api.status(request, response)

    assert status.authenticated is True
    assert status.session_expires_at == 1100
    assert captured["session"] == request.state.supabase_session

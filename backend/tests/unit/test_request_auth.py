import interfaces_backend.core.request_auth as request_auth
from types import SimpleNamespace
import urllib.error


def test_build_session_from_tokens_uses_verified_claims(monkeypatch):
    monkeypatch.setattr(
        request_auth,
        "_verify_supabase_access_token",
        lambda _token: {"sub": "user-1", "exp": 1234567890},
    )

    session = request_auth.build_session_from_tokens("access-token", "refresh-token")

    assert session == {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": 1234567890,
        "user_id": "user-1",
    }


def test_build_session_from_tokens_rejects_unverified_token(monkeypatch):
    monkeypatch.setattr(request_auth, "_verify_supabase_access_token", lambda _token: None)

    assert request_auth.build_session_from_tokens("invalid-token", "refresh-token") is None


def test_resolve_session_from_request_keeps_valid_session(monkeypatch):
    session = {"access_token": "valid", "user_id": "user-1", "expires_at": 1234567890}

    monkeypatch.setattr(request_auth, "build_session_from_request", lambda _request: session)
    monkeypatch.setattr(request_auth, "is_session_expired", lambda _session: False)
    monkeypatch.setattr(request_auth, "refresh_session_from_request", lambda _request: None)

    resolved, refreshed = request_auth.resolve_session_from_request(object())

    assert resolved == session
    assert refreshed is False


def test_resolve_session_from_request_refreshes_invalid_token(monkeypatch):
    refreshed_session = {
        "access_token": "fresh-token",
        "refresh_token": "fresh-refresh",
        "expires_at": 1234567890,
        "user_id": "user-1",
    }

    monkeypatch.setattr(request_auth, "build_session_from_request", lambda _request: None)
    monkeypatch.setattr(request_auth, "refresh_session_from_request", lambda _request: refreshed_session)

    resolved, refreshed = request_auth.resolve_session_from_request(object())

    assert resolved == refreshed_session
    assert refreshed is True


def test_build_session_from_request_tries_duplicate_access_cookies(monkeypatch):
    request = SimpleNamespace(
        headers={
            "cookie": "phi_access_token=stale-token; phi_access_token=valid-token; phi_refresh_token=refresh-token"
        },
        cookies={"phi_access_token": "stale-token", "phi_refresh_token": "refresh-token"},
    )

    monkeypatch.setattr(
        request_auth,
        "build_session_from_tokens",
        lambda access_token, refresh_token=None: (
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": 1234567890,
                "user_id": "user-1",
            }
            if access_token == "valid-token"
            else None
        ),
    )

    session = request_auth.build_session_from_request(request)

    assert session == {
        "access_token": "valid-token",
        "refresh_token": "refresh-token",
        "expires_at": 1234567890,
        "user_id": "user-1",
    }


def test_refresh_session_from_request_tries_duplicate_refresh_cookies(monkeypatch):
    request = SimpleNamespace(
        headers={"cookie": "phi_refresh_token=stale-refresh; phi_refresh_token=valid-refresh"},
        cookies={"phi_refresh_token": "stale-refresh"},
    )

    monkeypatch.setattr(
        request_auth,
        "_refresh_session",
        lambda refresh_token: (
            {
                "access_token": "fresh-access",
                "refresh_token": refresh_token,
                "expires_at": 1234567890,
                "user_id": "user-1",
            }
            if refresh_token == "valid-refresh"
            else None
        ),
    )

    session = request_auth.refresh_session_from_request(request)

    assert session == {
        "access_token": "fresh-access",
        "refresh_token": "valid-refresh",
        "expires_at": 1234567890,
        "user_id": "user-1",
    }


def test_refresh_session_backoff_after_rate_limit(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(_req, timeout=0):
        calls["count"] += 1
        raise urllib.error.HTTPError(
            url="https://example.test",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(request_auth.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(request_auth, "_get_supabase_auth_config", lambda: ("https://example.test", "key"))
    monkeypatch.setattr(request_auth, "_refresh_timeout_seconds", lambda: 1)
    monkeypatch.setattr(request_auth, "_refresh_backoff_seconds", lambda: 60)
    request_auth._refresh_backoff_until.clear()

    assert request_auth.refresh_session_from_refresh_token("refresh-token") is None
    assert request_auth.refresh_session_from_refresh_token("refresh-token") is None
    assert calls["count"] == 1


def test_extract_request_user_id_hint_uses_unverified_access_payload(monkeypatch):
    request = SimpleNamespace(
        headers={"cookie": "phi_access_token=expired-token"},
        cookies={"phi_access_token": "expired-token"},
    )

    monkeypatch.setattr(request_auth, "build_session_from_request", lambda _request: None)
    monkeypatch.setattr(
        request_auth,
        "_decode_jwt_payload",
        lambda _token: {"sub": "user-from-expired-token"},
    )

    assert request_auth.extract_request_user_id_hint(request) == "user-from-expired-token"

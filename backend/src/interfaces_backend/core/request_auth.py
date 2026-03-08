"""Request-scoped auth helpers (Cookie/Bearer)."""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Any, Optional

import jwt
from fastapi import Request, Response

ACCESS_COOKIE_NAME = "phi_access_token"
REFRESH_COOKIE_NAME = "phi_refresh_token"
REFRESH_ISSUED_AT_COOKIE_NAME = "phi_refresh_issued_at"
DEFAULT_REFRESH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
DEFAULT_SUPABASE_REFRESH_TIMEOUT_SECONDS = 3
DEFAULT_SUPABASE_REFRESH_BACKOFF_SECONDS = 60

logger = logging.getLogger(__name__)
_refresh_backoff_until: dict[str, float] = {}


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _get_supabase_auth_config() -> tuple[str, str] | None:
    url = os.environ.get("SUPABASE_URL")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    api_key = secret_key or anon_key
    if not url or not api_key:
        return None
    return url.rstrip("/"), api_key


def _access_cookie_max_age(expires_at: Any) -> Optional[int]:
    if not expires_at:
        return None
    try:
        return max(0, int(float(expires_at) - time.time()))
    except (TypeError, ValueError):
        return None


def _refresh_cookie_max_age() -> int:
    raw = os.environ.get("PHI_REFRESH_COOKIE_MAX_AGE_SECONDS")
    if raw is None or raw == "":
        return DEFAULT_REFRESH_COOKIE_MAX_AGE_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_REFRESH_COOKIE_MAX_AGE_SECONDS


def _refresh_timeout_seconds() -> int:
    raw = os.environ.get("PHI_SUPABASE_REFRESH_TIMEOUT_SECONDS")
    if raw is None or raw == "":
        return DEFAULT_SUPABASE_REFRESH_TIMEOUT_SECONDS


def _refresh_backoff_seconds() -> int:
    raw = os.environ.get("PHI_SUPABASE_REFRESH_BACKOFF_SECONDS")
    if raw is None or raw == "":
        return DEFAULT_SUPABASE_REFRESH_BACKOFF_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_SUPABASE_REFRESH_BACKOFF_SECONDS


def _refresh_backoff_key(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_SUPABASE_REFRESH_TIMEOUT_SECONDS


def set_session_cookies(response: Response, session: dict[str, Any]) -> None:
    access_token = session.get("access_token")
    if not access_token:
        return
    refresh_max_age = _refresh_cookie_max_age()
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=_access_cookie_max_age(session.get("expires_at")),
    )
    refresh_token = session.get("refresh_token")
    if refresh_token:
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            refresh_token,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=refresh_max_age,
        )
        response.set_cookie(
            REFRESH_ISSUED_AT_COOKIE_NAME,
            str(int(time.time())),
            httponly=True,
            samesite="lax",
            path="/",
            max_age=refresh_max_age,
        )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_ISSUED_AT_COOKIE_NAME, path="/")


def extract_access_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    cookie_token = request.cookies.get(ACCESS_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


def extract_refresh_token(request: Request) -> Optional[str]:
    return request.cookies.get(REFRESH_COOKIE_NAME)


def _extract_cookie_values(request: Request, name: str) -> list[str]:
    raw_cookie = request.headers.get("cookie", "")
    values: list[str] = []
    for chunk in raw_cookie.split(";"):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() != name:
            continue
        candidate = value.strip()
        if candidate and candidate not in values:
            values.append(candidate)
    fallback = request.cookies.get(name)
    if fallback and fallback not in values:
        values.append(fallback)
    return values


def _iter_refresh_candidates(request: Request) -> Iterable[str]:
    return _extract_cookie_values(request, REFRESH_COOKIE_NAME)


def _iter_access_candidates(request: Request) -> Iterable[str]:
    auth_header = request.headers.get("authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1]:
            return [parts[1]]
    return _extract_cookie_values(request, ACCESS_COOKIE_NAME)


def build_session_from_tokens(
    access_token: Optional[str],
    refresh_token: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    if not access_token:
        return None
    payload = _verify_supabase_access_token(access_token)
    if payload is None:
        return None
    user_id = payload.get("sub")
    expires_at = payload.get("exp")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "user_id": user_id,
    }


def compute_session_expires_at(issued_at: int) -> int:
    return issued_at + _refresh_cookie_max_age()


def get_session_expires_at_from_request(request: Request) -> Optional[int]:
    issued_at_raw = request.cookies.get(REFRESH_ISSUED_AT_COOKIE_NAME)
    if not issued_at_raw:
        return None
    try:
        issued_at = int(float(issued_at_raw))
    except (TypeError, ValueError):
        return None
    return compute_session_expires_at(issued_at)


@functools.lru_cache(maxsize=8)
def _get_jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        f"{issuer.rstrip('/')}/.well-known/jwks.json",
        cache_keys=True,
        cache_jwk_set=True,
        lifespan=600,
        timeout=_refresh_timeout_seconds(),
    )


def _verify_with_jwks(access_token: str, issuer: str, algorithm: str) -> Optional[dict[str, Any]]:
    try:
        jwks_client = _get_jwks_client(issuer)
        signing_key = jwks_client.get_signing_key_from_jwt(access_token)
        payload = jwt.decode(
            access_token,
            signing_key.key,
            algorithms=[algorithm],
            issuer=issuer,
            options={"verify_aud": False},
        )
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _verify_with_auth_server(access_token: str) -> Optional[dict[str, Any]]:
    config = _get_supabase_auth_config()
    if not config:
        return None
    url, api_key = config
    req = urllib.request.Request(
        f"{url}/auth/v1/user",
        method="GET",
    )
    req.add_header("apikey", api_key)
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urllib.request.urlopen(req, timeout=_refresh_timeout_seconds()) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        logger.warning("Supabase user lookup failed: %s %s", exc, body)
        return None
    except Exception as exc:
        logger.warning("Supabase user lookup error: %s", exc)
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    decoded = _decode_jwt_payload(access_token) or {}
    user_id = payload.get("id")
    if not user_id:
        return None
    return {
        "sub": user_id,
        "exp": decoded.get("exp"),
        "iss": decoded.get("iss"),
    }


def _verify_supabase_access_token(access_token: str) -> Optional[dict[str, Any]]:
    decoded = _decode_jwt_payload(access_token)
    if not decoded:
        return None
    issuer = decoded.get("iss")
    try:
        header = jwt.get_unverified_header(access_token)
    except Exception:
        header = {}
    algorithm = header.get("alg")
    if issuer and isinstance(algorithm, str) and algorithm.upper().startswith(("ES", "RS")):
        verified = _verify_with_jwks(access_token, issuer, algorithm)
        if verified is not None:
            return verified
    return _verify_with_auth_server(access_token)


def needs_session_cookie_update(request: Request) -> bool:
    if not request.cookies.get(REFRESH_COOKIE_NAME):
        return False
    issued_at_raw = request.cookies.get(REFRESH_ISSUED_AT_COOKIE_NAME)
    if not issued_at_raw:
        return True
    try:
        int(float(issued_at_raw))
    except (TypeError, ValueError):
        return True
    return False


def resolve_session_from_request(request: Request) -> tuple[Optional[dict[str, Any]], bool]:
    session = build_session_from_request(request)
    if session and not is_session_expired(session):
        return session, False
    refreshed_session = refresh_session_from_request(request)
    if refreshed_session:
        return refreshed_session, True
    return None, False


def is_session_expired(session: Optional[dict[str, Any]], leeway_seconds: int = 30) -> bool:
    if not session:
        return True
    expires_at = session.get("expires_at")
    if not expires_at:
        return False
    try:
        return time.time() >= float(expires_at) - leeway_seconds
    except (TypeError, ValueError):
        return False


def _refresh_session(refresh_token: str) -> Optional[dict[str, Any]]:
    backoff_key = _refresh_backoff_key(refresh_token)
    blocked_until = _refresh_backoff_until.get(backoff_key, 0.0)
    if blocked_until > time.time():
        return None

    config = _get_supabase_auth_config()
    if not config:
        return None
    url, api_key = config
    payload = json.dumps({"refresh_token": refresh_token}).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/auth/v1/token?grant_type=refresh_token",
        data=payload,
        method="POST",
    )
    req.add_header("apikey", api_key)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_refresh_timeout_seconds()) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        if exc.code == 429:
            _refresh_backoff_until[backoff_key] = time.time() + _refresh_backoff_seconds()
        logger.warning("Supabase refresh failed: %s %s", exc, body)
        return None
    except Exception as exc:
        logger.warning("Supabase refresh error: %s", exc)
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    access_token = payload.get("access_token")
    if not access_token:
        return None
    new_refresh = payload.get("refresh_token") or refresh_token
    user_id = None
    user = payload.get("user")
    if isinstance(user, dict):
        user_id = user.get("id")
    if not user_id:
        user_id = (_decode_jwt_payload(access_token) or {}).get("sub")
    expires_at = payload.get("expires_at")
    if not expires_at:
        expires_at = (_decode_jwt_payload(access_token) or {}).get("exp")
    _refresh_backoff_until.pop(backoff_key, None)
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "expires_at": expires_at,
        "user_id": user_id,
    }


def build_session_from_request(request: Request) -> Optional[dict[str, Any]]:
    refresh_candidates = list(_iter_refresh_candidates(request))
    refresh_token = refresh_candidates[0] if refresh_candidates else None
    for access_token in _iter_access_candidates(request):
        session = build_session_from_tokens(access_token, refresh_token)
        if session:
            return session
    return None


def refresh_session_from_request(request: Request) -> Optional[dict[str, Any]]:
    for refresh_token in _iter_refresh_candidates(request):
        session = _refresh_session(refresh_token)
        if session:
            return session
    return None


def refresh_session_from_refresh_token(
    refresh_token: Optional[str],
) -> Optional[dict[str, Any]]:
    if not refresh_token:
        return None
    return _refresh_session(refresh_token)


def extract_request_user_id_hint(request: Request) -> Optional[str]:
    session = build_session_from_request(request)
    if session and session.get("user_id"):
        return str(session["user_id"])
    for access_token in _iter_access_candidates(request):
        payload = _decode_jwt_payload(access_token) or {}
        user_id = str(payload.get("sub") or "").strip()
        if user_id:
            return user_id
    return None

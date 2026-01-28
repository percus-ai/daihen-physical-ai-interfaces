"""Authentication API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from interfaces_backend.models.auth import (
    AuthLoginRequest,
    AuthLoginResponse,
    AuthStatusResponse,
    AuthTokenResponse,
)
from interfaces_backend.core.request_auth import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    build_session_from_request_with_refresh,
    set_session_cookies,
)
from percus_ai.db import create_supabase_anon_client

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _extract_value(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _extract_session(response: Any) -> Any:
    session = _extract_value(response, "session")
    if session is not None:
        return session
    data = _extract_value(response, "data")
    return _extract_value(data, "session")


def _extract_user_id(response: Any, session: Any) -> str | None:
    user = _extract_value(response, "user") or _extract_value(session, "user")
    return _extract_value(user, "id")


@router.post("/login", response_model=AuthLoginResponse)
def login(request: AuthLoginRequest, response: Response, http_request: Request) -> AuthLoginResponse:
    client = create_supabase_anon_client()
    supabase_response = client.auth.sign_in_with_password(
        {"email": request.email, "password": request.password}
    )
    session = _extract_session(supabase_response)
    if session is None:
        raise HTTPException(status_code=401, detail="Login failed")

    access_token = _extract_value(session, "access_token")
    refresh_token = _extract_value(session, "refresh_token")
    expires_at = _extract_value(session, "expires_at")
    user_id = _extract_user_id(supabase_response, session)

    if not access_token or not user_id:
        raise HTTPException(status_code=401, detail="Login failed")

    session_payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "user_id": user_id,
    }
    set_session_cookies(response, session_payload)

    is_cli = http_request.headers.get("x-client") == "cli"
    return AuthLoginResponse(
        success=True,
        user_id=user_id,
        expires_at=expires_at,
        access_token=access_token if is_cli else None,
        refresh_token=refresh_token if is_cli else None,
    )


@router.post("/logout", response_model=AuthStatusResponse)
def logout(response: Response) -> AuthStatusResponse:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    return AuthStatusResponse(authenticated=False, user_id=None, expires_at=None)


@router.get("/status", response_model=AuthStatusResponse)
def status(http_request: Request, response: Response) -> AuthStatusResponse:
    session, refreshed = build_session_from_request_with_refresh(http_request)
    if not session:
        return AuthStatusResponse(authenticated=False, user_id=None, expires_at=None)
    if refreshed:
        set_session_cookies(response, session)
    return AuthStatusResponse(
        authenticated=True,
        user_id=session.get("user_id"),
        expires_at=session.get("expires_at"),
    )


@router.get("/token", response_model=AuthTokenResponse)
def token(http_request: Request, response: Response) -> AuthTokenResponse:
    session, refreshed = build_session_from_request_with_refresh(http_request)
    if not session:
        raise HTTPException(status_code=401, detail="unauthenticated")
    access_token = session.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="unauthenticated")
    if refreshed:
        set_session_cookies(response, session)
    return AuthTokenResponse(
        access_token=access_token,
        refresh_token=session.get("refresh_token"),
        user_id=session.get("user_id"),
        expires_at=session.get("expires_at"),
    )

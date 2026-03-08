"""Realtime tab-session control + stream API."""

from __future__ import annotations

import asyncio
import json
import re
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from interfaces_backend.models.realtime import (
    TabSessionStatePutResponse,
    TabSessionStateRequest,
    TabSessionStateResponse,
)
from interfaces_backend.services.tab_realtime import (
    TabSessionNotFoundError,
    TabSessionRevisionConflictError,
    get_tab_realtime_registry,
)
from percus_ai.db import get_current_user_id

router = APIRouter(prefix="/api/realtime", tags=["realtime"])

STREAM_HEARTBEAT_SECONDS = 20.0
STREAM_POLL_INTERVAL_SECONDS = 0.1
TAB_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _normalize_tab_session_id(tab_session_id: str) -> str:
    normalized = tab_session_id.strip()
    if not TAB_SESSION_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=422,
            detail="tab_session_id must match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        )
    return normalized


def _parse_last_event_id(request: Request) -> int | None:
    raw = (request.headers.get("last-event-id") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be integer") from exc
    if value < 0:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be >= 0")
    return value


def _format_sse_event(event: dict) -> str:
    event_id = event.get("stream_seq")
    encoded = json.dumps(event, ensure_ascii=False, sort_keys=True)
    return f"id: {event_id}\ndata: {encoded}\n\n"


@router.put(
    "/tab-sessions/{tab_session_id}/state",
    response_model=TabSessionStatePutResponse,
)
async def put_tab_session_state(tab_session_id: str, request: TabSessionStateRequest):
    user_id = _require_user_id()
    normalized_tab_session_id = _normalize_tab_session_id(tab_session_id)
    registry = get_tab_realtime_registry()
    try:
        result = registry.apply_state(
            user_id=user_id,
            tab_session_id=normalized_tab_session_id,
            state=request,
        )
    except TabSessionRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TabSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return TabSessionStatePutResponse(
        tab_session_id=result.tab_session_id,
        revision=result.revision,
        applied_at=result.applied_at,
        subscription_count=result.subscription_count,
    )


@router.get(
    "/tab-sessions/{tab_session_id}/state",
    response_model=TabSessionStateResponse,
)
async def get_tab_session_state(tab_session_id: str):
    user_id = _require_user_id()
    normalized_tab_session_id = _normalize_tab_session_id(tab_session_id)
    registry = get_tab_realtime_registry()
    try:
        return registry.get_state(
            user_id=user_id,
            tab_session_id=normalized_tab_session_id,
        )
    except TabSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tab-sessions/{tab_session_id}/stream")
async def stream_tab_session(request: Request, tab_session_id: str):
    user_id = _require_user_id()
    normalized_tab_session_id = _normalize_tab_session_id(tab_session_id)
    last_event_id = _parse_last_event_id(request)
    registry = get_tab_realtime_registry()

    try:
        handle = registry.open_stream(
            user_id=user_id,
            tab_session_id=normalized_tab_session_id,
            last_event_id=last_event_id,
        )
    except TabSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def event_stream():
        after_seq = last_event_id or 0
        last_sent_mono = time.monotonic()
        try:
            for event in handle.replay_events:
                after_seq = max(after_seq, int(event.get("stream_seq", 0)))
                yield _format_sse_event(event)
                last_sent_mono = time.monotonic()

            while True:
                if await request.is_disconnected():
                    break

                status, events = handle.poll(after_seq=after_seq)
                if events:
                    for event in events:
                        after_seq = max(after_seq, int(event.get("stream_seq", 0)))
                        yield _format_sse_event(event)
                        last_sent_mono = time.monotonic()
                    continue

                if status in {"deleted", "superseded"}:
                    break

                now_mono = time.monotonic()
                if (now_mono - last_sent_mono) >= STREAM_HEARTBEAT_SECONDS:
                    yield ": ping\n\n"
                    last_sent_mono = now_mono

                await asyncio.sleep(STREAM_POLL_INTERVAL_SECONDS)
        finally:
            handle.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/tab-sessions/{tab_session_id}", status_code=204)
async def delete_tab_session(tab_session_id: str):
    user_id = _require_user_id()
    normalized_tab_session_id = _normalize_tab_session_id(tab_session_id)
    registry = get_tab_realtime_registry()
    registry.delete_session(
        user_id=user_id,
        tab_session_id=normalized_tab_session_id,
    )
    return Response(status_code=204)


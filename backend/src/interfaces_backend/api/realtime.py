"""Realtime track stream API."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from interfaces_backend.models.realtime import RealtimeFrame
from interfaces_backend.services.realtime_runtime import get_realtime_runtime
from percus_ai.db import get_current_user_id

router = APIRouter(prefix="/api/realtime", tags=["realtime"])

STREAM_HEARTBEAT_SECONDS = 20.0
TAB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _require_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Login required") from exc


def _require_tab_id(request: Request) -> str:
    raw = (request.query_params.get("tab_id") or "").strip()
    if not raw:
        raw = (request.headers.get("x-tab-id") or "").strip()
    if not raw or not TAB_ID_PATTERN.fullmatch(raw):
        raise HTTPException(
            status_code=422,
            detail="tab_id must match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        )
    return raw


def _format_sse_frame(frame: RealtimeFrame) -> str:
    encoded = json.dumps(frame.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return f"event: realtime\ndata: {encoded}\n\n"


@router.get("/stream")
async def stream_realtime(request: Request):
    user_id = _require_user_id()
    tab_id = _require_tab_id(request)
    connection = get_realtime_runtime().open_connection(user_id=user_id, tab_id=tab_id)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    frame = await connection.next_frame(timeout_seconds=STREAM_HEARTBEAT_SECONDS)
                except StopAsyncIteration:
                    break
                if frame is None:
                    yield ": ping\n\n"
                    continue
                yield _format_sse_frame(frame)
        finally:
            connection.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

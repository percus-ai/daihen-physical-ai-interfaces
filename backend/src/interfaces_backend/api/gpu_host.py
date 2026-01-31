from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from interfaces_backend.clients.gpu_host import GpuHostClient
from percus_ai.gpu_host.models import (
    LoadRequest,
    LoadResponse,
    StartRequest,
    StartResponse,
    StatusResponse,
    StopRequest,
    StopResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gpu-host", tags=["gpu-host"])


@router.get("/status", response_model=StatusResponse)
async def get_status():
    client = GpuHostClient()
    try:
        return client.status()
    except Exception as exc:
        logger.exception("GPU host status failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/load", response_model=LoadResponse)
async def load_model(request: LoadRequest):
    client = GpuHostClient()
    try:
        return client.load(request)
    except Exception as exc:
        logger.exception("GPU host load failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/start", response_model=StartResponse)
async def start_worker(request: StartRequest):
    client = GpuHostClient()
    try:
        return client.start(request)
    except Exception as exc:
        logger.exception("GPU host start failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stop", response_model=StopResponse)
async def stop_worker(request: StopRequest):
    client = GpuHostClient()
    try:
        return client.stop(request)
    except Exception as exc:
        logger.exception("GPU host stop failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

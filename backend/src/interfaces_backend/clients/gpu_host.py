from __future__ import annotations

import os
from typing import Optional

import httpx

from percus_ai.gpu_host.models import (
    LoadRequest,
    LoadResponse,
    StartRequest,
    StartResponse,
    StatusResponse,
    StopRequest,
    StopResponse,
)


class GpuHostClient:
    def __init__(self, base_url: Optional[str] = None, timeout_s: float = 10.0) -> None:
        self.base_url = base_url or os.getenv("GPU_HOST_BASE_URL", "http://127.0.0.1:8088")
        self.timeout_s = timeout_s

    def start(self, request: StartRequest) -> StartResponse:
        return self._post("/start", request, StartResponse)

    def stop(self, request: StopRequest) -> StopResponse:
        return self._post("/stop", request, StopResponse)

    def load(self, request: LoadRequest) -> LoadResponse:
        return self._post("/load", request, LoadResponse)

    def status(self) -> StatusResponse:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_s) as client:
            resp = client.get("/status")
            resp.raise_for_status()
            return StatusResponse(**resp.json())

    def _post(self, path: str, request, response_cls):
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_s) as client:
            resp = client.post(path, json=request.model_dump())
            resp.raise_for_status()
            return response_cls(**resp.json())

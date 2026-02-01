from __future__ import annotations

import os
from typing import Optional

import httpx


class RunnerBridgeClient:
    def __init__(self, base_url: Optional[str] = None, timeout_s: float = 10.0) -> None:
        self.base_url = base_url or os.getenv("LEROBOT_RUNNER_URL", "http://127.0.0.1:8083")
        self.timeout_s = timeout_s

    def status(self) -> dict:
        return self._get("/api/status")

    def start(self, payload: dict) -> dict:
        return self._post("/api/start", payload)

    def stop(self) -> dict:
        return self._post("/api/stop", {})

    def load(self, payload: dict) -> dict:
        return self._post("/api/load", payload)

    def unload(self) -> dict:
        return self._post("/api/unload", {})

    def _get(self, path: str) -> dict:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_s) as client:
            resp = client.get(path)
            resp.raise_for_status()
            return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout_s) as client:
            resp = client.post(path, json=payload)
            resp.raise_for_status()
            return resp.json()

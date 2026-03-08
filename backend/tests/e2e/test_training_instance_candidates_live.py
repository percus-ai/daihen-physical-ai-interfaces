from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from verda import VerdaClient

from percus_ai.training.providers.vast import search_offers_minimal


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_live_verda_credentials(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    env_path = _repo_root() / "data" / ".env"
    if not env_path.exists():
        pytest.skip("data/.env not found")

    values = dotenv_values(env_path)
    client_id = str(values.get("DATACRUNCH_CLIENT_ID") or "").strip()
    client_secret = str(values.get("DATACRUNCH_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        pytest.skip("DATACRUNCH credentials not configured in data/.env")

    monkeypatch.setenv("DATACRUNCH_CLIENT_ID", client_id)
    monkeypatch.setenv("DATACRUNCH_CLIENT_SECRET", client_secret)
    return client_id, client_secret


def _load_live_vast_credentials(monkeypatch: pytest.MonkeyPatch) -> str:
    env_path = _repo_root() / "data" / ".env"
    if not env_path.exists():
        pytest.skip("data/.env not found")

    values = dotenv_values(env_path)
    api_key = str(values.get("VAST_API_KEY") or "").strip()
    if not api_key:
        pytest.skip("VAST_API_KEY not configured in data/.env")

    monkeypatch.setenv("VAST_API_KEY", api_key)
    return api_key


def test_live_instance_candidates_normalize_resource_fields(monkeypatch: pytest.MonkeyPatch):
    from interfaces_backend.main import app

    client_id, client_secret = _load_live_verda_credentials(monkeypatch)
    _load_live_vast_credentials(monkeypatch)
    verda_client = VerdaClient(client_id, client_secret)
    instance_types = {
        item.instance_type: item
        for item in verda_client.instance_types.get()
        if getattr(item, "instance_type", None)
    }

    with TestClient(app) as client:
        response = client.get(
            "/api/training/instance-candidates",
            params={
                "provider": "verda",
                "storage_size": 200,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    candidates = payload.get("candidates", [])
    assert candidates, "expected at least one live Verda candidate"

    checked = 0
    for candidate in candidates:
        instance_type = str(candidate.get("instance_type") or "").strip()
        if not instance_type:
            continue
        source = instance_types.get(instance_type)
        if source is None:
            continue

        gpu_count = source.gpu["number_of_gpus"]
        expected_gpu_memory = source.gpu_memory["size_in_gigabytes"] / gpu_count
        expected_cpu_cores = source.cpu["number_of_cores"]
        expected_system_memory = source.memory["size_in_gigabytes"]

        assert candidate["gpu_memory_gb"] == pytest.approx(expected_gpu_memory)
        assert candidate["cpu_cores"] == pytest.approx(expected_cpu_cores)
        assert candidate["system_memory_gb"] == pytest.approx(expected_system_memory)
        assert "VRAM" in candidate["detail"]
        assert "RAM" in candidate["detail"]
        checked += 1

    assert checked > 0, "expected at least one candidate to match live instance_types data"
    offers = search_offers_minimal(
        gpu_model="L40S",
        gpu_count=1,
        interruptible=True,
        max_price=None,
        min_disk_gb=200,
        limit=10,
    )
    assert offers, "expected at least one live Vast offer"

    offers_by_id = {int(offer["id"]): offer for offer in offers if offer.get("id") is not None}

    with TestClient(app) as client:
        response = client.get(
            "/api/training/instance-candidates",
            params={
                "provider": "vast",
                "gpu_model": "L40S",
                "gpu_count": 1,
                "mode": "spot",
                "storage_size": 200,
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        candidates = payload.get("candidates", [])
        assert candidates, "expected at least one live Vast candidate"

        checked = 0
        for candidate in candidates:
            offer_id = candidate.get("offer_id")
            if offer_id not in offers_by_id:
                continue
            source = offers_by_id[offer_id]

            expected_gpu_memory = float(source["gpu_ram"]) / 1024.0
            expected_system_memory = float(source["cpu_ram"]) / 1024.0
            expected_cpu_cores = float(source["cpu_cores_effective"])

            assert candidate["title"] == "L40S x1"
            assert candidate["gpu_memory_gb"] == pytest.approx(expected_gpu_memory, rel=1e-3)
            assert candidate["cpu_cores"] == pytest.approx(expected_cpu_cores)
            assert candidate["system_memory_gb"] == pytest.approx(expected_system_memory, rel=1e-3)
            assert "VRAM" in candidate["detail"]
            assert "RAM" in candidate["detail"]
            checked += 1

        assert checked > 0, "expected at least one candidate to match live Vast offer data"

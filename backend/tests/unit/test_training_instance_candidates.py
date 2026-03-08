from __future__ import annotations

import interfaces_backend.api.training as training_api


def test_build_vast_instance_candidates_without_mode_queries_spot_and_ondemand(monkeypatch):
    calls: list[bool] = []

    def fake_search_offers_minimal(
        *,
        gpu_model: str,
        gpu_count: int,
        interruptible: bool,
        max_price: float | None,
        min_disk_gb: int | None = None,
        limit: int = 40,
    ):
        del gpu_model, gpu_count, max_price, min_disk_gb, limit
        calls.append(interruptible)
        if interruptible:
            return [{"id": 101, "dph_total": 0.6, "disk_space": 200}]
        return [{"id": 202, "dph_total": 1.2, "disk_space": 200}]

    monkeypatch.setattr(
        "percus_ai.training.providers.vast.search_offers_minimal",
        fake_search_offers_minimal,
    )

    candidates = training_api._build_vast_instance_candidates(
        gpu_model="L40S",
        gpu_count=1,
        mode=None,
        storage_size=120,
        max_price=None,
    )

    assert calls == [True, False]
    assert [candidate.offer_id for candidate in candidates] == [101, 202]
    assert [candidate.mode for candidate in candidates] == ["spot", "ondemand"]

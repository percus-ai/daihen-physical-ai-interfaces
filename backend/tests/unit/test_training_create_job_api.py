from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError


def _valid_create_job_payload() -> dict[str, Any]:
    return {
        "job_name": "job-vast-unit",
        "dataset": {"id": "dataset-1", "source": "r2"},
        "policy": {"type": "pi05"},
        "cloud": {
            "provider": "vast",
            "gpu_model": "RTX_4090",
            "gpus_per_instance": 1,
            "interruptible": True,
            "max_price": 1.2,
            "storage_size": 120,
        },
        "training": {"steps": 100, "batch_size": 2},
        "background": True,
    }


def test_job_create_request_rejects_invalid_provider_schema():
    from interfaces_backend.models.training import JobCreateRequest

    invalid = _valid_create_job_payload()
    invalid["cloud"] = {**invalid["cloud"], "provider": "invalid"}

    with pytest.raises(ValidationError):
        JobCreateRequest.model_validate(invalid)


def test_job_create_request_defaults_provider_when_cloud_omitted():
    from interfaces_backend.models.training import JobCreateRequest

    without_cloud = _valid_create_job_payload()
    without_cloud.pop("cloud")

    request_defaulted = JobCreateRequest.model_validate(without_cloud)
    assert request_defaulted.cloud.provider == "verda"


def test_create_job_function_preflights_without_fastapi_lifecycle(monkeypatch):
    from interfaces_backend.models.training import JobCreateRequest
    import interfaces_backend.api.training as training_api
    import percus_ai.training.orchestrator as orchestrator

    called: dict[str, Any] = {}

    def fake_create_job_with_progress(
        request_data: dict,
        emit_progress,
        supabase_session: dict,
    ):
        called["request_data"] = request_data
        called["supabase_session"] = supabase_session
        emit_progress({"type": "start", "message": "開始"})
        emit_progress(
            {
                "type": "complete",
                "job_id": request_data["job_id"],
                "instance_id": "inst-1",
                "ip": "1.2.3.4",
                "status": "starting",
            }
        )
        return {"success": True, "job_id": request_data["job_id"]}

    monkeypatch.setattr(orchestrator, "create_job_with_progress", fake_create_job_with_progress)
    monkeypatch.setattr(training_api, "get_supabase_session", lambda: {"user_id": "user-1"})

    request = JobCreateRequest.model_validate(_valid_create_job_payload())
    background_tasks = BackgroundTasks()

    response = asyncio.run(training_api.create_job(request, background_tasks))

    assert response.status == "starting"
    assert response.job_id
    assert len(background_tasks.tasks) == 1
    assert called == {}

    task = background_tasks.tasks[0]
    task.func(*task.args, **task.kwargs)

    assert called["request_data"]["job_id"] == response.job_id
    assert called["request_data"]["cloud"]["provider"] == "vast"
    assert called["supabase_session"]["user_id"] == "user-1"


def test_create_continue_job_rejects_non_verda_provider():
    from interfaces_backend.models.training import JobCreateContinueRequest
    import interfaces_backend.api.training as training_api

    request = JobCreateContinueRequest.model_validate(
        {
            "type": "continue",
            "checkpoint": {"job_name": "checkpoint-job"},
            "dataset": {"id": "dataset-1", "use_original": True},
            "training": {"additional_steps": 100},
            "cloud": {
                "provider": "vast",
                "gpu_model": "H100",
                "gpus_per_instance": 1,
            },
        }
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(training_api.create_continue_job(request, BackgroundTasks()))
    assert exc.value.status_code == 400
    assert "cloud.provider=verda" in str(exc.value.detail)

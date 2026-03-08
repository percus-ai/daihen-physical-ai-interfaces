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
            "selected_mode": "spot",
            "selected_offer_id": 123456,
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


def test_job_create_request_rejects_cloud_when_omitted():
    from interfaces_backend.models.training import JobCreateRequest

    without_cloud = _valid_create_job_payload()
    without_cloud.pop("cloud")

    with pytest.raises(ValidationError):
        JobCreateRequest.model_validate(without_cloud)


def test_start_provision_operation_preflights_without_fastapi_lifecycle(monkeypatch):
    from interfaces_backend.models.training import JobCreateRequest
    import interfaces_backend.api.training as training_api

    called: dict[str, Any] = {}

    class _FakeOperations:
        async def create(self, *, user_id: str, request: JobCreateRequest):
            called["created_user_id"] = user_id
            called["created_provider"] = request.cloud.provider
            return training_api.TrainingProvisionOperationAcceptedResponse(
                accepted=True,
                operation_id="op-1",
                state="queued",
                message="accepted",
            )

    async def fake_run_training_provision_operation(*, operation_id: str, request_data: dict, supabase_session: dict):
        called["request_data"] = request_data
        called["supabase_session"] = supabase_session
        called["operation_id"] = operation_id

    def fake_create_task(coro):
        return asyncio.get_running_loop().create_task(coro)

    monkeypatch.setattr(training_api, "get_training_provision_operations_service", lambda: _FakeOperations())
    monkeypatch.setattr(training_api, "_run_training_provision_operation", fake_run_training_provision_operation)
    monkeypatch.setattr(training_api.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(training_api, "get_supabase_session", lambda: {"user_id": "user-1"})
    monkeypatch.setattr(training_api, "get_current_user_id", lambda: "user-1")
    monkeypatch.setenv("VAST_API_KEY", "test-api-key")
    monkeypatch.setenv("VAST_SSH_PRIVATE_KEY", "/tmp/id_rsa_test")

    request = JobCreateRequest.model_validate(_valid_create_job_payload())
    
    async def _run():
        response = await training_api.start_training_provision_operation(request)
        await asyncio.sleep(0)
        return response

    response = asyncio.run(_run())

    assert response.state == "queued"
    assert response.operation_id == "op-1"
    assert called["created_user_id"] == "user-1"
    assert called["operation_id"] == "op-1"
    assert called["request_data"]["cloud"]["provider"] == "vast"
    assert called["supabase_session"]["user_id"] == "user-1"
    assert called["request_data"]["job_id"]


def test_start_provision_operation_rejects_vast_when_required_env_missing(monkeypatch):
    from interfaces_backend.models.training import JobCreateRequest
    import interfaces_backend.api.training as training_api

    monkeypatch.delenv("VAST_API_KEY", raising=False)
    monkeypatch.delenv("VAST_SSH_PRIVATE_KEY", raising=False)

    request = JobCreateRequest.model_validate(_valid_create_job_payload())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(training_api.start_training_provision_operation(request))

    assert exc.value.status_code == 400
    assert "VAST_API_KEY" in str(exc.value.detail)
    assert "VAST_SSH_PRIVATE_KEY" in str(exc.value.detail)


def test_run_training_provision_operation_cleans_up_instance_after_job_created(monkeypatch):
    import interfaces_backend.api.training as training_api
    from fastapi import HTTPException
    from percus_ai.training import orchestrator as orch

    progress_events: list[dict[str, Any]] = []
    cleanup_calls: list[tuple[str, str]] = []
    fail_calls: list[dict[str, str]] = []

    class _FakeOperations:
        async def update_from_progress(self, *, operation_id: str, progress: dict):
            progress_events.append({"operation_id": operation_id, **progress})

        async def fail(self, *, operation_id: str, message: str, failure_reason: str):
            fail_calls.append(
                {
                    "operation_id": operation_id,
                    "message": message,
                    "failure_reason": failure_reason,
                }
            )

    def fake_create_job_with_progress(request_data: dict, emit_progress, supabase_session: dict):
        assert request_data["job_id"] == "job-1"
        assert supabase_session["user_id"] == "user-1"
        emit_progress({"type": "instance_created", "instance_id": "inst-1"})
        emit_progress({"type": "job_created", "job_id": "job-1", "instance_id": "inst-1"})
        raise HTTPException(status_code=500, detail="ssh failed")

    def fake_cleanup(provider: str, instance_id: str):
        cleanup_calls.append((provider, instance_id))
        return True, "deleted"

    monkeypatch.setattr(training_api, "get_training_provision_operations_service", lambda: _FakeOperations())
    monkeypatch.setattr(training_api, "cleanup_provision_instance", fake_cleanup)
    monkeypatch.setattr(orch, "create_job_with_progress", fake_create_job_with_progress)

    async def _run():
        await training_api._run_training_provision_operation(
            operation_id="op-1",
            request_data={
                "job_id": "job-1",
                "job_name": "job",
                "dataset": {"id": "dataset-1"},
                "policy": {"type": "pi05"},
                "cloud": {"provider": "vast"},
            },
            supabase_session={"user_id": "user-1"},
        )
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert cleanup_calls == [("vast", "inst-1")]
    assert fail_calls == [
        {
            "operation_id": "op-1",
            "message": "学習インスタンス作成に失敗しました。 作成中インスタンスは削除しました。",
            "failure_reason": "ssh failed",
        }
    ]
    assert [event["type"] for event in progress_events] == ["instance_created", "job_created"]


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
                "selected_mode": "spot",
                "selected_offer_id": 123456,
            },
        }
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(training_api.create_continue_job(request, BackgroundTasks()))
    assert exc.value.status_code == 400
    assert "cloud.provider=verda" in str(exc.value.detail)

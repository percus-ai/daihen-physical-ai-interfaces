from __future__ import annotations

import asyncio

from interfaces_backend.services.realtime_runtime import get_realtime_runtime, reset_realtime_runtime
from interfaces_backend.services.training_provision_operations import (
    TrainingProvisionOperationsService,
)


def test_update_from_progress_maps_job_created(monkeypatch):
    service = TrainingProvisionOperationsService()
    captured: dict[str, object] = {}

    async def fake_update(*, operation_id: str, **patch):
        captured['operation_id'] = operation_id
        captured['patch'] = patch

    monkeypatch.setattr(service, '_update', fake_update)

    asyncio.run(
        service.update_from_progress(
            operation_id='op-1',
            progress={
                'type': 'job_created',
                'message': 'ジョブ作成完了',
                'job_id': 'job-1',
                'instance_id': 'inst-1',
            },
        )
    )

    patch = captured['patch']
    assert captured['operation_id'] == 'op-1'
    assert patch['state'] == 'running'
    assert patch['step'] == 'job_created'
    assert patch['job_id'] == 'job-1'
    assert patch['instance_id'] == 'inst-1'
    assert patch['message'] == 'ジョブ作成完了'


def test_update_from_progress_maps_error_to_failed(monkeypatch):
    service = TrainingProvisionOperationsService()
    captured: dict[str, object] = {}

    async def fake_update(*, operation_id: str, **patch):
        captured['operation_id'] = operation_id
        captured['patch'] = patch

    monkeypatch.setattr(service, '_update', fake_update)

    asyncio.run(
        service.update_from_progress(
            operation_id='op-2',
            progress={
                'type': 'error',
                'error': 'boom',
                'instance_id': 'inst-2',
            },
        )
    )

    patch = captured['patch']
    assert captured['operation_id'] == 'op-2'
    assert patch['state'] == 'failed'
    assert patch['step'] == 'failed'
    assert patch['failure_reason'] == 'boom'
    assert patch['instance_id'] == 'inst-2'
    assert patch['finished_at']


def test_update_emits_snapshot(monkeypatch):
    service = TrainingProvisionOperationsService()
    reset_realtime_runtime()

    async def fake_get_supabase_async_client():
        return object()

    async def fake_update_with_client(_client, *, operation_id: str, patch: dict[str, object]):
        assert operation_id == "op-3"
        assert patch["state"] == "running"

    async def fake_load(operation_id: str, *, owner_user_id: str | None):
        assert operation_id == "op-3"
        assert owner_user_id is None
        return {
            "operation_id": "op-3",
            "owner_user_id": "user-1",
            "state": "running",
            "step": "wait_ip",
            "message": "waiting",
            "failure_reason": None,
            "provider": "vast",
            "instance_id": "inst-3",
            "job_id": None,
            "created_at": None,
            "updated_at": None,
            "started_at": None,
            "finished_at": None,
        }

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_operations.get_supabase_async_client",
        fake_get_supabase_async_client,
    )
    monkeypatch.setattr(service, "_update_with_client", fake_update_with_client)
    monkeypatch.setattr(service, "_load", fake_load)

    async def _run():
        connection = get_realtime_runtime().open_connection(user_id="user-1", tab_id="tab-1")
        await service._update(operation_id="op-3", state="running")
        return await connection.next_frame(timeout_seconds=0.1)

    frame = asyncio.run(_run())

    assert frame is not None
    assert frame.kind == "training.provision-operation"
    assert frame.key == "op-3"
    assert frame.detail["state"] == "running"

from __future__ import annotations

import asyncio

from interfaces_backend.models.training import TrainingProvisionOperationStatusResponse
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


def test_update_publishes_snapshot(monkeypatch):
    service = TrainingProvisionOperationsService()
    published: list[TrainingProvisionOperationStatusResponse] = []

    async def fake_get_supabase_async_client():
        return object()

    async def fake_update_with_client(_client, *, operation_id: str, patch: dict[str, object]):
        assert operation_id == "op-3"
        assert patch["state"] == "running"

    async def fake_get_system(*, operation_id: str):
        assert operation_id == "op-3"
        return TrainingProvisionOperationStatusResponse(
            operation_id="op-3",
            state="running",
            step="wait_ip",
            message="waiting",
            failure_reason=None,
            provider="vast",
            instance_id="inst-3",
            job_id=None,
            created_at=None,
            updated_at=None,
            started_at=None,
            finished_at=None,
        )

    async def fake_publish(snapshot: TrainingProvisionOperationStatusResponse):
        published.append(snapshot)

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_operations.get_supabase_async_client",
        fake_get_supabase_async_client,
    )
    monkeypatch.setattr(service, "_update_with_client", fake_update_with_client)
    monkeypatch.setattr(service, "get_system", fake_get_system)
    monkeypatch.setattr(service, "_publish", fake_publish)

    asyncio.run(service._update(operation_id="op-3", state="running"))

    assert [snapshot.operation_id for snapshot in published] == ["op-3"]

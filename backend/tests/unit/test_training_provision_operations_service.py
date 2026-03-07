from __future__ import annotations

import asyncio

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

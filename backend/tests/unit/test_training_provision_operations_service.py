from __future__ import annotations

import asyncio

from interfaces_backend.services.training_provision_operations import (
    TrainingProvisionOperationsService,
)
from interfaces_backend.models.training import TrainingProvisionOperationStatusResponse


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, rows: list[dict[str, object]]):
        self._rows = rows
        self._mode = "select"
        self._update_patch: dict[str, object] | None = None
        self._eq_key: str | None = None
        self._eq_value: object | None = None

    def select(self, *_args, **_kwargs):
        self._mode = "select"
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def lt(self, *_args, **_kwargs):
        return self

    def update(self, patch: dict[str, object]):
        self._mode = "update"
        self._update_patch = patch
        return self

    def eq(self, key: str, value: object):
        self._eq_key = key
        self._eq_value = value
        return self

    async def execute(self):
        if self._mode == "select":
            return _FakeResponse([dict(row) for row in self._rows])
        if self._mode == "update":
            for row in self._rows:
                if self._eq_key is None or row.get(self._eq_key) == self._eq_value:
                    row.update(self._update_patch or {})
            return _FakeResponse([dict(row) for row in self._rows])
        raise AssertionError(f"Unexpected mode: {self._mode}")


class _FakeClient:
    def __init__(self, rows: list[dict[str, object]]):
        self._rows = rows

    def table(self, _name: str):
        return _FakeTable(self._rows)


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


def test_cleanup_stale_operations_marks_failed_without_instance(monkeypatch):
    service = TrainingProvisionOperationsService()
    rows = [
        {
            "operation_id": "op-1",
            "owner_user_id": "user-1",
            "state": "running",
            "step": "connect_ssh",
            "message": "SSH接続",
            "failure_reason": None,
            "provider": "verda",
            "instance_id": None,
            "job_id": None,
            "created_at": "2026-03-07T00:00:00+00:00",
            "updated_at": "2026-03-07T00:00:00+00:00",
            "started_at": "2026-03-07T00:00:10+00:00",
            "finished_at": None,
        }
    ]
    fake_client = _FakeClient(rows)
    published: list[TrainingProvisionOperationStatusResponse] = []

    async def fake_get_system(*, operation_id: str):
        assert operation_id == "op-1"
        row = rows[0]
        return TrainingProvisionOperationStatusResponse(
            operation_id=str(row["operation_id"]),
            state=str(row["state"]),
            step=str(row["step"]),
            message=row["message"],
            failure_reason=row["failure_reason"],
            provider=str(row["provider"]),
            instance_id=row["instance_id"],
            job_id=row["job_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    async def fake_publish(snapshot: TrainingProvisionOperationStatusResponse):
        published.append(snapshot)

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_operations._get_service_db_client",
        lambda: asyncio.sleep(0, result=fake_client),
    )
    monkeypatch.setattr(service, "get_system", fake_get_system)
    monkeypatch.setattr(service, "_publish", fake_publish)

    cleaned = asyncio.run(service.cleanup_stale_operations())

    assert cleaned == ["op-1"]
    assert rows[0]["state"] == "failed"
    assert rows[0]["step"] == "failed"
    assert rows[0]["failure_reason"] == "backend_restart_cleanup"
    assert "中断" in str(rows[0]["message"])
    assert published
    assert published[0].operation_id == "op-1"
    assert published[0].state == "failed"


def test_cleanup_stale_operations_deletes_instance_when_present(monkeypatch):
    service = TrainingProvisionOperationsService()
    rows = [
        {
            "operation_id": "op-2",
            "owner_user_id": "user-1",
            "state": "running",
            "step": "setup_env",
            "message": "環境構築",
            "failure_reason": None,
            "provider": "vast",
            "instance_id": "inst-9",
            "job_id": None,
            "created_at": "2026-03-07T00:00:00+00:00",
            "updated_at": "2026-03-07T00:00:00+00:00",
            "started_at": "2026-03-07T00:00:10+00:00",
            "finished_at": None,
        }
    ]
    fake_client = _FakeClient(rows)
    cleanup_calls: list[tuple[str, str]] = []

    async def fake_get_system(*, operation_id: str):
        row = rows[0]
        return TrainingProvisionOperationStatusResponse(
            operation_id=operation_id,
            state=str(row["state"]),
            step=str(row["step"]),
            message=row["message"],
            failure_reason=row["failure_reason"],
            provider=str(row["provider"]),
            instance_id=row["instance_id"],
            job_id=row["job_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    async def fake_publish(_snapshot: TrainingProvisionOperationStatusResponse):
        return None

    async def fake_get_client():
        return fake_client

    def fake_cleanup(provider: str, instance_id: str):
        cleanup_calls.append((provider, instance_id))
        return True, "deleted"

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_operations._get_service_db_client",
        fake_get_client,
    )
    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_operations.cleanup_provision_instance",
        fake_cleanup,
    )
    monkeypatch.setattr(service, "get_system", fake_get_system)
    monkeypatch.setattr(service, "_publish", fake_publish)

    cleaned = asyncio.run(service.cleanup_stale_operations())

    assert cleaned == ["op-2"]
    assert cleanup_calls == [("vast", "inst-9")]
    assert rows[0]["state"] == "failed"
    assert "クリーンアップしました" in str(rows[0]["message"])


def test_cleanup_stale_operations_preserves_job_bound_instance(monkeypatch):
    service = TrainingProvisionOperationsService()
    rows = [
        {
            "operation_id": "op-3",
            "owner_user_id": "user-1",
            "state": "running",
            "step": "setup_env",
            "message": "環境構築",
            "failure_reason": None,
            "provider": "verda",
            "instance_id": "inst-keep",
            "job_id": "job-1",
            "created_at": "2026-03-07T00:00:00+00:00",
            "updated_at": "2026-03-07T00:00:00+00:00",
            "started_at": "2026-03-07T00:00:10+00:00",
            "finished_at": None,
        }
    ]
    fake_client = _FakeClient(rows)
    cleanup_calls: list[tuple[str, str]] = []

    async def fake_get_system(*, operation_id: str):
        row = rows[0]
        return TrainingProvisionOperationStatusResponse(
            operation_id=operation_id,
            state=str(row["state"]),
            step=str(row["step"]),
            message=row["message"],
            failure_reason=row["failure_reason"],
            provider=str(row["provider"]),
            instance_id=row["instance_id"],
            job_id=row["job_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    async def fake_publish(_snapshot: TrainingProvisionOperationStatusResponse):
        return None

    async def fake_get_client():
        return fake_client

    def fake_cleanup(provider: str, instance_id: str):
        cleanup_calls.append((provider, instance_id))
        return True, "deleted"

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_operations._get_service_db_client",
        fake_get_client,
    )
    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_operations.cleanup_provision_instance",
        fake_cleanup,
    )
    monkeypatch.setattr(service, "get_system", fake_get_system)
    monkeypatch.setattr(service, "_publish", fake_publish)

    cleaned = asyncio.run(service.cleanup_stale_operations())

    assert cleaned == ["op-3"]
    assert cleanup_calls == []
    assert rows[0]["state"] == "failed"
    assert "詳細画面" in str(rows[0]["message"])

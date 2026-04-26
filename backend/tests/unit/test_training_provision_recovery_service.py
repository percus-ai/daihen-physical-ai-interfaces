from __future__ import annotations

import asyncio

from interfaces_backend.services.realtime_runtime import get_realtime_runtime, reset_realtime_runtime
from interfaces_backend.services.training_provision_operations import (
    TrainingProvisionOperationsService,
)
from interfaces_backend.services.training_provision_recovery import (
    TrainingProvisionRecoveryService,
)


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


def _build_service(rows: list[dict[str, object]]) -> tuple[TrainingProvisionRecoveryService, TrainingProvisionOperationsService]:
    operations = TrainingProvisionOperationsService()
    recovery = TrainingProvisionRecoveryService(operations)
    return recovery, operations


def test_recovery_pass_marks_failed_without_instance(monkeypatch):
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
    recovery, _operations = _build_service(rows)
    reset_realtime_runtime()

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_recovery._get_recovery_db_client",
        lambda: asyncio.sleep(0, result=fake_client),
    )

    async def _run():
        connection = get_realtime_runtime().open_connection(user_id="user-1", tab_id="tab-1")
        should_retry = await recovery._run_recovery_pass()
        frame = await connection.next_frame(timeout_seconds=0.1)
        return should_retry, frame

    should_retry, frame = asyncio.run(_run())

    assert should_retry is False
    assert rows[0]["state"] == "failed"
    assert rows[0]["step"] == "failed"
    assert rows[0]["failure_reason"] == "backend_restart_cleanup"
    assert "中断" in str(rows[0]["message"])
    assert frame is not None
    assert frame.kind == "training.provision-operation"
    assert frame.key == "op-1"
    assert frame.detail["state"] == "failed"


def test_recovery_pass_deletes_instance_when_present(monkeypatch):
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
    recovery, _operations = _build_service(rows)
    cleanup_calls: list[tuple[str, str]] = []

    def fake_cleanup(provider: str, instance_id: str):
        cleanup_calls.append((provider, instance_id))
        return True, "deleted"

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_recovery._get_recovery_db_client",
        lambda: asyncio.sleep(0, result=fake_client),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_recovery.cleanup_provision_instance",
        fake_cleanup,
    )

    should_retry = asyncio.run(recovery._run_recovery_pass())

    assert should_retry is False
    assert cleanup_calls == [("vast", "inst-9")]
    assert rows[0]["state"] == "failed"
    assert "クリーンアップしました" in str(rows[0]["message"])


def test_recovery_pass_preserves_job_bound_instance(monkeypatch):
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
    recovery, _operations = _build_service(rows)
    cleanup_calls: list[tuple[str, str]] = []

    def fake_cleanup(provider: str, instance_id: str):
        cleanup_calls.append((provider, instance_id))
        return True, "deleted"

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_recovery._get_recovery_db_client",
        lambda: asyncio.sleep(0, result=fake_client),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_recovery.cleanup_provision_instance",
        fake_cleanup,
    )

    should_retry = asyncio.run(recovery._run_recovery_pass())

    assert should_retry is False
    assert cleanup_calls == []
    assert rows[0]["state"] == "failed"
    assert "詳細画面" in str(rows[0]["message"])


def test_recovery_pass_retries_when_fetch_fails(monkeypatch):
    recovery, _operations = _build_service([])
    attempts = {"count": 0}
    sleeps: list[float] = []

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    async def fake_load_stale_rows(_service_client):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return None
        return []

    async def fake_get_client():
        return object()

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_recovery._get_recovery_db_client",
        fake_get_client,
    )
    monkeypatch.setattr(recovery, "_load_stale_rows", fake_load_stale_rows)
    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_recovery._recovery_retry_seconds",
        lambda: 0.0,
    )
    monkeypatch.setattr("interfaces_backend.services.training_provision_recovery.asyncio.sleep", fake_sleep)

    asyncio.run(recovery._run_until_stable())

    assert attempts["count"] == 2
    assert sleeps == [0.0]


def test_recovery_pass_retries_when_cleanup_raises(monkeypatch):
    rows = [
        {
            "operation_id": "op-raise",
            "owner_user_id": "user-1",
            "state": "running",
            "step": "setup_env",
            "message": "環境構築",
            "failure_reason": None,
            "provider": "vast",
            "instance_id": "inst-raise",
            "job_id": None,
            "created_at": "2026-03-07T00:00:00+00:00",
            "updated_at": "2026-03-07T00:00:00+00:00",
            "started_at": "2026-03-07T00:00:10+00:00",
            "finished_at": None,
        }
    ]
    fake_client = _FakeClient(rows)
    recovery, _operations = _build_service(rows)

    async def fake_get_client():
        return fake_client

    def fake_cleanup(_provider: str, _instance_id: str):
        raise RuntimeError("cleanup exploded")

    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_recovery._get_recovery_db_client",
        fake_get_client,
    )
    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_recovery.cleanup_provision_instance",
        fake_cleanup,
    )

    should_retry = asyncio.run(recovery._run_recovery_pass())

    assert should_retry is True
    assert rows[0]["state"] == "running"


def test_recovery_disabled_flag_skips_task(monkeypatch):
    recovery, _operations = _build_service([])
    monkeypatch.setenv("PHI_DISABLE_TRAINING_PROVISION_RECOVERY", "1")

    recovery.ensure_started()

    assert recovery._task is None

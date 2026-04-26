from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from interfaces_backend.services import dataset_sync_jobs
from interfaces_backend.services.dataset_sync_jobs import DatasetSyncJobsService


def test_create_allows_parallel_jobs_for_different_datasets_same_user() -> None:
    service = DatasetSyncJobsService()

    first = service.create(user_id="user-1", dataset_id="dataset-a")
    second = service.create(user_id="user-1", dataset_id="dataset-b")

    assert first.accepted is True
    assert second.accepted is True
    assert first.dataset_id == "dataset-a"
    assert second.dataset_id == "dataset-b"
    assert first.job_id != second.job_id


def test_create_rejects_parallel_jobs_for_same_dataset_same_user() -> None:
    service = DatasetSyncJobsService()
    service.create(user_id="user-1", dataset_id="dataset-a")

    with pytest.raises(HTTPException) as exc_info:
        service.create(user_id="user-1", dataset_id="dataset-a")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "A dataset sync job is already in progress"


def test_create_allows_same_dataset_for_different_users() -> None:
    service = DatasetSyncJobsService()

    first = service.create(user_id="user-1", dataset_id="dataset-a")
    second = service.create(user_id="user-2", dataset_id="dataset-a")

    assert first.accepted is True
    assert second.accepted is True
    assert first.dataset_id == "dataset-a"
    assert second.dataset_id == "dataset-a"
    assert first.job_id != second.job_id


def test_run_job_uses_system_sync_without_request_session(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DatasetSyncJobsService()
    accepted = service.create(
        user_id="user-1",
        dataset_id="dataset-a",
    )

    class _FakeSyncService:
        async def ensure_dataset_local(self, dataset_id: str, **_kwargs):
            assert dataset_id == "dataset-a"
            return SimpleNamespace(success=True, message="ok", skipped=False, cancelled=False)

    monkeypatch.setattr(dataset_sync_jobs, "R2DBSyncService", lambda: _FakeSyncService())

    asyncio.run(service._run_job(accepted.job_id))

    assert service.get(user_id="user-1", job_id=accepted.job_id).state == "completed"

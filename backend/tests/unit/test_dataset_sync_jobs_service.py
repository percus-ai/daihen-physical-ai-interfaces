from __future__ import annotations

import asyncio

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


def test_run_job_refreshes_saved_session(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DatasetSyncJobsService()
    accepted = service.create(
        user_id="user-1",
        dataset_id="dataset-a",
        auth_session={"access_token": "expired", "refresh_token": "refresh-token", "user_id": "user-1", "expires_at": 1},
    )

    captured_sessions: list[dict | None] = []

    class _FakeSyncService:
        async def ensure_dataset_local(self, dataset_id: str, **_kwargs):
            assert dataset_id == "dataset-a"
            return dataset_sync_jobs.SyncResult(True, "ok")

    monkeypatch.setattr(dataset_sync_jobs, "R2DBSyncService", lambda: _FakeSyncService())
    monkeypatch.setattr(
        dataset_sync_jobs,
        "refresh_session_from_refresh_token",
        lambda token: {"access_token": "fresh", "refresh_token": token, "user_id": "user-1", "expires_at": 9999},
    )
    monkeypatch.setattr(dataset_sync_jobs, "set_request_session", lambda session: captured_sessions.append(session) or object())
    monkeypatch.setattr(dataset_sync_jobs, "reset_request_session", lambda _token: None)

    asyncio.run(service._run_job(accepted.job_id))

    assert captured_sessions == [
        {"access_token": "fresh", "refresh_token": "refresh-token", "user_id": "user-1", "expires_at": 9999}
    ]


def test_resolve_job_session_drops_expired_session_without_refresh() -> None:
    resolved = DatasetSyncJobsService._resolve_job_session(
        {"access_token": "expired", "user_id": "user-1", "expires_at": 1}
    )

    assert resolved is None

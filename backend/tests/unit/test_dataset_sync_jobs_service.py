from __future__ import annotations

import pytest
from fastapi import HTTPException

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

from __future__ import annotations

import pytest
from fastapi import HTTPException

from interfaces_backend.models.storage import DatasetMergeRequest, DatasetMergeResponse
from interfaces_backend.services import dataset_merge_jobs as jobs_module
from interfaces_backend.services.dataset_merge_jobs import DatasetMergeJobsService


class _DummyBus:
    def publish_threadsafe(self, _topic: str, _key: str, _payload: dict) -> None:
        return


@pytest.fixture(autouse=True)
def _stub_realtime_event_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_module, "get_realtime_event_bus", lambda: _DummyBus())


def test_create_rejects_parallel_jobs_for_same_user() -> None:
    service = DatasetMergeJobsService()
    request = DatasetMergeRequest(dataset_name="merged", source_dataset_ids=["a", "b"])

    service.create(user_id="user-1", request=request)
    with pytest.raises(HTTPException) as exc_info:
        service.create(user_id="user-1", request=request)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "A dataset merge job is already in progress"


def test_create_allows_new_job_after_completion() -> None:
    service = DatasetMergeJobsService()
    request = DatasetMergeRequest(dataset_name="merged", source_dataset_ids=["a", "b"])

    first = service.create(user_id="user-1", request=request)
    service.complete(
        job_id=first.job_id,
        result=DatasetMergeResponse(
            success=True,
            dataset_id="new-id",
            message="ok",
            size_bytes=123,
            episode_count=4,
        ),
    )

    second = service.create(user_id="user-1", request=request)
    assert second.job_id != first.job_id


def test_update_from_progress_upload_advances_progress() -> None:
    service = DatasetMergeJobsService()
    request = DatasetMergeRequest(dataset_name="merged", source_dataset_ids=["a", "b"])
    accepted = service.create(user_id="user-1", request=request)

    service.update_from_progress(
        job_id=accepted.job_id,
        progress={"type": "upload_start", "step": "upload", "total_files": 10, "total_size": 100},
    )

    status = service.get(user_id="user-1", job_id=accepted.job_id)
    assert status.state == "running"
    assert status.detail.step == "upload"
    assert status.detail.total_files == 10
    assert status.detail.total_size == 100
    assert status.progress_percent >= 55.0


def test_update_from_progress_error_marks_failed() -> None:
    service = DatasetMergeJobsService()
    request = DatasetMergeRequest(dataset_name="merged", source_dataset_ids=["a", "b"])
    accepted = service.create(user_id="user-1", request=request)

    service.update_from_progress(
        job_id=accepted.job_id,
        progress={"type": "error", "step": "validate", "error": "boom"},
    )

    status = service.get(user_id="user-1", job_id=accepted.job_id)
    assert status.state == "failed"
    assert status.error == "boom"


"""Bulk storage and recording actions shared across API routers."""

from __future__ import annotations

from fastapi import HTTPException

from interfaces_backend.models.storage import BulkActionResult
from interfaces_backend.services.dataset_lifecycle import get_dataset_lifecycle
from interfaces_backend.services.model_sync_jobs import get_model_sync_jobs_service
from percus_ai.db import get_supabase_async_client
from percus_ai.storage.paths import get_datasets_dir


async def set_dataset_status(dataset_id: str, *, status: str) -> tuple[str, bool]:
    normalized_id = dataset_id.strip()
    if not normalized_id:
        raise HTTPException(status_code=400, detail="Dataset ID is required")

    client = await get_supabase_async_client()
    rows = (
        await client.table("datasets").select("id,status").eq("id", normalized_id).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if rows[0].get("status") == status:
        return status, False

    await client.table("datasets").update({"status": status}).eq("id", normalized_id).execute()
    refreshed = (
        await client.table("datasets").select("id,status").eq("id", normalized_id).execute()
    ).data or []
    if not refreshed or refreshed[0].get("status") != status:
        raise HTTPException(
            status_code=500,
            detail=f"Dataset {'archive' if status == 'archived' else 'restore'} was not persisted",
        )
    return status, True


async def archive_dataset_for_bulk(dataset_id: str) -> BulkActionResult:
    normalized_id = dataset_id.strip()
    if not normalized_id:
        return BulkActionResult(id=dataset_id, status="failed", message="Dataset ID is required")

    try:
        _status, changed = await set_dataset_status(normalized_id, status="archived")
    except HTTPException as exc:
        return BulkActionResult(id=normalized_id, status="failed", message=str(exc.detail))
    if not changed:
        return BulkActionResult(id=normalized_id, status="skipped", message="Dataset is already archived")
    return BulkActionResult(id=normalized_id, status="succeeded", message="Dataset archived")


async def reupload_dataset_for_bulk(dataset_id: str) -> BulkActionResult:
    normalized_id = dataset_id.strip()
    if not normalized_id:
        return BulkActionResult(id=dataset_id, status="failed", message="Dataset ID is required")

    local_path = get_datasets_dir() / normalized_id
    if not local_path.exists():
        return BulkActionResult(id=normalized_id, status="failed", message="Local dataset not found")
    if not local_path.is_dir():
        return BulkActionResult(id=normalized_id, status="failed", message="Invalid dataset path")

    lifecycle = get_dataset_lifecycle()
    ok, error = await lifecycle.reupload(normalized_id)
    if not ok:
        return BulkActionResult(id=normalized_id, status="failed", message=f"Dataset re-upload failed: {error}")

    return BulkActionResult(id=normalized_id, status="succeeded", message="Dataset re-upload completed")


async def sync_model_for_bulk(*, user_id: str, model_id: str) -> BulkActionResult:
    normalized_id = model_id.strip()
    if not normalized_id:
        return BulkActionResult(id=model_id, status="failed", message="Model ID is required")

    client = await get_supabase_async_client()
    rows = (
        await client.table("models").select("id,status").eq("id", normalized_id).execute()
    ).data or []
    if not rows:
        return BulkActionResult(id=normalized_id, status="failed", message="Model not found")
    if rows[0].get("status") != "active":
        return BulkActionResult(id=normalized_id, status="failed", message="Model is not active")

    jobs = get_model_sync_jobs_service()
    try:
        accepted = jobs.create(user_id=user_id, model_id=normalized_id)
    except HTTPException as exc:
        if exc.status_code == 409:
            return BulkActionResult(id=normalized_id, status="skipped", message=str(exc.detail))
        return BulkActionResult(id=normalized_id, status="failed", message=str(exc.detail))

    jobs.ensure_worker()
    return BulkActionResult(
        id=normalized_id,
        status="succeeded",
        message="Model sync job accepted",
        job_id=accepted.job_id,
    )


async def archive_model_for_bulk(*, user_id: str, model_id: str) -> BulkActionResult:
    normalized_id = model_id.strip()
    if not normalized_id:
        return BulkActionResult(id=model_id, status="failed", message="Model ID is required")

    client = await get_supabase_async_client()
    rows = (
        await client.table("models").select("id,status").eq("id", normalized_id).execute()
    ).data or []
    if not rows:
        return BulkActionResult(id=normalized_id, status="failed", message="Model not found")
    if rows[0].get("status") == "archived":
        return BulkActionResult(id=normalized_id, status="skipped", message="Model is already archived")

    jobs = get_model_sync_jobs_service()
    active_jobs = jobs.list(user_id=user_id, include_terminal=False).jobs
    active_job = next((job for job in active_jobs if job.model_id == normalized_id), None)
    cancelled = False
    if active_job is not None:
        try:
            jobs.cancel(user_id=user_id, job_id=active_job.job_id)
            cancelled = True
        except HTTPException:
            cancelled = False

    await client.table("models").update({"status": "archived"}).eq("id", normalized_id).execute()
    refreshed = (
        await client.table("models").select("id,status").eq("id", normalized_id).execute()
    ).data or []
    if not refreshed or refreshed[0].get("status") != "archived":
        return BulkActionResult(id=normalized_id, status="failed", message="Model archive was not persisted")
    message = "Model archived"
    if cancelled:
        message = "Model archived after cancel request"
    return BulkActionResult(id=normalized_id, status="succeeded", message=message)

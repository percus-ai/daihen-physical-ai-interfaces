"""Build management API for the new environment architecture."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter

from interfaces_backend.models.build_management import (
    BuildArtifactDeleteResponse,
    BuildErrorReportResponse,
    BuildJobCancelResponse,
    BuildRunAcceptedResponse,
    EnvBuildSettingsListResponse,
    SharedBuildSettingsListResponse,
)
from interfaces_backend.services.build_management import get_build_management_service
from interfaces_backend.services.build_jobs import get_build_jobs_service

router = APIRouter(prefix="/api/builds", tags=["builds"])


@router.get("/envs", response_model=EnvBuildSettingsListResponse)
async def list_env_build_settings() -> EnvBuildSettingsListResponse:
    return await asyncio.to_thread(get_build_management_service().list_env_settings)


@router.get("/shared", response_model=SharedBuildSettingsListResponse)
async def list_shared_build_settings() -> SharedBuildSettingsListResponse:
    return await asyncio.to_thread(get_build_management_service().list_shared_settings)


@router.post("/envs/{config_group}/{config_id}/{env_name}/run", response_model=BuildRunAcceptedResponse)
async def run_env_build(config_group: Literal["envs", "train"], config_id: str, env_name: str) -> BuildRunAcceptedResponse:
    return get_build_jobs_service().start_env_build(config_group=config_group, config_id=config_id, env_name=env_name)


@router.post("/shared/{package}/{variant}/run", response_model=BuildRunAcceptedResponse)
async def run_shared_build(package: str, variant: str) -> BuildRunAcceptedResponse:
    return get_build_jobs_service().start_shared_build(package=package, variant=variant)


@router.post("/jobs/{job_id}/cancel", response_model=BuildJobCancelResponse)
async def cancel_build_job(job_id: str) -> BuildJobCancelResponse:
    return get_build_jobs_service().cancel(job_id=job_id)


@router.delete("/envs/{config_group}/{config_id}/{env_name}/artifacts/{build_id}", response_model=BuildArtifactDeleteResponse)
async def delete_env_build_artifact(
    config_group: Literal["envs", "train"],
    config_id: str,
    env_name: str,
    build_id: str,
) -> BuildArtifactDeleteResponse:
    await asyncio.to_thread(
        get_build_management_service().delete_env_artifact,
        config_group=config_group,
        config_id=config_id,
        env_name=env_name,
        build_id=build_id,
    )
    return BuildArtifactDeleteResponse(
        kind="env",
        setting_id=f"{config_group}:{config_id}:{env_name}",
        build_id=build_id,
    )


@router.delete("/shared/{package}/{variant}/artifacts/{build_id}", response_model=BuildArtifactDeleteResponse)
async def delete_shared_build_artifact(package: str, variant: str, build_id: str) -> BuildArtifactDeleteResponse:
    await asyncio.to_thread(
        get_build_management_service().delete_shared_artifact,
        package=package,
        variant=variant,
        build_id=build_id,
    )
    return BuildArtifactDeleteResponse(
        kind="shared",
        setting_id=f"{package}:{variant}",
        build_id=build_id,
    )


@router.post("/envs/{config_group}/{config_id}/{env_name}/artifacts/{build_id}/error-report", response_model=BuildErrorReportResponse)
async def create_env_build_error_report(
    config_group: Literal["envs", "train"],
    config_id: str,
    env_name: str,
    build_id: str,
) -> BuildErrorReportResponse:
    return await asyncio.to_thread(
        get_build_management_service().create_env_error_report,
        config_group=config_group,
        config_id=config_id,
        env_name=env_name,
        build_id=build_id,
    )


@router.post("/shared/{package}/{variant}/artifacts/{build_id}/error-report", response_model=BuildErrorReportResponse)
async def create_shared_build_error_report(package: str, variant: str, build_id: str) -> BuildErrorReportResponse:
    return await asyncio.to_thread(
        get_build_management_service().create_shared_error_report,
        package=package,
        variant=variant,
        build_id=build_id,
    )

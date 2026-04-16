"""Build management API for the new environment architecture."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from interfaces_backend.models.build_management import (
    EnvBuildSettingsListResponse,
    SharedBuildSettingsListResponse,
)
from interfaces_backend.services.build_management import get_build_management_service

router = APIRouter(prefix="/api/builds", tags=["builds"])


@router.get("/envs", response_model=EnvBuildSettingsListResponse)
async def list_env_build_settings() -> EnvBuildSettingsListResponse:
    return await asyncio.to_thread(get_build_management_service().list_env_settings)


@router.get("/shared", response_model=SharedBuildSettingsListResponse)
async def list_shared_build_settings() -> SharedBuildSettingsListResponse:
    return await asyncio.to_thread(get_build_management_service().list_shared_settings)

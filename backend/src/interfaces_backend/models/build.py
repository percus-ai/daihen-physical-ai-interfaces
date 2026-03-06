"""Bundled-torch state models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


BundledTorchState = Literal["idle", "building", "cleaning", "completed", "failed"]


class BundledTorchPlatformInfo(BaseModel):
    platform_name: str
    is_jetson: bool = False
    pytorch_build_required: bool = False
    supported: bool = False
    gpu_name: str | None = None
    cuda_version: str | None = None


class BundledTorchInstallStatus(BaseModel):
    exists: bool = False
    pytorch_version: str | None = None
    torchvision_version: str | None = None
    numpy_version: str | None = None
    pytorch_path: str | None = None
    torchvision_path: str | None = None
    is_valid: bool = False


class BundledTorchLogEntry(BaseModel):
    at: str
    type: str
    step: str | None = None
    message: str | None = None
    line: str | None = None
    percent: int | None = None


class BundledTorchBuildSnapshot(BaseModel):
    platform: BundledTorchPlatformInfo
    install: BundledTorchInstallStatus = Field(default_factory=BundledTorchInstallStatus)
    state: BundledTorchState = "idle"
    current_step: str | None = None
    message: str | None = None
    started_at: str | None = None
    updated_at: str
    finished_at: str | None = None
    requested_pytorch_version: str | None = None
    requested_torchvision_version: str | None = None
    last_error: str | None = None
    logs: list[BundledTorchLogEntry] = Field(default_factory=list)
    can_build: bool = False
    can_clean: bool = False
    can_rebuild: bool = False


class BundledTorchBuildRequest(BaseModel):
    pytorch_version: str | None = None
    torchvision_version: str | None = None
    force: bool = False

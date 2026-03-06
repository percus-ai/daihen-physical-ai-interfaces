"""Runtime environment management models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RuntimeEnvState = Literal["idle", "building", "deleting", "completed", "failed"]


class RuntimeEnvLogEntry(BaseModel):
    at: str
    type: str
    step: str | None = None
    message: str | None = None
    error: str | None = None
    percent: int | None = None


class RuntimeEnvStatusSnapshot(BaseModel):
    env_name: str
    description: str | None = None
    policies: list[str] = Field(default_factory=list)
    exists: bool = False
    gpu_required: bool = False
    python_path: str | None = None
    packages_hash: str | None = None
    state: RuntimeEnvState = "idle"
    current_step: str | None = None
    progress_percent: int | None = None
    message: str | None = None
    started_at: str | None = None
    updated_at: str
    finished_at: str | None = None
    last_error: str | None = None
    logs: list[RuntimeEnvLogEntry] = Field(default_factory=list)
    can_build: bool = False
    can_rebuild: bool = False
    can_delete: bool = False


class RuntimeEnvSnapshot(BaseModel):
    updated_at: str
    active_env_name: str | None = None
    envs: list[RuntimeEnvStatusSnapshot] = Field(default_factory=list)


class RuntimeEnvActionRequest(BaseModel):
    env_name: str
    force: bool = False


class RuntimeEnvDeleteRequest(BaseModel):
    env_name: str

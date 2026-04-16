"""Build management API models for the new environment architecture."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


BuildSettingState = Literal["unbuilt", "building", "success", "failed"]
BuildSettingKind = Literal["env", "shared"]
BuildJobState = Literal["queued", "running", "completed", "failed"]


class BuildSettingActionsModel(BaseModel):
    run: bool = False
    cancel: bool = False
    delete: bool = False
    create_error_report: bool = False


class BuildSettingSummaryModel(BaseModel):
    kind: BuildSettingKind
    setting_id: str
    display_name: str
    state: BuildSettingState
    selected: bool = False
    config_origin: Literal["default", "data"] | None = None
    config_id: str | None = None
    env_name: str | None = None
    package: str | None = None
    variant: str | None = None
    latest_build_id: str | None = None
    current_build_id: str | None = None
    current_job_id: str | None = None
    current_step_name: str | None = None
    current_step_index: int | None = None
    total_steps: int | None = None
    progress_percent: float | None = None
    latest_started_at: str | None = None
    latest_finished_at: str | None = None
    latest_error_summary: str | None = None
    actions: BuildSettingActionsModel = Field(default_factory=BuildSettingActionsModel)


class EnvBuildSettingsListResponse(BaseModel):
    selected_config_id: str | None = None
    items: list[BuildSettingSummaryModel] = Field(default_factory=list)


class SharedBuildSettingsListResponse(BaseModel):
    items: list[BuildSettingSummaryModel] = Field(default_factory=list)


class BuildJobSummaryModel(BaseModel):
    job_id: str
    build_id: str
    kind: BuildSettingKind
    setting_id: str
    state: BuildJobState
    current_step_name: str | None = None
    current_step_index: int = 0
    total_steps: int = 0
    progress_percent: float = 0.0
    message: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class BuildRunAcceptedResponse(BaseModel):
    accepted: bool = True
    job: BuildJobSummaryModel


class BuildJobCancelResponse(BaseModel):
    accepted: bool
    job: BuildJobSummaryModel


class BuildArtifactDeleteResponse(BaseModel):
    deleted: bool = True
    kind: BuildSettingKind
    setting_id: str
    build_id: str


class BuildsStatusSnapshotModel(BaseModel):
    running_jobs: list[BuildJobSummaryModel] = Field(default_factory=list)
    envs: EnvBuildSettingsListResponse
    shared: SharedBuildSettingsListResponse

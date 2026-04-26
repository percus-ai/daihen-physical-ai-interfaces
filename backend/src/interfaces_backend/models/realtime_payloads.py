"""Typed detail payloads carried by realtime tracks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from interfaces_backend.models.operate import OperateStatusResponse
from interfaces_backend.models.training import (
    TrainingJobOperationStatusResponse,
    TrainingProvisionOperationStatusResponse,
)


class OperateStatusRealtimeDetail(BaseModel):
    operate_status: OperateStatusResponse


class TrainingJobOperationsRealtimeDetail(BaseModel):
    operations: list[TrainingJobOperationStatusResponse] = Field(default_factory=list)


class TrainingJobProvisionRealtimeDetail(BaseModel):
    provision_operation: TrainingProvisionOperationStatusResponse


class RecordingUploadStatusResponse(BaseModel):
    dataset_id: str
    status: str = "idle"
    phase: str = "idle"
    progress_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    message: str = ""
    files_done: int = Field(default=0, ge=0)
    total_files: int = Field(default=0, ge=0)
    current_file: str | None = None
    error: str | None = None
    updated_at: str | None = None

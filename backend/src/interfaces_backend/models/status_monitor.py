"""System status snapshot models for SSE monitoring."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


HealthLevel = Literal["healthy", "degraded", "error", "unknown"]


class StatusAlert(BaseModel):
    code: str
    level: HealthLevel
    summary: str
    source: str


class OverallStatus(BaseModel):
    level: HealthLevel = "unknown"
    summary: str = ""
    active_alerts: list[StatusAlert] = Field(default_factory=list)


class RecorderDependencies(BaseModel):
    cameras_ready: bool | None = None
    robot_ready: bool | None = None
    storage_ready: bool | None = None


class RecorderStatusSnapshot(BaseModel):
    level: HealthLevel = "unknown"
    state: str = "unknown"
    process_alive: bool = False
    session_id: str | None = None
    active_profile: str | None = None
    dataset_id: str | None = None
    output_path: str | None = None
    last_frame_at: str | None = None
    write_ok: bool | None = None
    disk_ok: bool | None = None
    dependencies: RecorderDependencies = Field(default_factory=RecorderDependencies)
    last_error: str | None = None


class InferenceStatusSnapshot(BaseModel):
    level: HealthLevel = "unknown"
    state: str = "unknown"
    session_id: str | None = None
    policy_type: str | None = None
    model_id: str | None = None
    device: str | None = None
    env_name: str | None = None
    worker_alive: bool = False
    recording_dataset_id: str | None = None
    recording_prepared: bool = False
    recording_active: bool = False
    recorder_state: str | None = None
    queue_length: int | None = None
    last_error: str | None = None


class ContainerStatusSnapshot(BaseModel):
    name: str
    state: str


class VlaborStatusSnapshot(BaseModel):
    level: HealthLevel = "unknown"
    state: str = "unknown"
    containers: list[ContainerStatusSnapshot] = Field(default_factory=list)
    last_error: str | None = None


class Ros2StatusSnapshot(BaseModel):
    level: HealthLevel = "unknown"
    state: str = "unknown"
    required_nodes_ok: bool | None = None
    required_topics_ok: bool | None = None
    missing_nodes: list[str] = Field(default_factory=list)
    missing_topics: list[str] = Field(default_factory=list)
    last_error: str | None = None


class ServicesStatus(BaseModel):
    recorder: RecorderStatusSnapshot = Field(default_factory=RecorderStatusSnapshot)
    inference: InferenceStatusSnapshot = Field(default_factory=InferenceStatusSnapshot)
    vlabor: VlaborStatusSnapshot = Field(default_factory=VlaborStatusSnapshot)
    ros2: Ros2StatusSnapshot = Field(default_factory=Ros2StatusSnapshot)


class GpuDeviceSnapshot(BaseModel):
    index: int
    name: str
    memory_total_mb: float | None = None
    memory_used_mb: float | None = None
    utilization_gpu_pct: float | None = None
    temperature_c: float | None = None


class GpuSnapshot(BaseModel):
    level: HealthLevel = "unknown"
    driver_version: str | None = None
    cuda_version: str | None = None
    gpus: list[GpuDeviceSnapshot] = Field(default_factory=list)


class StatusSnapshot(BaseModel):
    generated_at: str
    overall: OverallStatus = Field(default_factory=OverallStatus)
    services: ServicesStatus = Field(default_factory=ServicesStatus)
    gpu: GpuSnapshot = Field(default_factory=GpuSnapshot)

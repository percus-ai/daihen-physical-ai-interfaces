"""Inference API models."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class InferenceModelInfo(BaseModel):
    """Model information for inference."""

    model_id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Model name")
    policy_type: str = Field(..., description="Policy type")
    local_path: Optional[str] = Field(None, description="Local path")
    size_mb: float = Field(0.0, description="Model size in MB")
    is_loaded: bool = Field(False, description="Model is loaded in memory")
    is_local: bool = Field(True, description="Model is downloaded locally")
    source: str = Field("local", description="Model source: r2, hub, local")


class InferenceModelsResponse(BaseModel):
    """Response for models list endpoint."""

    models: List[InferenceModelInfo]
    total: int


class InferenceDeviceCompatibility(BaseModel):
    """Device compatibility information."""

    device: str = Field(..., description="Device name")
    available: bool = Field(..., description="Device is available")
    memory_total_mb: Optional[float] = Field(None, description="Total memory in MB")
    memory_free_mb: Optional[float] = Field(None, description="Free memory in MB")


class InferenceDeviceCompatibilityResponse(BaseModel):
    """Response for device compatibility endpoint."""

    devices: List[InferenceDeviceCompatibility]
    recommended: str = Field("cpu", description="Recommended device")


class InferenceRunnerStartRequest(BaseModel):
    model_id: str = Field(..., description="Model ID to run")
    session_id: Optional[str] = Field(None, description="Session ID (auto-generate if omitted)")
    task: Optional[str] = Field(None, description="Task description")
    policy_type: Optional[str] = Field(None, description="Policy type override")
    device: Optional[str] = Field(None, description="Device override (e.g., cuda:0)")
    actions_per_chunk: int = Field(default=1, ge=1)
    arm_namespaces: List[str] = Field(default_factory=list)
    joint_names: List[str] = Field(
        default_factory=list,
        description="Joint name list per arm (defaults to runner status/robot_config)",
    )
    camera_shapes: Optional[Dict[str, List[int]]] = Field(default=None)
    rename_map: Dict[str, str] = Field(default_factory=dict)
    zmq_endpoint: Optional[str] = Field(None, description="ZMQ endpoint for runner bridge")


class InferenceRunnerStartResponse(BaseModel):
    success: bool
    session_id: str
    zmq_endpoint: str
    runner_status: Dict[str, Optional[object]] = Field(default_factory=dict)
    gpu_host_status: Dict[str, Optional[object]] = Field(default_factory=dict)


class InferenceRunnerStopRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Session ID to stop (default: current)")


class InferenceRunnerStopResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    runner_status: Dict[str, Optional[object]] = Field(default_factory=dict)
    gpu_host_status: Dict[str, Optional[object]] = Field(default_factory=dict)


class InferenceRunnerStatusResponse(BaseModel):
    runner_status: Dict[str, Optional[object]]
    gpu_host_status: Dict[str, Optional[object]]

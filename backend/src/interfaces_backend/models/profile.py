"""VLAbor profile API models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class VlaborProfileSummary(BaseModel):
    name: str
    description: str = ""
    updated_at: Optional[str] = None
    source_path: Optional[str] = None


class VlaborProfilesResponse(BaseModel):
    profiles: List[VlaborProfileSummary] = Field(default_factory=list)
    active_profile_name: Optional[str] = None
    total: int = 0


class VlaborActiveProfileResponse(BaseModel):
    profile_name: str
    profile_snapshot: Dict[str, Any] = Field(default_factory=dict)


class VlaborProfileSelectRequest(BaseModel):
    profile_name: str = Field(..., min_length=1)


class ProfileDeviceStatusCamera(BaseModel):
    name: str
    enabled: bool = True
    connected: bool = False
    topics: List[str] = Field(default_factory=list)


class ProfileDeviceStatusArm(BaseModel):
    name: str
    enabled: bool = True
    connected: bool = False


class VlaborActiveProfileStatusResponse(BaseModel):
    profile_name: Optional[str] = None
    profile_snapshot: Dict[str, Any] = Field(default_factory=dict)
    cameras: List[ProfileDeviceStatusCamera] = Field(default_factory=list)
    arms: List[ProfileDeviceStatusArm] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)


class VlaborStatusResponse(BaseModel):
    status: str = Field("unknown", description="running | stopped | unknown")
    service: str = Field("vlabor", description="compose service name")
    state: Optional[str] = None
    status_detail: Optional[str] = None
    running_for: Optional[str] = None
    created_at: Optional[str] = None
    container_id: Optional[str] = None

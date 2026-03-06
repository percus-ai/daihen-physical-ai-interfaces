"""Settings and secret API models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BundledTorchDefaultsModel(BaseModel):
    """Bundled torch default versions."""

    pytorch_version: str = Field("v2.8.0", description="Default PyTorch version")
    torchvision_version: str = Field("v0.23.0", description="Default torchvision version")


class SystemSettingsModel(BaseModel):
    """Machine-scoped settings."""

    bundled_torch: BundledTorchDefaultsModel = Field(default_factory=BundledTorchDefaultsModel)
    updated_at: str | None = Field(None, description="Last update timestamp")


class SystemSettingsUpdateRequest(BaseModel):
    """Machine-scoped settings update request."""

    bundled_torch: BundledTorchDefaultsModel | None = None


class HuggingFaceSecretStatusModel(BaseModel):
    """Masked HF token state for one user."""

    has_token: bool = Field(False, description="Whether HF token is configured")
    token_preview: str | None = Field(None, description="Masked HF token preview")
    updated_at: str | None = Field(None, description="Last update timestamp")


class UserSettingsModel(BaseModel):
    """User-scoped settings."""

    user_id: str = Field(..., description="Current authenticated user id")
    huggingface: HuggingFaceSecretStatusModel = Field(default_factory=HuggingFaceSecretStatusModel)


class UserSettingsUpdateRequest(BaseModel):
    """User-scoped settings update request."""

    huggingface_token: str | None = Field(None, description="New HF token")
    clear_huggingface_token: bool = Field(False, description="Clear stored HF token")

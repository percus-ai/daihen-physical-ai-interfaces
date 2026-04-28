"""Settings and secret API models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FeaturesRepoSettingsModel(BaseModel):
    """Features repository checkout settings."""

    repo_url: str = Field(
        "https://github.com/percus-ai/physical-ai-features.git",
        description="Features repository URL",
    )
    repo_ref: str = Field("main", description="Features repository branch or tag")
    repo_commit: str | None = Field(None, description="Pinned features repository commit hash")


class EnvironmentBuildSettingsModel(BaseModel):
    """Selected environment build config for this machine."""

    env_config_id: str = Field("default", description="Selected env config file id")


class SystemSettingsModel(BaseModel):
    """Machine-scoped settings."""

    features_repo: FeaturesRepoSettingsModel = Field(default_factory=FeaturesRepoSettingsModel)
    environment_build: EnvironmentBuildSettingsModel = Field(default_factory=EnvironmentBuildSettingsModel)
    updated_at: str | None = Field(None, description="Last update timestamp")


class SystemSettingsUpdateRequest(BaseModel):
    """Machine-scoped settings update request."""

    features_repo: FeaturesRepoSettingsModel | None = None
    environment_build: EnvironmentBuildSettingsModel | None = None


class FeaturesRepoCommitSuggestionModel(BaseModel):
    """Commit suggestion for features repo selection."""

    sha: str
    short_sha: str
    message: str


class FeaturesRepoSuggestionsResponse(BaseModel):
    """Autocomplete suggestions for features repo settings."""

    repo_url: str
    repo_ref: str | None = None
    default_branch: str | None = None
    branches: list[str] = Field(default_factory=list)
    commits: list[FeaturesRepoCommitSuggestionModel] = Field(default_factory=list)


class HuggingFaceSecretStatusModel(BaseModel):
    """HF token state for one user."""

    has_token: bool = Field(False, description="Whether HF token is configured")
    token: str | None = Field(None, description="Stored HF token for current authenticated user")
    updated_at: str | None = Field(None, description="Last update timestamp")


class UserProfileSettingsModel(BaseModel):
    """User profile settings."""

    username: str | None = Field(None, description="Username")
    first_name: str | None = Field(None, description="First name")
    last_name: str | None = Field(None, description="Last name")
    updated_at: str | None = Field(None, description="Last update timestamp")


class UserSettingsModel(BaseModel):
    """User-scoped settings."""

    user_id: str = Field(..., description="Current authenticated user id")
    profile: UserProfileSettingsModel = Field(default_factory=UserProfileSettingsModel)
    huggingface: HuggingFaceSecretStatusModel = Field(default_factory=HuggingFaceSecretStatusModel)


class UserSettingsUpdateRequest(BaseModel):
    """User-scoped settings update request."""

    username: str | None = Field(None, description="Username")
    first_name: str | None = Field(None, description="First name")
    last_name: str | None = Field(None, description="Last name")
    huggingface_token: str | None = Field(None, description="New HF token")
    clear_huggingface_token: bool = Field(False, description="Clear stored HF token")

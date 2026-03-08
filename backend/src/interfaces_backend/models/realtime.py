"""Realtime tab-session API models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TabSessionLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Literal["foreground", "background", "closing"] = "foreground"
    reason: str | None = Field(default=None, max_length=128)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized


class TabSessionRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=128)
    url: str = Field(..., min_length=1, max_length=2048)
    params: dict[str, str] = Field(default_factory=dict)

    @field_validator("id", "url")
    @classmethod
    def _normalize_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("params")
    @classmethod
    def _validate_params(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, item in value.items():
            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("route.params key must not be empty")
            normalized_value = item.strip()
            if not normalized_value:
                raise ValueError(f"route.params.{normalized_key} must not be empty")
            normalized[normalized_key] = normalized_value
        return normalized


class _SubscriptionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_id: str = Field(..., min_length=1, max_length=128)

    @field_validator("subscription_id")
    @classmethod
    def _normalize_subscription_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("subscription_id must not be empty")
        return normalized


class ProfilesActiveParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrainingJobRefParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., min_length=1, max_length=256)

    @field_validator("job_id")
    @classmethod
    def _normalize_job_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        return normalized


class TrainingJobMetricsParams(TrainingJobRefParams):
    limit: int | None = Field(default=None, ge=1, le=5000)


class TrainingJobLogsParams(TrainingJobRefParams):
    log_type: Literal["training", "setup"] = "training"
    tail_lines: int | None = Field(default=None, ge=1, le=5000)


class ProfilesActiveSubscription(_SubscriptionBase):
    kind: Literal["profiles.active"]
    params: ProfilesActiveParams = Field(default_factory=ProfilesActiveParams)


class TrainingJobCoreSubscription(_SubscriptionBase):
    kind: Literal["training.job.core"]
    params: TrainingJobRefParams


class TrainingJobProvisionSubscription(_SubscriptionBase):
    kind: Literal["training.job.provision"]
    params: TrainingJobRefParams


class TrainingJobMetricsSubscription(_SubscriptionBase):
    kind: Literal["training.job.metrics"]
    params: TrainingJobMetricsParams


class TrainingJobLogsSubscription(_SubscriptionBase):
    kind: Literal["training.job.logs"]
    params: TrainingJobLogsParams


TabSessionSubscription = Annotated[
    ProfilesActiveSubscription
    | TrainingJobCoreSubscription
    | TrainingJobProvisionSubscription
    | TrainingJobMetricsSubscription
    | TrainingJobLogsSubscription,
    Field(discriminator="kind"),
]


class TabSessionStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(..., ge=1)
    lifecycle: TabSessionLifecycle
    route: TabSessionRoute
    subscriptions: list[TabSessionSubscription] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_subscription_ids(self) -> "TabSessionStateRequest":
        seen: set[str] = set()
        for subscription in self.subscriptions:
            if subscription.subscription_id in seen:
                raise ValueError(f"Duplicate subscription_id: {subscription.subscription_id}")
            seen.add(subscription.subscription_id)
        return self


class TabSessionStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tab_session_id: str
    revision: int
    lifecycle: TabSessionLifecycle
    route: TabSessionRoute
    subscriptions: list[TabSessionSubscription] = Field(default_factory=list)


class TabSessionStatePutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tab_session_id: str
    revision: int
    applied_at: str
    subscription_count: int

"""Realtime track frame models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RealtimeFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(..., min_length=1, max_length=128)
    key: str = Field(..., min_length=1, max_length=256)
    revision: int = Field(..., ge=1)
    detail: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind", "key")
    @classmethod
    def _normalize_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

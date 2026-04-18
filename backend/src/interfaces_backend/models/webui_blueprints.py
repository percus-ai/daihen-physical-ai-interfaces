"""WebUI blueprint API models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SessionKind = Literal["recording", "teleop", "inference"]
ResolveReason = Literal["binding", "last_used", "latest", "default_created"]

_MAX_BLUEPRINT_DEPTH = 48
_DEFAULT_BLUEPRINT_CANVAS_WIDTH = 2050
_DEFAULT_BLUEPRINT_CANVAS_HEIGHT = 900

# バリデーションが複雑なため、blueprintの型はAnyとしている
def _validate_blueprint_node(node: Any, path: str = "root", depth: int = 0) -> None:
    if depth > _MAX_BLUEPRINT_DEPTH:
        raise ValueError(f"{path} exceeds max depth")
    if not isinstance(node, dict):
        raise ValueError(f"{path} must be object")

    node_id = node.get("id")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError(f"{path}.id must be non-empty string")

    node_type = node.get("type")
    if node_type not in {"view", "split", "tabs"}:
        raise ValueError(f"{path}.type must be one of: view, split, tabs")

    if node_type == "view":
        view_type = node.get("viewType")
        if not isinstance(view_type, str) or not view_type.strip():
            raise ValueError(f"{path}.viewType must be non-empty string")
        config = node.get("config")
        if not isinstance(config, dict):
            raise ValueError(f"{path}.config must be object")
        return

    if node_type == "split":
        direction = node.get("direction")
        if direction not in {"row", "column"}:
            raise ValueError(f"{path}.direction must be row or column")
        sizes = node.get("sizes")
        if not isinstance(sizes, list) or len(sizes) != 2:
            raise ValueError(f"{path}.sizes must be 2-length array")
        for index, value in enumerate(sizes):
            if not isinstance(value, (int, float)):
                raise ValueError(f"{path}.sizes[{index}] must be number")
        children = node.get("children")
        if not isinstance(children, list) or len(children) != 2:
            raise ValueError(f"{path}.children must be 2-length array")
        _validate_blueprint_node(children[0], f"{path}.children[0]", depth + 1)
        _validate_blueprint_node(children[1], f"{path}.children[1]", depth + 1)
        return

    active_id = node.get("activeId")
    if not isinstance(active_id, str) or not active_id.strip():
        raise ValueError(f"{path}.activeId must be non-empty string")

    tabs = node.get("tabs")
    if not isinstance(tabs, list) or len(tabs) == 0:
        raise ValueError(f"{path}.tabs must be non-empty array")

    tab_ids: list[str] = []
    for index, tab in enumerate(tabs):
        if not isinstance(tab, dict):
            raise ValueError(f"{path}.tabs[{index}] must be object")
        tab_id = tab.get("id")
        if not isinstance(tab_id, str) or not tab_id.strip():
            raise ValueError(f"{path}.tabs[{index}].id must be non-empty string")
        title = tab.get("title")
        if not isinstance(title, str):
            raise ValueError(f"{path}.tabs[{index}].title must be string")
        if "child" not in tab:
            raise ValueError(f"{path}.tabs[{index}].child is required")
        tab_ids.append(tab_id)
        _validate_blueprint_node(tab.get("child"), f"{path}.tabs[{index}].child", depth + 1)

    if active_id not in tab_ids:
        raise ValueError(f"{path}.activeId must match one of tabs[].id")


def _normalize_canvas_dimension(value: Any, *, field_name: str, fallback: int) -> int:
    try:
        normalized = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    if normalized < 320 or normalized > 4096:
        raise ValueError(f"{field_name} must be between 320 and 4096")
    return normalized


def validate_blueprint_payload(blueprint: dict[str, Any]) -> dict[str, Any]:
    root = blueprint.get("root")
    if isinstance(root, dict):
        _validate_blueprint_node(root)
        return {
            "canvasWidth": _normalize_canvas_dimension(
                blueprint.get("canvasWidth"),
                field_name="canvasWidth",
                fallback=_DEFAULT_BLUEPRINT_CANVAS_WIDTH,
            ),
            "canvasHeight": _normalize_canvas_dimension(
                blueprint.get("canvasHeight"),
                field_name="canvasHeight",
                fallback=_DEFAULT_BLUEPRINT_CANVAS_HEIGHT,
            ),
            "root": root,
        }

    _validate_blueprint_node(blueprint)
    return {
        "canvasWidth": _DEFAULT_BLUEPRINT_CANVAS_WIDTH,
        "canvasHeight": _DEFAULT_BLUEPRINT_CANVAS_HEIGHT,
        "root": blueprint,
    }


def normalize_blueprint_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("name must not be empty")
    if len(normalized) > 128:
        raise ValueError("name must be at most 128 chars")
    return normalized


class WebuiBlueprintSummary(BaseModel):
    id: str
    name: str
    created_at: str | None = None
    updated_at: str | None = None


class WebuiBlueprintDetail(WebuiBlueprintSummary):
    blueprint: dict[str, Any]


class WebuiBlueprintListResponse(BaseModel):
    blueprints: list[WebuiBlueprintSummary] = Field(default_factory=list)
    last_used_blueprint_id: str | None = None


class WebuiBlueprintCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    blueprint: dict[str, Any]

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return normalize_blueprint_name(value)

    @field_validator("blueprint")
    @classmethod
    def _validate_blueprint(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_blueprint_payload(value)


class WebuiBlueprintUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    blueprint: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_blueprint_name(value)

    @field_validator("blueprint")
    @classmethod
    def _validate_blueprint(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return validate_blueprint_payload(value)


class WebuiBlueprintDeleteResponse(BaseModel):
    success: bool
    replacement_blueprint_id: str | None = None
    rebound_session_count: int = 0


class WebuiBlueprintSessionResolveRequest(BaseModel):
    session_kind: SessionKind
    session_id: str = Field(..., min_length=1, max_length=256)

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        return normalized


class WebuiBlueprintSessionBindRequest(WebuiBlueprintSessionResolveRequest):
    blueprint_id: str = Field(..., min_length=1)

    @field_validator("blueprint_id")
    @classmethod
    def _validate_blueprint_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("blueprint_id must not be empty")
        return normalized


class WebuiBlueprintResolveResponse(BaseModel):
    blueprint: WebuiBlueprintDetail
    resolved_by: ResolveReason


class WebuiBlueprintBindResponse(BaseModel):
    blueprint: WebuiBlueprintDetail

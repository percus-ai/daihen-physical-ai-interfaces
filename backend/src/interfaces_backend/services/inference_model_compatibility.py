"""Lightweight model/profile compatibility checks for inference startup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from interfaces_backend.services.vlabor_profiles import (
    build_inference_joint_names,
    extract_camera_specs,
)
from interfaces_backend.services.inference_runtime import _resolve_model_config_path
from percus_ai.inference.camera_maps import get_camera_key_map


class InferenceModelCompatibilityError(ValueError):
    """Raised when a model cannot run with the active profile."""


@dataclass(frozen=True)
class InferenceModelProfileCompatibility:
    policy_type: str
    config_path: Path
    joint_names: list[str]
    state_dim: int | None
    action_dim: int | None
    model_image_keys: list[str]
    resolved_camera_keys: list[str]


def _load_model_config(model_dir: Path) -> tuple[Path, dict[str, Any]]:
    config_path = _resolve_model_config_path(model_dir)
    if config_path is None:
        raise InferenceModelCompatibilityError(f"config.json not found under model: {model_dir.name}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InferenceModelCompatibilityError(
            f"failed to read model config.json for '{model_dir.name}': {exc}"
        ) from exc
    if not isinstance(config, dict):
        raise InferenceModelCompatibilityError(
            f"invalid model config.json for '{model_dir.name}': expected object"
        )
    return config_path, config


def _read_shape_dim(features: Any, feature_key: str) -> int | None:
    if not isinstance(features, dict):
        return None
    feature = features.get(feature_key)
    if not isinstance(feature, dict):
        return None
    shape = feature.get("shape")
    if not isinstance(shape, (list, tuple)) or not shape:
        return None
    try:
        return int(shape[0])
    except (TypeError, ValueError):
        return None


def _collect_model_image_keys(input_features: Any) -> list[str]:
    if not isinstance(input_features, dict):
        return []
    keys = []
    for key in input_features:
        if not isinstance(key, str) or not key.startswith("observation.images."):
            continue
        keys.append(key.replace("observation.images.", "", 1))
    return sorted(keys)


def _collect_resolved_profile_camera_keys(
    *,
    profile_snapshot: dict[str, Any],
    model_image_keys: list[str],
    policy_type: str,
) -> list[str]:
    camera_key_map = get_camera_key_map(policy_type)
    resolved_keys: list[str] = []
    seen: set[str] = set()
    for spec in extract_camera_specs(profile_snapshot):
        if not bool(spec.get("enabled", True)):
            continue
        runtime_key = str(spec.get("name") or "").strip()
        if not runtime_key:
            continue
        if runtime_key in model_image_keys:
            resolved_key = runtime_key
        else:
            resolved_key = camera_key_map.get(runtime_key, runtime_key)
        if resolved_key in seen:
            continue
        seen.add(resolved_key)
        resolved_keys.append(resolved_key)
    return sorted(resolved_keys)


def _canonical_camera_labels(policy_type: str, model_image_keys: list[str]) -> list[str]:
    inverse_map = {dst: src for src, dst in get_camera_key_map(policy_type).items()}
    return [inverse_map.get(key, key) for key in model_image_keys]


def validate_inference_model_profile_compatibility(
    *,
    model_dir: Path,
    profile_snapshot: dict[str, Any],
) -> InferenceModelProfileCompatibility:
    config_path, config = _load_model_config(model_dir)

    policy_type = str(config.get("type") or "").strip().lower()
    if not policy_type:
        raise InferenceModelCompatibilityError(
            f"model config is missing type: {config_path}"
        )

    input_features = config.get("input_features", {})
    output_features = config.get("output_features", {})
    state_dim = _read_shape_dim(input_features, "observation.state")
    action_dim = _read_shape_dim(output_features, "action")
    model_image_keys = _collect_model_image_keys(input_features)
    joint_names = build_inference_joint_names(profile_snapshot)

    if state_dim is None:
        raise InferenceModelCompatibilityError(
            f"model config is missing observation.state.shape[0]: {config_path}"
        )
    if action_dim is None:
        raise InferenceModelCompatibilityError(
            f"model config is missing output_features.action.shape[0]: {config_path}"
        )

    joint_summary = ", ".join(joint_names) if joint_names else "(none)"
    if state_dim != len(joint_names):
        raise InferenceModelCompatibilityError(
            f"model expects observation.state={state_dim} but active profile resolves "
            f"{len(joint_names)} joints ({joint_summary})"
        )
    if action_dim != len(joint_names):
        raise InferenceModelCompatibilityError(
            f"model expects action={action_dim} but active profile resolves "
            f"{len(joint_names)} joints ({joint_summary})"
        )

    resolved_camera_keys = _collect_resolved_profile_camera_keys(
        profile_snapshot=profile_snapshot,
        model_image_keys=model_image_keys,
        policy_type=policy_type,
    )
    missing_camera_keys = [key for key in model_image_keys if key not in resolved_camera_keys]
    if missing_camera_keys:
        required_cameras = ", ".join(_canonical_camera_labels(policy_type, model_image_keys))
        resolved_cameras = ", ".join(_canonical_camera_labels(policy_type, resolved_camera_keys))
        raise InferenceModelCompatibilityError(
            "model requires cameras "
            f"[{required_cameras}] but active profile resolves [{resolved_cameras}]"
        )

    return InferenceModelProfileCompatibility(
        policy_type=policy_type,
        config_path=config_path,
        joint_names=joint_names,
        state_dim=state_dim,
        action_dim=action_dim,
        model_image_keys=model_image_keys,
        resolved_camera_keys=resolved_camera_keys,
    )

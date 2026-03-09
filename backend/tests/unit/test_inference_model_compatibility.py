from __future__ import annotations

import json

import pytest

from interfaces_backend.services.inference_model_compatibility import (
    InferenceModelCompatibilityError,
    validate_inference_model_profile_compatibility,
)


def _build_profile_snapshot(*, camera_specs: list[dict[str, object]]) -> dict[str, object]:
    joints = ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "gripper"]
    return {
        "profile": {
            "lerobot": {
                "left_arm": {
                    "namespace": "left_arm",
                    "joints": joints,
                },
                "cameras": camera_specs,
            }
        }
    }


def _write_model_config(
    tmp_path,
    *,
    policy_type: str,
    state_dim: int,
    action_dim: int,
    image_keys: list[str],
):
    model_dir = tmp_path / f"model-{policy_type}"
    model_dir.mkdir()
    input_features = {"observation.state": {"shape": [state_dim]}}
    for image_key in image_keys:
        input_features[f"observation.images.{image_key}"] = {"shape": [3, 224, 224]}
    config = {
        "type": policy_type,
        "input_features": input_features,
        "output_features": {"action": {"shape": [action_dim]}},
    }
    (model_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return model_dir


def test_validate_inference_model_profile_compatibility_blocks_state_dim_mismatch(tmp_path):
    model_dir = _write_model_config(
        tmp_path,
        policy_type="act",
        state_dim=6,
        action_dim=6,
        image_keys=[],
    )
    profile_snapshot = _build_profile_snapshot(
        camera_specs=[{"name": "top_camera", "source": "top_camera", "topic": "/top"}]
    )

    with pytest.raises(InferenceModelCompatibilityError) as exc_info:
        validate_inference_model_profile_compatibility(
            model_dir=model_dir,
            profile_snapshot=profile_snapshot,
        )

    assert "model expects observation.state=6 but active profile resolves 7 joints" in str(
        exc_info.value
    )


def test_validate_inference_model_profile_compatibility_allows_extra_cameras(tmp_path):
    model_dir = _write_model_config(
        tmp_path,
        policy_type="pi05",
        state_dim=7,
        action_dim=7,
        image_keys=["cam_high", "cam_left_wrist"],
    )
    profile_snapshot = _build_profile_snapshot(
        camera_specs=[
            {"name": "top_camera", "source": "top_camera", "topic": "/top"},
            {"name": "arm_camera_1", "source": "d405_color", "topic": "/wrist"},
            {"name": "side_camera", "source": "side_camera", "topic": "/side"},
        ]
    )

    result = validate_inference_model_profile_compatibility(
        model_dir=model_dir,
        profile_snapshot=profile_snapshot,
    )

    assert result.policy_type == "pi05"
    assert result.state_dim == 7
    assert result.action_dim == 7
    assert result.model_image_keys == ["cam_high", "cam_left_wrist"]


def test_validate_inference_model_profile_compatibility_blocks_missing_required_camera(tmp_path):
    model_dir = _write_model_config(
        tmp_path,
        policy_type="act",
        state_dim=7,
        action_dim=7,
        image_keys=["top_camera", "arm_camera_1"],
    )
    profile_snapshot = _build_profile_snapshot(
        camera_specs=[
            {"name": "top_camera", "source": "top_camera", "topic": "/top"},
            {"name": "d405_color", "source": "d405_color", "topic": "/wrist"},
        ]
    )

    with pytest.raises(InferenceModelCompatibilityError) as exc_info:
        validate_inference_model_profile_compatibility(
            model_dir=model_dir,
            profile_snapshot=profile_snapshot,
        )

    assert (
        str(exc_info.value)
        == "model requires cameras [arm_camera_1, top_camera] "
        "but active profile resolves [d405_color, top_camera]"
    )


def test_validate_inference_model_profile_compatibility_uses_runtime_config_resolution(tmp_path):
    model_dir = tmp_path / "model-act"
    model_dir.mkdir()
    pretrained_dir = model_dir / "pretrained_model"
    pretrained_dir.mkdir()

    root_config = {
        "type": "act",
        "input_features": {"observation.state": {"shape": [7]}},
        "output_features": {"action": {"shape": [7]}},
    }
    nested_config = {
        "type": "act",
        "input_features": {"observation.state": {"shape": [6]}},
        "output_features": {"action": {"shape": [6]}},
    }
    (model_dir / "config.json").write_text(json.dumps(root_config), encoding="utf-8")
    (pretrained_dir / "config.json").write_text(json.dumps(nested_config), encoding="utf-8")

    result = validate_inference_model_profile_compatibility(
        model_dir=model_dir,
        profile_snapshot=_build_profile_snapshot(camera_specs=[]),
    )

    assert result.config_path == model_dir / "config.json"
    assert result.state_dim == 7
    assert result.action_dim == 7

from pathlib import Path

import pytest
import yaml

from interfaces_backend.services.vlabor_profiles import (
    build_inference_bridge_config,
    extract_camera_specs,
    extract_arm_namespaces,
    extract_recorder_arm_streams,
)


def test_extract_camera_specs_uses_lerobot_cameras_only() -> None:
    snapshot = {
        "profile": {
            "actions": [
                {
                    "type": "include",
                    "package": "fv_camera",
                    "args": {"node_name": "fallback_camera"},
                    "enabled": True,
                }
            ]
        }
    }

    assert extract_camera_specs(snapshot) == []


def test_extract_camera_specs_resolves_lerobot_camera_fields() -> None:
    snapshot = {
        "profile": {
            "variables": {
                "camera_topic": "/top_camera/image_raw/compressed",
                "camera_enabled": "true",
            },
            "lerobot": {
                "cameras": [
                    {
                        "name": "cam_top",
                        "source": "top_camera",
                        "topic": "${camera_topic}",
                        "enabled": "${camera_enabled}",
                    },
                    {
                        "name": "cam_disabled",
                        "source": "depth_camera",
                        "topic": "/depth_camera/hha/compressed",
                        "enabled": False,
                    },
                ]
            },
        }
    }

    assert extract_camera_specs(snapshot) == [
        {
            "name": "cam_top",
            "source": "top_camera",
            "topic": "/top_camera/image_raw/compressed",
            "enabled": True,
            "package": "lerobot",
        },
        {
            "name": "cam_disabled",
            "source": "depth_camera",
            "topic": "/depth_camera/hha/compressed",
            "enabled": False,
            "package": "lerobot",
        },
    ]


def test_extract_recorder_arm_streams_resolves_from_snapshot() -> None:
    snapshot = {
        "profile": {
            "teleop": {"follower_arms": [{"namespace": "follower_left"}, {"namespace": "follower_right"}]},
            "lerobot": {
                "follower_left": {
                    "namespace": "follower_left",
                    "topic": "/follower_left/joint_states_single",
                    "action_topic": "/follower_left/joint_ctrl_single",
                    "joints": ["joint1", "joint2", "joint3"],
                },
                "follower_right": {
                    "namespace": "follower_right",
                    "topic": "/follower_right/joint_states_single",
                    "action_topic": "/follower_right/joint_ctrl_single",
                    "joints": ["joint1", "joint2", "joint3"],
                },
            },
        }
    }

    assert extract_recorder_arm_streams(
        snapshot,
        arm_namespaces=["follower_left", "follower_right"],
    ) == [
        {
            "namespace": "follower_left",
            "state_topic": "/follower_left/joint_states_single",
            "action_topic": "/follower_left/joint_ctrl_single",
            "joint_names": ["joint1", "joint2", "joint3"],
        },
        {
            "namespace": "follower_right",
            "state_topic": "/follower_right/joint_states_single",
            "action_topic": "/follower_right/joint_ctrl_single",
            "joint_names": ["joint1", "joint2", "joint3"],
        },
    ]


def test_extract_recorder_arm_streams_returns_empty_when_action_topic_missing() -> None:
    snapshot = {
        "profile": {
            "teleop": {"follower_arms": [{"namespace": "follower_left"}, {"namespace": "follower_right"}]},
            "lerobot": {
                "follower_left": {
                    "namespace": "follower_left",
                    "topic": "/follower_left/joint_states_single",
                    "action_topic": "/follower_left/joint_ctrl_single",
                    "joints": ["joint1", "joint2", "joint3"],
                },
                "follower_right": {
                    "namespace": "follower_right",
                    "topic": "/follower_right/joint_states_single",
                    "joints": ["joint1", "joint2", "joint3"],
                },
            },
        }
    }

    assert extract_recorder_arm_streams(
        snapshot,
        arm_namespaces=["follower_left", "follower_right"],
    ) == []


def test_extract_recorder_arm_streams_returns_empty_when_joints_missing() -> None:
    snapshot = {
        "profile": {
            "teleop": {"follower_arms": [{"namespace": "follower_left"}]},
            "lerobot": {
                "follower_left": {
                    "namespace": "follower_left",
                    "topic": "/follower_left/joint_states_single",
                    "action_topic": "/follower_left/joint_ctrl_single",
                },
            },
        }
    }

    assert extract_recorder_arm_streams(snapshot, arm_namespaces=["follower_left"]) == []


def test_extract_recorder_arm_streams_returns_empty_when_topic_not_absolute() -> None:
    snapshot = {
        "profile": {
            "teleop": {"follower_arms": [{"namespace": "follower_left"}]},
            "lerobot": {
                "follower_left": {
                    "namespace": "follower_left",
                    "topic": "follower_left/joint_states_single",
                    "action_topic": "/follower_left/joint_ctrl_single",
                    "joints": ["joint1", "joint2", "joint3"],
                },
            },
        }
    }
    assert extract_recorder_arm_streams(snapshot, arm_namespaces=["follower_left"]) == []


def test_extract_recorder_arm_streams_returns_empty_when_namespace_is_duplicated() -> None:
    snapshot = {
        "profile": {
            "teleop": {"follower_arms": [{"namespace": "follower_left"}]},
            "lerobot": {
                "follower_left_a": {
                    "namespace": "follower_left",
                    "topic": "/follower_left/joint_states_single",
                    "action_topic": "/follower_left/joint_ctrl_single",
                    "joints": ["joint1", "joint2", "joint3"],
                },
                "follower_left_b": {
                    "namespace": "follower_left",
                    "topic": "/follower_left/joint_states_single",
                    "action_topic": "/follower_left/joint_ctrl_single",
                    "joints": ["joint1", "joint2", "joint3"],
                },
            },
        }
    }
    assert extract_recorder_arm_streams(snapshot, arm_namespaces=["follower_left"]) == []


def test_build_inference_bridge_config_uses_profile_resolution() -> None:
    snapshot = {
        "profile": {
            "teleop": {"follower_arms": [{"namespace": "follower_left"}, {"namespace": "follower_right"}]},
            "lerobot": {
                "follower_left": {
                    "namespace": "follower_left",
                    "topic": "/follower_left/joint_states_single",
                    "action_topic": "/follower_left/joint_ctrl_single",
                    "joints": ["joint1", "joint2", "joint3"],
                },
                "follower_right": {
                    "namespace": "follower_right",
                    "topic": "/follower_right/joint_states_single",
                    "action_topic": "/follower_right/joint_ctrl_single",
                    "joints": ["joint1", "joint2", "joint3"],
                },
                "cameras": [
                    {
                        "name": "cam_top",
                        "source": "top_camera",
                        "topic": "/top_camera/image_raw/compressed",
                        "enabled": True,
                    },
                    {
                        "name": "cam_side",
                        "source": "side_camera",
                        "topic": "/side_camera/image_raw/compressed",
                        "enabled": True,
                    },
                ],
            },
        }
    }

    assert build_inference_bridge_config(snapshot) == {
        "arm_streams": [
            {
                "namespace": "follower_left",
                "state_topic": "/follower_left/joint_states_single",
                "action_topic": "/follower_left/joint_ctrl_single",
                "joint_names": ["joint1", "joint2", "joint3"],
            },
            {
                "namespace": "follower_right",
                "state_topic": "/follower_right/joint_states_single",
                "action_topic": "/follower_right/joint_ctrl_single",
                "joint_names": ["joint1", "joint2", "joint3"],
            },
        ],
        "camera_streams": [
            {"name": "top_camera", "topic": "/top_camera/image_raw/compressed"},
            {"name": "side_camera", "topic": "/side_camera/image_raw/compressed"},
        ],
    }


def _profiles_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "ros2_ws" / "src" / "vlabor_ros2" / "vlabor_launch" / "config" / "profiles"


def _load_profile_snapshot(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert isinstance(payload, dict)
    profile = payload.get("profile")
    assert isinstance(profile, dict)
    return {"profile": profile}


@pytest.mark.parametrize(
    "profile_name",
    [
        "so101_single_teleop",
        "so101_dual_teleop",
        "so101_vr_dual_teleop",
        "piper_single_teleop",
        "piper_vr_single_teleop",
        "piper_vr_dual_teleop",
    ],
)
def test_extract_recorder_arm_streams_from_real_profile_yaml(profile_name: str) -> None:
    profile_path = _profiles_dir() / f"{profile_name}.yaml"
    assert profile_path.is_file(), f"missing profile yaml: {profile_path}"

    snapshot = _load_profile_snapshot(profile_path)
    arm_namespaces = extract_arm_namespaces(snapshot)
    streams = extract_recorder_arm_streams(snapshot, arm_namespaces=arm_namespaces)

    assert streams, f"no arm streams resolved for {profile_name}"
    for stream in streams:
        assert stream["namespace"]
        assert stream["state_topic"].startswith("/")
        assert stream["action_topic"].startswith("/")
        assert isinstance(stream.get("joint_names"), list)
        assert len(stream["joint_names"]) > 0

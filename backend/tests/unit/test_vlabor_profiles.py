from interfaces_backend.services.vlabor_profiles import (
    build_inference_bridge_config,
    extract_camera_specs,
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
                },
                "follower_right": {
                    "namespace": "follower_right",
                    "topic": "/follower_right/joint_states_single",
                    "action_topic": "/follower_right/joint_ctrl_single",
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
        },
        {
            "namespace": "follower_right",
            "state_topic": "/follower_right/joint_states_single",
            "action_topic": "/follower_right/joint_ctrl_single",
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
                },
                "follower_right": {
                    "namespace": "follower_right",
                    "topic": "/follower_right/joint_states_single",
                },
            },
        }
    }

    assert extract_recorder_arm_streams(
        snapshot,
        arm_namespaces=["follower_left", "follower_right"],
    ) == []


def test_extract_recorder_arm_streams_returns_empty_when_topic_not_absolute() -> None:
    snapshot = {
        "profile": {
            "teleop": {"follower_arms": [{"namespace": "follower_left"}]},
            "lerobot": {
                "follower_left": {
                    "namespace": "follower_left",
                    "topic": "follower_left/joint_states_single",
                    "action_topic": "/follower_left/joint_ctrl_single",
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
                },
                "follower_left_b": {
                    "namespace": "follower_left",
                    "topic": "/follower_left/joint_states_single",
                    "action_topic": "/follower_left/joint_ctrl_single",
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
                },
                "follower_right": {
                    "namespace": "follower_right",
                    "topic": "/follower_right/joint_states_single",
                    "action_topic": "/follower_right/joint_ctrl_single",
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
            },
            {
                "namespace": "follower_right",
                "state_topic": "/follower_right/joint_states_single",
                "action_topic": "/follower_right/joint_ctrl_single",
            },
        ],
        "camera_streams": [
            {"name": "top_camera", "topic": "/top_camera/image_raw/compressed"},
            {"name": "side_camera", "topic": "/side_camera/image_raw/compressed"},
        ],
    }

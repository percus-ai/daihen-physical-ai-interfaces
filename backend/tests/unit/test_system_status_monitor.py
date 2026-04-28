from interfaces_backend.services.system_status_monitor import SystemStatusMonitor
from interfaces_backend.services.vlabor_profiles import build_profile_health_contract


def _contract_snapshot() -> dict:
    return {
        "name": "test_profile",
        "profile": {
            "teleop": {"follower_arms": [{"namespace": "follower_arm"}]},
            "lerobot": {
                "follower_arm": {
                    "namespace": "follower_arm",
                    "topic": "/follower_arm/joint_states_single",
                    "action_topic": "/follower_arm/joint_ctrl_single",
                    "joints": ["joint1", "joint2"],
                },
                "cameras": [
                    {
                        "name": "cam_top",
                        "source": "top_camera",
                        "topic": "/top_camera/image_raw/compressed",
                    }
                ],
            },
            "actions": [
                {
                    "type": "node",
                    "package": "unity_robot_control",
                    "name": "so101_control_node",
                    "namespace": "follower_arm",
                },
                {
                    "type": "include",
                    "package": "fv_camera",
                    "args": {"node_name": "top_camera"},
                },
            ],
        },
    }


def test_evaluate_ros2_health_marks_missing_required_inputs_as_error() -> None:
    monitor = SystemStatusMonitor()
    contract = build_profile_health_contract(_contract_snapshot())

    graph = {
        "nodes": ["/follower_arm/so101_control_node"],
        "all_topics": ["/follower_arm/joint_states_single"],
        "topics": {
            "/follower_arm/joint_states_single": {
                "exists": True,
                "publisher_nodes": ["/follower_arm/so101_control_node"],
                "publisher_count": 1,
            },
            "/top_camera/image_raw/compressed": {
                "exists": False,
                "publisher_nodes": [],
                "publisher_count": 0,
            },
        },
    }

    snapshot, state = monitor._evaluate_ros2_health(contract, graph)

    assert snapshot.level == "error"
    assert snapshot.required_topics_ok is False
    assert snapshot.missing_topics == ["/top_camera/image_raw/compressed"]
    assert state.cameras_ready is False
    assert state.robot_ready is True


def test_evaluate_ros2_health_marks_required_inputs_as_healthy() -> None:
    monitor = SystemStatusMonitor()
    contract = build_profile_health_contract(_contract_snapshot())

    graph = {
        "nodes": ["/follower_arm/so101_control_node", "/top_camera"],
        "all_topics": [
            "/follower_arm/joint_states_single",
            "/top_camera/image_raw/compressed",
        ],
        "topics": {
            "/follower_arm/joint_states_single": {
                "exists": True,
                "publisher_nodes": ["/follower_arm/so101_control_node"],
                "publisher_count": 1,
            },
            "/top_camera/image_raw/compressed": {
                "exists": True,
                "publisher_nodes": ["/top_camera"],
                "publisher_count": 1,
            },
        },
    }

    snapshot, state = monitor._evaluate_ros2_health(contract, graph)

    assert snapshot.level == "healthy"
    assert snapshot.required_topics_ok is True
    assert snapshot.required_nodes_ok is True
    assert state.cameras_ready is True
    assert state.robot_ready is True
    assert snapshot.last_error is None


def test_evaluate_recorder_health_keeps_idle_storage_unknown_healthy() -> None:
    monitor = SystemStatusMonitor()

    snapshot = monitor._evaluate_recorder_health(
        recorder_status={
            "state": "idle",
            "dataset_id": "",
            "write_ok": None,
            "disk_ok": None,
        },
        ros2_state=monitor._ros2_contract_state.__class__(
            cameras_ready=True,
            robot_ready=True,
        ),
        active_profile_name="so101_single_teleop",
    )

    assert snapshot.level == "healthy"
    assert snapshot.dependencies.storage_ready is None
    assert snapshot.last_error is None


def test_evaluate_recorder_health_keeps_recording_storage_unknown_healthy() -> None:
    monitor = SystemStatusMonitor()

    snapshot = monitor._evaluate_recorder_health(
        recorder_status={
            "state": "recording",
            "dataset_id": "dataset-1",
            "write_ok": None,
            "disk_ok": None,
            "last_frame_at": "2026-03-06T00:00:00Z",
        },
        ros2_state=monitor._ros2_contract_state.__class__(
            cameras_ready=True,
            robot_ready=True,
        ),
        active_profile_name="so101_single_teleop",
    )

    assert snapshot.level == "healthy"
    assert snapshot.dependencies.storage_ready is None
    assert snapshot.last_error is None

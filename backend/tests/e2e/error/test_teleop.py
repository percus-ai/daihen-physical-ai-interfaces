from importlib.util import find_spec

import pytest


def test_local_teleop_missing_session(client):
    resp = client.get("/api/teleop/local/sessions")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    resp = client.get("/api/teleop/local/status/missing")
    assert resp.status_code == 404

    resp = client.post("/api/teleop/local/missing/run")
    assert resp.status_code == 404

    resp = client.post("/api/teleop/local/stop", json={"session_id": "missing"})
    assert resp.status_code == 404


def test_local_teleop_start_without_lerobot(client):
    if find_spec("lerobot") is not None:
        pytest.skip("LeRobot available; local teleop requires hardware.")

    payload = {
        "leader_port": "dummy",
        "follower_port": "dummy",
        "mode": "simple",
        "robot_preset": "so101",
        "fps": 60,
    }
    resp = client.post("/api/teleop/local/start", json=payload)
    assert resp.status_code == 500

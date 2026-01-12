def test_remote_teleop_sessions(client):
    leader_payload = {
        "host": "0.0.0.0",
        "port": 9000,
        "leader_port": "dummy",
        "camera_id": None,
    }
    resp = client.post("/api/teleop/remote/leader/start", json=leader_payload)
    assert resp.status_code == 200
    leader_session = resp.json()["session"]
    leader_id = leader_session["session_id"]

    resp = client.get(f"/api/teleop/remote/leader/status/{leader_id}")
    assert resp.status_code == 200

    follower_payload = {
        "leader_url": leader_session["url"],
        "follower_port": "dummy",
    }
    resp = client.post("/api/teleop/remote/follower/start", json=follower_payload)
    assert resp.status_code == 200
    follower_id = resp.json()["session"]["session_id"]

    resp = client.get(f"/api/teleop/remote/follower/status/{follower_id}")
    assert resp.status_code == 200

    resp = client.get("/api/teleop/remote/sessions")
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["leaders"]) == 1
    assert len(payload["followers"]) == 1

    resp = client.post(f"/api/teleop/remote/leader/{leader_id}/stop")
    assert resp.status_code == 200

    resp = client.post(f"/api/teleop/remote/follower/{follower_id}/stop")
    assert resp.status_code == 200

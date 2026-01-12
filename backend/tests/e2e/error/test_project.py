def test_project_validate_devices_missing(client):
    payload = {
        "display_name": "Demo Project",
        "description": "E2E test",
        "episode_time_s": 20,
        "reset_time_s": 10,
        "robot_type": "so101",
    }
    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 200
    project_name = resp.json()["name"]

    resp = client.get(f"/api/projects/{project_name}/validate-devices")
    assert resp.status_code == 404

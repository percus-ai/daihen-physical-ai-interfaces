def test_project_lifecycle(client):
    payload = {
        "display_name": "Demo Project",
        "description": "E2E test",
        "episode_time_s": 20,
        "reset_time_s": 10,
        "robot_type": "so101",
    }
    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 200
    project = resp.json()
    project_name = project["name"]

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert project_name in resp.json()["projects"]

    resp = client.get(f"/api/projects/{project_name}")
    assert resp.status_code == 200
    assert resp.json()["name"] == project_name

    resp = client.get(f"/api/projects/{project_name}/stats")
    assert resp.status_code == 200
    assert resp.json()["project_name"] == project_name

    resp = client.get(f"/api/projects/{project_name}/validate")
    assert resp.status_code == 200

    resp = client.delete(f"/api/projects/{project_name}")
    assert resp.status_code == 200


def test_project_debug_paths(client):
    resp = client.get("/api/projects/debug-paths")
    assert resp.status_code == 200
    payload = resp.json()
    assert "projects_dir" in payload

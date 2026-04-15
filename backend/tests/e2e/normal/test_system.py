def test_system_health(client):
    resp = client.get("/api/system/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert "status" in payload
    assert "services" in payload
    assert "uptime_seconds" in payload


def test_system_resources(client):
    resp = client.get("/api/system/resources")
    assert resp.status_code == 200
    payload = resp.json()
    assert "resources" in payload
    assert "timestamp" in payload


def test_system_logs(client):
    resp = client.get("/api/system/logs")
    assert resp.status_code == 200

    resp = client.post("/api/system/logs/clear")
    assert resp.status_code == 200
    assert "message" in resp.json()


def test_system_info(client):
    resp = client.get("/api/system/info")
    assert resp.status_code == 200
    payload = resp.json()
    assert "info" in payload


def test_system_settings(client):
    resp = client.get("/api/system/settings")
    assert resp.status_code == 200
    assert resp.json()["bundled_torch"]["pytorch_version"] == "v2.10.0"
    assert resp.json()["environment_build"]["env_config_id"] == "default"

    resp = client.put(
        "/api/system/settings",
        json={
            "bundled_torch": {
                "pytorch_version": "v2.9.0",
                "torchvision_version": "v0.24.0",
            },
            "environment_build": {
                "env_config_id": "default",
            },
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["bundled_torch"]["pytorch_version"] == "v2.9.0"
    assert payload["bundled_torch"]["torchvision_version"] == "v0.24.0"
    assert payload["environment_build"]["env_config_id"] == "default"


def test_system_gpu(client):
    resp = client.get("/api/system/gpu")
    assert resp.status_code == 200
    payload = resp.json()
    assert "available" in payload
    assert "gpus" in payload

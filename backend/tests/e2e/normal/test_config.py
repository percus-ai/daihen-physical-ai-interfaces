def test_config(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    payload = resp.json()
    assert "config" in payload
    assert "data_dir" in payload["config"]


def test_environments(client):
    resp = client.get("/api/config/environments")
    assert resp.status_code == 200
    payload = resp.json()
    assert "environments" in payload
    assert "available_policies" in payload

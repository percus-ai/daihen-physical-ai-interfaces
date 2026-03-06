def test_bundled_torch_status(client):
    resp = client.get("/api/system/bundled-torch/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert "platform" in payload
    assert "install" in payload
    assert "state" in payload

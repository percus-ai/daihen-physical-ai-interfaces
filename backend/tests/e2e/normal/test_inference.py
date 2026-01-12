from pathlib import Path

from tests.e2e.helpers import write_inference_model_config


def test_inference_models(client):
    workspace = Path.cwd()
    write_inference_model_config(workspace, "demo_model")

    resp = client.get("/api/inference/models")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["models"][0]["model_id"] == "demo_model"


def test_inference_device_compatibility(client):
    resp = client.get("/api/inference/device-compatibility")
    assert resp.status_code == 200
    payload = resp.json()
    assert "devices" in payload

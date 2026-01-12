def test_inference_run_missing_model(client):
    payload = {
        "model_id": "missing",
        "project": "demo_project",
        "episodes": 1,
        "robot_type": "so101",
        "device": None,
    }
    resp = client.post("/api/inference/run", json=payload)
    assert resp.status_code == 404

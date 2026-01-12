def test_inference_ws_missing_model(client):
    with client.websocket_connect("/api/inference/ws/run") as ws:
        ws.send_json(
            {
                "model_id": "missing",
                "project": "demo_project",
                "episodes": 1,
                "robot_type": "so101",
                "device": None,
            }
        )
        message = ws.receive_json()
        assert message["type"] == "error"

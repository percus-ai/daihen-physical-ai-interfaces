def test_recording_ws_missing_project(client):
    with client.websocket_connect("/api/recording/ws/record") as ws:
        ws.send_json({"num_episodes": 1})
        message = ws.receive_json()
        assert message["type"] == "error"

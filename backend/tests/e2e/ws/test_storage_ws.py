def test_storage_ws_errors(client):
    with client.websocket_connect("/api/storage/ws/migration") as ws:
        ws.send_json({"action": "invalid"})
        message = ws.receive_json()
        assert message["type"] == "error"

    with client.websocket_connect("/api/storage/ws/sync") as ws:
        ws.send_json({"action": "invalid"})
        message = ws.receive_json()
        assert message["type"] == "error"

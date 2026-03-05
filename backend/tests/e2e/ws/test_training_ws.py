def test_training_ws_missing_job(client):
    with client.websocket_connect("/api/training/ws/jobs/missing/logs") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"

    with client.websocket_connect("/api/training/ws/jobs/missing/session") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"


def test_training_ws_gpu_availability_missing_creds(client, monkeypatch):
    monkeypatch.delenv("DATACRUNCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("DATACRUNCH_CLIENT_SECRET", raising=False)
    with client.websocket_connect("/api/training/ws/gpu-availability?provider=verda") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"


def test_training_ws_verda_storage_invalid_action(client):
    with client.websocket_connect("/api/training/ws/verda/storage") as ws:
        ws.send_json({"action": "invalid", "volume_ids": []})
        message = ws.receive_json()
        assert message["type"] == "error"


def test_training_ws_logs_requires_auth_session(client, monkeypatch):
    import interfaces_backend.api.training as training_api

    monkeypatch.setattr(training_api, "_resolve_websocket_supabase_session", lambda _ws: None)

    with client.websocket_connect("/api/training/ws/jobs/job-1/logs") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"
        assert "認証情報がありません" in message["error"]


def test_training_ws_logs_sets_request_session_for_load_job(client, monkeypatch):
    import interfaces_backend.api.training as training_api

    captured = {}

    async def _fake_load_job(job_id: str, include_deleted: bool = False):
        del include_deleted
        captured["job_id"] = job_id
        captured["session"] = training_api.get_supabase_session()
        return {"job_id": job_id, "ip": None}

    monkeypatch.setattr(
        training_api,
        "_resolve_websocket_supabase_session",
        lambda _ws: {"user_id": "user-1", "access_token": "token-1"},
    )
    monkeypatch.setattr(training_api, "_load_job", _fake_load_job)

    with client.websocket_connect("/api/training/ws/jobs/job-1/logs") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"
        assert message["error"] == "Job has no IP address"

    assert captured["job_id"] == "job-1"
    assert captured["session"]["user_id"] == "user-1"

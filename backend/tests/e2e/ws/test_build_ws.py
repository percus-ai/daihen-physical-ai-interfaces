import json
import os

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.api.stream as stream_api


def test_bundled_torch_sse_status(client, monkeypatch):
    monkeypatch.setattr(stream_api, "_require_user_id", lambda: "user-1")

    with client.stream("GET", "/api/stream/system/bundled-torch") as response:
        assert response.status_code == 200
        assert response.headers.get("content-type", "").startswith("text/event-stream")
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            assert "platform" in payload
            assert "install" in payload
            assert "state" in payload
            break

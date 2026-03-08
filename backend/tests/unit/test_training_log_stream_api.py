from __future__ import annotations

import asyncio
import json

import interfaces_backend.api.stream as stream_api


class _FakeRequest:
    def __init__(self) -> None:
        self._disconnected = False

    async def is_disconnected(self) -> bool:
        return self._disconnected


class _FakeChannel:
    def __init__(self) -> None:
        self._reads = 0

    def exec_command(self, _command: str) -> None:
        return None

    def setblocking(self, _flag: int) -> None:
        return None

    def recv_ready(self) -> bool:
        return self._reads == 0

    def recv(self, _size: int) -> bytes:
        self._reads += 1
        return b"line-1\n"

    def exit_status_ready(self) -> bool:
        return self._reads > 0

    def close(self) -> None:
        return None


class _FakeTransport:
    def __init__(self, channel: _FakeChannel) -> None:
        self._channel = channel

    def open_session(self) -> _FakeChannel:
        return self._channel


class _FakeClient:
    def __init__(self, channel: _FakeChannel) -> None:
        self._channel = channel

    def get_transport(self) -> _FakeTransport:
        return _FakeTransport(self._channel)


class _FakeSshConnection:
    def __init__(self, channel: _FakeChannel) -> None:
        self.client = _FakeClient(channel)
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True


def _decode_sse(chunk: bytes | str) -> dict:
    text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
    assert text.startswith("data: ")
    payload = text.removeprefix("data: ").strip()
    return json.loads(payload)


def test_training_job_logs_stream_emits_connected_log_and_terminal_status(monkeypatch):
    fake_channel = _FakeChannel()
    fake_conn = _FakeSshConnection(fake_channel)

    async def fake_load_job(job_id: str, include_deleted: bool = False):
        assert job_id == "job-1"
        assert include_deleted is False
        return {
            "job_id": job_id,
            "ip": "10.0.0.1",
            "remote_base_dir": "/root/.physical-ai",
            "mode": "train",
        }

    monkeypatch.setattr(stream_api, "_require_user_id", lambda: "user-1")
    monkeypatch.setattr(stream_api, "_refresh_stream_session_if_needed", lambda: None)
    monkeypatch.setattr(stream_api, "_load_job", fake_load_job)
    monkeypatch.setattr(stream_api, "_get_ssh_connection_for_job", lambda job_data, timeout=30: fake_conn)

    async def _run():
        response = await stream_api.stream_training_job_logs(_FakeRequest(), "job-1")
        iterator = response.body_iterator
        connected = _decode_sse(await anext(iterator))
        log_line = _decode_sse(await anext(iterator))
        terminal = _decode_sse(await anext(iterator))
        await iterator.aclose()

        assert connected == {"type": "connected", "message": "SSH接続完了"}
        assert log_line == {"type": "log", "line": "line-1"}
        assert terminal == {
            "type": "status",
            "status": "stream_ended",
            "message": "ログストリーム終了",
        }
        assert fake_conn.disconnected is True

    asyncio.run(_run())


def test_training_job_logs_stream_emits_error_when_ip_missing(monkeypatch):
    async def fake_load_job(job_id: str, include_deleted: bool = False):
        assert job_id == "job-2"
        assert include_deleted is False
        return {"job_id": job_id, "ip": None}

    monkeypatch.setattr(stream_api, "_require_user_id", lambda: "user-1")
    monkeypatch.setattr(stream_api, "_refresh_stream_session_if_needed", lambda: None)
    monkeypatch.setattr(stream_api, "_load_job", fake_load_job)

    async def _run():
        response = await stream_api.stream_training_job_logs(_FakeRequest(), "job-2")
        iterator = response.body_iterator
        payload = _decode_sse(await anext(iterator))
        await iterator.aclose()
        assert payload == {"type": "error", "error": "Job has no IP address"}

    asyncio.run(_run())

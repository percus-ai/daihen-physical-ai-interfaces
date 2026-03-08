from __future__ import annotations

import asyncio

from interfaces_backend.models.realtime import TrainingJobLogsSubscription
from interfaces_backend.services.tab_realtime_sources import (
    TabRealtimeSourceRegistry,
    TrainingJobLogStreamState,
)


class _FakeChannel:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.closed = False

    def exec_command(self, _command: str) -> None:
        return None

    def setblocking(self, _flag: int) -> None:
        return None

    def recv_ready(self) -> bool:
        return bool(self._chunks)

    def recv(self, _size: int) -> bytes:
        return self._chunks.pop(0)

    def exit_status_ready(self) -> bool:
        return not self._chunks

    def close(self) -> None:
        self.closed = True


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


def _make_subscription() -> TrainingJobLogsSubscription:
    return TrainingJobLogsSubscription.model_validate(
        {
            "subscription_id": "job.logs",
            "kind": "training.job.logs",
            "params": {
                "job_id": "job-1",
                "log_type": "training",
                "tail_lines": 3,
            },
        }
    )


def test_log_source_emits_connected_then_append_batches(monkeypatch):
    import interfaces_backend.api.training as training_api

    fake_channel = _FakeChannel([b"line-1\nline-2", b"\nline-3\n"])
    fake_conn = _FakeSshConnection(fake_channel)
    registry = TabRealtimeSourceRegistry()
    subscription = _make_subscription()

    async def fake_load_job(job_id: str, include_deleted: bool = False):
        assert job_id == "job-1"
        del include_deleted
        return {
            "job_id": job_id,
            "ip": "10.0.0.1",
            "remote_base_dir": "/root/.physical-ai",
            "mode": "train",
            "status": "running",
        }

    monkeypatch.setattr(training_api, "_load_job", fake_load_job)
    monkeypatch.setattr(training_api, "_get_ssh_connection_for_job", lambda job_data, timeout=30: fake_conn)
    monkeypatch.setattr(training_api, "_get_training_log_file_path", lambda job_data: "/tmp/train.log")

    async def _run():
        connected = await registry.poll(subscription)
        assert connected.op == "control"
        assert connected.payload == {
            "type": "connected",
            "job_id": "job-1",
            "log_type": "training",
        }
        assert isinstance(connected.next_state, TrainingJobLogStreamState)

        append_1 = await registry.poll(subscription, connected.next_state)
        assert append_1.op == "append"
        assert append_1.payload == {
            "job_id": "job-1",
            "log_type": "training",
            "lines": ["line-1", "line-2", "line-3"],
        }
        assert append_1.cursor == "3"

        append_2 = await registry.poll(subscription, append_1.next_state)
        assert append_2.op == "control"
        assert append_2.payload == {
            "job_id": "job-1",
            "log_type": "training",
            "type": "stream_ended",
        }
        assert append_2.close_state is True

    asyncio.run(_run())


def test_log_source_emits_stream_ended_and_cleanup(monkeypatch):
    import interfaces_backend.api.training as training_api

    fake_channel = _FakeChannel([])
    fake_conn = _FakeSshConnection(fake_channel)
    registry = TabRealtimeSourceRegistry()
    subscription = _make_subscription()

    async def fake_load_job(job_id: str, include_deleted: bool = False):
        assert job_id == "job-1"
        del include_deleted
        return {
            "job_id": job_id,
            "ip": "10.0.0.1",
            "remote_base_dir": "/root/.physical-ai",
            "mode": "train",
            "status": "running",
        }

    monkeypatch.setattr(training_api, "_load_job", fake_load_job)
    monkeypatch.setattr(training_api, "_get_ssh_connection_for_job", lambda job_data, timeout=30: fake_conn)
    monkeypatch.setattr(training_api, "_get_training_log_file_path", lambda job_data: "/tmp/train.log")

    async def _run():
        connected = await registry.poll(subscription)
        ended = await registry.poll(subscription, connected.next_state)
        assert ended.op == "control"
        assert ended.payload == {
            "type": "stream_ended",
            "job_id": "job-1",
            "log_type": "training",
        }
        assert ended.close_state is True
        registry.cleanup(subscription, connected.next_state)
        assert fake_channel.closed is True
        assert fake_conn.disconnected is True

    asyncio.run(_run())

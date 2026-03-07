from __future__ import annotations

import asyncio

import interfaces_backend.api.stream as stream_api
from interfaces_backend.models.training import TrainingProvisionOperationStatusResponse
from interfaces_backend.services.realtime_events import get_realtime_event_bus


class _FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


class _FakeOperations:
    async def get(self, *, user_id: str, operation_id: str) -> TrainingProvisionOperationStatusResponse:
        assert user_id == 'user-1'
        return TrainingProvisionOperationStatusResponse(
            operation_id=operation_id,
            state='running',
            step='connect_ssh',
            message='SSH接続',
            provider='verda',
            instance_id='inst-1',
            job_id=None,
        )


def test_training_provision_operation_stream_emits_snapshot(monkeypatch):
    captured: dict[str, object] = {}

    def fake_sse_queue_response(request, queue, *, event=None, heartbeat=25.0, payload_key='payload', on_close=None):
        captured['request'] = request
        captured['queue'] = queue
        captured['payload_key'] = payload_key
        captured['on_close'] = on_close
        return 'stream-response'

    monkeypatch.setattr(stream_api, '_require_user_id', lambda: 'user-1')
    monkeypatch.setattr(stream_api, 'get_training_provision_operations_service', lambda: _FakeOperations())
    monkeypatch.setattr(stream_api, 'sse_queue_response', fake_sse_queue_response)

    async def _run():
        response = await stream_api.stream_training_provision_operation(_FakeRequest(), 'op-1')
        assert response == 'stream-response'
        event = await asyncio.wait_for(captured['queue'].get(), timeout=1.0)
        payload = event['payload']
        assert payload['operation_id'] == 'op-1'
        assert payload['state'] == 'running'
        assert payload['step'] == 'connect_ssh'
        assert payload['message'] == 'SSH接続'
        captured['on_close']()
        assert get_realtime_event_bus().subscriber_count(stream_api.TRAINING_PROVISION_OPERATION_TOPIC, 'op-1') == 0

    asyncio.run(_run())

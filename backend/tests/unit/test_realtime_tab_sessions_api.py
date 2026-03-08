from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from interfaces_backend.models.realtime import TabSessionStateRequest
from interfaces_backend.services.tab_realtime import (
    TabRealtimeRegistry,
    TabSessionNotFoundError,
    TabSessionRevisionConflictError,
)
from interfaces_backend.services.tab_realtime_sources import RealtimeSourcePollResult


def _make_state_payload(*, revision: int = 1, visibility: str = "foreground") -> dict:
    return {
        "revision": revision,
        "lifecycle": {
            "visibility": visibility,
            "reason": "route-change",
        },
        "route": {
            "id": "train.job.detail",
            "url": "/train/jobs/job-1",
            "params": {"job_id": "job-1"},
        },
        "subscriptions": [
            {
                "subscription_id": "profiles.active",
                "kind": "profiles.active",
                "params": {},
            },
            {
                "subscription_id": "job.core",
                "kind": "training.job.core",
                "params": {"job_id": "job-1"},
            },
            {
                "subscription_id": "job.logs",
                "kind": "training.job.logs",
                "params": {"job_id": "job-1", "log_type": "training", "tail_lines": 200},
            },
        ],
    }


class _FakeSourceRegistry:
    def __init__(self) -> None:
        self.poll_counts: dict[str, int] = {}

    def interval_for(self, subscription) -> float:
        return 0.0

    async def poll(self, subscription) -> RealtimeSourcePollResult:
        self.poll_counts[subscription.subscription_id] = self.poll_counts.get(subscription.subscription_id, 0) + 1
        if subscription.kind == "training.job.logs":
            return RealtimeSourcePollResult(error="logs unsupported")
        return RealtimeSourcePollResult(
            payload={
                "subscription_id": subscription.subscription_id,
                "kind": subscription.kind,
                "job_id": getattr(subscription.params, "job_id", None),
            }
        )


def test_tab_session_subscription_schema_is_typed():
    invalid_payload = _make_state_payload()
    invalid_payload["subscriptions"][1]["params"] = {}

    with pytest.raises(ValidationError):
        TabSessionStateRequest.model_validate(invalid_payload)


def test_tab_session_registry_put_get_delete_flow():
    registry = TabRealtimeRegistry()
    state = TabSessionStateRequest.model_validate(_make_state_payload(revision=1))

    result = registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state)
    assert result.tab_session_id == "tab-1"
    assert result.revision == 1
    assert result.subscription_count == 3

    loaded_state = registry.get_state(user_id="user-1", tab_session_id="tab-1")
    assert loaded_state.revision == 1
    assert loaded_state.route.id == "train.job.detail"
    assert loaded_state.subscriptions[1].kind == "training.job.core"

    deleted = registry.delete_session(user_id="user-1", tab_session_id="tab-1")
    assert deleted is True

    with pytest.raises(TabSessionNotFoundError):
        registry.get_state(user_id="user-1", tab_session_id="tab-1")


def test_tab_session_registry_rejects_stale_revision():
    registry = TabRealtimeRegistry()
    state_v2 = TabSessionStateRequest.model_validate(_make_state_payload(revision=2))

    result = registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state_v2)
    assert result.revision == 2

    with pytest.raises(TabSessionRevisionConflictError):
        registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state_v2)


def test_tab_session_registry_stream_replay_from_last_event_id():
    registry = TabRealtimeRegistry()
    source_registry = _FakeSourceRegistry()
    state_v1 = TabSessionStateRequest.model_validate(_make_state_payload(revision=1))
    registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state_v1)

    stream1 = registry.open_stream(
        user_id="user-1",
        tab_session_id="tab-1",
        last_event_id=None,
        source_registry=source_registry,
    )
    replay_types = [(event.get("payload") or {}).get("type") for event in stream1.replay_events]
    assert "state_applied" in replay_types
    assert "stream_connected" in replay_types
    last_event_id = max(event["stream_seq"] for event in stream1.replay_events)
    stream1.close()

    state_v2 = TabSessionStateRequest.model_validate(_make_state_payload(revision=2, visibility="background"))
    registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state_v2)

    stream2 = registry.open_stream(
        user_id="user-1",
        tab_session_id="tab-1",
        last_event_id=last_event_id,
        source_registry=source_registry,
    )
    replayed_state_event = next(
        event
        for event in stream2.replay_events
        if (event.get("payload") or {}).get("type") == "state_applied"
    )
    assert replayed_state_event["config_revision"] == 2
    assert replayed_state_event["stream_seq"] > last_event_id
    stream2.close()


def test_tab_session_registry_polls_snapshot_sources_and_emits_source_metadata():
    registry = TabRealtimeRegistry()
    source_registry = _FakeSourceRegistry()
    state = TabSessionStateRequest.model_validate(_make_state_payload(revision=1))
    registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state)

    stream = registry.open_stream(
        user_id="user-1",
        tab_session_id="tab-1",
        last_event_id=None,
        source_registry=source_registry,
    )

    async def _run():
        last_event_id = max(event["stream_seq"] for event in stream.replay_events)
        status, events = await stream.poll(after_seq=last_event_id)
        assert status == "events"
        snapshots = [event for event in events if event["op"] == "snapshot"]
        errors = [event for event in events if event["op"] == "error"]
        assert len(snapshots) == 2
        assert len(errors) == 1
        assert snapshots[0]["source"]["subscription_id"] == "profiles.active"
        assert snapshots[0]["source"]["generation"] == 1
        assert snapshots[0]["source_version"] == 1
        assert errors[0]["source"]["subscription_id"] == "job.logs"
        assert errors[0]["payload"]["message"] == "logs unsupported"

        next_status, next_events = await stream.poll(
            after_seq=max(event["stream_seq"] for event in events)
        )
        assert next_status == "idle"
        assert next_events == []

    asyncio.run(_run())
    stream.close()


def test_tab_session_registry_bumps_generation_when_subscription_changes():
    registry = TabRealtimeRegistry()
    source_registry = _FakeSourceRegistry()
    state_v1 = TabSessionStateRequest.model_validate(_make_state_payload(revision=1))
    registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state_v1)

    stream = registry.open_stream(
        user_id="user-1",
        tab_session_id="tab-1",
        last_event_id=None,
        source_registry=source_registry,
    )

    async def _run():
        last_event_id = max(event["stream_seq"] for event in stream.replay_events)
        _, initial_events = await stream.poll(after_seq=last_event_id)
        after_initial = max(event["stream_seq"] for event in initial_events)

        next_payload = _make_state_payload(revision=2)
        next_payload["subscriptions"][1]["params"]["job_id"] = "job-2"
        state_v2 = TabSessionStateRequest.model_validate(next_payload)
        registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state_v2)

        _, changed_events = await stream.poll(after_seq=after_initial)
        changed_snapshot = next(
            event
            for event in changed_events
            if event["op"] == "snapshot" and event["source"]["subscription_id"] == "job.core"
        )
        assert changed_snapshot["source"]["generation"] == 2
        assert changed_snapshot["payload"]["job_id"] == "job-2"

    asyncio.run(_run())
    stream.close()

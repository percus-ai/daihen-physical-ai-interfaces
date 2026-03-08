from __future__ import annotations

import pytest
from pydantic import ValidationError

from interfaces_backend.models.realtime import TabSessionStateRequest
from interfaces_backend.services.tab_realtime import (
    TabRealtimeRegistry,
    TabSessionNotFoundError,
    TabSessionRevisionConflictError,
)


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
    state_v1 = TabSessionStateRequest.model_validate(_make_state_payload(revision=1))
    registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state_v1)

    stream1 = registry.open_stream(
        user_id="user-1",
        tab_session_id="tab-1",
        last_event_id=None,
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
    )
    replayed_state_event = next(
        event
        for event in stream2.replay_events
        if (event.get("payload") or {}).get("type") == "state_applied"
    )
    assert replayed_state_event["config_revision"] == 2
    assert replayed_state_event["stream_seq"] > last_event_id
    stream2.close()

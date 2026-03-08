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
from interfaces_backend.services.tab_realtime_sources import (
    RealtimeSourcePollResult,
    TabRealtimeSourceRegistry,
)
from percus_ai.db import get_current_user_id


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
        self.cleaned: list[str] = []

    def interval_for(self, subscription) -> float:
        return 0.0

    async def poll(self, subscription, state=None) -> RealtimeSourcePollResult:
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

    def cleanup(self, subscription, state) -> None:
        del state
        self.cleaned.append(subscription.subscription_id)


class _FakeAppendSourceRegistry(_FakeSourceRegistry):
    async def poll(self, subscription, state=None) -> RealtimeSourcePollResult:
        count = self.poll_counts.get(subscription.subscription_id, 0) + 1
        self.poll_counts[subscription.subscription_id] = count
        if subscription.kind == "training.job.logs":
            return RealtimeSourcePollResult(
                op="append",
                payload={
                    "job_id": getattr(subscription.params, "job_id", None),
                    "lines": [f"log-line-{count}"],
                },
                cursor=str(count),
                next_state={"count": count},
            )
        return await super().poll(subscription, state=state)


class _FakeAuthCheckingSourceRegistry(_FakeSourceRegistry):
    async def poll(self, subscription, state=None) -> RealtimeSourcePollResult:
        return RealtimeSourcePollResult(
            payload={
                "subscription_id": subscription.subscription_id,
                "user_id": get_current_user_id(),
            }
        )


def test_tab_session_subscription_schema_is_typed():
    invalid_payload = _make_state_payload()
    invalid_payload["subscriptions"][1]["params"] = {}

    with pytest.raises(ValidationError):
        TabSessionStateRequest.model_validate(invalid_payload)


def test_tab_session_subscription_schema_accepts_system_operate_recording_sources():
    payload = _make_state_payload()
    payload["subscriptions"] = [
        {
            "subscription_id": "system.status",
            "kind": "system.status",
            "params": {},
        },
        {
            "subscription_id": "operate.status",
            "kind": "operate.status",
            "params": {},
        },
        {
            "subscription_id": "system.runtime-envs",
            "kind": "system.runtime-envs",
            "params": {},
        },
        {
            "subscription_id": "system.bundled-torch",
            "kind": "system.bundled-torch",
            "params": {},
        },
        {
            "subscription_id": "profiles.vlabor",
            "kind": "profiles.vlabor",
            "params": {},
        },
        {
            "subscription_id": "recording.upload-status",
            "kind": "recording.upload-status",
            "params": {"session_id": "dataset-1"},
        },
        {
            "subscription_id": "startup.operation",
            "kind": "startup.operation",
            "params": {"operation_id": "op-1"},
        },
        {
            "subscription_id": "training.provision-operation",
            "kind": "training.provision-operation",
            "params": {"operation_id": "prov-1"},
        },
        {
            "subscription_id": "storage.model-sync",
            "kind": "storage.model-sync",
            "params": {"job_id": "model-job-1"},
        },
        {
            "subscription_id": "storage.dataset-sync",
            "kind": "storage.dataset-sync",
            "params": {"job_id": "dataset-job-1"},
        },
        {
            "subscription_id": "storage.dataset-merge",
            "kind": "storage.dataset-merge",
            "params": {"job_id": "merge-job-1"},
        },
    ]

    state = TabSessionStateRequest.model_validate(payload)

    assert len(state.subscriptions) == 11
    assert state.subscriptions[0].kind == "system.status"
    assert state.subscriptions[-1].kind == "storage.dataset-merge"


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

    changed = _make_state_payload(revision=2)
    changed["route"]["url"] = "/train/jobs/job-1?tab=logs"
    changed_state = TabSessionStateRequest.model_validate(changed)

    with pytest.raises(TabSessionRevisionConflictError):
        registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=changed_state)


def test_tab_session_registry_accepts_same_revision_when_state_is_identical():
    registry = TabRealtimeRegistry()
    state_v2 = TabSessionStateRequest.model_validate(_make_state_payload(revision=2))

    first = registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state_v2)
    second = registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=state_v2)

    assert second.revision == first.revision
    assert second.subscription_count == first.subscription_count

    changed = _make_state_payload(revision=2)
    changed["route"]["url"] = "/train/jobs/job-1?tab=logs"
    changed_state = TabSessionStateRequest.model_validate(changed)

    with pytest.raises(TabSessionRevisionConflictError):
        registry.apply_state(user_id="user-1", tab_session_id="tab-1", state=changed_state)


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


def test_tab_session_registry_forwards_append_events_without_payload_dedup():
    registry = TabRealtimeRegistry()
    source_registry = _FakeAppendSourceRegistry()
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
        _, first_events = await stream.poll(after_seq=last_event_id)
        after_first = max(event["stream_seq"] for event in first_events)
        first_append = next(event for event in first_events if event["op"] == "append")
        assert first_append["payload"]["lines"] == ["log-line-1"]
        assert first_append["cursor"] == "1"

        _, second_events = await stream.poll(after_seq=after_first)
        second_append = next(event for event in second_events if event["op"] == "append")
        assert second_append["payload"]["lines"] == ["log-line-2"]
        assert second_append["cursor"] == "2"

    asyncio.run(_run())
    stream.close()


def test_tab_session_registry_restores_user_context_for_polling():
    registry = TabRealtimeRegistry()
    source_registry = _FakeAuthCheckingSourceRegistry()
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
        payloads = [event["payload"] for event in events if event["op"] == "snapshot"]
        assert payloads
        assert all(payload["user_id"] == "user-1" for payload in payloads)

    asyncio.run(_run())
    stream.close()


def test_tab_realtime_source_registry_supports_system_operate_and_recording_sources(monkeypatch):
    registry = TabRealtimeSourceRegistry()

    class _Snapshot:
        def __init__(self, payload):
            self._payload = payload

        def model_dump(self, mode="json"):
            assert mode == "json"
            return dict(self._payload)

    class _Monitor:
        def ensure_started(self):
            return None

        def get_snapshot(self):
            return _Snapshot({"overall": {"level": "healthy"}})

    class _RuntimeEnvService:
        async def refresh_snapshot(self):
            return None

        def get_snapshot(self):
            return _Snapshot({"envs": [], "updated_at": "2026-03-08T00:00:00Z"})

    class _BundledTorchService:
        async def refresh_snapshot(self):
            return None

        def get_snapshot(self):
            return _Snapshot({"state": "idle", "updated_at": "2026-03-08T00:00:00Z"})

    class _DatasetLifecycle:
        def get_dataset_upload_status(self, session_id):
            return {
                "dataset_id": session_id,
                "status": "running",
                "phase": "upload",
                "progress_percent": 12.5,
                "message": "uploading",
                "files_done": 1,
                "total_files": 8,
            }

    class _StartupOperations:
        def get(self, *, user_id, operation_id):
            assert user_id == "user-1"
            return _Snapshot(
                {
                    "operation_id": operation_id,
                    "kind": "inference_start",
                    "state": "running",
                    "phase": "launch_worker",
                    "progress_percent": 55,
                }
            )

    class _TrainingProvisionOperations:
        async def get(self, *, user_id, operation_id):
            assert user_id == "user-1"
            return _Snapshot(
                {
                    "operation_id": operation_id,
                    "state": "running",
                    "step": "create_instance",
                    "message": "creating",
                }
            )

    class _SyncJobs:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        def get(self, *, user_id, job_id):
            assert user_id == "user-1"
            return _Snapshot({"job_id": job_id, "state": "running", "kind": self.kind})

    async def _get_vlabor_status():
        return _Snapshot({"status": "running", "dashboard_url": "http://example.test"})

    async def _get_inference_runner_status():
        return _Snapshot({"runner_status": {"active": True, "session_id": "inf-1"}})

    async def _get_operate_status():
        return _Snapshot({"network": {"status": "healthy"}})

    monkeypatch.setattr(
        "interfaces_backend.api.profiles.get_vlabor_status",
        _get_vlabor_status,
    )
    monkeypatch.setattr(
        "interfaces_backend.api.inference.get_inference_runner_status",
        _get_inference_runner_status,
    )
    monkeypatch.setattr(
        "interfaces_backend.api.operate.get_operate_status",
        _get_operate_status,
    )
    monkeypatch.setattr(
        "interfaces_backend.services.system_status_monitor.get_system_status_monitor",
        lambda: _Monitor(),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.runtime_env_service.get_runtime_env_service",
        lambda: _RuntimeEnvService(),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.bundled_torch_build_service.get_bundled_torch_build_service",
        lambda: _BundledTorchService(),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.dataset_lifecycle.get_dataset_lifecycle",
        lambda: _DatasetLifecycle(),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.startup_operations.get_startup_operations_service",
        lambda: _StartupOperations(),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.training_provision_operations.get_training_provision_operations_service",
        lambda: _TrainingProvisionOperations(),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.model_sync_jobs.get_model_sync_jobs_service",
        lambda: _SyncJobs("model"),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.dataset_sync_jobs.get_dataset_sync_jobs_service",
        lambda: _SyncJobs("dataset"),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.dataset_merge_jobs.get_dataset_merge_jobs_service",
        lambda: _SyncJobs("merge"),
    )
    monkeypatch.setattr(
        "interfaces_backend.services.session_manager.require_user_id",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "percus_ai.db.get_current_user_id",
        lambda: "user-1",
    )

    state = TabSessionStateRequest.model_validate(
        {
            **_make_state_payload(),
            "subscriptions": [
                {"subscription_id": "profiles.vlabor", "kind": "profiles.vlabor", "params": {}},
                {"subscription_id": "system.status", "kind": "system.status", "params": {}},
                {"subscription_id": "operate.status", "kind": "operate.status", "params": {}},
                {"subscription_id": "system.runtime-envs", "kind": "system.runtime-envs", "params": {}},
                {"subscription_id": "system.bundled-torch", "kind": "system.bundled-torch", "params": {}},
                {
                    "subscription_id": "recording.upload-status",
                    "kind": "recording.upload-status",
                    "params": {"session_id": "dataset-1"},
                },
                {
                    "subscription_id": "startup.operation",
                    "kind": "startup.operation",
                    "params": {"operation_id": "op-1"},
                },
                {
                    "subscription_id": "training.provision-operation",
                    "kind": "training.provision-operation",
                    "params": {"operation_id": "prov-1"},
                },
                {
                    "subscription_id": "storage.model-sync",
                    "kind": "storage.model-sync",
                    "params": {"job_id": "model-job-1"},
                },
                {
                    "subscription_id": "storage.dataset-sync",
                    "kind": "storage.dataset-sync",
                    "params": {"job_id": "dataset-job-1"},
                },
                {
                    "subscription_id": "storage.dataset-merge",
                    "kind": "storage.dataset-merge",
                    "params": {"job_id": "merge-job-1"},
                },
            ],
        }
    )

    async def _run():
        payloads = {}
        for subscription in state.subscriptions:
            result = await registry.poll(subscription)
            payloads[subscription.kind] = result.payload

        assert payloads["profiles.vlabor"]["status"] == "running"
        assert payloads["system.status"]["overall"]["level"] == "healthy"
        assert payloads["operate.status"]["inference_runner_status"]["runner_status"]["active"] is True
        assert payloads["system.runtime-envs"]["envs"] == []
        assert payloads["system.bundled-torch"]["state"] == "idle"
        assert payloads["recording.upload-status"]["dataset_id"] == "dataset-1"
        assert payloads["startup.operation"]["operation_id"] == "op-1"
        assert payloads["startup.operation"]["state"] == "running"
        assert payloads["training.provision-operation"]["operation_id"] == "prov-1"
        assert payloads["storage.model-sync"]["job_id"] == "model-job-1"
        assert payloads["storage.dataset-sync"]["job_id"] == "dataset-job-1"
        assert payloads["storage.dataset-merge"]["job_id"] == "merge-job-1"

    asyncio.run(_run())

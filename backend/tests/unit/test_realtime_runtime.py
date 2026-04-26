from __future__ import annotations

import asyncio

from interfaces_backend.models.realtime import RealtimeFrame
from interfaces_backend.services.realtime_runtime import (
    Broadcast,
    RealtimeRuntime,
    UserID,
    get_realtime_runtime,
    reset_realtime_runtime,
)


def test_track_replace_patch_and_commit():
    async def _run():
        runtime = RealtimeRuntime()
        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        track = runtime.track(scope=UserID("user-1"), kind="training.job.rescue_cpu", key="op-1")

        frame_1 = track.replace({"status": "queued", "stage": "queued"})
        assert frame_1 == RealtimeFrame(
            kind="training.job.rescue_cpu",
            key="op-1",
            revision=1,
            detail={"status": "queued", "stage": "queued"},
        )
        assert await connection.next_frame(timeout_seconds=0.1) == frame_1

        pending = track.patch({"status": "running"}, commit=False)
        assert pending is None
        assert track.revision == 1
        assert track.state == {"status": "queued", "stage": "queued"}

        track.patch({"stage": "creating_instance"}, commit=False)
        frame_2 = track.commit()
        assert frame_2.revision == 2
        assert frame_2.detail == {"status": "running", "stage": "creating_instance"}
        assert track.state == frame_2.detail
        assert await connection.next_frame(timeout_seconds=0.1) == frame_2

    asyncio.run(_run())


def test_open_connection_receives_latest_frames_for_same_user_only():
    async def _run():
        runtime = RealtimeRuntime()
        runtime.track(scope=UserID("user-1"), kind="system.status", key="system").replace({"backend": "ok"})
        runtime.track(scope=UserID("user-2"), kind="system.status", key="system").replace({"backend": "other"})

        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        frame = await connection.next_frame(timeout_seconds=0.1)

        assert frame is not None
        assert frame.kind == "system.status"
        assert frame.key == "system"
        assert frame.revision == 1
        assert frame.detail == {"backend": "ok"}
        assert await connection.next_frame(timeout_seconds=0.01) is None

    asyncio.run(_run())


def test_broadcast_track_is_delivered_to_all_user_connections():
    async def _run():
        runtime = RealtimeRuntime()
        connection_1 = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        connection_2 = runtime.open_connection(user_id="user-2", tab_id="tab-2")

        frame = runtime.track(scope=Broadcast(), kind="system.status", key="system").replace({"backend": "ok"})

        assert await connection_1.next_frame(timeout_seconds=0.1) == frame
        assert await connection_2.next_frame(timeout_seconds=0.1) == frame

        late_connection = runtime.open_connection(user_id="user-3", tab_id="tab-3")
        assert await late_connection.next_frame(timeout_seconds=0.1) == frame

    asyncio.run(_run())


def test_training_job_operations_emit_full_job_operations_state():
    async def _run():
        from interfaces_backend.models.training import TrainingJobOperationProgressEvent
        from interfaces_backend.services.training_job_operations import TrainingJobOperationsService

        reset_realtime_runtime()
        runtime = get_realtime_runtime()
        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        operations = TrainingJobOperationsService()

        accepted = operations.create(
            user_id="user-1",
            job_id="job-1",
            kind="rescue_cpu",
            message="CPU rescue を開始しました。",
        )
        frame_1 = await connection.next_frame(timeout_seconds=0.1)
        assert frame_1 is not None
        assert frame_1.kind == "training.job.operations"
        assert frame_1.key == "job-1"
        assert frame_1.detail["operations"][0]["operation_id"] == accepted.operation_id
        assert frame_1.detail["operations"][0]["state"] == "queued"

        operations.update_from_event(
            operation_id=accepted.operation_id,
            event=TrainingJobOperationProgressEvent(
                type="creating_instance",
                phase="creating_instance",
                progress_percent=40,
                message="CPUインスタンスを作成中...",
                detail={"instance_id": "instance-1"},
            ),
        )
        frame_2 = await connection.next_frame(timeout_seconds=0.1)
        assert frame_2 is not None
        assert frame_2.revision == 2
        operation = frame_2.detail["operations"][0]
        assert operation["state"] == "running"
        assert operation["phase"] == "creating_instance"
        assert operation["progress_percent"] == 40.0
        assert operation["detail"] == {"instance_id": "instance-1"}

    asyncio.run(_run())


def test_training_provision_operation_emits_operation_and_job_tracks(monkeypatch):
    async def _run():
        from interfaces_backend.services.training_provision_operations import (
            TrainingProvisionOperationsService,
        )

        async def fake_get_supabase_service_client_required():
            return object()

        async def fake_update_with_client(_client, *, operation_id: str, patch: dict[str, object]):
            assert operation_id == "op-1"
            assert patch["state"] == "running"

        async def fake_load(operation_id: str, *, owner_user_id: str | None):
            assert operation_id == "op-1"
            assert owner_user_id is None
            return {
                "owner_user_id": "user-1",
                "operation_id": "op-1",
                "state": "running",
                "step": "wait_ip",
                "message": "IP割り当てを待機中...",
                "failure_reason": None,
                "provider": "verda",
                "instance_id": "instance-1",
                "job_id": "job-1",
                "created_at": "2026-04-26T00:00:00+00:00",
                "updated_at": "2026-04-26T00:00:01+00:00",
                "started_at": "2026-04-26T00:00:00+00:00",
                "finished_at": None,
            }

        reset_realtime_runtime()
        runtime = get_realtime_runtime()
        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        service = TrainingProvisionOperationsService()
        monkeypatch.setattr(
            "interfaces_backend.services.training_provision_operations.get_supabase_service_client_required",
            fake_get_supabase_service_client_required,
        )
        monkeypatch.setattr(service, "_update_with_client", fake_update_with_client)
        monkeypatch.setattr(service, "_load", fake_load)

        await service._update(operation_id="op-1", state="running")

        frame_1 = await connection.next_frame(timeout_seconds=0.1)
        frame_2 = await connection.next_frame(timeout_seconds=0.1)
        assert frame_1 is not None
        assert frame_2 is not None
        assert frame_1.kind == "training.provision-operation"
        assert frame_1.key == "op-1"
        assert frame_1.detail["state"] == "running"
        assert frame_1.detail["step"] == "wait_ip"
        assert frame_2.kind == "training.job.provision"
        assert frame_2.key == "job-1"
        assert frame_2.detail["provision_operation"]["operation_id"] == "op-1"

    asyncio.run(_run())


def test_startup_operations_emit_operation_track():
    async def _run():
        from interfaces_backend.services.startup_operations import StartupOperationsService

        reset_realtime_runtime()
        runtime = get_realtime_runtime()
        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        operations = StartupOperationsService()

        accepted = operations.create(user_id="user-1", kind="inference_start")
        frame_1 = await connection.next_frame(timeout_seconds=0.1)
        assert frame_1 is not None
        assert frame_1.kind == "startup.operation"
        assert frame_1.key == accepted.operation_id
        assert frame_1.detail["state"] == "queued"

        operations.set_running(
            operation_id=accepted.operation_id,
            phase="prepare",
            progress_percent=25,
            message="準備中...",
        )
        frame_2 = await connection.next_frame(timeout_seconds=0.1)
        assert frame_2 is not None
        assert frame_2.revision == 2
        assert frame_2.detail["state"] == "running"
        assert frame_2.detail["phase"] == "prepare"
        assert frame_2.detail["progress_percent"] == 25.0

    asyncio.run(_run())


def test_storage_sync_jobs_emit_job_track():
    async def _run():
        from interfaces_backend.services.dataset_sync_jobs import DatasetSyncJobsService

        reset_realtime_runtime()
        runtime = get_realtime_runtime()
        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        jobs = DatasetSyncJobsService()

        accepted = jobs.create(user_id="user-1", dataset_id="dataset-1")
        frame_1 = await connection.next_frame(timeout_seconds=0.1)
        assert frame_1 is not None
        assert frame_1.kind == "storage.dataset-sync"
        assert frame_1.key == accepted.job_id
        assert frame_1.detail["state"] == "queued"

        jobs.set_running(
            job_id=accepted.job_id,
            progress_percent=50,
            message="同期中...",
            detail={"files_done": 2, "total_files": 4},
        )
        frame_2 = await connection.next_frame(timeout_seconds=0.1)
        assert frame_2 is not None
        assert frame_2.revision == 2
        assert frame_2.detail["state"] == "running"
        assert frame_2.detail["progress_percent"] == 50.0
        assert frame_2.detail["detail"]["files_done"] == 2

    asyncio.run(_run())


def test_realtime_stream_requires_tab_id(client, monkeypatch):
    import interfaces_backend.api.realtime as realtime_api

    monkeypatch.setattr(realtime_api, "get_current_user_id", lambda: "user-1")

    response = client.get("/api/realtime/stream")

    assert response.status_code == 422
    assert "tab_id" in response.json()["detail"]


def test_realtime_sse_frame_format():
    import interfaces_backend.api.realtime as realtime_api

    frame = RealtimeFrame(kind="system.status", key="system", revision=1, detail={"backend": "ok"})

    assert realtime_api._format_sse_frame(frame) == (
        'event: realtime\n'
        'data: {"detail": {"backend": "ok"}, "key": "system", "kind": "system.status", "revision": 1}\n\n'
    )


def test_training_job_event_publishes_log_frames():
    async def _run():
        import interfaces_backend.api.training as training_api
        from percus_ai.training.events import TrainingJobLogAppendEvent, TrainingJobLogControlEvent

        reset_realtime_runtime()

        runtime = get_realtime_runtime()
        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        training_api._publish_training_job_event(
            user_id="user-1",
            event=TrainingJobLogControlEvent(
                job_id="job-1",
                log_type="setup",
                control_type="connected",
                status="streaming",
                message="connected",
            ),
        )
        training_api._publish_training_job_event(
            user_id="user-1",
            event=TrainingJobLogAppendEvent(
                job_id="job-1",
                log_type="setup",
                lines=["setup line 1", "setup line 2"],
            ),
        )
        training_api._publish_training_job_event(
            user_id="user-1",
            event=TrainingJobLogAppendEvent(
                job_id="job-1",
                log_type="setup",
                lines=["setup line 3"],
            ),
        )
        training_api._publish_training_job_event(
            user_id="user-1",
            event=TrainingJobLogControlEvent(
                job_id="job-1",
                log_type="setup",
                control_type="stream_ended",
                status="completed",
            ),
        )

        connected = await connection.next_frame(timeout_seconds=0.1)
        first = await connection.next_frame(timeout_seconds=0.1)
        second = await connection.next_frame(timeout_seconds=0.1)
        ended = await connection.next_frame(timeout_seconds=0.1)

        assert connected is not None
        assert connected.kind == "training.job.logs"
        assert connected.key == "job-1:setup"
        assert connected.detail["type"] == "connected"
        assert first is not None
        assert first.detail["lines"] == ["setup line 1", "setup line 2"]
        assert second is not None
        assert second.detail["lines"] == ["setup line 1", "setup line 2", "setup line 3"]
        assert ended is not None
        assert ended.detail["type"] == "stream_ended"
        assert ended.detail["status"] == "completed"

    asyncio.run(_run())


def test_start_job_log_stream_uses_active_event_stream_without_opening_ssh(monkeypatch):
    async def _run():
        import interfaces_backend.api.training as training_api
        from interfaces_backend.models.training import TrainingJobLogStreamRequest
        from interfaces_backend.services.training_job_event_streams import get_training_job_event_stream_registry

        reset_realtime_runtime()
        registry = get_training_job_event_stream_registry()
        registry.clear()
        registry.open(job_id="job-1")

        async def fake_load_job(job_id: str, include_deleted: bool = False):
            return {
                "job_id": job_id,
                "status": "starting",
                "ip": "192.0.2.10",
            }

        def fail_get_ssh_connection_for_job(*_args, **_kwargs):
            raise AssertionError("/logs/live must not open SSH")

        monkeypatch.setattr(training_api, "get_current_user_id", lambda: "user-1")
        monkeypatch.setattr(training_api, "_load_job", fake_load_job)
        monkeypatch.setattr(training_api, "_get_ssh_connection_for_job", fail_get_ssh_connection_for_job)

        runtime = get_realtime_runtime()
        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        response = await training_api.start_job_log_stream(
            "job-1",
            TrainingJobLogStreamRequest(log_type="setup"),
        )

        frame = await connection.next_frame(timeout_seconds=0.1)
        assert response.key == "job-1:setup"
        assert frame is not None
        assert frame.kind == "training.job.logs"
        assert frame.detail["type"] == "connected"
        assert await connection.next_frame(timeout_seconds=0.05) is None
        registry.clear()

    asyncio.run(_run())


def test_start_job_log_stream_publishes_active_log_snapshot(monkeypatch):
    async def _run():
        import interfaces_backend.api.training as training_api
        from interfaces_backend.models.training import TrainingJobLogStreamRequest
        from interfaces_backend.services.training_job_event_streams import get_training_job_event_stream_registry

        reset_realtime_runtime()
        registry = get_training_job_event_stream_registry()
        registry.clear()
        registry.open(job_id="job-1")
        registry.append_log_lines(
            job_id="job-1",
            log_type="setup",
            lines=["setup line 1", "setup line 2"],
        )

        async def fake_load_job(job_id: str, include_deleted: bool = False):
            return {
                "job_id": job_id,
                "status": "starting",
                "ip": "192.0.2.10",
            }

        def fail_get_ssh_connection_for_job(*_args, **_kwargs):
            raise AssertionError("/logs/live must not open SSH")

        monkeypatch.setattr(training_api, "get_current_user_id", lambda: "user-1")
        monkeypatch.setattr(training_api, "_load_job", fake_load_job)
        monkeypatch.setattr(training_api, "_get_ssh_connection_for_job", fail_get_ssh_connection_for_job)

        runtime = get_realtime_runtime()
        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        response = await training_api.start_job_log_stream(
            "job-1",
            TrainingJobLogStreamRequest(log_type="setup"),
        )

        connected = await connection.next_frame(timeout_seconds=0.1)
        snapshot = await connection.next_frame(timeout_seconds=0.1)

        assert response.key == "job-1:setup"
        assert connected is not None
        assert connected.detail["type"] == "connected"
        assert snapshot is not None
        assert snapshot.kind == "training.job.logs"
        assert snapshot.detail["lines"] == ["setup line 1", "setup line 2"]
        registry.clear()

    asyncio.run(_run())


def test_training_log_track_latest_frame_is_authoritative_recent_lines():
    async def _run():
        import interfaces_backend.api.training as training_api
        from interfaces_backend.services.training_job_event_streams import get_training_job_event_stream_registry
        from percus_ai.training.events import TrainingJobLogAppendEvent

        reset_realtime_runtime()
        registry = get_training_job_event_stream_registry()
        registry.clear()
        registry.open(job_id="job-1")

        training_api._publish_training_job_event(
            user_id="user-1",
            event=TrainingJobLogAppendEvent(
                job_id="job-1",
                log_type="setup",
                lines=["setup line 1"],
            ),
        )
        training_api._publish_training_job_event(
            user_id="user-1",
            event=TrainingJobLogAppendEvent(
                job_id="job-1",
                log_type="setup",
                lines=["setup line 2"],
            ),
        )

        connection = get_realtime_runtime().open_connection(user_id="user-1", tab_id="tab-1")
        frame = await connection.next_frame(timeout_seconds=0.1)

        assert frame is not None
        assert frame.kind == "training.job.logs"
        assert frame.key == "job-1:setup"
        assert frame.detail["lines"] == ["setup line 1", "setup line 2"]
        registry.clear()

    asyncio.run(_run())


def test_start_job_log_stream_without_active_event_stream_does_not_open_ssh(monkeypatch):
    async def _run():
        import interfaces_backend.api.training as training_api
        from interfaces_backend.models.training import TrainingJobLogStreamRequest
        from interfaces_backend.services.training_job_event_streams import get_training_job_event_stream_registry

        reset_realtime_runtime()
        registry = get_training_job_event_stream_registry()
        registry.clear()

        async def fake_load_job(job_id: str, include_deleted: bool = False):
            return {
                "job_id": job_id,
                "status": "completed",
                "ip": "192.0.2.10",
            }

        def fail_get_ssh_connection_for_job(*_args, **_kwargs):
            raise AssertionError("/logs/live must not open SSH")

        monkeypatch.setattr(training_api, "get_current_user_id", lambda: "user-1")
        monkeypatch.setattr(training_api, "_load_job", fake_load_job)
        monkeypatch.setattr(training_api, "_get_ssh_connection_for_job", fail_get_ssh_connection_for_job)

        runtime = get_realtime_runtime()
        connection = runtime.open_connection(user_id="user-1", tab_id="tab-1")
        response = await training_api.start_job_log_stream(
            "job-1",
            TrainingJobLogStreamRequest(log_type="training"),
        )

        frame = await connection.next_frame(timeout_seconds=0.1)
        assert response.key == "job-1:training"
        assert frame is not None
        assert frame.kind == "training.job.logs"
        assert frame.detail["type"] == "stream_ended"
        assert frame.detail["status"] == "completed"

    asyncio.run(_run())


def test_get_job_logs_for_active_job_uses_event_buffer_without_opening_ssh(monkeypatch):
    async def _run():
        import interfaces_backend.api.training as training_api
        from interfaces_backend.services.training_job_event_streams import get_training_job_event_stream_registry

        registry = get_training_job_event_stream_registry()
        registry.clear()
        registry.open(job_id="job-1")
        registry.append_log_lines(
            job_id="job-1",
            log_type="setup",
            lines=["setup line 1", "setup line 2", "setup line 3"],
        )

        async def fake_load_job(job_id: str, include_deleted: bool = False):
            return {
                "job_id": job_id,
                "status": "starting",
                "ip": "192.0.2.10",
            }

        async def fail_get_remote_logs_async(*_args, **_kwargs):
            raise AssertionError("/logs for active jobs must not open SSH")

        monkeypatch.setattr(training_api, "_load_job", fake_load_job)
        monkeypatch.setattr(training_api, "_get_remote_logs_async", fail_get_remote_logs_async)

        response = await training_api.get_job_logs("job-1", lines=2, log_type="setup")

        assert response.source == "active"
        assert response.logs == "setup line 2\nsetup line 3"
        registry.clear()

    asyncio.run(_run())

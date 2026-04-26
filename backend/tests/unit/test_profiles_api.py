import asyncio

import pytest
from fastapi import BackgroundTasks, HTTPException

import interfaces_backend.api.profiles as profiles_api
from interfaces_backend.models.profile import (
    VlaborOperationAcceptedResponse,
    VlaborActiveProfileStatusResponse,
    VlaborStatusResponse,
)
from interfaces_backend.services.realtime_runtime import get_realtime_runtime, reset_realtime_runtime


class _FakeActiveProfile:
    def __init__(self):
        self.name = "so101_single_teleop"
        self.snapshot = {"name": "so101_single_teleop"}


def test_get_vlabor_status_runs_probe_in_thread(monkeypatch):
    captured: dict[str, object] = {}

    def fake_status():
        captured["status_called"] = True
        return {"status": "running", "service": "vlabor"}

    async def fake_to_thread(func, /, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return func(*args, **kwargs)

    monkeypatch.setattr(profiles_api, "_get_vlabor_status", fake_status)
    monkeypatch.setattr(profiles_api.asyncio, "to_thread", fake_to_thread)

    response = asyncio.run(profiles_api.get_vlabor_status())

    assert isinstance(response, VlaborStatusResponse)
    assert response.status == "running"
    assert captured["func"] is fake_status
    assert captured["args"] == ()
    assert captured["kwargs"] == {}
    assert captured["status_called"] is True


def test_get_active_profile_status_fetches_topics_in_thread(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_active_profile():
        return _FakeActiveProfile()

    class _FakeMonitor:
        def ensure_started(self):
            captured["ensure_started"] = True

        def get_cached_ros2_topics(self):
            captured["topics_called"] = True
            return ["/cam/image_raw"]

    monkeypatch.setattr(profiles_api, "_require_user_id", lambda: "user-1")
    monkeypatch.setattr(profiles_api, "get_active_profile_spec", fake_active_profile)
    monkeypatch.setattr(profiles_api, "get_system_status_monitor", lambda: _FakeMonitor())
    monkeypatch.setattr(profiles_api, "extract_status_camera_specs", lambda snapshot: [])
    monkeypatch.setattr(profiles_api, "extract_status_arm_specs", lambda snapshot: [])

    response = asyncio.run(profiles_api.get_active_profile_status())

    assert isinstance(response, VlaborActiveProfileStatusResponse)
    assert response.profile_name == "so101_single_teleop"
    assert response.topics == ["/cam/image_raw"]
    assert captured["ensure_started"] is True
    assert captured["topics_called"] is True


def test_restart_vlabor_endpoint_returns_operation_and_commits_queued_status(monkeypatch):
    async def fake_active_profile():
        return _FakeActiveProfile()

    async def fake_restart_task(**_kwargs):
        return None

    reset_realtime_runtime()
    profiles_api._end_vlabor_operation()
    monkeypatch.setattr(profiles_api, "_require_user_id", lambda: "user-1")
    monkeypatch.setattr(profiles_api, "get_active_profile_spec", fake_active_profile)
    monkeypatch.setattr(profiles_api, "_run_vlabor_restart_operation_task", fake_restart_task)

    try:
        response = asyncio.run(profiles_api.restart_vlabor_endpoint(BackgroundTasks(), profile=None))
    finally:
        profiles_api._end_vlabor_operation()

    assert isinstance(response, VlaborOperationAcceptedResponse)
    assert response.action == "restart"
    assert response.state == "queued"
    frame = get_realtime_runtime().track(
        scope=profiles_api.UserID("user-1"),
        kind="profiles.vlabor.operation",
        key=response.operation_id,
    ).latest_frame
    assert frame is not None
    assert frame.detail["state"] == "queued"
    assert frame.detail["profile_name"] == "so101_single_teleop"


def test_restart_vlabor_endpoint_rejects_concurrent_operation(monkeypatch):
    monkeypatch.setattr(profiles_api, "_require_user_id", lambda: "user-1")
    profiles_api._begin_vlabor_operation()
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(profiles_api.restart_vlabor_endpoint(BackgroundTasks(), profile=None))
    finally:
        profiles_api._end_vlabor_operation()

    assert exc_info.value.status_code == 409

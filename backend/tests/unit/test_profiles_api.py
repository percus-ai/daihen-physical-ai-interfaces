import asyncio

import interfaces_backend.api.profiles as profiles_api
from interfaces_backend.models.profile import (
    VlaborActiveProfileStatusResponse,
    VlaborStatusResponse,
)


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

    def fake_topics():
        captured["topics_called"] = True
        return ["/cam/image_raw"]

    async def fake_to_thread(func, /, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return func(*args, **kwargs)

    monkeypatch.setattr(profiles_api, "_require_user_id", lambda: "user-1")
    monkeypatch.setattr(profiles_api, "get_active_profile_spec", fake_active_profile)
    monkeypatch.setattr(profiles_api, "_fetch_ros2_topics", fake_topics)
    monkeypatch.setattr(profiles_api, "extract_status_camera_specs", lambda snapshot: [])
    monkeypatch.setattr(profiles_api, "extract_status_arm_specs", lambda snapshot: [])
    monkeypatch.setattr(profiles_api.asyncio, "to_thread", fake_to_thread)

    response = asyncio.run(profiles_api.get_active_profile_status())

    assert isinstance(response, VlaborActiveProfileStatusResponse)
    assert response.profile_name == "so101_single_teleop"
    assert response.topics == ["/cam/image_raw"]
    assert captured["func"] is fake_topics
    assert captured["args"] == ()
    assert captured["kwargs"] == {}
    assert captured["topics_called"] is True

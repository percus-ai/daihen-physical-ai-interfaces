import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")

import interfaces_backend.services.inference_session as inference_session
import interfaces_backend.services.session_manager as session_manager
from interfaces_backend.services.inference_model_compatibility import (
    InferenceModelCompatibilityError,
    InferenceModelProfileCompatibility,
)
from interfaces_backend.services.inference_session import InferenceSessionManager
from interfaces_backend.services.session_manager import SessionState


@pytest.fixture(autouse=True)
def _silence_inference_session_logger(monkeypatch):
    monkeypatch.setattr(inference_session.logger, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(inference_session.logger, "warning", lambda *args, **kwargs: None)
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(inference_session.asyncio, "to_thread", fake_to_thread)


class _FakeRuntime:
    def __init__(
        self,
        *,
        startable_error: RuntimeError | None = None,
        stop_exception: Exception | None = None,
    ):
        self.call_order: list[str] = []
        self.ensure_startable_calls = 0
        self.prepare_calls: list[str] = []
        self.start_calls: list[dict] = []
        self.stop_calls: list[str | None] = []
        self.pause_calls: list[tuple[str, bool]] = []
        self.task_calls: list[tuple[str, str]] = []
        self.policy_calls: list[tuple[str, int | None]] = []
        self.startable_error = startable_error
        self.stop_exception = stop_exception

    def ensure_startable(self) -> None:
        self.ensure_startable_calls += 1
        if self.startable_error is not None:
            raise self.startable_error

    def prepare_environment(self, *, policy_type: str, runtime_target_id: str | None = None, progress_callback=None) -> str:
        self.call_order.append("prepare_environment")
        self.prepare_calls.append(f"{policy_type}:{runtime_target_id or ''}")
        if progress_callback is not None:
            progress_callback(
                "prepare_env",
                90.0,
                "推論実行環境の準備が完了しました。",
                {"env_name": policy_type},
            )
        return f".venv-{policy_type}"

    def start(self, **kwargs) -> str:
        self.call_order.append("start")
        self.start_calls.append(kwargs)
        return "worker-1"

    def stop(self, session_id: str | None = None) -> bool:
        self.stop_calls.append(session_id)
        if self.stop_exception is not None:
            raise self.stop_exception
        return True

    def set_paused(self, session_id: str, *, paused: bool) -> int:
        self.pause_calls.append((session_id, paused))
        return 1

    def set_task(self, *, session_id: str, task: str) -> int:
        self.task_calls.append((session_id, task))
        return 1

    def set_policy_options(self, *, session_id: str, denoising_steps: int | None = None) -> int:
        self.policy_calls.append((session_id, denoising_steps))
        return 1


class _FakeRecorder:
    def __init__(
        self,
        *,
        stop_exception: Exception | None = None,
        final_status: dict | None = None,
        status_payload: dict | None = None,
        status_exception: Exception | None = None,
    ):
        self.stop_exception = stop_exception
        self.final_status = final_status
        self.status_payload = status_payload
        self.status_exception = status_exception
        self.stop_calls = 0
        self.wait_calls = 0
        self.status_calls = 0
        self.ensure_running_calls = 0

    def build_cameras(self, _profile_snapshot: dict) -> list[dict]:
        return [{"name": "front", "topic": "/cam/front/compressed"}]

    def ensure_running(self) -> None:
        self.ensure_running_calls += 1

    def status(self) -> dict:
        self.status_calls += 1
        if self.status_exception is not None:
            raise self.status_exception
        return self.status_payload or {}

    def stop(self, *, save_current: bool = True) -> dict:
        _ = save_current
        self.stop_calls += 1
        if self.stop_exception is not None:
            raise self.stop_exception
        return {"success": True, "message": "stopped"}

    def wait_until_finalized(
        self,
        dataset_id: str,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
    ) -> dict | None:
        _ = (dataset_id, timeout_s, poll_interval_s)
        self.wait_calls += 1
        return self.final_status


class _FakeDataset:
    def __init__(self, *, upload_exception: Exception | None = None):
        self.ensured_models: list[str] = []
        self.updated: list[str] = []
        self.marked: list[str] = []
        self.uploaded: list[str] = []
        self.upload_exception = upload_exception

    async def ensure_model_local(self, model_id: str, sync_status_callback=None) -> None:
        self.ensured_models.append(model_id)
        if sync_status_callback is not None:
            sync_status_callback(
                SimpleNamespace(
                    status="completed",
                    progress_percent=100.0,
                    message="completed",
                    files_done=1,
                    total_files=1,
                    transferred_bytes=10,
                    total_bytes=10,
                    current_file="config.json",
                    error=None,
                )
            )

    async def mark_active(self, dataset_id: str) -> None:
        self.marked.append(dataset_id)

    async def update_stats(self, dataset_id: str) -> None:
        self.updated.append(dataset_id)

    async def auto_upload(self, dataset_id: str) -> None:
        self.uploaded.append(dataset_id)
        if self.upload_exception is not None:
            raise self.upload_exception


def _build_manager(
    *,
    recorder: _FakeRecorder,
    dataset: _FakeDataset,
    runtime: _FakeRuntime,
) -> InferenceSessionManager:
    manager = InferenceSessionManager(
        runtime=runtime,
        recorder=recorder,
        dataset=dataset,
    )
    manager._sessions["session-1"] = SessionState(
        id="session-1",
        kind="inference",
        profile=SimpleNamespace(name="profile-a", snapshot={"raw": {}}),
        extras={
            "worker_session_id": "worker-1",
            "dataset_id": "dataset-1",
            "recording_started": True,
        },
    )
    return manager


def _build_profile_snapshot() -> dict:
    return {
        "profile": {
            "lerobot": {
                "left_arm": {
                    "namespace": "left_arm",
                    "topic": "/left_arm/joint_states",
                    "action_topic": "/left_arm/joint_actions",
                    "joints": [f"left_arm_joint{i}" for i in range(1, 8)],
                }
            }
        }
    }


def test_stop_treats_recorder_timeout_as_stopped_when_already_inactive() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(
        stop_exception=HTTPException(status_code=503, detail="Recorder request timed out: /api/session/stop"),
        final_status={"state": "idle", "dataset_id": ""},
    )
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )

    state = asyncio.run(manager.stop("session-1"))

    assert state.status == "stopped"
    assert runtime.stop_calls == ["worker-1"]
    assert recorder.stop_calls == 1
    assert recorder.wait_calls == 1
    assert dataset.updated == ["dataset-1"]
    assert dataset.marked == ["dataset-1"]
    assert dataset.uploaded == ["dataset-1"]


def test_stop_keeps_dataset_unmarked_when_recorder_may_still_be_active() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(
        stop_exception=HTTPException(status_code=503, detail="Recorder request timed out: /api/session/stop"),
        final_status={"state": "recording", "dataset_id": "dataset-1"},
    )
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )

    state = asyncio.run(manager.stop("session-1"))

    assert state.status == "stopped"
    assert runtime.stop_calls == ["worker-1"]
    assert recorder.stop_calls == 1
    assert recorder.wait_calls == 1
    assert dataset.updated == []
    assert dataset.marked == []
    assert dataset.uploaded == ["dataset-1"]


def test_stop_unregisters_recording_when_auto_upload_fails() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(final_status={"state": "idle", "dataset_id": ""})
    dataset = _FakeDataset(upload_exception=RuntimeError("upload failed"))
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )

    state = asyncio.run(manager.stop("session-1"))

    assert state.status == "stopped"
    assert recorder.stop_calls == 1
    assert dataset.uploaded == ["dataset-1"]
    assert manager.status("session-1") is None


def test_stop_resolves_recording_dataset_id_from_controller_status() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(final_status={"state": "idle", "dataset_id": ""})
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )
    manager._sessions["session-1"].extras.pop("dataset_id")

    class _FakeRecordingController:
        def __init__(self):
            self.marked: list[str] = []
            self.unregistered: list[str] = []

        def get_status(self, session_id: str) -> dict:
            assert session_id == "session-1"
            return {"recording_dataset_id": "dataset-from-controller"}

        def mark_stop_requested(self, session_id: str) -> None:
            self.marked.append(session_id)

        def unregister(self, session_id: str) -> None:
            self.unregistered.append(session_id)

    controller = _FakeRecordingController()
    manager._recording_controller = controller

    state = asyncio.run(manager.stop("session-1"))

    assert state.status == "stopped"
    assert recorder.stop_calls == 1
    assert dataset.uploaded == ["dataset-from-controller"]
    assert controller.marked == ["session-1"]
    assert controller.unregistered == ["session-1"]


def test_stop_cleans_recording_even_when_runtime_stop_fails() -> None:
    runtime = _FakeRuntime(stop_exception=RuntimeError("worker stop failed"))
    recorder = _FakeRecorder(final_status={"state": "idle", "dataset_id": ""})
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(manager.stop("session-1"))

    assert exc_info.value.status_code == 400
    assert "worker stop failed" in str(exc_info.value.detail)
    assert recorder.stop_calls == 1
    assert dataset.uploaded == ["dataset-1"]
    assert manager.status("session-1") is not None


def test_stop_recording_without_active_session_finalizes_completed_dataset() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(
        status_payload={"state": "completed", "dataset_id": "dataset-1"},
    )
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )

    result = asyncio.run(manager.stop_recording_without_active_session("dataset-1"))

    assert result == {
        "recording_dataset_id": "dataset-1",
        "recording_stopped": True,
    }
    assert recorder.status_calls == 1
    assert recorder.stop_calls == 0
    assert dataset.updated == ["dataset-1"]
    assert dataset.marked == ["dataset-1"]
    assert dataset.uploaded == ["dataset-1"]


def test_stop_recording_attempts_stop_when_status_read_fails() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(
        status_exception=RuntimeError("status unavailable"),
        final_status={"state": "idle", "dataset_id": ""},
    )
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )

    result = asyncio.run(manager.stop_recording_without_active_session("dataset-1"))

    assert result == {
        "recording_dataset_id": "dataset-1",
        "recording_stopped": True,
    }
    assert recorder.status_calls == 1
    assert recorder.stop_calls == 1
    assert recorder.wait_calls == 1
    assert dataset.updated == ["dataset-1"]
    assert dataset.marked == ["dataset-1"]
    assert dataset.uploaded == ["dataset-1"]


def test_stop_recording_without_active_session_reports_unconfirmed_stop() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder(
        stop_exception=HTTPException(status_code=503, detail="Recorder request timed out: /api/session/stop"),
        final_status={"state": "recording", "dataset_id": "dataset-1"},
    )
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )

    result = asyncio.run(manager.stop_recording_without_active_session("dataset-1"))

    assert result == {
        "recording_dataset_id": "dataset-1",
        "recording_stopped": False,
    }
    assert recorder.stop_calls == 1
    assert recorder.wait_calls == 1
    assert dataset.updated == []
    assert dataset.marked == []
    assert dataset.uploaded == ["dataset-1"]


def test_resume_starts_recording_when_session_not_started() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )
    manager._sessions["session-1"].status = "created"
    manager._sessions["session-1"].extras = {
        "worker_session_id": "worker-1",
        "task": "pick and place",
        "num_episodes": 12,
        "episode_time_s": 45.0,
        "reset_time_s": 8.0,
        "denoising_steps": 6,
        "recording_started": False,
    }

    class _FakeRecordingController:
        async def start(
            self,
            *,
            session,
            task,
            denoising_steps,
            num_episodes=None,
            episode_time_s=None,
            reset_time_s=None,
        ):
            _ = (task, denoising_steps, num_episodes, episode_time_s, reset_time_s)
            session.extras["dataset_id"] = "dataset-started"
            return {"success": True}

        def get_status(self, _session_id: str) -> dict:
            return {"batch_size": 20, "episode_time_s": 45.0, "reset_time_s": 8.0}

    manager._recording_controller = _FakeRecordingController()

    result = asyncio.run(manager.resume_active_recording_and_inference())

    assert result["started"] is True
    assert manager._sessions["session-1"].status == "running"
    assert manager._sessions["session-1"].extras["recording_started"] is True
    assert runtime.pause_calls == [("worker-1", False)]


def test_apply_active_settings_updates_pending_values_before_start() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )
    manager._sessions["session-1"].extras = {
        "worker_session_id": "worker-1",
        "task": "old-task",
        "num_episodes": 20,
        "episode_time_s": 60.0,
        "reset_time_s": 10.0,
        "denoising_steps": 8,
        "recording_started": False,
    }

    result = asyncio.run(
        manager.apply_active_settings(
            task="new-task",
            episode_time_s=30.0,
            reset_time_s=5.0,
            denoising_steps=4,
        )
    )

    assert runtime.task_calls == [("worker-1", "new-task")]
    assert runtime.policy_calls == [("worker-1", 4)]
    assert manager._sessions["session-1"].extras["task"] == "new-task"
    assert manager._sessions["session-1"].extras["episode_time_s"] == 30.0
    assert manager._sessions["session-1"].extras["reset_time_s"] == 5.0
    assert manager._sessions["session-1"].extras["denoising_steps"] == 4
    assert result["task"] == "new-task"


def test_any_active_prefers_latest_session_with_worker_session_id() -> None:
    runtime = _FakeRuntime()
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    manager = _build_manager(
        recorder=recorder,
        dataset=dataset,
        runtime=runtime,
    )
    manager._sessions["session-stale"] = SessionState(
        id="session-stale",
        kind="inference",
        status="created",
        profile=SimpleNamespace(name="profile-a", snapshot={"raw": {}}),
        extras={},
    )
    manager._sessions["session-active"] = SessionState(
        id="session-active",
        kind="inference",
        status="created",
        profile=SimpleNamespace(name="profile-a", snapshot={"raw": {}}),
        extras={"worker_session_id": "worker-2"},
    )

    active = manager.any_active()

    assert active is not None
    assert active.id == "session-active"


def test_create_prepares_environment_before_worker_start(monkeypatch, tmp_path) -> None:
    async def fake_resolve_profile(self, _profile):
        return SimpleNamespace(
            name="profile-a",
            source_path="profiles/profile-a.yaml",
            snapshot=_build_profile_snapshot(),
        )

    async def fake_save_session_profile_binding(**_kwargs):
        return None

    runtime = _FakeRuntime()
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    manager = InferenceSessionManager(
        runtime=runtime,
        recorder=recorder,
        dataset=dataset,
    )

    monkeypatch.setattr(InferenceSessionManager, "_resolve_profile", fake_resolve_profile)
    monkeypatch.setattr(session_manager, "get_current_user_id", lambda: "user-1")
    monkeypatch.setattr(session_manager, "save_session_profile_binding", fake_save_session_profile_binding)
    monkeypatch.setattr(
        inference_session,
        "build_inference_joint_names",
        lambda _snapshot: [f"left_arm_joint{i}" for i in range(1, 8)],
    )
    monkeypatch.setattr(
        inference_session,
        "build_inference_camera_aliases",
        lambda _snapshot: {"top_camera": "top_camera"},
    )
    monkeypatch.setattr(
        inference_session,
        "build_inference_bridge_config",
        lambda _snapshot: {
            "arm_streams": [
                {
                    "namespace": "left_arm",
                    "state_topic": "/left_arm/joint_states_single",
                    "action_topic": "/left_arm/joint_ctrl_single",
                }
            ],
            "camera_streams": [{"name": "top_camera", "topic": "/top"}],
        },
    )
    monkeypatch.setattr(inference_session, "get_models_dir", lambda: tmp_path)
    monkeypatch.setattr(
        inference_session,
        "resolve_huggingface_token_for_user",
        lambda user_id: "hf_user_token" if user_id == "user-1" else None,
    )
    monkeypatch.setattr(
        inference_session,
        "validate_inference_model_profile_compatibility",
        lambda **_kwargs: InferenceModelProfileCompatibility(
            policy_type="pi05",
            config_path=tmp_path / "model-1" / "config.json",
            joint_names=[f"left_arm_joint{i}" for i in range(1, 8)],
            state_dim=7,
            action_dim=7,
            model_image_keys=["cam_high"],
            resolved_camera_keys=["cam_high"],
        ),
    )

    progress_events: list[str] = []

    def progress_callback(phase: str, _percent: float, _message: str, _detail):
        progress_events.append(phase)

    state = asyncio.run(
        manager.create(
            session_id="session-1",
            model_id="model-1",
            runtime_target_id="cpu",
            user_id="user-1",
            task="pick-and-place",
            progress_callback=progress_callback,
        )
    )

    assert dataset.ensured_models == ["model-1"]
    assert runtime.ensure_startable_calls == 1
    assert recorder.ensure_running_calls == 1
    assert runtime.call_order == ["prepare_environment", "start"]
    assert runtime.prepare_calls == ["pi05:cpu"]
    assert runtime.start_calls[0]["model_id"] == "model-1"
    assert runtime.start_calls[0]["runtime_target_id"] == "cpu"
    assert runtime.start_calls[0]["huggingface_token"] == "hf_user_token"
    assert progress_events.index("prepare_env") < progress_events.index("launch_worker")
    assert runtime.pause_calls == [("worker-1", True)]
    assert state.extras["worker_session_id"] == "worker-1"
    assert state.extras["recording_prepared"] is True
    assert state.extras["recording_started"] is False


def test_create_blocks_worker_start_on_model_profile_mismatch(monkeypatch, tmp_path) -> None:
    async def fake_resolve_profile(self, _profile):
        return SimpleNamespace(
            name="profile-a",
            source_path="profiles/profile-a.yaml",
            snapshot={"profile": {"lerobot": {}}},
        )

    async def fake_save_session_profile_binding(**_kwargs):
        return None

    runtime = _FakeRuntime()
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    manager = InferenceSessionManager(
        runtime=runtime,
        recorder=recorder,
        dataset=dataset,
    )

    monkeypatch.setattr(InferenceSessionManager, "_resolve_profile", fake_resolve_profile)
    monkeypatch.setattr(session_manager, "get_current_user_id", lambda: "user-1")
    monkeypatch.setattr(session_manager, "save_session_profile_binding", fake_save_session_profile_binding)
    monkeypatch.setattr(
        inference_session,
        "build_inference_joint_names",
        lambda _snapshot: [f"left_arm_joint{i}" for i in range(1, 8)],
    )
    monkeypatch.setattr(
        inference_session,
        "build_inference_camera_aliases",
        lambda _snapshot: {"top_camera": "top_camera"},
    )
    monkeypatch.setattr(
        inference_session,
        "build_inference_bridge_config",
        lambda _snapshot: {
            "arm_streams": [
                {
                    "namespace": "left_arm",
                    "state_topic": "/left_arm/joint_states_single",
                    "action_topic": "/left_arm/joint_ctrl_single",
                }
            ],
            "camera_streams": [{"name": "top_camera", "topic": "/top"}],
        },
    )
    monkeypatch.setattr(inference_session, "get_models_dir", lambda: tmp_path)

    def fail_compatibility(**_kwargs):
        raise InferenceModelCompatibilityError(
            "model expects observation.state=6 but active profile resolves 7 joints "
            "(left_arm_joint1, left_arm_joint2, left_arm_joint3, left_arm_joint4, "
            "left_arm_joint5, left_arm_joint6, left_arm_joint7)"
        )

    monkeypatch.setattr(
        inference_session,
        "validate_inference_model_profile_compatibility",
        fail_compatibility,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            manager.create(
                session_id="session-1",
                model_id="model-1",
                runtime_target_id="cpu",
                task="pick-and-place",
            )
        )

    assert exc_info.value.status_code == 400
    assert "model expects observation.state=6 but active profile resolves 7 joints" in str(
        exc_info.value.detail
    )
    assert dataset.ensured_models == ["model-1"]
    assert runtime.ensure_startable_calls == 1
    assert runtime.prepare_calls == []
    assert runtime.start_calls == []


def test_create_rejects_when_worker_already_running_before_sync(monkeypatch) -> None:
    async def fake_resolve_profile(self, _profile):
        return SimpleNamespace(
            name="profile-a",
            source_path="profiles/profile-a.yaml",
            snapshot={"profile": {"lerobot": {}}},
        )

    async def fake_save_session_profile_binding(**_kwargs):
        return None

    runtime = _FakeRuntime(startable_error=RuntimeError("Inference worker already running"))
    recorder = _FakeRecorder()
    dataset = _FakeDataset()
    manager = InferenceSessionManager(
        runtime=runtime,
        recorder=recorder,
        dataset=dataset,
    )

    monkeypatch.setattr(InferenceSessionManager, "_resolve_profile", fake_resolve_profile)
    monkeypatch.setattr(session_manager, "get_current_user_id", lambda: "user-1")
    monkeypatch.setattr(session_manager, "save_session_profile_binding", fake_save_session_profile_binding)
    monkeypatch.setattr(
        inference_session,
        "build_inference_joint_names",
        lambda _snapshot: [f"left_arm_joint{i}" for i in range(1, 8)],
    )
    monkeypatch.setattr(
        inference_session,
        "build_inference_camera_aliases",
        lambda _snapshot: {"top_camera": "top_camera"},
    )
    monkeypatch.setattr(
        inference_session,
        "build_inference_bridge_config",
        lambda _snapshot: {
            "arm_streams": [
                {
                    "namespace": "left_arm",
                    "state_topic": "/left_arm/joint_states_single",
                    "action_topic": "/left_arm/joint_ctrl_single",
                }
            ],
            "camera_streams": [{"name": "top_camera", "topic": "/top"}],
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            manager.create(
                session_id="session-1",
                model_id="model-1",
                runtime_target_id="cpu",
                task="pick-and-place",
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Inference worker already running"
    assert runtime.ensure_startable_calls == 1
    assert dataset.ensured_models == []
    assert runtime.prepare_calls == []
    assert runtime.start_calls == []

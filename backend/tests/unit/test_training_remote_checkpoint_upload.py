import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import types

from fastapi import HTTPException
import pytest
from percus_ai.storage.models import CheckpointDatasetInfo as StorageCheckpointDatasetInfo

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _load_training_api_module():
    inserted_module_names: list[str] = []
    training_pkg = types.ModuleType("percus_ai.training")
    providers_pkg = types.ModuleType("percus_ai.training.providers")
    providers_vast_module = types.ModuleType("percus_ai.training.providers.vast")
    providers_verda_module = types.ModuleType("percus_ai.training.providers.verda")
    features_repo_module = types.ModuleType("percus_ai.training.features_repo")
    ssh_pkg = types.ModuleType("percus_ai.training.ssh")
    ssh_client_module = types.ModuleType("percus_ai.training.ssh.client")
    ssh_executor_module = types.ModuleType("percus_ai.training.ssh.executor")

    class _StubSSHConnection:
        pass

    class _StubRemoteExecutor:
        pass

    def _stub_run_remote_command(*_args, **_kwargs):
        return 0, "", ""

    def _stub_destroy_instance(*_args, **_kwargs):
        return None

    class _StubVerdaProvider:
        def terminate_instance(self, *_args, **_kwargs):
            return None

    class _StubFeaturesRepoConfig:
        def __init__(self, repo_url: str = "", repo_ref: str = "", repo_commit: str | None = None):
            self.repo_url = repo_url
            self.repo_ref = repo_ref
            self.repo_commit = repo_commit

    ssh_client_module.SSHConnection = _StubSSHConnection
    ssh_executor_module.RemoteExecutor = _StubRemoteExecutor
    ssh_executor_module.run_remote_command = _stub_run_remote_command
    providers_vast_module.destroy_instance = _stub_destroy_instance
    providers_verda_module.VerdaProvider = _StubVerdaProvider
    features_repo_module.resolve_features_repo_config = lambda: _StubFeaturesRepoConfig(
        repo_url="https://github.com/percus-ai/physical-ai-features.git",
        repo_ref="main",
        repo_commit=None,
    )

    for name, module in (
        ("percus_ai.training", training_pkg),
        ("percus_ai.training.providers", providers_pkg),
        ("percus_ai.training.providers.vast", providers_vast_module),
        ("percus_ai.training.providers.verda", providers_verda_module),
        ("percus_ai.training.features_repo", features_repo_module),
        ("percus_ai.training.ssh", ssh_pkg),
        ("percus_ai.training.ssh.client", ssh_client_module),
        ("percus_ai.training.ssh.executor", ssh_executor_module),
    ):
        if name in sys.modules:
            continue
        sys.modules[name] = module
        inserted_module_names.append(name)

    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "interfaces_backend"
        / "api"
        / "training.py"
    )
    spec = importlib.util.spec_from_file_location("interfaces_backend_api_training_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for name in inserted_module_names:
        sys.modules.pop(name, None)
    return module


training = _load_training_api_module()


class _DummySync:
    bucket = "daihen"

    @staticmethod
    def _get_prefix() -> str:
        return "v2/"


class _DummyCheckpointManager:
    def __init__(self, existing_steps: list[int] | None = None) -> None:
        self.sync = _DummySync()
        self._existing_steps = list(existing_steps or [])
        self.upload_calls: list[dict] = []

    def upload_step_checkpoint(self, **kwargs):
        self.upload_calls.append(kwargs)
        return True, ""

    def get_job_steps(self, _job_name: str):
        return list(self._existing_steps)


class _DummyConn:
    def __init__(self) -> None:
        self.disconnected = False

    def exec_command(self, _cmd: str, timeout: int = 0):
        return 0, "", ""

    def download_directory(self, _remote_path: str, _local_path):
        return None

    def disconnect(self):
        self.disconnected = True


def _job() -> dict:
    return {
        "job_id": "job-1",
        "job_name": "pick_place_train_20260309",
        "dataset_id": "dataset-1",
        "policy_type": "pi0",
        "training_config": {"policy": {"type": "pi0"}, "dataset": {"id": "dataset-1"}},
        "remote_base_dir": "/root/.physical-ai",
    }


def test_register_job_for_checkpoint_if_needed_converts_dataset_info_for_storage(monkeypatch):
    class _CapturingCheckpointManager:
        def __init__(self) -> None:
            self.dataset_info = None

        @staticmethod
        def get_job_info(_job_name: str):
            return None

        def register_job(self, **kwargs):
            self.dataset_info = kwargs["dataset_info"]
            return True

    manager = _CapturingCheckpointManager()
    api_dataset_info = training.CheckpointDatasetInfo(
        camera_names=["cam_left", "cam_right"],
        action_dim=7,
        state_dim=7,
    )

    monkeypatch.setattr(
        training,
        "_get_dataset_info_from_manifest",
        lambda _dataset_id: api_dataset_info,
    )

    training._register_job_for_checkpoint_if_needed(manager, _job())

    assert isinstance(manager.dataset_info, StorageCheckpointDatasetInfo)
    assert manager.dataset_info.model_dump() == api_dataset_info.model_dump()


def test_save_job_with_registered_model_upserts_model_before_saving_job(monkeypatch):
    call_order: list[tuple[str, str]] = []

    async def fake_upsert_model(job_data: dict):
        call_order.append(("upsert", str(job_data["model_id"])))

    async def fake_save_job(job_data: dict):
        call_order.append(("save", str(job_data["model_id"])))

    monkeypatch.setattr(training, "_upsert_model_for_job", fake_upsert_model)
    monkeypatch.setattr(training, "_save_job", fake_save_job)

    asyncio.run(training._save_job_with_registered_model(_job()))

    assert call_order == [("upsert", "job-1"), ("save", "job-1")]


def test_build_rescue_checkpoint_model_identity_is_step_specific():
    step_1000_id, step_1000_name = training._build_rescue_checkpoint_model_identity(
        "job-1",
        "pick_place_train_20260309",
        1000,
    )
    same_step_id, same_step_name = training._build_rescue_checkpoint_model_identity(
        "job-1",
        "pick_place_train_20260309",
        1000,
    )
    step_1500_id, step_1500_name = training._build_rescue_checkpoint_model_identity(
        "job-1",
        "pick_place_train_20260309",
        1500,
    )

    assert step_1000_id == same_step_id
    assert step_1000_name == same_step_name
    assert step_1000_id != step_1500_id
    assert step_1000_name == "pick_place_train_20260309_step_001000"
    assert step_1500_name == "pick_place_train_20260309_step_001500"


def test_stop_job_stops_running_training_process(monkeypatch):
    saved_jobs: list[dict] = []
    archived_job_ids: list[str] = []

    async def fake_load_job(_job_id: str):
        return {
            **_job(),
            "status": "running",
            "instance_id": "instance-1",
        }

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    async def fake_archive_job_metrics(job_id: str):
        archived_job_ids.append(job_id)
        return True

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "_stop_remote_job", lambda _job_data: True)
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_archive_job_metrics", fake_archive_job_metrics)

    result = asyncio.run(training.stop_job("job-1"))

    assert result.success is True
    assert result.message == "Job stopped"
    assert saved_jobs[-1]["status"] == "stopped"
    assert saved_jobs[-1]["termination_reason"] == "USER_STOP"
    assert archived_job_ids == ["job-1"]


def test_stop_job_terminates_live_instance_for_completed_job(monkeypatch):
    saved_jobs: list[dict] = []
    archived_job_ids: list[str] = []

    async def fake_load_job(_job_id: str):
        return {
            **_job(),
            "status": "completed",
            "instance_id": "instance-1",
            "ip": "86.38.238.107",
        }

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    async def fake_archive_job_metrics(job_id: str):
        archived_job_ids.append(job_id)
        return True

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "_check_instance_status", lambda _job_data: "running")
    monkeypatch.setattr(training, "_delete_verda_instance", lambda _instance_id: True)
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_archive_job_metrics", fake_archive_job_metrics)

    result = asyncio.run(training.stop_job("job-1"))

    assert result.success is True
    assert result.message == "Instance stopped"
    assert saved_jobs[-1]["status"] == "completed"
    assert saved_jobs[-1]["ip"] is None
    assert archived_job_ids == []


def test_upload_selected_remote_checkpoint_registers_model(monkeypatch):
    manager = _DummyCheckpointManager(existing_steps=[])
    conn = _DummyConn()
    saved_jobs: list[dict] = []
    upserted: list[dict] = []
    call_order: list[str] = []
    progress: list[dict] = []

    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return _job()

    async def fake_save_job(job_data: dict):
        call_order.append("save")
        saved_jobs.append(dict(job_data))

    async def fake_upsert_model(job_data: dict):
        call_order.append("upsert")
        upserted.append(dict(job_data))

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(
        training,
        "_refresh_job_ssh_target_if_needed",
        lambda job_data: asyncio.sleep(0, result=job_data),
    )
    monkeypatch.setattr(training, "_get_ssh_connection_for_job", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: manager)
    monkeypatch.setattr(training, "_register_job_for_checkpoint_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        training,
        "_upload_remote_checkpoint_to_r2_direct",
        lambda *_args, **_kwargs: 1234,
    )
    monkeypatch.setattr(
        training,
        "_upload_remote_checkpoint_to_r2",
        lambda *_args, **_kwargs: 1234,
    )
    monkeypatch.setattr(
        training,
        "_ensure_model_artifact_in_r2_from_checkpoint",
        lambda *_args, **_kwargs: ("s3://daihen/v2/models/job-1", 1234, True),
    )
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_upsert_model_for_job", fake_upsert_model)

    expected_model_id, expected_model_name = training._build_rescue_checkpoint_model_identity(
        "job-1",
        "pick_place_train_20260309",
        1000,
    )

    result = asyncio.run(
        training._upload_selected_remote_checkpoint_with_progress(
            "job-1",
            "001000",
            progress.append,
        )
    )

    assert result["job_id"] == "job-1"
    assert result["step"] == 1000
    assert result["model_id"] == expected_model_id
    assert result["db_registered"] is True
    assert saved_jobs and saved_jobs[-1]["model_id"] == expected_model_id
    assert saved_jobs[-1]["model_name"] == expected_model_name
    assert saved_jobs[-1]["model_training_steps"] == 1000
    assert saved_jobs[-1]["model_size_bytes"] == 1234
    assert upserted and upserted[-1]["model_id"] == expected_model_id
    assert upserted[-1]["model_name"] == expected_model_name
    assert upserted[-1]["model_training_steps"] == 1000
    assert call_order == ["upsert", "save"]
    assert any(msg.get("type") == "model_registered" for msg in progress)
    assert any(msg.get("phase") == "registering_model" for msg in progress)
    assert all("progress_percent" in msg for msg in progress)
    assert conn.disconnected is True


def test_build_remote_checkpoint_upload_script_uses_thread_safe_progress_reporter():
    script = training._build_remote_checkpoint_upload_script()

    assert "import threading" in script
    assert "_emit_lock = threading.Lock()" in script
    assert "def progress_reporter() -> None:" in script
    assert "reporter = threading.Thread(target=progress_reporter, daemon=True)" in script
    assert "with progress_lock:" in script


def test_list_remote_job_checkpoints_returns_rescue_hint_when_ssh_unavailable(monkeypatch):
    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return {
            **_job(),
            "status": "terminated",
            "training_config": {"cloud": {"provider": "verda"}},
        }

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(
        training,
        "_refresh_job_ssh_target_if_needed",
        lambda job_data: asyncio.sleep(0, result=job_data),
    )
    monkeypatch.setattr(
        training,
        "_list_remote_checkpoint_dirs",
        lambda _job_data: (_ for _ in ()).throw(RuntimeError("SSH接続に失敗しました。インスタンス状態を確認してください。")),
    )
    monkeypatch.setattr(
        training.asyncio,
        "to_thread",
        lambda func, *args, **kwargs: asyncio.sleep(0, result=func(*args, **kwargs)),
    )

    response = asyncio.run(training.list_remote_job_checkpoints("job-1"))

    assert response.job_id == "job-1"
    assert response.checkpoint_names == []
    assert response.ssh_available is False
    assert response.requires_rescue_cpu is True
    assert "SSH接続に失敗" in response.message


def test_get_job_omits_training_job_operations_from_detail(monkeypatch):
    async def fake_load_job(_job_id: str):
        return {
            **_job(),
            "instance_id": "",
            "status": "completed",
            "mode": "train",
            "created_at": "2026-03-08T05:15:57.42918+00:00",
            "updated_at": "2026-03-08T05:15:57.42918+00:00",
        }

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "_get_latest_metrics", lambda _job_id: asyncio.sleep(0, result=({}, {})))
    monkeypatch.setattr(training, "_resolve_job_provision_operation", lambda _job_data: asyncio.sleep(0, result=None))

    response = asyncio.run(training.get_job("job-1"))

    assert response.job.job_id == "job-1"


def test_start_checkpoint_upload_operation_accepts_and_starts_background_worker(monkeypatch):
    started: list[dict] = []

    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return _job()

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "get_current_user_id", lambda: "user-1")
    monkeypatch.setattr(training, "get_supabase_session", lambda: {"user_id": "user-1"})

    accepted = training.TrainingJobOperationAcceptedResponse(
        accepted=True,
        operation_id="op-upload-1",
        job_id="job-1",
        kind="checkpoint_upload",
        state="queued",
        message="accepted",
        reused=False,
    )

    class _Ops:
        @staticmethod
        def create(**kwargs):
            started.append({"create": kwargs})
            return accepted

    monkeypatch.setattr(training, "get_training_job_operations_service", lambda: _Ops())
    monkeypatch.setattr(
        training,
        "_start_training_job_operation_thread",
        lambda **kwargs: started.append({"thread": kwargs}),
    )

    response = asyncio.run(
        training.start_checkpoint_upload_operation(
            "job-1",
            training.RemoteCheckpointUploadRequest(checkpoint_name="001000"),
        )
    )

    assert response.operation_id == "op-upload-1"
    assert started[0]["create"]["kind"] == "checkpoint_upload"
    assert started[1]["thread"]["operation_id"] == "op-upload-1"


def test_start_rescue_cpu_operation_reuses_active_operation(monkeypatch):
    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return _job()

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "get_current_user_id", lambda: "user-1")
    monkeypatch.setattr(training, "get_supabase_session", lambda: {"user_id": "user-1"})

    accepted = training.TrainingJobOperationAcceptedResponse(
        accepted=True,
        operation_id="op-rescue-1",
        job_id="job-1",
        kind="rescue_cpu",
        state="running",
        message="already_running",
        reused=True,
    )

    class _Ops:
        @staticmethod
        def create(**_kwargs):
            return accepted

    monkeypatch.setattr(training, "get_training_job_operations_service", lambda: _Ops())
    monkeypatch.setattr(
        training,
        "_start_training_job_operation_thread",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("thread should not start for reused operation")),
    )

    response = asyncio.run(training.start_rescue_cpu_operation("job-1"))

    assert response.operation_id == "op-rescue-1"
    assert response.reused is True


def test_upload_selected_remote_checkpoint_reports_db_failure(monkeypatch):
    manager = _DummyCheckpointManager(existing_steps=[])
    conn = _DummyConn()
    save_calls: list[dict] = []

    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        return _job()

    async def fake_save_job(job_data: dict):
        save_calls.append(dict(job_data))

    async def fake_upsert_model(_job_data: dict):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(
        training,
        "_refresh_job_ssh_target_if_needed",
        lambda job_data: asyncio.sleep(0, result=job_data),
    )
    monkeypatch.setattr(training, "_get_ssh_connection_for_job", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: manager)
    monkeypatch.setattr(training, "_register_job_for_checkpoint_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        training,
        "_upload_remote_checkpoint_to_r2_direct",
        lambda *_args, **_kwargs: 1234,
    )
    monkeypatch.setattr(
        training,
        "_upload_remote_checkpoint_to_r2",
        lambda *_args, **_kwargs: 1234,
    )
    monkeypatch.setattr(
        training,
        "_ensure_model_artifact_in_r2_from_checkpoint",
        lambda *_args, **_kwargs: ("s3://daihen/v2/models/job-1", 1234, True),
    )
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_upsert_model_for_job", fake_upsert_model)

    try:
        asyncio.run(
            training._upload_selected_remote_checkpoint_with_progress(
                "job-1",
                "001000",
                lambda _msg: None,
            )
        )
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 500
        assert "R2登録は完了しましたが、モデルのDB登録またはジョブ関連付けに失敗しました" in str(exc.detail)
    assert save_calls == []
    assert conn.disconnected is True


def test_upload_selected_remote_checkpoint_skips_r2_reupload_if_step_exists(monkeypatch):
    manager = _DummyCheckpointManager(existing_steps=[1000])
    saved_jobs: list[dict] = []
    upserted: list[dict] = []

    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return _job()

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    async def fake_upsert_model(job_data: dict):
        upserted.append(dict(job_data))

    def fail_if_called(*_args, **_kwargs):
        assert False, "SSH should not be used when checkpoint already exists in R2 index"

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(
        training,
        "_refresh_job_ssh_target_if_needed",
        lambda job_data: asyncio.sleep(0, result=job_data),
    )
    monkeypatch.setattr(training, "_get_ssh_connection_for_job", fail_if_called)
    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: manager)
    monkeypatch.setattr(
        training,
        "_upload_remote_checkpoint_to_r2_direct",
        fail_if_called,
    )
    monkeypatch.setattr(
        training,
        "_ensure_model_artifact_in_r2_from_checkpoint",
        lambda *_args, **_kwargs: ("s3://daihen/v2/models/job-1", 1234, False),
    )
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_upsert_model_for_job", fake_upsert_model)

    result = asyncio.run(
        training._upload_selected_remote_checkpoint_with_progress(
            "job-1",
            "001000",
            lambda _msg: None,
        )
    )

    assert result["step"] == 1000
    assert result["db_registered"] is True
    assert manager.upload_calls == []
    assert saved_jobs and upserted


def test_resolve_ssh_private_key_path_supports_project_relative(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "repo"
    key_path = project_root / "data" / "id_verda"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(training, "get_project_root", lambda: project_root)

    resolved = training._resolve_ssh_private_key_path("./data/id_verda")
    assert resolved == str(key_path)


def test_build_ssh_private_key_candidates_reads_relative_env_key(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "repo"
    key_path = project_root / "data" / "id_env"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text("dummy", encoding="utf-8")
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(training, "get_project_root", lambda: project_root)
    monkeypatch.setattr(training.Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.setenv("VERDA_SSH_PRIVATE_KEY", "./data/id_env")
    monkeypatch.delenv("VERDA_SSH_PRIVATE_KEYS", raising=False)
    monkeypatch.delenv("PHYSICAL_AI_DATA_DIR", raising=False)

    candidates = training._build_ssh_private_key_candidates(None)
    assert candidates
    assert candidates[0] == key_path


def test_build_ssh_private_key_candidates_discovers_keys_in_data_dir(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "repo"
    data_dir = project_root / "data"
    key_path = data_dir / "id_team_shared"
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path.write_text("dummy", encoding="utf-8")
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(training, "get_project_root", lambda: project_root)
    monkeypatch.setattr(training.Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.delenv("VERDA_SSH_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VERDA_SSH_PRIVATE_KEYS", raising=False)
    monkeypatch.setenv("PHYSICAL_AI_DATA_DIR", "./data")

    candidates = training._build_ssh_private_key_candidates(None)
    assert key_path in candidates


def test_refresh_job_ssh_target_if_needed_rebinds_to_running_rescue_cpu(monkeypatch):
    saved_jobs: list[dict] = []

    class _Inst:
        def __init__(self, iid: str, hostname: str, status: str, ip: str, created_at: str):
            self.id = iid
            self.hostname = hostname
            self.status = status
            self.ip = ip
            self.created_at = created_at

    class _Instances:
        @staticmethod
        def get():
            return [
                _Inst("old-rescue", "rescue-cpu-d2f7cdb2", "running", "86.38.238.109", "2026-02-19T12:30:00Z"),
                _Inst("new-rescue", "rescue-cpu-d2f7cdb2", "running", "86.38.238.110", "2026-02-19T12:33:52Z"),
            ]

    class _Client:
        instances = _Instances()

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    monkeypatch.setattr(training, "_check_instance_via_api", lambda _instance_id: "discontinued")
    monkeypatch.setattr(training, "_get_verda_client", lambda: _Client())
    monkeypatch.setattr(training, "_select_preferred_ssh_private_key", lambda _path: "/tmp/key")
    monkeypatch.setattr(training, "_save_job", fake_save_job)

    job = {
        "job_id": "d2f7cdb2-0b87-438a-b195-5b5cc70f4a67",
        "instance_id": "old-instance",
        "ip": "86.38.238.114",
        "ssh_user": "root",
        "ssh_private_key": "/old/key",
    }

    updated = asyncio.run(training._refresh_job_ssh_target_if_needed(dict(job)))
    assert updated["instance_id"] == "new-rescue"
    assert updated["ip"] == "86.38.238.110"
    assert updated["ssh_private_key"] == "/tmp/key"
    assert saved_jobs


def test_refresh_job_ssh_target_if_needed_keeps_current_when_not_stale(monkeypatch):
    async def fake_save_job(_job_data: dict):
        assert False, "should not persist when refresh is unnecessary"

    monkeypatch.setattr(training, "_check_instance_via_api", lambda _instance_id: "running")
    monkeypatch.setattr(training, "_get_verda_client", lambda: None)
    monkeypatch.setattr(training, "_save_job", fake_save_job)

    job = {
        "job_id": "d2f7cdb2-0b87-438a-b195-5b5cc70f4a67",
        "instance_id": "inst-running",
        "ip": "86.38.238.110",
        "ssh_user": "root",
        "ssh_private_key": "/tmp/key",
    }

    updated = asyncio.run(training._refresh_job_ssh_target_if_needed(dict(job)))
    assert updated["instance_id"] == "inst-running"
    assert updated["ip"] == "86.38.238.110"


def test_refresh_job_status_from_instance_uses_vast_provider(monkeypatch):
    saved_jobs: list[dict] = []
    providers_pkg = types.ModuleType("percus_ai.training.providers")
    vast_module = types.ModuleType("percus_ai.training.providers.vast")

    class _VastInstance:
        status = None
        ip = "ssh8.vast.ai"
        ssh_port = 15434

    def _get_instance(_instance_id: str):
        return _VastInstance()

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    vast_module.get_instance = _get_instance
    monkeypatch.setitem(sys.modules, "percus_ai.training.providers", providers_pkg)
    monkeypatch.setitem(sys.modules, "percus_ai.training.providers.vast", vast_module)
    monkeypatch.setattr(training, "_save_job", fake_save_job)

    job = {
        "job_id": "job-vast-1",
        "instance_id": "32405434",
        "status": "running",
        "training_config": {"cloud": {"provider": "vast"}},
    }

    instance_status = asyncio.run(training._refresh_job_status_from_instance(job))
    assert instance_status == "running"
    assert job["status"] == "running"
    assert not saved_jobs


def test_refresh_job_status_from_instance_marks_vast_not_found(monkeypatch):
    saved_jobs: list[dict] = []
    providers_pkg = types.ModuleType("percus_ai.training.providers")
    vast_module = types.ModuleType("percus_ai.training.providers.vast")

    def _get_instance(_instance_id: str):
        raise RuntimeError("404 not found")

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    vast_module.get_instance = _get_instance
    monkeypatch.setitem(sys.modules, "percus_ai.training.providers", providers_pkg)
    monkeypatch.setitem(sys.modules, "percus_ai.training.providers.vast", vast_module)
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_refresh_job_ssh_target_if_needed", lambda job_data: asyncio.sleep(0, result=job_data))
    monkeypatch.setattr(training, "_check_remote_status", lambda _job_data: "unreachable")
    monkeypatch.setattr(training, "_has_recent_training_metrics", lambda _job_id: asyncio.sleep(0, result=False))

    job = {
        "job_id": "job-vast-2",
        "instance_id": "dead-instance",
        "status": "running",
        "training_config": {"cloud": {"provider": "vast"}},
    }

    instance_status = asyncio.run(training._refresh_job_status_from_instance(job))
    assert instance_status is None
    assert job["status"] == "terminated"
    assert job["termination_reason"] == "INSTANCE_NOT_FOUND"
    assert saved_jobs and saved_jobs[-1]["status"] == "terminated"


def test_refresh_job_status_from_instance_keeps_vast_running_when_provider_missing(monkeypatch):
    saved_jobs: list[dict] = []
    providers_pkg = types.ModuleType("percus_ai.training.providers")
    vast_module = types.ModuleType("percus_ai.training.providers.vast")

    def _get_instance(_instance_id: str):
        raise RuntimeError("404 not found")

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    vast_module.get_instance = _get_instance
    monkeypatch.setitem(sys.modules, "percus_ai.training.providers", providers_pkg)
    monkeypatch.setitem(sys.modules, "percus_ai.training.providers.vast", vast_module)
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_check_remote_status", lambda _job_data: "running")

    job = {
        "job_id": "job-vast-keep-1",
        "instance_id": "dead-instance",
        "ip": "ssh8.vast.ai",
        "ssh_port": 15434,
        "status": "running",
        "training_config": {"cloud": {"provider": "vast", "ssh_port": 15434}},
    }

    instance_status = asyncio.run(training._refresh_job_status_from_instance(job))
    assert instance_status == "running"
    assert job["status"] == "running"
    assert "termination_reason" not in job
    assert not saved_jobs


def test_refresh_job_status_from_instance_keeps_vast_running_when_recent_metrics_exist(monkeypatch):
    saved_jobs: list[dict] = []

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_check_instance_status", lambda _job_data: "terminated")
    monkeypatch.setattr(training, "_refresh_job_ssh_target_if_needed", lambda job_data: asyncio.sleep(0, result=job_data))
    monkeypatch.setattr(training, "_check_remote_status", lambda _job_data: "unreachable")
    monkeypatch.setattr(training, "_has_recent_training_metrics", lambda _job_id: asyncio.sleep(0, result=True))

    job = {
        "job_id": "job-vast-metrics-1",
        "instance_id": "32405434",
        "ip": "ssh8.vast.ai",
        "ssh_port": 15434,
        "status": "running",
        "training_config": {"cloud": {"provider": "vast", "ssh_port": 15434}},
    }

    instance_status = asyncio.run(training._refresh_job_status_from_instance(job))
    assert instance_status == "running"
    assert job["status"] == "running"
    assert "termination_reason" not in job
    assert not saved_jobs


def test_refresh_job_ssh_target_if_needed_updates_vast_port(monkeypatch):
    saved_jobs: list[dict] = []
    providers_pkg = types.ModuleType("percus_ai.training.providers")
    vast_module = types.ModuleType("percus_ai.training.providers.vast")

    class _VastInstance:
        ip = "ssh8.vast.ai"
        ssh_port = 21456

    def _get_instance(_instance_id: str):
        return _VastInstance()

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    vast_module.get_instance = _get_instance
    monkeypatch.setitem(sys.modules, "percus_ai.training.providers", providers_pkg)
    monkeypatch.setitem(sys.modules, "percus_ai.training.providers.vast", vast_module)
    monkeypatch.setattr(training, "_save_job", fake_save_job)

    job = {
        "job_id": "job-vast-port-1",
        "instance_id": "32405434",
        "ip": "ssh8.vast.ai",
        "ssh_port": 15434,
        "training_config": {"cloud": {"provider": "vast", "ssh_port": 15434}},
    }

    updated = asyncio.run(training._refresh_job_ssh_target_if_needed(dict(job)))
    assert updated["ssh_port"] == 21456
    assert updated["training_config"]["cloud"]["ssh_port"] == 21456
    assert saved_jobs and saved_jobs[-1]["ssh_port"] == 21456


def test_get_instance_status_uses_provider_aware_status_checker(monkeypatch):
    async def fake_load_job(_job_id: str):
        return {
            "job_id": "job-vast-status-1",
            "instance_id": "32405434",
            "ip": "ssh8.vast.ai",
            "status": "running",
            "training_config": {"cloud": {"provider": "vast"}},
        }

    called = {"count": 0}

    def fake_check_instance_status(job_data: dict):
        called["count"] += 1
        assert job_data["instance_id"] == "32405434"
        return "running"

    def fail_if_called(*_args, **_kwargs):
        assert False, "_check_instance_via_api should not be called for instance-status endpoint"

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "_check_instance_status", fake_check_instance_status)
    monkeypatch.setattr(training, "_check_instance_via_api", fail_if_called)
    monkeypatch.setattr(training, "_check_remote_status", lambda _job_data: "running")

    response = asyncio.run(training.get_instance_status("job-vast-status-1"))
    assert response.instance_status == "running"
    assert response.remote_process_status == "running"
    assert response.message == "Instance running, training in progress"
    assert called["count"] == 1


def test_check_all_jobs_status_keeps_vast_running_when_remote_running(monkeypatch):
    saved_jobs: list[dict] = []
    archived_jobs: list[str] = []

    async def fake_list_jobs(*_args, **_kwargs):
        return (
            [
                {
                    "job_id": "job-vast-bulk-1",
                    "instance_id": "32405434",
                    "ip": "ssh8.vast.ai",
                    "ssh_port": 15434,
                    "status": "running",
                    "training_config": {"cloud": {"provider": "vast", "ssh_port": 15434}},
                }
            ],
            1,
        )

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    async def fake_archive_job_metrics(job_id: str):
        archived_jobs.append(job_id)

    monkeypatch.setattr(training, "_list_jobs", fake_list_jobs)
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_archive_job_metrics", fake_archive_job_metrics)
    monkeypatch.setattr(training, "_check_instance_status", lambda _job_data: None)
    monkeypatch.setattr(training, "_refresh_job_ssh_target_if_needed", lambda job_data: asyncio.sleep(0, result=job_data))
    monkeypatch.setattr(training, "_check_remote_status", lambda _job_data: "running")

    response = asyncio.run(training.check_all_jobs_status())
    assert response.checked_count == 1
    assert response.updates[0].new_status == "running"
    assert response.updates[0].instance_status == "running"
    assert "stale" in response.updates[0].reason.lower()
    assert not saved_jobs
    assert not archived_jobs


def test_check_all_jobs_status_keeps_vast_running_when_recent_metrics_exist(monkeypatch):
    saved_jobs: list[dict] = []
    archived_jobs: list[str] = []

    async def fake_list_jobs(*_args, **_kwargs):
        return (
            [
                {
                    "job_id": "job-vast-bulk-2",
                    "instance_id": "32405435",
                    "ip": "ssh8.vast.ai",
                    "ssh_port": 15435,
                    "status": "running",
                    "training_config": {"cloud": {"provider": "vast", "ssh_port": 15435}},
                }
            ],
            1,
        )

    async def fake_save_job(job_data: dict):
        saved_jobs.append(dict(job_data))

    async def fake_archive_job_metrics(job_id: str):
        archived_jobs.append(job_id)

    monkeypatch.setattr(training, "_list_jobs", fake_list_jobs)
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_archive_job_metrics", fake_archive_job_metrics)
    monkeypatch.setattr(training, "_check_instance_status", lambda _job_data: "terminated")
    monkeypatch.setattr(training, "_refresh_job_ssh_target_if_needed", lambda job_data: asyncio.sleep(0, result=job_data))
    monkeypatch.setattr(training, "_check_remote_status", lambda _job_data: "unreachable")
    monkeypatch.setattr(training, "_has_recent_training_metrics", lambda _job_id: asyncio.sleep(0, result=True))

    response = asyncio.run(training.check_all_jobs_status())
    assert response.checked_count == 1
    assert response.updates[0].new_status == "running"
    assert response.updates[0].instance_status == "running"
    assert "recent metrics" in response.updates[0].reason.lower()
    assert not saved_jobs
    assert not archived_jobs


def test_list_jobs_passes_owner_user_id_filter(monkeypatch):
    captured: dict = {}

    async def fake_list_jobs(days: int = 365, owner_user_id: str | None = None, **kwargs):
        captured["days"] = days
        captured["owner_user_id"] = owner_user_id
        captured["kwargs"] = kwargs
        return [], 0, [], [], []

    monkeypatch.setattr(training, "_list_jobs", fake_list_jobs)

    response = asyncio.run(training.list_jobs(days=30, owner_user_id="user-123"))
    assert response.total == 0
    assert captured["days"] == 30
    assert captured["owner_user_id"] == "user-123"
    assert set(captured["kwargs"]) == {
        "search",
        "status",
        "policy_type",
        "created_from",
        "created_to",
        "sort_by",
        "sort_order",
        "limit",
        "offset",
    }


def test_parse_job_created_at_accepts_five_digit_fraction():
    parsed = training._parse_job_created_at("2026-03-08T05:15:57.42918+00:00")
    assert parsed.isoformat() == "2026-03-08T05:15:57.429180+00:00"


def test_list_jobs_includes_recent_vast_jobs_with_five_digit_fraction(monkeypatch):
    rows = [
        {
            "job_id": "job-vast-1",
            "status": "completed",
            "created_at": "2026-03-08T05:15:57.42918+00:00",
            "deleted_at": None,
        },
        {
            "job_id": "job-vast-2",
            "status": "terminated",
            "created_at": "2026-03-08T04:39:08.34181+00:00",
            "deleted_at": None,
        },
    ]

    class _Query:
        def select(self, *_args, **_kwargs):
            return self

        def is_(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        async def execute(self):
            return types.SimpleNamespace(data=rows)

    class _Client:
        def table(self, _name: str):
            return _Query()

    async def fake_get_supabase_async_client():
        return _Client()

    async def fake_resolve_user_directory_entries(_user_ids):
        return {}

    async def fake_resolve_dataset_names(_dataset_ids):
        return {}

    monkeypatch.setattr(training, "get_supabase_async_client", fake_get_supabase_async_client)
    monkeypatch.setattr(training, "resolve_user_directory_entries", fake_resolve_user_directory_entries)
    monkeypatch.setattr(training, "_resolve_dataset_names", fake_resolve_dataset_names)

    jobs, total, *_ = asyncio.run(training._list_jobs(days=365))
    assert total == 2
    assert [job["job_id"] for job in jobs] == ["job-vast-1", "job-vast-2"]


def test_list_jobs_status_filter_uses_query_parameter(monkeypatch):
    rows = [
        {
            "job_id": "job-1",
            "job_name": "first completed",
            "status": "completed",
            "policy_type": "pi05",
            "owner_user_id": "user-1",
            "created_at": "2026-03-08T05:15:57.42918+00:00",
            "deleted_at": None,
        },
        {
            "job_id": "job-2",
            "job_name": "second failed",
            "status": "failed",
            "policy_type": "pi05",
            "owner_user_id": "user-1",
            "created_at": "2026-03-08T04:39:08.34181+00:00",
            "deleted_at": None,
        },
    ]

    class _Query:
        def select(self, *_args, **_kwargs):
            return self

        def is_(self, *_args, **_kwargs):
            return self

        async def execute(self):
            return types.SimpleNamespace(data=rows)

    class _Client:
        def table(self, _name: str):
            return _Query()

    async def fake_get_supabase_async_client():
        return _Client()

    async def fake_resolve_user_directory_entries(_user_ids):
        return {}

    async def fake_resolve_dataset_names(_dataset_ids):
        return {}

    monkeypatch.setattr(training, "get_supabase_async_client", fake_get_supabase_async_client)
    monkeypatch.setattr(training, "resolve_user_directory_entries", fake_resolve_user_directory_entries)
    monkeypatch.setattr(training, "_resolve_dataset_names", fake_resolve_dataset_names)

    jobs, total, _, status_options, _ = asyncio.run(training._list_jobs(days=365, status="failed"))

    assert total == 1
    assert [job["job_id"] for job in jobs] == ["job-2"]
    assert [(option.value, option.total_count, option.available_count) for option in status_options] == [
        ("completed", 1, 1),
        ("failed", 1, 1),
    ]


def test_rescue_cpu_rejects_non_verda_job(monkeypatch):
    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return {
            "job_id": "job-vast-rescue-1",
            "instance_id": "32405434",
            "training_config": {"cloud": {"provider": "vast"}},
        }

    def fail_if_called():
        assert False, "_get_verda_client should not be called for non-verda rescue-cpu"

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(training, "_get_verda_client", fail_if_called)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(training._rescue_cpu_job_with_progress("job-vast-rescue-1", lambda _msg: None))
    assert exc.value.status_code == 400
    assert "cloud.provider=verda" in str(exc.value.detail)


def test_pick_os_volume_from_instance_record_uses_instance_os_volume_id_for_detached_volume():
    class _Volume:
        def __init__(self):
            self.id = "vol-detached-1"
            self.status = "detached"
            self.name = "os-lerobot-1773470371"
            self.size = 400
            self.type = "NVMe"
            self.is_os_volume = True
            self.created_at = "2026-03-14T06:39:32.974Z"
            self.location = "FIN-03"
            self.instance_id = None
            self.deleted_at = None

    class _Instances:
        @staticmethod
        def get_by_id(instance_id: str):
            assert instance_id == "instance-1"
            return types.SimpleNamespace(os_volume_id="vol-detached-1")

    class _Volumes:
        @staticmethod
        def get_by_id(_volume_id: str):
            raise AssertionError("cache hit should avoid direct volume lookup")

    client = types.SimpleNamespace(instances=_Instances(), volumes=_Volumes())
    volume = _Volume()

    picked = training._pick_os_volume_from_instance_record(
        client,
        {"vol-detached-1": ("active", volume)},
        "instance-1",
    )

    assert picked == ("active", volume)


def test_pick_os_volume_from_instance_record_fetches_volume_detail_when_not_cached():
    class _Volume:
        def __init__(self):
            self.id = "vol-deleted-1"
            self.status = "deleted"
            self.name = "os-lerobot-1773447130"
            self.size = 400
            self.type = "NVMe"
            self.is_os_volume = True
            self.created_at = "2026-03-14T00:12:11.871Z"
            self.location = "FIN-03"
            self.instance_id = None
            self.deleted_at = "2026-03-14T21:40:08.913Z"

    class _Instances:
        @staticmethod
        def get_by_id(instance_id: str):
            assert instance_id == "instance-2"
            return types.SimpleNamespace(os_volume_id="vol-deleted-1")

    class _Volumes:
        @staticmethod
        def get_by_id(volume_id: str):
            assert volume_id == "vol-deleted-1"
            return _Volume()

    client = types.SimpleNamespace(instances=_Instances(), volumes=_Volumes())

    picked = training._pick_os_volume_from_instance_record(client, {}, "instance-2")

    assert picked is not None
    state, volume = picked
    assert state == "deleted"
    assert volume.id == "vol-deleted-1"


def test_wait_for_volume_detached_requires_detached_status(monkeypatch):
    volumes = [
        types.SimpleNamespace(id="vol-1", status="attached", instance_id=None),
        types.SimpleNamespace(id="vol-1", status="detached", instance_id=None),
    ]

    class _Volumes:
        def get_by_id(self, volume_id: str):
            assert volume_id == "vol-1"
            return volumes.pop(0)

    client = types.SimpleNamespace(volumes=_Volumes())
    sleep_calls: list[float] = []
    monkeypatch.setattr(training.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    training._wait_for_volume_detached(client, "vol-1", timeout_sec=10)

    assert sleep_calls == [5]


def test_create_verda_instance_from_volume_retries_until_detached(monkeypatch):
    calls: list[str] = []

    class _Instances:
        def create(self, **kwargs):
            calls.append(kwargs["image"])
            if len(calls) == 1:
                raise RuntimeError("error code: invalid_request message: OS volume must be detached")
            return types.SimpleNamespace(id="new-instance-1")

    client = types.SimpleNamespace(instances=_Instances())
    progress: list[dict] = []
    waited: list[tuple[str, int]] = []
    slept: list[float] = []

    monkeypatch.setattr(
        training,
        "_wait_for_volume_detached",
        lambda _client, volume_id, timeout_sec=20: waited.append((volume_id, timeout_sec)),
    )
    monkeypatch.setattr(training.time, "sleep", lambda seconds: slept.append(seconds))

    instance = training._create_verda_instance_from_volume(
        client,
        volume_id="vol-1",
        instance_type="cpu.small",
        ssh_key_id="ssh-1",
        location="FIN-02",
        hostname="rescue-cpu-job",
        description="Rescue CPU job",
        emit_progress=progress.append,
        retry_timeout_sec=30,
    )

    assert instance.id == "new-instance-1"
    assert calls == ["vol-1", "vol-1"]
    assert waited == [("vol-1", 20)]
    assert slept == [5]
    assert any(msg.get("type") == "waiting_detach_propagation" for msg in progress)


def test_get_ssh_connection_for_job_uses_cloud_ssh_port(monkeypatch, tmp_path: Path):
    key_path = tmp_path / "id_test"
    key_path.write_text("dummy", encoding="utf-8")
    captured: dict = {}

    class _Conn:
        def __init__(self, *, host, user, private_key_path, port=22):
            captured["host"] = host
            captured["user"] = user
            captured["private_key_path"] = str(private_key_path)
            captured["port"] = port

        def connect(self, timeout_sec: int = 30):
            captured["timeout_sec"] = timeout_sec

    monkeypatch.setattr(training, "SSHConnection", _Conn)
    monkeypatch.setattr(training, "_build_ssh_user_candidates", lambda _u: ["root"])
    monkeypatch.setattr(training, "_build_ssh_private_key_candidates", lambda _k: [key_path])

    job = {
        "job_id": "job-port-1",
        "ip": "ssh8.vast.ai",
        "ssh_user": "root",
        "ssh_private_key": str(key_path),
        "training_config": {"cloud": {"provider": "vast", "ssh_port": 15434}},
    }
    conn = training._get_ssh_connection_for_job(job, timeout=17)
    assert conn is not None
    assert captured["host"] == "ssh8.vast.ai"
    assert captured["port"] == 15434
    assert captured["timeout_sec"] == 17


def test_upsert_model_for_job_includes_checkpoint_size_and_latest_step(monkeypatch):
    captured: dict = {}

    class _Entry:
        latest_step = 1000
        size_mb = 18.5

    class _CheckpointMgr:
        @staticmethod
        def get_job_info(job_name: str):
            if job_name == "job-1":
                return _Entry()
            return None

    async def fake_upsert_with_owner(_table: str, _key: str, payload: dict):
        captured.update(payload)

    async def fake_load_existing_model_name(_model_id: str):
        return None

    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: _CheckpointMgr())
    monkeypatch.setattr(training, "_load_existing_model_name", fake_load_existing_model_name)
    monkeypatch.setattr(training, "upsert_with_owner", fake_upsert_with_owner)

    job_data = {
        "job_id": "job-1",
        "job_name": "pick_place_train_20260222",
        "dataset_id": "dataset-1",
        "policy_type": "pi0",
        "training_config": {"training": {"steps": 9999, "batch_size": 4}},
        "profile_instance_id": "profile-1",
        "profile_snapshot": {"name": "so101_dual_teleop"},
    }
    asyncio.run(training._upsert_model_for_job(job_data))

    assert captured["id"] == "job-1"
    assert captured["name"] == "pick_place_train_20260222"
    assert captured["training_steps"] == 1000
    assert captured["size_bytes"] == int(18.5 * 1024 * 1024)


def test_upsert_model_for_job_resolves_checkpoint_by_job_name(monkeypatch):
    captured: dict = {}

    class _Entry:
        latest_step = 2000
        size_mb = 5.0

    class _CheckpointMgr:
        @staticmethod
        def get_job_info(job_name: str):
            if job_name == "pick_place_train_20260309":
                return _Entry()
            return None

    async def fake_upsert_with_owner(_table: str, _key: str, payload: dict):
        captured.update(payload)

    async def fake_load_existing_model_name(_model_id: str):
        return None

    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: _CheckpointMgr())
    monkeypatch.setattr(training, "_load_existing_model_name", fake_load_existing_model_name)
    monkeypatch.setattr(training, "upsert_with_owner", fake_upsert_with_owner)

    job_data = {
        "job_id": "job-1",
        "job_name": "pick_place_train_20260309",
        "dataset_id": "dataset-1",
        "policy_type": "pi0",
        "training_config": {"training": {"steps": 9999, "batch_size": 4}},
        "profile_instance_id": "profile-1",
        "profile_snapshot": {"name": "so101_dual_teleop"},
    }
    asyncio.run(training._upsert_model_for_job(job_data))

    assert captured["id"] == "job-1"
    assert captured["name"] == "pick_place_train_20260309"
    assert captured["training_steps"] == 2000
    assert captured["size_bytes"] == int(5.0 * 1024 * 1024)


def test_upsert_model_for_job_skips_size_when_checkpoint_missing(monkeypatch):
    captured: dict = {}

    class _CheckpointMgr:
        @staticmethod
        def get_job_info(_job_name: str):
            return None

    async def fake_upsert_with_owner(_table: str, _key: str, payload: dict):
        captured.update(payload)

    async def fake_load_existing_model_name(_model_id: str):
        return None

    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: _CheckpointMgr())
    monkeypatch.setattr(training, "_load_existing_model_name", fake_load_existing_model_name)
    monkeypatch.setattr(training, "upsert_with_owner", fake_upsert_with_owner)

    job_data = {
        "job_id": "job-2",
        "dataset_id": "dataset-2",
        "policy_type": "pi0",
        "training_config": {"training": {"steps": 3000, "batch_size": 4}},
        "profile_instance_id": "profile-1",
        "profile_snapshot": {"name": "so101_dual_teleop"},
    }
    asyncio.run(training._upsert_model_for_job(job_data))

    assert captured["id"] == "job-2"
    assert captured["name"] == "job-2"
    assert captured["training_steps"] == 3000
    assert "size_bytes" not in captured


def test_upsert_model_for_job_preserves_custom_existing_name(monkeypatch):
    captured: dict = {}

    class _CheckpointMgr:
        @staticmethod
        def get_job_info(_job_name: str):
            return None

    async def fake_upsert_with_owner(_table: str, _key: str, payload: dict):
        captured.update(payload)

    async def fake_load_existing_model_name(_model_id: str):
        return "custom_name"

    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: _CheckpointMgr())
    monkeypatch.setattr(training, "_load_existing_model_name", fake_load_existing_model_name)
    monkeypatch.setattr(training, "upsert_with_owner", fake_upsert_with_owner)

    job_data = {
        "job_id": "job-3",
        "job_name": "train_job_name_should_not_overwrite",
        "dataset_id": "dataset-3",
        "profile_instance_id": "profile-3",
        "profile_snapshot": {"name": "so101_dual_teleop"},
        "policy_type": "pi0",
        "training_config": {"training": {"steps": 100, "batch_size": 2}},
    }
    asyncio.run(training._upsert_model_for_job(job_data))

    assert captured["id"] == "job-3"
    assert captured["name"] == "custom_name"


def test_upsert_model_for_job_prefers_explicit_rescue_name_and_step(monkeypatch):
    captured: dict = {}

    class _Entry:
        latest_step = 15000
        size_mb = 42.0

    class _CheckpointMgr:
        @staticmethod
        def get_job_info(job_name: str):
            if job_name == "pick_place_train_20260309":
                return _Entry()
            return None

    async def fake_upsert_with_owner(_table: str, _key: str, payload: dict):
        captured.update(payload)

    async def fake_load_existing_model_name(_model_id: str):
        return None

    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: _CheckpointMgr())
    monkeypatch.setattr(training, "_load_existing_model_name", fake_load_existing_model_name)
    monkeypatch.setattr(training, "upsert_with_owner", fake_upsert_with_owner)

    job_data = {
        "job_id": "job-1",
        "job_name": "pick_place_train_20260309",
        "model_id": "model-step-10000",
        "model_name": "pick_place_train_20260309_step_010000",
        "model_training_steps": 10000,
        "dataset_id": "dataset-1",
        "policy_type": "pi0",
        "training_config": {"training": {"steps": 9999, "batch_size": 4}},
        "profile_instance_id": "profile-1",
        "profile_snapshot": {"name": "so101_dual_teleop"},
    }
    asyncio.run(training._upsert_model_for_job(job_data))

    assert captured["id"] == "model-step-10000"
    assert captured["name"] == "pick_place_train_20260309_step_010000"
    assert captured["training_steps"] == 10000
    assert captured["size_bytes"] == int(42.0 * 1024 * 1024)


def test_upload_selected_remote_checkpoint_uses_job_name_for_r2_paths(monkeypatch):
    manager = _DummyCheckpointManager(existing_steps=[])
    conn = _DummyConn()
    captured: dict = {}
    progress: list[dict] = []

    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return _job()

    async def fake_save_job(_job_data: dict):
        return None

    async def fake_upsert_model(_job_data: dict):
        return None

    def fake_ensure_model_artifact(_checkpoint_mgr, *, checkpoint_job_name: str, model_id: str, step: int):
        captured["checkpoint_job_name"] = checkpoint_job_name
        captured["model_id"] = model_id
        captured["step"] = step
        return "s3://daihen/v2/models/job-1", 1234, True

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(
        training,
        "_refresh_job_ssh_target_if_needed",
        lambda job_data: asyncio.sleep(0, result=job_data),
    )
    monkeypatch.setattr(training, "_get_ssh_connection_for_job", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: manager)
    monkeypatch.setattr(training, "_register_job_for_checkpoint_if_needed", lambda *_args, **_kwargs: None)
    def fake_upload_remote_checkpoint_direct(
        _checkpoint_mgr,
        _conn,
        *,
        job_data: dict,
        checkpoint_job_name: str,
        step: int,
        remote_checkpoint_path: str,
        emit_progress,
    ):
        captured["job_data_job_id"] = job_data["job_id"]
        manager.upload_calls.append(
            {
                "job_name": checkpoint_job_name,
                "step": step,
                "remote_checkpoint_path": remote_checkpoint_path,
            }
        )
        emit_progress({"type": "uploaded", "message": "R2登録が完了しました", "step": step})
        return 1234

    monkeypatch.setattr(training, "_upload_remote_checkpoint_to_r2_direct", fake_upload_remote_checkpoint_direct)
    def fake_upload_remote_checkpoint(
        _checkpoint_mgr,
        _conn,
        *,
        checkpoint_job_name: str,
        step: int,
        remote_checkpoint_path: str,
        emit_progress,
    ):
        manager.upload_calls.append(
            {
                "job_name": checkpoint_job_name,
                "step": step,
                "remote_checkpoint_path": remote_checkpoint_path,
            }
        )
        emit_progress({"type": "uploaded", "message": "R2登録が完了しました", "step": step})
        return 1234

    monkeypatch.setattr(training, "_upload_remote_checkpoint_to_r2", fake_upload_remote_checkpoint)
    monkeypatch.setattr(training, "_ensure_model_artifact_in_r2_from_checkpoint", fake_ensure_model_artifact)
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_upsert_model_for_job", fake_upsert_model)

    expected_model_id, expected_model_name = training._build_rescue_checkpoint_model_identity(
        "job-1",
        "pick_place_train_20260309",
        1000,
    )

    result = asyncio.run(
        training._upload_selected_remote_checkpoint_with_progress(
            "job-1",
            "001000",
            progress.append,
        )
    )

    assert manager.upload_calls[0]["job_name"] == "pick_place_train_20260309"
    assert captured["checkpoint_job_name"] == "pick_place_train_20260309"
    assert captured["model_id"] == expected_model_id
    assert captured["job_data_job_id"] == "job-1"
    assert result["model_id"] == expected_model_id
    assert result["r2_step_path"] == "s3://daihen/v2/checkpoints/pick_place_train_20260309/step_001000"


def test_upload_selected_remote_checkpoint_falls_back_when_direct_upload_fails(monkeypatch):
    manager = _DummyCheckpointManager(existing_steps=[])
    conn = _DummyConn()
    progress: list[dict] = []
    fallback_calls: list[dict] = []

    async def fake_load_job(_job_id: str, include_deleted: bool = False):
        assert include_deleted is True
        return _job()

    async def fake_save_job(_job_data: dict):
        return None

    async def fake_upsert_model(_job_data: dict):
        return None

    monkeypatch.setattr(training, "_load_job", fake_load_job)
    monkeypatch.setattr(
        training,
        "_refresh_job_ssh_target_if_needed",
        lambda job_data: asyncio.sleep(0, result=job_data),
    )
    monkeypatch.setattr(training, "_get_ssh_connection_for_job", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(training, "_get_checkpoint_index_manager", lambda: manager)
    monkeypatch.setattr(training, "_register_job_for_checkpoint_if_needed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        training,
        "_upload_remote_checkpoint_to_r2_direct",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("direct path failed")),
    )

    def fake_fallback_upload(
        _checkpoint_mgr,
        _conn,
        *,
        checkpoint_job_name: str,
        step: int,
        remote_checkpoint_path: str,
        emit_progress,
    ):
        fallback_calls.append(
            {
                "job_name": checkpoint_job_name,
                "step": step,
                "remote_checkpoint_path": remote_checkpoint_path,
            }
        )
        emit_progress({"type": "uploaded", "message": "R2登録が完了しました", "step": step})
        return 1234

    monkeypatch.setattr(training, "_upload_remote_checkpoint_to_r2", fake_fallback_upload)
    monkeypatch.setattr(
        training,
        "_ensure_model_artifact_in_r2_from_checkpoint",
        lambda *_args, **_kwargs: ("s3://daihen/v2/models/job-1", 1234, True),
    )
    monkeypatch.setattr(training, "_save_job", fake_save_job)
    monkeypatch.setattr(training, "_upsert_model_for_job", fake_upsert_model)

    result = asyncio.run(
        training._upload_selected_remote_checkpoint_with_progress(
            "job-1",
            "001000",
            progress.append,
        )
    )

    assert result["step"] == 1000
    assert fallback_calls and fallback_calls[0]["job_name"] == "pick_place_train_20260309"
    assert any(msg.get("type") == "direct_upload_fallback" for msg in progress)


def test_ensure_model_artifact_in_r2_from_checkpoint_skips_when_model_exists():
    class _CopyClient:
        calls: list[tuple[dict, str, str]] = []

        def copy(self, source: dict, bucket: str, key: str):
            self.calls.append((source, bucket, key))

    class _S3:
        def __init__(self):
            self.client = _CopyClient()

        @staticmethod
        def list_objects(path: str):
            if path == "s3://daihen/v2/models/job-1/":
                return [{"Key": "v2/models/job-1/config.json", "Size": 10}]
            return []

    class _Sync:
        bucket = "daihen"
        s3 = _S3()

        @staticmethod
        def _get_prefix() -> str:
            return "v2/"

    class _Mgr:
        sync = _Sync()

    path, size_bytes, copied = training._ensure_model_artifact_in_r2_from_checkpoint(
        _Mgr(),
        checkpoint_job_name="pick_place_train_20260309",
        model_id="job-1",
        step=1000,
    )

    assert path == "s3://daihen/v2/models/job-1"
    assert size_bytes == 10
    assert copied is False
    assert _Mgr.sync.s3.client.calls == []


def test_ensure_model_artifact_in_r2_from_checkpoint_copies_from_checkpoint():
    class _CopyClient:
        def __init__(self):
            self.calls: list[tuple[dict, str, str]] = []

        def copy(self, source: dict, bucket: str, key: str):
            self.calls.append((source, bucket, key))

    class _S3:
        def __init__(self):
            self.client = _CopyClient()

        @staticmethod
        def list_objects(path: str):
            if path == "s3://daihen/v2/models/job-1/":
                return []
            if path == "s3://daihen/v2/checkpoints/pick_place_train_20260309/step_001000/pretrained_model/":
                return [
                    {
                        "Key": "v2/checkpoints/pick_place_train_20260309/step_001000/pretrained_model/config.json",
                        "Size": 3,
                    },
                    {
                        "Key": "v2/checkpoints/pick_place_train_20260309/step_001000/pretrained_model/model.safetensors",
                        "Size": 7,
                    },
                ]
            return []

    class _Sync:
        bucket = "daihen"

        def __init__(self):
            self.s3 = _S3()

        @staticmethod
        def _get_prefix() -> str:
            return "v2/"

    class _Mgr:
        def __init__(self):
            self.sync = _Sync()

    mgr = _Mgr()
    path, size_bytes, copied = training._ensure_model_artifact_in_r2_from_checkpoint(
        mgr,
        checkpoint_job_name="pick_place_train_20260309",
        model_id="job-1",
        step=1000,
    )

    assert path == "s3://daihen/v2/models/job-1"
    assert size_bytes == 10
    assert copied is True
    assert len(mgr.sync.s3.client.calls) == 2
    assert mgr.sync.s3.client.calls[0][2] == "v2/models/job-1/config.json"
    assert mgr.sync.s3.client.calls[1][2] == "v2/models/job-1/model.safetensors"


def test_generate_env_file_reads_features_repo_from_system_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PHYSICAL_AI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PERCUS_AI_REPO_URL", raising=False)
    monkeypatch.delenv("PERCUS_AI_REPO_REF", raising=False)
    monkeypatch.delenv("PERCUS_AI_REPO_COMMIT", raising=False)
    monkeypatch.setattr(
        training,
        "resolve_features_repo_config",
        lambda: type(
            "_Config",
            (),
            {
                "repo_url": "https://github.com/example/features.git",
                "repo_ref": "sync/daihen-physical-ai/abc1234",
                "repo_commit": "deadbeef",
            },
        )(),
    )

    content = training._generate_env_file(
        job_id="job-1",
        instance_id="inst-1",
        policy_type="pi0",
        supabase_access_token=None,
        supabase_refresh_token=None,
        supabase_user_id=None,
    )

    assert "PERCUS_AI_REPO_URL=https://github.com/example/features.git" in content
    assert "PERCUS_AI_REPO_REF=sync/daihen-physical-ai/abc1234" in content
    assert "PERCUS_AI_REPO_COMMIT=deadbeef" in content

from pathlib import Path

from interfaces_backend.models.settings import (
    EnvironmentBuildSettingsModel,
    SystemSettingsModel,
)
from interfaces_backend.models.build_management import BuildJobSummaryModel
from interfaces_backend.services.build_management import BuildManagementService
from percus_ai.environment.build import BuildStore
from percus_ai.environment.build.build_layout import BuildLayout
from percus_ai.environment.build.build_metadata import (
    BuildStepLogModel,
    EnvBuildMetadataModel,
    SharedBuildMetadataModel,
)
from percus_ai.environment.config import EnvironmentConfigLoader


class _FakeSettingsService:
    def __init__(self, env_config_id: str) -> None:
        self._env_config_id = env_config_id

    def get_settings(self) -> SystemSettingsModel:
        return SystemSettingsModel(
            environment_build=EnvironmentBuildSettingsModel(env_config_id=self._env_config_id),
        )


class _FakeBuildJobsService:
    def __init__(self, jobs=None) -> None:
        self._jobs = list(jobs or [])

    def list_active_jobs(self):
        return list(self._jobs)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_list_env_settings_filters_state_by_config_id(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/config-a.yaml",
        """
id: config-a
display_name: Config A
envs:
  groot:
    display_name: GR00T A
    description: config a description
    python: "3.12"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/config-b.yaml",
        """
id: config-b
display_name: Config B
envs:
  groot:
    display_name: GR00T B
    description: config b description
    python: "3.12"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )
    store = BuildStore(layout=BuildLayout(data_dir=data_dir))
    store.save_env_metadata(
        EnvBuildMetadataModel(
            build_id="2026-04-16T00-00-00Z_a",
            env_name="groot",
            config_id="config-a",
            config_group="vla_runtime",
            success=True,
            steps=[BuildStepLogModel(step="install", started_at="2026-04-16T00:00:00Z", finished_at="2026-04-16T00:01:00Z")],
        )
    )
    store.switch_env_current("groot", "2026-04-16T00-00-00Z_a")
    store.save_env_metadata(
        EnvBuildMetadataModel(
            build_id="2026-04-16T00-00-01Z_b",
            env_name="groot",
            config_id="config-b",
            config_group="vla_runtime",
            success=False,
            steps=[BuildStepLogModel(step="flash-attn", exit_code=1, started_at="2026-04-16T00:02:00Z", finished_at="2026-04-16T00:03:00Z")],
        )
    )

    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        settings_service=_FakeSettingsService("config-a"),
        build_jobs_service=_FakeBuildJobsService(),
        current_platform_resolver=lambda: "jetson_agx_thor",
        current_sm_resolver=lambda: "sm_120",
    )

    response = service.list_env_settings()

    assert response.selected_config_id == "config-a"
    items = {item.config_id: item for item in response.items}
    assert items["config-a"].state == "success"
    assert items["config-a"].display_name == "GR00T A"
    assert items["config-a"].description == "config a description"
    assert items["config-a"].current_sm == "sm_120"
    assert items["config-a"].current_platform == "jetson_agx_thor"
    assert items["config-a"].config_group == "vla_runtime"
    assert items["config-a"].supported_platforms == []
    assert items["config-a"].platform_supported is True
    assert items["config-a"].supported_sms == ["*"]
    assert items["config-a"].sm_supported is True
    assert items["config-a"].current_build_id == "2026-04-16T00-00-00Z_a"
    assert items["config-a"].selected is True
    assert items["config-b"].state == "failed"
    assert items["config-b"].current_build_id is None
    assert items["config-b"].latest_error_summary == "flash-attn failed (exit=1)"


def test_list_shared_settings_filters_state_by_variant(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/default.yaml",
        """
id: default
envs: {}
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants:
  a:
    build:
      source:
        type: index
      outputs:
        python_paths:
          - output/site-packages
  b:
    build:
      source:
        type: index
      outputs:
        python_paths:
          - output/site-packages
""".strip()
        + "\n",
    )
    store = BuildStore(layout=BuildLayout(data_dir=data_dir))
    store.save_shared_metadata(
        SharedBuildMetadataModel(
            build_id="2026-04-16T00-00-00Z_a",
            package="pytorch",
            variant="a",
            success=True,
            steps=[BuildStepLogModel(step="build", started_at="2026-04-16T00:00:00Z", finished_at="2026-04-16T00:01:00Z")],
        )
    )
    store.save_shared_metadata(
        SharedBuildMetadataModel(
            build_id="2026-04-16T00-00-01Z_b",
            package="pytorch",
            variant="b",
            success=False,
            steps=[BuildStepLogModel(step="build", exit_code=7, started_at="2026-04-16T00:02:00Z", finished_at="2026-04-16T00:03:00Z")],
        )
    )

    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        settings_service=_FakeSettingsService("default"),
        build_jobs_service=_FakeBuildJobsService(),
        current_platform_resolver=lambda: "jetson_agx_thor",
        current_sm_resolver=lambda: "sm_120",
    )

    response = service.list_shared_settings()

    items = {item.variant: item for item in response.items}
    assert response.current_platform == "jetson_agx_thor"
    assert response.current_sm == "sm_120"
    assert items["a"].state == "success"
    assert items["a"].supported_platforms == []
    assert items["a"].platform_supported is True
    assert items["a"].supported_sms == ["*"]
    assert items["a"].sm_supported is True
    assert items["a"].actions.run is False
    assert items["a"].actions.delete is True
    assert items["b"].state == "failed"
    assert items["b"].latest_error_summary == "build failed (exit=7)"


def test_list_env_settings_overlays_active_job(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/default.yaml",
        """
id: default
display_name: Default
envs:
  pi0:
    display_name: Pi0
    description: Pi0 runtime
    python: "3.10"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )
    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
        settings_service=_FakeSettingsService("default"),
        build_jobs_service=_FakeBuildJobsService(
            [
                BuildJobSummaryModel(
                    job_id="job-1",
                    build_id="build-1",
                    kind="env",
                    setting_id="vla_runtime:default:pi0",
                    state="running",
                    current_step_name="runtime-common",
                    current_step_index=1,
                    total_steps=3,
                    progress_percent=33.0,
                    created_at="2026-04-16T00:00:00Z",
                    updated_at="2026-04-16T00:00:01Z",
                )
            ]
        ),
        current_platform_resolver=lambda: None,
        current_sm_resolver=lambda: "sm_120",
    )

    response = service.list_env_settings()

    item = next(item for item in response.items if item.setting_id == "vla_runtime:default:pi0")
    assert item.display_name == "Pi0"
    assert item.description == "Pi0 runtime"
    assert item.state == "building"
    assert item.current_job_id == "job-1"
    assert item.current_step_name == "runtime-common"
    assert item.progress_percent == 33.0
    assert item.usage == "runtime"


def test_list_env_settings_includes_train_group(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/default.yaml",
        """
id: default
display_name: Default
envs:
  pi0:
    display_name: Pi0
    description: runtime env
    usage: runtime
    python: "3.10"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/vla/train/sm_120.yaml",
        """
id: sm_120
display_name: SM 120
envs:
  pi0_train:
    display_name: Pi0 Train
    description: training env
    usage: training
    python: "3.10"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )

    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
        settings_service=_FakeSettingsService("default"),
        build_jobs_service=_FakeBuildJobsService(),
        current_sm_resolver=lambda: "sm_120",
    )

    response = service.list_env_settings()

    items = {item.setting_id: item for item in response.items}
    assert items["vla_runtime:default:pi0"].usage == "runtime"
    assert items["vla_runtime:default:pi0"].selected is True
    assert items["vla_runtime:default:pi0"].config_group == "vla_runtime"
    assert items["vla_train:sm_120:pi0_train"].usage == "training"
    assert items["vla_train:sm_120:pi0_train"].selected is False
    assert items["vla_train:sm_120:pi0_train"].config_group == "vla_train"


def test_list_env_settings_excludes_non_vla_env_groups(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/default.yaml",
        """
id: default
display_name: Default
envs:
  pi0:
    display_name: Pi0
    usage: runtime
    python: "3.10"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/vla/train/sm_120.yaml",
        """
id: sm_120
display_name: SM 120
envs:
  pi0_train:
    display_name: Pi0 Train
    usage: training
    python: "3.10"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/lingbot_depth/sm_120.yaml",
        """
id: sm_120
display_name: LingBot Depth SM 120
envs:
  lingbot_depth:
    display_name: LingBot Depth
    usage: runtime
    python: "3.10"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        "package: pytorch\nvariants: {}\n",
    )

    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
        settings_service=_FakeSettingsService("default"),
        build_jobs_service=_FakeBuildJobsService(),
    )

    response = service.list_env_settings()

    items = {item.setting_id: item for item in response.items}
    assert items["vla_runtime:default:pi0"].actions.run is True
    assert items["vla_train:sm_120:pi0_train"].actions.run is True
    assert "lingbot_depth:sm_120:lingbot_depth" not in items


def test_list_env_settings_marks_sm_compatibility(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/default.yaml",
        """
id: default
display_name: Default
envs:
  groot:
    display_name: GR00T
    description: Blackwell config
    python: "3.12"
    supported_sms:
      - sm_120
    installs: []
    checks: []
  act:
    display_name: ACT
    description: Broad config
    python: "3.10"
    supported_sms:
      - "sm_80..sm_90"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        "package: pytorch\nvariants: {}\n",
    )
    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
        settings_service=_FakeSettingsService("default"),
        build_jobs_service=_FakeBuildJobsService(),
        current_sm_resolver=lambda: "sm_120",
    )

    response = service.list_env_settings()
    items = {item.setting_id: item for item in response.items}

    assert response.current_sm == "sm_120"
    assert items["vla_runtime:default:groot"].sm_supported is True
    assert items["vla_runtime:default:act"].sm_supported is False


def test_delete_env_artifact_unlinks_current_when_current_build_matches(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/default.yaml",
        """
id: default
display_name: Default
envs:
  pi0:
    python: "3.10"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )
    store = BuildStore(layout=BuildLayout(data_dir=data_dir))
    store.save_env_metadata(
        EnvBuildMetadataModel(
            build_id="build-1",
            env_name="pi0",
            config_id="default",
            config_group="vla_runtime",
            success=True,
            steps=[BuildStepLogModel(step="done")],
        )
    )
    store.switch_env_current("pi0", "build-1")
    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        settings_service=_FakeSettingsService("default"),
        build_jobs_service=_FakeBuildJobsService(),
    )

    service.delete_env_artifact(config_group="vla_runtime", config_id="default", env_name="pi0", build_id="build-1")

    assert store.read_env_current_build_id("pi0") is None
    assert store.list_env_metadata("pi0") == []


def test_create_env_error_report_uses_explicit_config_group(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    for path in ("vla/runtime", "vla/train"):
        _write_text(
            data_dir / f"environment/configs/venv/{path}/sm_110.yaml",
            """
id: sm_110
envs:
  groot:
    python: "3.10"
    installs: []
    checks: []
""".strip()
            + "\n",
        )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )
    store = BuildStore(layout=BuildLayout(data_dir=data_dir))
    store.save_env_metadata(
        EnvBuildMetadataModel(
            build_id="build-1",
            env_name="groot",
            config_id="sm_110",
            config_group="vla_train",
            success=False,
            steps=[BuildStepLogModel(step="build", exit_code=1)],
        )
    )

    class _FakeErrorReportsService:
        def create_report(self, **kwargs):
            from interfaces_backend.models.build_management import BuildErrorReportResponse

            assert kwargs["kind"] == "env"
            assert kwargs["setting_id"] == "vla_train:sm_110:groot"
            assert kwargs["build_id"] == "build-1"
            return BuildErrorReportResponse(
                report_id="report-1",
                kind="env",
                setting_id=kwargs["setting_id"],
                build_id=kwargs["build_id"],
                object_path="s3://daihen/v2/build-reports/env/train-sm-110-groot/report-1.zip",
                uploaded_at="2026-04-16T00:00:00Z",
            )

    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        settings_service=_FakeSettingsService("sm_110"),
        build_jobs_service=_FakeBuildJobsService(),
        build_error_reports_service=_FakeErrorReportsService(),
    )

    response = service.create_env_error_report(
        config_group="vla_train",
        config_id="sm_110",
        env_name="groot",
        build_id="build-1",
    )

    assert response.setting_id == "vla_train:sm_110:groot"


def test_delete_shared_artifact_filters_by_variant(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/default.yaml",
        """
id: default
envs: {}
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants:
  thor:
    build:
      source:
        type: index
      outputs:
        python_paths:
          - output/site-packages
  other:
    build:
      source:
        type: index
      outputs:
        python_paths:
          - output/site-packages
""".strip()
        + "\n",
    )
    store = BuildStore(layout=BuildLayout(data_dir=data_dir))
    store.save_shared_metadata(
        SharedBuildMetadataModel(
            build_id="build-1",
            package="pytorch",
            variant="thor",
            success=True,
            steps=[BuildStepLogModel(step="done")],
        )
    )
    store.save_shared_metadata(
        SharedBuildMetadataModel(
            build_id="build-2",
            package="pytorch",
            variant="other",
            success=True,
            steps=[BuildStepLogModel(step="done")],
        )
    )
    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        settings_service=_FakeSettingsService("default"),
        build_jobs_service=_FakeBuildJobsService(),
    )

    service.delete_shared_artifact(package="pytorch", variant="thor", build_id="build-1")

    remaining = store.list_shared_metadata("pytorch")
    assert len(remaining) == 1
    assert remaining[0].build_id == "build-2"

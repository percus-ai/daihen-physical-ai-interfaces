from pathlib import Path

from interfaces_backend.models.settings import (
    EnvironmentBuildSettingsModel,
    SystemSettingsModel,
)
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


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_list_env_settings_filters_state_by_config_id(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        root_dir / "features/percus_ai/environment/configs/envs/config-a.yaml",
        """
id: config-a
display_name: Config A
envs:
  groot:
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        root_dir / "features/percus_ai/environment/configs/envs/config-b.yaml",
        """
id: config-b
display_name: Config B
envs:
  groot:
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        root_dir / "features/percus_ai/environment/configs/shared_packages/pytorch.yaml",
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
            success=False,
            steps=[BuildStepLogModel(step="flash-attn", exit_code=1, started_at="2026-04-16T00:02:00Z", finished_at="2026-04-16T00:03:00Z")],
        )
    )

    service = BuildManagementService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        settings_service=_FakeSettingsService("config-a"),
    )

    response = service.list_env_settings()

    assert response.selected_config_id == "config-a"
    items = {item.config_id: item for item in response.items}
    assert items["config-a"].state == "success"
    assert items["config-a"].current_build_id == "2026-04-16T00-00-00Z_a"
    assert items["config-a"].selected is True
    assert items["config-b"].state == "failed"
    assert items["config-b"].current_build_id is None
    assert items["config-b"].latest_error_summary == "flash-attn failed (exit=1)"


def test_list_shared_settings_filters_state_by_variant(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        root_dir / "features/percus_ai/environment/configs/envs/default.yaml",
        """
id: default
envs: {}
""".strip()
        + "\n",
    )
    _write_text(
        root_dir / "features/percus_ai/environment/configs/shared_packages/pytorch.yaml",
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
    )

    response = service.list_shared_settings()

    items = {item.variant: item for item in response.items}
    assert items["a"].state == "success"
    assert items["b"].state == "failed"
    assert items["b"].latest_error_summary == "build failed (exit=7)"

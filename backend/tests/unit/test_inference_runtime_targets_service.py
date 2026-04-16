from pathlib import Path

import pytest

from interfaces_backend.services.inference_runtime_targets import InferenceRuntimeTargetsService
from percus_ai.environment.build import BuildStore
from percus_ai.environment.build.build_layout import BuildLayout
from percus_ai.environment.build.build_metadata import BuildStepLogModel, EnvBuildMetadataModel
from percus_ai.environment.config import EnvironmentConfigLoader


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_list_targets_returns_cpu_and_matching_cuda_targets(tmp_path: Path) -> None:
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        root_dir / "features/percus_ai/environment/configs/envs/default.yaml",
        """
id: default
display_name: Default
envs:
  groot:
    display_name: GR00T N1.5
    description: Blackwell 向け GR00T N1.5 実行環境
    python: "3.12"
    policy_types:
      - groot
      - groot_n15
    supported_sms:
      - sm_120
    installs: []
    checks: []
  act:
    display_name: ACT
    description: ACT 系の推論・実行環境
    python: "3.10"
    policy_types:
      - act
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
            build_id="build-groot-1",
            env_name="groot",
            config_id="default",
            success=True,
            steps=[
                BuildStepLogModel(
                    step="lerobot",
                    started_at="2026-04-16T00:00:00Z",
                    finished_at="2026-04-16T00:01:00Z",
                )
            ],
        )
    )

    service = InferenceRuntimeTargetsService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        current_sm_resolver=lambda: "sm_120",
        backend_python="/usr/bin/python3",
    )

    response = service.list_targets(policy_type="groot")

    assert response.current_sm == "sm_120"
    assert response.recommended_target_id == "cuda:default:groot:build-groot-1"
    assert [item.label for item in response.targets] == ["CPU", "CUDA #1"]
    assert response.targets[1].display_name == "GR00T N1.5"
    assert response.targets[1].description == "Blackwell 向け GR00T N1.5 実行環境"


def test_list_targets_returns_cpu_only_when_no_matching_build_exists(tmp_path: Path) -> None:
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        root_dir / "features/percus_ai/environment/configs/envs/default.yaml",
        """
id: default
display_name: Default
envs:
  groot:
    display_name: GR00T N1.5
    python: "3.12"
    policy_types:
      - groot
    supported_sms:
      - sm_120
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

    service = InferenceRuntimeTargetsService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
        current_sm_resolver=lambda: "sm_120",
        backend_python="/usr/bin/python3",
    )

    response = service.list_targets(policy_type="groot")

    assert response.recommended_target_id == "cpu"
    assert [item.label for item in response.targets] == ["CPU"]


def test_resolve_target_uses_built_env_python_for_cuda_and_cpu_backing(tmp_path: Path) -> None:
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        root_dir / "features/percus_ai/environment/configs/envs/default.yaml",
        """
id: default
display_name: Default
envs:
  groot:
    display_name: GR00T N1.5
    python: "3.12"
    policy_types:
      - groot
    supported_sms:
      - sm_120
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
    layout = BuildLayout(data_dir=data_dir)
    store = BuildStore(layout=layout)
    store.save_env_metadata(
        EnvBuildMetadataModel(
            build_id="build-groot-1",
            env_name="groot",
            config_id="default",
            success=True,
            steps=[
                BuildStepLogModel(
                    step="lerobot",
                    started_at="2026-04-16T00:00:00Z",
                    finished_at="2026-04-16T00:01:00Z",
                )
            ],
        )
    )

    service = InferenceRuntimeTargetsService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        current_sm_resolver=lambda: "sm_120",
        backend_python="/usr/bin/python3",
    )

    cpu_target = service.resolve_target(policy_type="groot", target_id="cpu")
    cuda_target = service.resolve_target(
        policy_type="groot",
        target_id="cuda:default:groot:build-groot-1",
    )

    expected_python = layout.env_build_dir("groot", "build-groot-1") / "venv" / "bin" / "python"
    assert cpu_target.python_executable == str(expected_python)
    assert cuda_target.python_executable == str(expected_python)
    assert cuda_target.device == "cuda:0"


def test_resolve_target_raises_for_unknown_id(tmp_path: Path) -> None:
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        root_dir / "features/percus_ai/environment/configs/envs/default.yaml",
        """
id: default
envs:
  act:
    python: "3.10"
    policy_types:
      - act
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

    service = InferenceRuntimeTargetsService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
        current_sm_resolver=lambda: "sm_120",
        backend_python="/usr/bin/python3",
    )

    with pytest.raises(RuntimeError, match="Runtime target 'cuda:missing' is not available"):
        service.resolve_target(policy_type="act", target_id="cuda:missing")

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
        data_dir / "environment/configs/envs/default.yaml",
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
        data_dir / "environment/configs/shared_packages/pytorch.yaml",
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
        current_platform_resolver=lambda: None,
        current_sm_resolver=lambda: "sm_120",
        backend_python="/usr/bin/python3",
    )

    response = service.list_targets(policy_type="groot")

    assert response.current_platform is None
    assert response.current_sm == "sm_120"
    assert response.recommended_target_id == "cuda:default:groot:build-groot-1"
    assert [item.label for item in response.targets] == ["CPU", "CUDA #1"]
    assert response.targets[1].display_name == "GR00T N1.5"
    assert response.targets[1].description == "Blackwell 向け GR00T N1.5 実行環境"


def test_list_targets_includes_multiple_cuda_candidates_for_same_policy(tmp_path: Path) -> None:
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/envs/default.yaml",
        """
id: default
display_name: Default
envs:
  pi0:
    display_name: Pi0
    description: OpenPI 系の推論・実行環境
    python: "3.10"
    policy_types: [pi0, pi05, openpi]
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/envs/sm_120.yaml",
        """
id: sm_120
display_name: SM 120
envs:
  pi0:
    display_name: Pi0 Blackwell
    description: OpenPI 系の推論・実行環境
    python: "3.12"
    policy_types: [pi0, pi05, openpi]
    supported_sms: [sm_120]
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )
    layout = BuildLayout(data_dir=data_dir)
    store = BuildStore(layout=layout)
    for config_id, build_id in [("default", "build-pi0-default"), ("sm_120", "build-pi0-sm120")]:
        store.save_env_metadata(
            EnvBuildMetadataModel(
                build_id=build_id,
                env_name="pi0",
                config_id=config_id,
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
        current_platform_resolver=lambda: None,
        current_sm_resolver=lambda: "sm_120",
        backend_python="/usr/bin/python3",
    )

    response = service.list_targets(policy_type="pi05")

    assert [item.label for item in response.targets] == ["CPU", "CUDA #1", "CUDA #2"]
    assert response.targets[1].display_name == "Pi0"
    assert response.targets[2].display_name == "Pi0 Blackwell"


def test_list_targets_returns_cpu_only_when_no_matching_build_exists(tmp_path: Path) -> None:
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/envs/default.yaml",
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
        data_dir / "environment/configs/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )

    service = InferenceRuntimeTargetsService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
        current_platform_resolver=lambda: None,
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
        data_dir / "environment/configs/envs/default.yaml",
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
        data_dir / "environment/configs/shared_packages/pytorch.yaml",
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
        current_platform_resolver=lambda: None,
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
        data_dir / "environment/configs/envs/default.yaml",
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
        data_dir / "environment/configs/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )

    service = InferenceRuntimeTargetsService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
        current_platform_resolver=lambda: None,
        current_sm_resolver=lambda: "sm_120",
        backend_python="/usr/bin/python3",
    )

    with pytest.raises(RuntimeError, match="Runtime target 'cuda:missing' is not available"):
        service.resolve_target(policy_type="act", target_id="cuda:missing")


def test_list_targets_filters_platform_specific_runtime_targets(tmp_path: Path) -> None:
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/envs/default.yaml",
        """
id: default
envs:
  groot:
    display_name: Generic GR00T
    python: "3.12"
    policy_types: [groot]
    supported_sms: [sm_110]
    installs: []
    checks: []
  groot_thor:
    display_name: Thor GR00T
    python: "3.12"
    policy_types: [groot]
    supported_platforms: [jetson_agx_thor]
    supported_sms: [sm_110]
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/shared_packages/pytorch.yaml",
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
            build_id="generic-build",
            env_name="groot",
            config_id="default",
            success=True,
            steps=[BuildStepLogModel(step="ok", started_at="2026-04-16T00:00:00Z", finished_at="2026-04-16T00:01:00Z")],
        )
    )
    store.save_env_metadata(
        EnvBuildMetadataModel(
            build_id="thor-build",
            env_name="groot_thor",
            config_id="default",
            success=True,
            steps=[BuildStepLogModel(step="ok", started_at="2026-04-16T00:00:00Z", finished_at="2026-04-16T00:01:00Z")],
        )
    )

    generic_service = InferenceRuntimeTargetsService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        current_platform_resolver=lambda: None,
        current_sm_resolver=lambda: "sm_110",
        backend_python="/usr/bin/python3",
    )
    thor_service = InferenceRuntimeTargetsService(
        config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
        build_store=store,
        current_platform_resolver=lambda: "jetson_agx_thor",
        current_sm_resolver=lambda: "sm_110",
        backend_python="/usr/bin/python3",
    )

    generic_targets = generic_service.list_targets(policy_type="groot")
    thor_targets = thor_service.list_targets(policy_type="groot")

    assert [item.label for item in generic_targets.targets] == ["CPU", "CUDA #1"]
    assert [item.display_name for item in generic_targets.targets[1:]] == ["Generic GR00T"]
    assert [item.label for item in thor_targets.targets] == ["CPU", "CUDA #1", "CUDA #2"]
    assert [item.display_name for item in thor_targets.targets[1:]] == ["Generic GR00T", "Thor GR00T"]

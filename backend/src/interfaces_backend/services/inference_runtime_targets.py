"""Resolve inference runtime targets from new environment build configs."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from interfaces_backend.models.inference import InferenceRuntimeTargetInfo, InferenceRuntimeTargetsResponse
from percus_ai.environment.build import BuildStore
from percus_ai.environment.build.build_metadata import EnvBuildMetadataModel
from percus_ai.environment.config import EnvironmentConfigLoader, detect_current_sm, matches_supported_sms, normalize_supported_sms


@dataclass(frozen=True)
class ResolvedInferenceRuntimeTarget:
    target_id: str
    kind: str
    device: str
    python_executable: str
    config_id: str | None
    env_name: str | None
    build_id: str | None


class InferenceRuntimeTargetsService:
    def __init__(
        self,
        *,
        config_loader: EnvironmentConfigLoader | None = None,
        build_store: BuildStore | None = None,
        current_sm_resolver=None,
        backend_python: str | None = None,
    ) -> None:
        self._config_loader = config_loader or EnvironmentConfigLoader()
        self._build_store = build_store or BuildStore()
        self._layout = self._build_store.layout
        self._current_sm_resolver = current_sm_resolver or detect_current_sm
        self._backend_python = backend_python or sys.executable
        self._host_arch = str(platform.machine() or "").strip() or "unknown"

    def list_targets(self, *, policy_type: str | None) -> InferenceRuntimeTargetsResponse:
        normalized_policy = str(policy_type or "").strip().lower() or None
        current_sm = self._current_sm_resolver()

        cpu_backing = self._resolve_cpu_backing_target(policy_type=normalized_policy)
        targets: list[InferenceRuntimeTargetInfo] = [
            InferenceRuntimeTargetInfo(
                id="cpu",
                kind="cpu",
                label="CPU",
                display_name=self._host_arch,
                description="ホスト CPU で実行",
                device="cpu",
                available=True,
                config_id=cpu_backing.config_id if cpu_backing else None,
                env_name=cpu_backing.env_name if cpu_backing else None,
                build_id=cpu_backing.build_id if cpu_backing else None,
                supported_sms=["*"],
                current_sm=current_sm,
                sm_supported=True,
            )
        ]

        cuda_targets: list[InferenceRuntimeTargetInfo] = []
        for candidate in self._iter_env_candidates(policy_type=normalized_policy):
            if candidate.build_metadata is None:
                continue
            if candidate.sm_supported is not True:
                continue
            index = len(cuda_targets) + 1
            cuda_targets.append(
                InferenceRuntimeTargetInfo(
                    id=f"cuda:{candidate.config_id}:{candidate.env_name}:{candidate.build_metadata.build_id}",
                    kind="cuda",
                    label=f"CUDA #{index}",
                    display_name=candidate.display_name,
                    description=candidate.description,
                    device="cuda:0",
                    available=True,
                    config_id=candidate.config_id,
                    env_name=candidate.env_name,
                    build_id=candidate.build_metadata.build_id,
                    supported_sms=candidate.supported_sms,
                    current_sm=current_sm,
                    sm_supported=candidate.sm_supported,
                )
            )
        targets.extend(cuda_targets)
        recommended = cuda_targets[0].id if cuda_targets else "cpu"
        return InferenceRuntimeTargetsResponse(
            policy_type=normalized_policy,
            current_sm=current_sm,
            targets=targets,
            recommended_target_id=recommended,
        )

    def resolve_target(self, *, policy_type: str | None, target_id: str | None) -> ResolvedInferenceRuntimeTarget:
        targets = self.list_targets(policy_type=policy_type)
        normalized_target_id = str(target_id or "").strip() or targets.recommended_target_id
        if normalized_target_id == "cpu":
            cpu_backing = self._resolve_cpu_backing_target(policy_type=str(policy_type or "").strip().lower() or None)
            if cpu_backing is None:
                return ResolvedInferenceRuntimeTarget(
                    target_id="cpu",
                    kind="cpu",
                    device="cpu",
                    python_executable=self._backend_python,
                    config_id=None,
                    env_name=None,
                    build_id=None,
                )
            python_executable = self._env_python_path(cpu_backing.env_name, cpu_backing.build_id)
            return ResolvedInferenceRuntimeTarget(
                target_id="cpu",
                kind="cpu",
                device="cpu",
                python_executable=str(python_executable),
                config_id=cpu_backing.config_id,
                env_name=cpu_backing.env_name,
                build_id=cpu_backing.build_id,
            )

        for target in targets.targets:
            if target.id != normalized_target_id:
                continue
            if target.kind != "cuda" or not target.env_name or not target.build_id:
                break
            return ResolvedInferenceRuntimeTarget(
                target_id=target.id,
                kind="cuda",
                device=target.device,
                python_executable=str(self._env_python_path(target.env_name, target.build_id)),
                config_id=target.config_id,
                env_name=target.env_name,
                build_id=target.build_id,
            )
        raise RuntimeError(f"Runtime target '{normalized_target_id}' is not available")

    def _resolve_cpu_backing_target(self, *, policy_type: str | None) -> ResolvedInferenceRuntimeTarget | None:
        for candidate in self._iter_env_candidates(policy_type=policy_type):
            if candidate.build_metadata is None:
                continue
            return ResolvedInferenceRuntimeTarget(
                target_id="cpu",
                kind="cpu",
                device="cpu",
                python_executable=str(self._env_python_path(candidate.env_name, candidate.build_metadata.build_id)),
                config_id=candidate.config_id,
                env_name=candidate.env_name,
                build_id=candidate.build_metadata.build_id,
            )
        return None

    def _iter_env_candidates(self, *, policy_type: str | None):
        current_sm = self._current_sm_resolver()
        for ref in self._config_loader.list_env_configs():
            config = self._config_loader.load_env_config(ref.config_id)
            for env_name, env_definition in sorted(config.envs.items()):
                supported_policy_types = [entry.strip().lower() for entry in env_definition.policy_types if entry.strip()]
                if supported_policy_types and policy_type and policy_type not in supported_policy_types:
                    continue
                if not supported_policy_types and policy_type and policy_type != env_name.lower():
                    continue
                latest_success = self._find_latest_successful_env_build(config_id=config.id, env_name=env_name)
                yield _EnvCandidate(
                    config_id=config.id,
                    env_name=env_name,
                    display_name=env_definition.display_name or config.display_name or env_name,
                    description=env_definition.description,
                    supported_sms=normalize_supported_sms(env_definition.supported_sms),
                    sm_supported=matches_supported_sms(current_sm, env_definition.supported_sms),
                    build_metadata=latest_success,
                )

    def _find_latest_successful_env_build(self, *, config_id: str, env_name: str) -> EnvBuildMetadataModel | None:
        matching = [
            item
            for item in self._build_store.list_env_metadata(env_name)
            if item.config_id == config_id and item.success
        ]
        return matching[-1] if matching else None

    def _env_python_path(self, env_name: str, build_id: str) -> Path:
        return self._layout.env_build_dir(env_name, build_id) / "venv" / "bin" / "python"


@dataclass(frozen=True)
class _EnvCandidate:
    config_id: str
    env_name: str
    display_name: str
    description: str | None
    supported_sms: list[str]
    sm_supported: bool | None
    build_metadata: EnvBuildMetadataModel | None


_inference_runtime_targets_service: InferenceRuntimeTargetsService | None = None


def get_inference_runtime_targets_service() -> InferenceRuntimeTargetsService:
    global _inference_runtime_targets_service
    if _inference_runtime_targets_service is None:
        _inference_runtime_targets_service = InferenceRuntimeTargetsService()
    return _inference_runtime_targets_service

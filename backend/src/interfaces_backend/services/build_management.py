"""Build definition listing and latest-state aggregation for the new architecture."""

from __future__ import annotations

from fastapi import HTTPException

from typing import Protocol

from interfaces_backend.models.build_management import (
    BuildErrorReportResponse,
    BuildJobSummaryModel,
    BuildsStatusSnapshotModel,
    BuildSettingActionsModel,
    BuildSettingState,
    BuildSettingSummaryModel,
    EnvBuildSettingsListResponse,
    SharedBuildSettingsListResponse,
)
from interfaces_backend.models.settings import SystemSettingsModel
from percus_ai.environment.build import BuildStore
from percus_ai.environment.build.build_metadata import BuildStepLogModel, EnvBuildMetadataModel, SharedBuildMetadataModel
from percus_ai.environment.config import (
    EnvironmentConfigLoader,
    detect_current_sm,
    matches_supported_sms,
    normalize_supported_sms,
)


class SystemSettingsReader(Protocol):
    def get_settings(self) -> SystemSettingsModel: ...


class BuildJobsReader(Protocol):
    def list_active_jobs(self) -> list[BuildJobSummaryModel]: ...


class BuildManagementService:
    def __init__(
        self,
        *,
        config_loader: EnvironmentConfigLoader | None = None,
        build_store: BuildStore | None = None,
        settings_service: SystemSettingsReader | None = None,
        build_jobs_service: BuildJobsReader | None = None,
        current_sm_resolver=None,
        build_error_reports_service=None,
    ) -> None:
        self._config_loader = config_loader or EnvironmentConfigLoader()
        self._build_store = build_store or BuildStore()
        self._current_sm_resolver = current_sm_resolver or detect_current_sm
        if settings_service is None:
            from interfaces_backend.services.settings_service import get_system_settings_service

            self._settings_service = get_system_settings_service()
        else:
            self._settings_service = settings_service
        if build_jobs_service is None:
            from interfaces_backend.services.build_jobs import get_build_jobs_service

            self._build_jobs_service = get_build_jobs_service()
        else:
            self._build_jobs_service = build_jobs_service
        if build_error_reports_service is None:
            from interfaces_backend.services.build_error_reports import get_build_error_reports_service

            self._build_error_reports_service = get_build_error_reports_service()
        else:
            self._build_error_reports_service = build_error_reports_service

    def list_env_settings(self) -> EnvBuildSettingsListResponse:
        selected_config_id = self._settings_service.get_settings().environment_build.env_config_id
        current_sm = self._current_sm_resolver()
        active_jobs = {item.setting_id: item for item in self._build_jobs_service.list_active_jobs()}
        items: list[BuildSettingSummaryModel] = []
        for ref in self._config_loader.list_env_configs():
            config = self._config_loader.load_env_config(ref.config_id)
            for env_name, env_definition in sorted(config.envs.items()):
                items.append(
                    self._build_env_summary(
                        config_id=config.id,
                        config_origin=ref.origin,
                        config_display_name=config.display_name,
                        env_display_name=env_definition.display_name,
                        env_description=env_definition.description,
                        supported_sms=env_definition.supported_sms,
                        current_sm=current_sm,
                        env_name=env_name,
                        selected_config_id=selected_config_id,
                        active_job=active_jobs.get(f"{config.id}:{env_name}"),
                    )
                )
        return EnvBuildSettingsListResponse(selected_config_id=selected_config_id, current_sm=current_sm, items=items)

    def list_shared_settings(self) -> SharedBuildSettingsListResponse:
        current_sm = self._current_sm_resolver()
        active_jobs = {item.setting_id: item for item in self._build_jobs_service.list_active_jobs()}
        items: list[BuildSettingSummaryModel] = []
        for ref in self._config_loader.list_shared_package_definitions():
            definition = self._config_loader.load_shared_package_definition(ref.config_id)
            for variant, variant_definition in sorted(definition.variants.items()):
                items.append(
                    self._build_shared_summary(
                        package=definition.package,
                        variant=variant,
                        supported_sms=variant_definition.supported_sms,
                        current_sm=current_sm,
                        config_origin=ref.origin,
                        active_job=active_jobs.get(f"{definition.package}:{variant}"),
                    )
                )
        return SharedBuildSettingsListResponse(current_sm=current_sm, items=items)

    def snapshot(self) -> BuildsStatusSnapshotModel:
        envs = self.list_env_settings()
        shared = self.list_shared_settings()
        return BuildsStatusSnapshotModel(
            current_sm=envs.current_sm or shared.current_sm,
            running_jobs=self._build_jobs_service.list_active_jobs(),
            envs=envs,
            shared=shared,
        )

    def delete_env_artifact(self, *, config_id: str, env_name: str, build_id: str) -> None:
        self._ensure_no_active_setting_job(setting_id=f"{config_id}:{env_name}")
        try:
            metadata = self._build_store.load_env_metadata(env_name, build_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Env build artifact not found: {env_name}:{build_id}") from exc
        if metadata.config_id != config_id:
            raise HTTPException(
                status_code=404,
                detail=f"Env build artifact not found for config: {config_id}:{env_name}:{build_id}",
            )
        self._build_store.delete_env_build(env_name, build_id)

    def delete_shared_artifact(self, *, package: str, variant: str, build_id: str) -> None:
        self._ensure_no_active_setting_job(setting_id=f"{package}:{variant}")
        try:
            metadata = self._build_store.load_shared_metadata(package, build_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Shared build artifact not found: {package}:{build_id}",
            ) from exc
        if metadata.variant != variant:
            raise HTTPException(
                status_code=404,
                detail=f"Shared build artifact not found for variant: {package}:{variant}:{build_id}",
            )
        self._build_store.delete_shared_build(package, build_id)

    def create_env_error_report(self, *, config_id: str, env_name: str, build_id: str) -> BuildErrorReportResponse:
        metadata = self._load_env_metadata_for_config(config_id=config_id, env_name=env_name, build_id=build_id)
        if metadata.success:
            raise HTTPException(status_code=409, detail="Build succeeded; error report is only available for failed builds")
        artifact_dir = self._build_store.env_metadata_path(env_name, build_id).parent
        return self._build_error_reports_service.create_report(
            kind="env",
            setting_id=f"{config_id}:{env_name}",
            build_id=build_id,
            artifact_dir=artifact_dir,
            metadata=metadata.model_dump(mode="json"),
        )

    def create_shared_error_report(self, *, package: str, variant: str, build_id: str) -> BuildErrorReportResponse:
        metadata = self._load_shared_metadata_for_variant(package=package, variant=variant, build_id=build_id)
        if metadata.success:
            raise HTTPException(status_code=409, detail="Build succeeded; error report is only available for failed builds")
        artifact_dir = self._build_store.shared_metadata_path(package, build_id).parent
        return self._build_error_reports_service.create_report(
            kind="shared",
            setting_id=f"{package}:{variant}",
            build_id=build_id,
            artifact_dir=artifact_dir,
            metadata=metadata.model_dump(mode="json"),
        )

    def _build_env_summary(
        self,
        *,
        config_id: str,
        config_origin: str,
        config_display_name: str | None,
        env_display_name: str | None,
        env_description: str | None,
        supported_sms: list[str],
        current_sm: str | None,
        env_name: str,
        selected_config_id: str | None,
        active_job: BuildJobSummaryModel | None,
    ) -> BuildSettingSummaryModel:
        matching_metadata = [
            item
            for item in self._build_store.list_env_metadata(env_name)
            if item.config_id == config_id
        ]
        latest = matching_metadata[-1] if matching_metadata else None
        current = self._load_current_env_metadata(env_name=env_name, config_id=config_id)
        state = _state_from_metadata(latest)
        has_artifact = bool(matching_metadata)
        summary = BuildSettingSummaryModel(
            kind="env",
            setting_id=f"{config_id}:{env_name}",
            display_name=env_display_name or config_display_name or env_name,
            description=env_description,
            supported_sms=normalize_supported_sms(supported_sms),
            current_sm=current_sm,
            sm_supported=matches_supported_sms(current_sm, supported_sms),
            state=state,
            selected=config_id == selected_config_id,
            config_origin=config_origin,
            config_id=config_id,
            env_name=env_name,
            latest_build_id=latest.build_id if latest else None,
            current_build_id=current.build_id if current else None,
            latest_started_at=_started_at(latest.steps) if latest else None,
            latest_finished_at=_finished_at(latest.steps) if latest else None,
            latest_error_summary=_error_summary(latest) if latest else None,
            actions=_actions_for_state(state=state, has_artifact=has_artifact),
        )
        return _with_active_job(summary, active_job)

    def _build_shared_summary(
        self,
        *,
        package: str,
        variant: str,
        supported_sms: list[str],
        current_sm: str | None,
        config_origin: str,
        active_job: BuildJobSummaryModel | None,
    ) -> BuildSettingSummaryModel:
        matching_metadata = [
            item
            for item in self._build_store.list_shared_metadata(package)
            if item.variant == variant
        ]
        latest = matching_metadata[-1] if matching_metadata else None
        state = _state_from_metadata(latest)
        has_artifact = bool(matching_metadata)
        summary = BuildSettingSummaryModel(
            kind="shared",
            setting_id=f"{package}:{variant}",
            display_name=package,
            description=variant,
            supported_sms=normalize_supported_sms(supported_sms),
            current_sm=current_sm,
            sm_supported=matches_supported_sms(current_sm, supported_sms),
            state=state,
            config_origin=config_origin,
            package=package,
            variant=variant,
            latest_build_id=latest.build_id if latest else None,
            latest_started_at=_started_at(latest.steps) if latest else None,
            latest_finished_at=_finished_at(latest.steps) if latest else None,
            latest_error_summary=_error_summary(latest) if latest else None,
            actions=_actions_for_state(state=state, has_artifact=has_artifact),
        )
        return _with_active_job(summary, active_job)

    def _load_current_env_metadata(self, *, env_name: str, config_id: str) -> EnvBuildMetadataModel | None:
        current_build_id = self._build_store.read_env_current_build_id(env_name)
        if not current_build_id:
            return None
        try:
            metadata = self._build_store.load_env_metadata(env_name, current_build_id)
        except FileNotFoundError:
            return None
        return metadata if metadata.config_id == config_id else None

    def _load_env_metadata_for_config(self, *, config_id: str, env_name: str, build_id: str) -> EnvBuildMetadataModel:
        try:
            metadata = self._build_store.load_env_metadata(env_name, build_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Env build artifact not found: {env_name}:{build_id}") from exc
        if metadata.config_id != config_id:
            raise HTTPException(
                status_code=404,
                detail=f"Env build artifact not found for config: {config_id}:{env_name}:{build_id}",
            )
        return metadata

    def _load_shared_metadata_for_variant(self, *, package: str, variant: str, build_id: str) -> SharedBuildMetadataModel:
        try:
            metadata = self._build_store.load_shared_metadata(package, build_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Shared build artifact not found: {package}:{build_id}",
            ) from exc
        if metadata.variant != variant:
            raise HTTPException(
                status_code=404,
                detail=f"Shared build artifact not found for variant: {package}:{variant}:{build_id}",
            )
        return metadata

    def _ensure_no_active_setting_job(self, *, setting_id: str) -> None:
        active_setting_ids = {item.setting_id for item in self._build_jobs_service.list_active_jobs()}
        if setting_id in active_setting_ids:
            raise HTTPException(status_code=409, detail=f"Build is currently active: {setting_id}")


def _started_at(steps: list[BuildStepLogModel]) -> str | None:
    for step in steps:
        if step.started_at:
            return step.started_at
    return None


def _finished_at(steps: list[BuildStepLogModel]) -> str | None:
    for step in reversed(steps):
        if step.finished_at:
            return step.finished_at
    return None


def _error_summary(metadata: EnvBuildMetadataModel | SharedBuildMetadataModel) -> str | None:
    if metadata.success:
        return None
    for step in reversed(metadata.steps):
        if step.exit_code not in (None, 0):
            return f"{step.step} failed (exit={step.exit_code})"
    return "Build failed"


def _state_from_metadata(metadata: EnvBuildMetadataModel | SharedBuildMetadataModel | None) -> BuildSettingState:
    if metadata is None:
        return "unbuilt"
    return "success" if metadata.success else "failed"


def _actions_for_state(*, has_artifact: bool, state: BuildSettingState) -> BuildSettingActionsModel:
    return BuildSettingActionsModel(
        run=state in {"unbuilt", "success", "failed"},
        cancel=state == "building",
        delete=has_artifact,
        create_error_report=state == "failed",
    )


def _with_active_job(
    summary: BuildSettingSummaryModel,
    active_job: BuildJobSummaryModel | None,
) -> BuildSettingSummaryModel:
    if active_job is None:
        return summary
    return summary.model_copy(
        update={
            "state": "building",
            "latest_build_id": active_job.build_id,
            "current_job_id": active_job.job_id,
            "current_step_name": active_job.current_step_name,
            "current_step_index": active_job.current_step_index,
            "total_steps": active_job.total_steps,
            "progress_percent": active_job.progress_percent,
            "actions": BuildSettingActionsModel(
                run=False,
                cancel=True,
                delete=False,
                create_error_report=False,
            ),
        }
    )


_build_management_service: BuildManagementService | None = None


def get_build_management_service() -> BuildManagementService:
    global _build_management_service
    if _build_management_service is None:
        _build_management_service = BuildManagementService()
    return _build_management_service

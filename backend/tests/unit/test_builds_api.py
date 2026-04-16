import interfaces_backend.api.builds as builds_api
from interfaces_backend.models.build_management import (
    BuildJobSummaryModel,
    BuildSettingActionsModel,
    BuildSettingSummaryModel,
    BuildRunAcceptedResponse,
    EnvBuildSettingsListResponse,
    SharedBuildSettingsListResponse,
)


class _FakeBuildManagementService:
    def list_env_settings(self) -> EnvBuildSettingsListResponse:
        return EnvBuildSettingsListResponse(
            selected_config_id="default",
            items=[
                BuildSettingSummaryModel(
                    kind="env",
                    setting_id="default:pi0",
                    display_name="Pi0",
                    description="Pi0 runtime",
                    state="unbuilt",
                    config_id="default",
                    env_name="pi0",
                    actions=BuildSettingActionsModel(run=True),
                )
            ],
        )

    def list_shared_settings(self) -> SharedBuildSettingsListResponse:
        return SharedBuildSettingsListResponse(
            items=[
                BuildSettingSummaryModel(
                    kind="shared",
                    setting_id="pytorch:thor",
                    display_name="pytorch",
                    description="thor",
                    state="success",
                    package="pytorch",
                    variant="thor",
                    latest_build_id="build-1",
                    actions=BuildSettingActionsModel(run=True, delete=True),
                )
            ]
        )

    def delete_env_artifact(self, *, config_id: str, env_name: str, build_id: str) -> None:
        assert config_id == "default"
        assert env_name == "pi0"
        assert build_id == "build-env-1"

    def delete_shared_artifact(self, *, package: str, variant: str, build_id: str) -> None:
        assert package == "pytorch"
        assert variant == "thor"
        assert build_id == "build-1"

    def create_env_error_report(self, *, config_id: str, env_name: str, build_id: str):
        from interfaces_backend.models.build_management import BuildErrorReportResponse

        assert config_id == "default"
        assert env_name == "pi0"
        assert build_id == "build-env-1"
        return BuildErrorReportResponse(
            report_id="report-env-1",
            kind="env",
            setting_id="default:pi0",
            build_id=build_id,
            object_path="s3://daihen/v2/build-reports/env/default-pi0/report-env-1.zip",
            uploaded_at="2026-04-16T00:00:00Z",
        )

    def create_shared_error_report(self, *, package: str, variant: str, build_id: str):
        from interfaces_backend.models.build_management import BuildErrorReportResponse

        assert package == "pytorch"
        assert variant == "thor"
        assert build_id == "build-1"
        return BuildErrorReportResponse(
            report_id="report-shared-1",
            kind="shared",
            setting_id="pytorch:thor",
            build_id=build_id,
            object_path="s3://daihen/v2/build-reports/shared/pytorch-thor/report-shared-1.zip",
            uploaded_at="2026-04-16T00:00:00Z",
        )


class _FakeBuildJobsService:
    def start_env_build(self, *, config_id: str, env_name: str) -> BuildRunAcceptedResponse:
        return BuildRunAcceptedResponse(
            job=BuildJobSummaryModel(
                job_id="job-env-1",
                build_id="build-env-1",
                kind="env",
                setting_id=f"{config_id}:{env_name}",
                state="queued",
                created_at="2026-04-16T00:00:00Z",
                updated_at="2026-04-16T00:00:00Z",
            )
        )

    def start_shared_build(self, *, package: str, variant: str) -> BuildRunAcceptedResponse:
        return BuildRunAcceptedResponse(
            job=BuildJobSummaryModel(
                job_id="job-shared-1",
                build_id="build-shared-1",
                kind="shared",
                setting_id=f"{package}:{variant}",
                state="queued",
                created_at="2026-04-16T00:00:00Z",
                updated_at="2026-04-16T00:00:00Z",
            )
        )

    def cancel(self, *, job_id: str):
        from interfaces_backend.models.build_management import BuildJobCancelResponse

        return BuildJobCancelResponse(
            accepted=True,
            job=BuildJobSummaryModel(
                job_id=job_id,
                build_id="build-env-1",
                kind="env",
                setting_id="default:pi0",
                state="running",
                created_at="2026-04-16T00:00:00Z",
                updated_at="2026-04-16T00:00:01Z",
                message="構築の中止を要求しました。",
            ),
        )


def test_list_env_build_settings(client, monkeypatch):
    monkeypatch.setattr(builds_api, "get_build_management_service", lambda: _FakeBuildManagementService())

    response = client.get("/api/builds/envs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_config_id"] == "default"
    assert payload["items"][0]["setting_id"] == "default:pi0"
    assert payload["items"][0]["actions"]["run"] is True


def test_list_shared_build_settings(client, monkeypatch):
    monkeypatch.setattr(builds_api, "get_build_management_service", lambda: _FakeBuildManagementService())

    response = client.get("/api/builds/shared")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["setting_id"] == "pytorch:thor"
    assert payload["items"][0]["latest_build_id"] == "build-1"
    assert payload["items"][0]["actions"]["delete"] is True


def test_run_env_build(client, monkeypatch):
    monkeypatch.setattr(builds_api, "get_build_jobs_service", lambda: _FakeBuildJobsService())

    response = client.post("/api/builds/envs/default/pi0/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["job_id"] == "job-env-1"
    assert payload["job"]["setting_id"] == "default:pi0"


def test_run_shared_build(client, monkeypatch):
    monkeypatch.setattr(builds_api, "get_build_jobs_service", lambda: _FakeBuildJobsService())

    response = client.post("/api/builds/shared/pytorch/thor/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["job_id"] == "job-shared-1"
    assert payload["job"]["setting_id"] == "pytorch:thor"


def test_cancel_build_job(client, monkeypatch):
    monkeypatch.setattr(builds_api, "get_build_jobs_service", lambda: _FakeBuildJobsService())

    response = client.post("/api/builds/jobs/job-env-1/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["job"]["job_id"] == "job-env-1"


def test_delete_env_build_artifact(client, monkeypatch):
    monkeypatch.setattr(builds_api, "get_build_management_service", lambda: _FakeBuildManagementService())

    response = client.delete("/api/builds/envs/default/pi0/artifacts/build-env-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] is True
    assert payload["kind"] == "env"
    assert payload["setting_id"] == "default:pi0"


def test_delete_shared_build_artifact(client, monkeypatch):
    monkeypatch.setattr(builds_api, "get_build_management_service", lambda: _FakeBuildManagementService())

    response = client.delete("/api/builds/shared/pytorch/thor/artifacts/build-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] is True
    assert payload["kind"] == "shared"
    assert payload["setting_id"] == "pytorch:thor"


def test_create_env_build_error_report(client, monkeypatch):
    monkeypatch.setattr(builds_api, "get_build_management_service", lambda: _FakeBuildManagementService())

    response = client.post("/api/builds/envs/default/pi0/artifacts/build-env-1/error-report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_id"] == "report-env-1"
    assert payload["kind"] == "env"


def test_create_shared_build_error_report(client, monkeypatch):
    monkeypatch.setattr(builds_api, "get_build_management_service", lambda: _FakeBuildManagementService())

    response = client.post("/api/builds/shared/pytorch/thor/artifacts/build-1/error-report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_id"] == "report-shared-1"
    assert payload["kind"] == "shared"

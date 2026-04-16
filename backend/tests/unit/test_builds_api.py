import interfaces_backend.api.builds as builds_api
from interfaces_backend.models.build_management import (
    BuildSettingActionsModel,
    BuildSettingSummaryModel,
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
                    display_name="Default",
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
                    display_name="pytorch:thor",
                    state="success",
                    package="pytorch",
                    variant="thor",
                    latest_build_id="build-1",
                    actions=BuildSettingActionsModel(run=True, delete=True),
                )
            ]
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

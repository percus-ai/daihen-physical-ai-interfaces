from interfaces_backend.services.settings_service import (
    SystemSettingsService,
    UserSecretsService,
)
import pytest


def test_system_settings_service_round_trip(tmp_path):
    service = SystemSettingsService(path=tmp_path / "system-settings.json")
    service._config_loader = type(
        "_Loader",
        (),
        {"load_env_config": staticmethod(lambda config_id: {"id": config_id})},
    )()

    initial = service.get_settings()
    assert initial.bundled_torch.pytorch_version == "v2.10.0"
    assert initial.bundled_torch.torchvision_version == "v0.25.0"
    assert initial.features_repo.repo_url == "https://github.com/percus-ai/physical-ai-features.git"
    assert initial.features_repo.repo_ref == "main"
    assert initial.features_repo.repo_commit is None
    assert initial.environment_build.env_config_id == "default"

    updated = service.update_settings(
        pytorch_version="v2.9.0",
        torchvision_version="v0.24.0",
        features_repo_url="https://github.com/example/repo.git",
        features_repo_ref="feature/test",
        features_repo_commit="abc1234",
        env_config_id="thor-dev-01",
    )

    assert updated.bundled_torch.pytorch_version == "v2.9.0"
    assert updated.bundled_torch.torchvision_version == "v0.24.0"
    assert updated.features_repo.repo_url == "https://github.com/example/repo.git"
    assert updated.features_repo.repo_ref == "feature/test"
    assert updated.features_repo.repo_commit == "abc1234"
    assert updated.environment_build.env_config_id == "thor-dev-01"
    assert updated.updated_at


def test_user_secrets_service_masks_and_clears_token(tmp_path):
    service = UserSecretsService(path=tmp_path / "user-secrets.json")

    status = service.set_huggingface_token("user-1", "hf_1234567890abcdef", clear=False)
    assert status.has_token is True
    assert status.token_preview == "hf_123...cdef"

    token = service.get_huggingface_token("user-1")
    assert token == "hf_1234567890abcdef"

    cleared = service.set_huggingface_token("user-1", None, clear=True)
    assert cleared.has_token is False
    assert cleared.token_preview is None
    assert service.get_huggingface_token("user-1") is None


def test_system_settings_rejects_unknown_env_config(monkeypatch, tmp_path):
    service = SystemSettingsService(path=tmp_path / "system-settings.json")

    class _Loader:
        def load_env_config(self, config_id: str):
            raise FileNotFoundError(config_id)

    monkeypatch.setattr(service, "_config_loader", _Loader())

    with pytest.raises(FileNotFoundError):
        service.update_settings(env_config_id="missing-config")

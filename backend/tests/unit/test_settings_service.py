from interfaces_backend.services.settings_service import (
    SystemSettingsService,
    UserSecretsService,
)


def test_system_settings_service_round_trip(tmp_path):
    service = SystemSettingsService(path=tmp_path / "system-settings.json")

    initial = service.get_settings()
    assert initial.bundled_torch.pytorch_version == "v2.8.0"
    assert initial.bundled_torch.torchvision_version == "v0.23.0"

    updated = service.update_settings(
        pytorch_version="v2.9.0",
        torchvision_version="v0.24.0",
    )

    assert updated.bundled_torch.pytorch_version == "v2.9.0"
    assert updated.bundled_torch.torchvision_version == "v0.24.0"
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

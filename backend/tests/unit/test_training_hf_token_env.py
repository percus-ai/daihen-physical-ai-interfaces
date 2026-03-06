import interfaces_backend.api.training as training_api


def test_generate_env_file_includes_user_scoped_hf_token(monkeypatch):
    monkeypatch.setattr(
        training_api,
        "resolve_huggingface_token_for_user",
        lambda user_id: "hf_user_scoped_token" if user_id == "user-1" else None,
    )

    env_content = training_api._generate_env_file(
        "job-1",
        "instance-1",
        "pi0",
        user_id="user-1",
    )

    assert "HF_TOKEN=hf_user_scoped_token" in env_content


def test_generate_env_file_omits_hf_token_when_user_has_none(monkeypatch):
    monkeypatch.setattr(training_api, "resolve_huggingface_token_for_user", lambda _user_id: None)

    env_content = training_api._generate_env_file(
        "job-1",
        "instance-1",
        "pi0",
        user_id="user-1",
    )

    assert "HF_TOKEN=" not in env_content

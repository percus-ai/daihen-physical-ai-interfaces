import asyncio

import interfaces_backend.api.system as system_api


def test_get_features_repo_suggestions_uses_github_payload(monkeypatch):
    calls: list[str] = []

    def fake_request(path: str):
        calls.append(path)
        if path == "/repos/percus-ai/physical-ai-features":
            return {"default_branch": "main"}
        if path == "/repos/percus-ai/physical-ai-features/branches?per_page=50":
            return [{"name": "main"}, {"name": "feature/provision"}]
        if path == "/repos/percus-ai/physical-ai-features/commits?sha=feature%2Fprovision&per_page=20":
            return [
                {"sha": "abcdef1234567890", "commit": {"message": "Fix provision flow\n\nbody"}},
                {"sha": "1234567890abcdef", "commit": {"message": "Add SSE route"}},
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(system_api, "_github_request_json", fake_request)

    response = system_api._load_features_repo_suggestions(
        repo_url="https://github.com/percus-ai/physical-ai-features.git",
        repo_ref="feature/provision",
    )

    assert response.default_branch == "main"
    assert response.branches == ["main", "feature/provision"]
    assert response.commits[0].sha == "abcdef1234567890"
    assert response.commits[0].short_sha == "abcdef1"
    assert response.commits[0].message == "Fix provision flow"
    assert calls


def test_get_features_repo_suggestions_runs_loader_in_thread(monkeypatch):
    captured: dict[str, object] = {}

    def fake_loader(*, repo_url: str, repo_ref: str | None):
        captured["loader"] = (repo_url, repo_ref)
        return system_api.FeaturesRepoSuggestionsResponse(
            repo_url=repo_url,
            repo_ref=repo_ref,
            default_branch="main",
            branches=["main"],
            commits=[],
        )

    async def fake_to_thread(func, /, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return func(*args, **kwargs)

    monkeypatch.setattr(system_api, "_load_features_repo_suggestions", fake_loader)
    monkeypatch.setattr(system_api.asyncio, "to_thread", fake_to_thread)

    response = asyncio.run(
        system_api.get_features_repo_suggestions(
            repo_url="https://github.com/percus-ai/physical-ai-features.git",
            repo_ref="main",
        )
    )

    assert response.default_branch == "main"
    assert captured["func"] is fake_loader
    assert captured["args"] == ()
    assert captured["kwargs"] == {
        "repo_url": "https://github.com/percus-ai/physical-ai-features.git",
        "repo_ref": "main",
    }
    assert captured["loader"] == (
        "https://github.com/percus-ai/physical-ai-features.git",
        "main",
    )


def test_get_gpu_info_runs_collection_in_thread(monkeypatch):
    captured: dict[str, object] = {}

    def fake_collect():
        captured["collect_called"] = True
        return system_api.GpuResponse(
            available=True,
            cuda_version="12.4",
            driver_version="550.00",
            gpus=[],
        )

    async def fake_to_thread(func, /, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return func(*args, **kwargs)

    monkeypatch.setattr(system_api, "_collect_gpu_info", fake_collect)
    monkeypatch.setattr(system_api.asyncio, "to_thread", fake_to_thread)

    response = asyncio.run(system_api.get_gpu_info())

    assert response.available is True
    assert captured["func"] is fake_collect
    assert captured["args"] == ()
    assert captured["kwargs"] == {}
    assert captured["collect_called"] is True

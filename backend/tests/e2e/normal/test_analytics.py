from pathlib import Path

from tests.e2e.helpers import create_recording


def test_analytics_overview(client):
    workspace = Path.cwd()
    create_recording(workspace, "demo_project", "episode_0001")

    resp = client.get("/api/analytics/overview")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["stats"]["total_projects"] == 1
    assert payload["stats"]["total_episodes"] == 1


def test_analytics_projects(client):
    workspace = Path.cwd()
    create_recording(workspace, "demo_project", "episode_0001")

    resp = client.get("/api/analytics/projects")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["projects"][0]["project_id"] == "demo_project"


def test_analytics_project_detail(client):
    workspace = Path.cwd()
    create_recording(workspace, "demo_project", "episode_0001")

    resp = client.get("/api/analytics/projects/demo_project")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["episode_count"] == 1


def test_analytics_training(client):
    resp = client.get("/api/analytics/training")
    assert resp.status_code == 200
    payload = resp.json()
    assert "stats" in payload


def test_analytics_storage(client):
    resp = client.get("/api/analytics/storage")
    assert resp.status_code == 200
    payload = resp.json()
    assert "categories" in payload

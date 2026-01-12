from pathlib import Path

from tests.e2e.helpers import create_recording


def test_recording_list_and_detail(client):
    workspace = Path.cwd()
    episode_dir = create_recording(workspace, "demo_project", "episode_0001")

    resp = client.get("/api/recording/recordings")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1

    recording_id = f"demo_project/{episode_dir.name}"
    resp = client.get(f"/api/recording/recordings/{recording_id}")
    assert resp.status_code == 200
    assert resp.json()["recording_id"] == recording_id

    resp = client.get(f"/api/recording/recordings/{recording_id}/validate")
    assert resp.status_code == 200
    assert "errors" in resp.json()

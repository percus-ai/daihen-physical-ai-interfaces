from pathlib import Path

from percus_ai.storage import ManifestManager

from tests.e2e.helpers import create_dataset_metadata, create_model_metadata, write_project_yaml


def test_storage_datasets_flow(client):
    workspace = Path.cwd()
    dataset_id = "demo_project/episode_0001"
    create_dataset_metadata(workspace, dataset_id, project_id="demo_project")

    resp = client.get("/api/storage/datasets", params={"include_remote": False})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1

    resp = client.get(f"/api/storage/datasets/{dataset_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == dataset_id

    resp = client.delete(f"/api/storage/datasets/{dataset_id}")
    assert resp.status_code == 200

    resp = client.post(f"/api/storage/datasets/{dataset_id}/restore")
    assert resp.status_code == 200


def test_storage_models_flow(client):
    workspace = Path.cwd()
    dataset_id = "demo_project/episode_0001"
    create_dataset_metadata(workspace, dataset_id, project_id="demo_project")
    create_model_metadata(workspace, "demo_model", dataset_id)

    resp = client.get("/api/storage/models")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1

    resp = client.get("/api/storage/models/demo_model")
    assert resp.status_code == 200
    assert resp.json()["id"] == "demo_model"

    resp = client.delete("/api/storage/models/demo_model")
    assert resp.status_code == 200

    resp = client.post("/api/storage/models/demo_model/restore")
    assert resp.status_code == 200


def test_storage_usage_and_archive(client):
    resp = client.get("/api/storage/usage")
    assert resp.status_code == 200

    resp = client.get("/api/storage/archive")
    assert resp.status_code == 200


def test_storage_projects_list(client):
    workspace = Path.cwd()
    project_id = "demo_project"
    write_project_yaml(workspace, project_id)

    manifest = ManifestManager(workspace)
    manifest.init_directories()
    manifest.register_project(project_id)

    resp = client.get("/api/storage/projects")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["projects"][0]["id"] == project_id

    resp = client.get(f"/api/storage/projects/{project_id}")
    assert resp.status_code == 200

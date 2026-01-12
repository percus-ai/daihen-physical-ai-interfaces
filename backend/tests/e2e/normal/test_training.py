def test_training_configs_flow(client):
    payload = {
        "config": {
            "name": "demo_config",
            "dataset": {"id": "demo_project/episode_0001", "source": "r2"},
            "policy": {"type": "act"},
            "training": {"steps": 100, "batch_size": 2, "save_freq": 50},
            "output": {},
            "wandb": {"enable": False},
            "cloud": {
                "gpu_model": "H100",
                "gpus_per_instance": 1,
                "location": "auto",
                "is_spot": True,
            },
        }
    }

    resp = client.post("/api/training/configs", json=payload)
    assert resp.status_code == 200
    config_id = resp.json()["config_id"]

    resp = client.get("/api/training/configs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp = client.get(f"/api/training/configs/{config_id}")
    assert resp.status_code == 200

    resp = client.get(f"/api/training/configs/{config_id}/validate")
    assert resp.status_code == 200

    resp = client.post(f"/api/training/configs/{config_id}/dry-run")
    assert resp.status_code == 200

    update_payload = payload.copy()
    update_payload["config"]["name"] = "demo_config_updated"
    resp = client.put(f"/api/training/configs/{config_id}", json=update_payload)
    assert resp.status_code == 200

    resp = client.delete(f"/api/training/configs/{config_id}")
    assert resp.status_code == 200


def test_training_jobs_list_empty(client):
    resp = client.get("/api/training/jobs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

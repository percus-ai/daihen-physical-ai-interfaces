from percus_ai.db import clear_supabase_session, set_supabase_session


def test_user_config(client):
    resp = client.get("/api/user/config")
    assert resp.status_code == 200

    update_payload = {
        "email": "tester@example.com",
        "auto_download_models": False,
    }
    resp = client.put("/api/user/config", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["email"] == "tester@example.com"


def test_user_devices(client):
    resp = client.get("/api/user/devices")
    assert resp.status_code == 200

    update_payload = {
        "cameras": {
            "top_camera": {"id": 0, "type": "opencv", "width": 640, "height": 480, "fps": 30}
        }
    }
    resp = client.put("/api/user/devices", json=update_payload)
    assert resp.status_code == 200
    assert "top_camera" in resp.json()["cameras"]


def test_user_validate_environment(client):
    resp = client.post("/api/user/validate-environment")
    assert resp.status_code == 200
    payload = resp.json()
    assert "checks" in payload


def test_user_settings(client):
    set_supabase_session({"user_id": "user-1"})
    try:
        resp = client.get("/api/user/settings")
        assert resp.status_code == 200
        assert resp.json()["huggingface"]["has_token"] is False

        resp = client.put(
            "/api/user/settings",
            json={"username": "tanaka.tarou", "first_name": "Tarou", "last_name": "Tanaka"},
        )
        assert resp.status_code == 200
        profile_payload = resp.json()["profile"]
        assert profile_payload["username"] == "tanaka.tarou"
        assert profile_payload["first_name"] == "Tarou"
        assert profile_payload["last_name"] == "Tanaka"

        resp = client.put(
            "/api/user/settings",
            json={"huggingface_token": "hf_1234567890abcdef"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["user_id"] == "user-1"
        assert payload["profile"]["username"] == "tanaka.tarou"
        assert payload["huggingface"]["has_token"] is True
        assert payload["huggingface"]["token_preview"] == "hf_123...cdef"

        resp = client.put(
            "/api/user/settings",
            json={"clear_huggingface_token": True},
        )
        assert resp.status_code == 200
        assert resp.json()["huggingface"]["has_token"] is False
    finally:
        clear_supabase_session()

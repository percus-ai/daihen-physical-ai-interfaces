from __future__ import annotations

from interfaces_backend.utils.docker_services import get_docker_service_summary


class _FakeAPI:
    def __init__(self, payload):
        self._payload = payload

    def containers(self, *, all: bool, filters: dict[str, list[str]]):
        assert all is True
        service_filter = ",".join(filters.get("label", []))
        service_name = service_filter.split("=", 1)[-1] if "=" in service_filter else ""
        return list(self._payload.get(service_name, []))


class _FakeClient:
    def __init__(self, payload):
        self.api = _FakeAPI(payload)
        self.closed = False

    def close(self):
        self.closed = True


def test_get_docker_service_summary_prefers_named_container(monkeypatch):
    import interfaces_backend.utils.docker_services as docker_services

    client = _FakeClient(
        {
            "vlabor": [
                {
                    "Names": ["/other-vlabor"],
                    "State": "running",
                    "Status": "Up 30 seconds",
                    "Created": 1741305600,
                    "Id": "0123456789abcdef",
                },
                {
                    "Names": ["/vlabor-backend"],
                    "State": "restarting",
                    "Status": "Restarting (1) 5 seconds ago",
                    "Created": 1741305601,
                    "Id": "abcdef0123456789",
                },
            ]
        }
    )

    monkeypatch.setattr(docker_services, "_create_docker_client", lambda: client)

    summary = get_docker_service_summary("vlabor")

    assert summary == {
        "service": "vlabor",
        "container_name": "vlabor-backend",
        "state": "restarting",
        "status_detail": "Restarting (1) 5 seconds ago",
        "running_for": "Restarting (1) 5 seconds ago",
        "created_at": "2025-03-07T00:00:01+00:00",
        "container_id": "abcdef012345",
    }
    assert client.closed is True


def test_get_docker_service_summary_returns_empty_without_client(monkeypatch):
    import interfaces_backend.utils.docker_services as docker_services

    monkeypatch.setattr(docker_services, "_create_docker_client", lambda: None)

    assert get_docker_service_summary("lerobot-ros2") == {}

"""Docker Engine helpers for compose-managed service state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_CONTAINER_NAME_OVERRIDES = {
    "vlabor": "vlabor-backend",
    "vlabor-zenoh-bridge": "vlabor-zenoh-bridge",
    "lerobot-ros2": "daihen-ros2-lerobot",
    "rosbridge": "daihen-rosbridge",
}


def _create_docker_client():
    try:
        import docker as docker_sdk
    except Exception:
        return None
    if not hasattr(docker_sdk, "from_env"):
        return None
    try:
        return docker_sdk.from_env(timeout=2)
    except Exception:
        return None


def _normalize_names(names: Any) -> list[str]:
    if not isinstance(names, list):
        return []
    normalized: list[str] = []
    for item in names:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value:
            continue
        normalized.append(value[1:] if value.startswith("/") else value)
    return normalized


def _normalize_created_at(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _pick_summary(service: str, summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not summaries:
        return None
    preferred_name = _CONTAINER_NAME_OVERRIDES.get(service)
    if preferred_name:
        for summary in summaries:
            if preferred_name in _normalize_names(summary.get("Names")):
                return summary
    for summary in summaries:
        state = str(summary.get("State") or "").strip().lower()
        if state == "running":
            return summary
    return summaries[0]


def get_docker_service_summary(service: str) -> dict[str, Any]:
    client = _create_docker_client()
    if client is None:
        return {}
    try:
        api = getattr(client, "api", None)
        if api is None or not hasattr(api, "containers"):
            return {}
        summaries = api.containers(
            all=True,
            filters={"label": [f"com.docker.compose.service={service}"]},
        )
        if not isinstance(summaries, list):
            return {}
        summary = _pick_summary(service, [item for item in summaries if isinstance(item, dict)])
        if summary is None:
            return {}
        names = _normalize_names(summary.get("Names"))
        state = str(summary.get("State") or "").strip().lower()
        status_detail = str(summary.get("Status") or "").strip() or None
        container_id = str(summary.get("Id") or "").strip() or None
        if container_id:
            container_id = container_id[:12]
        return {
            "service": service,
            "container_name": names[0] if names else _CONTAINER_NAME_OVERRIDES.get(service),
            "state": state or "unknown",
            "status_detail": status_detail,
            "running_for": status_detail,
            "created_at": _normalize_created_at(summary.get("Created")),
            "container_id": container_id,
        }
    except Exception:
        return {}
    finally:
        try:
            client.close()
        except Exception:
            pass


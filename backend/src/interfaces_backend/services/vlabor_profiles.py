"""VLAbor profile helpers.

This module treats VLAbor profile YAML as the source of truth and stores only
selection/session snapshots on backend side.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import HTTPException

from percus_ai.db import get_current_user_id, get_supabase_async_client
from percus_ai.storage.paths import get_project_root

logger = logging.getLogger(__name__)

_SESSION_PROFILE_TABLE = "session_profile_bindings"
_ACTIVE_PROFILE_FILE_ENV = "VLABOR_ACTIVE_PROFILE_FILE"

_SO101_DEFAULT_JOINT_SUFFIXES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]
_SHARE_REF_PATTERN = re.compile(r"\$\{share:([^}]+)\}")
_INCLUDE_PUBLISHER_RESOLVER_KEYS = {
    ("fv_camera", "fv_camera_launch.py"),
    ("vlabor_launch", "fv_camera_wrapper.launch.py"),
    ("fv_realsense", "fv_realsense_launch.py"),
    ("unity_robot_control", "vr_dual_arm_teleop_direct.launch.py"),
}
_IGNORED_INCLUDE_KEYS = {
    ("fluent_vision_system", "run.py"),
    ("foxglove_bridge", "foxglove_bridge_launch.xml"),
    ("piper_description", "display_urdf_follow.launch.py"),
    ("ros_gz_sim", "gz_sim.launch.py"),
    ("so101_description", "display.launch.py"),
    ("so101_description", "display_robot.launch.py"),
    ("so101_description", "rsp.launch.py"),
}


@dataclass(frozen=True)
class VlaborProfileSpec:
    name: str
    description: str
    snapshot: dict[str, Any]
    source_path: str
    updated_at: Optional[str]


@dataclass(frozen=True)
class ProfileHealthPublisherSpec:
    node: str
    publishes: tuple[str, ...] = ()
    publishes_any: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True)
class ProfileHealthContract:
    profile_name: str
    required_topics: tuple[str, ...]
    optional_topics: tuple[str, ...]
    required_camera_topics: tuple[str, ...]
    required_robot_topics: tuple[str, ...]
    required_publishers: tuple[ProfileHealthPublisherSpec, ...]
    optional_publishers: tuple[ProfileHealthPublisherSpec, ...]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_profile_local_path() -> Path:
    configured = str(os.environ.get(_ACTIVE_PROFILE_FILE_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".vlabor" / "active_profile.json"


def _load_active_profile_name_local() -> str | None:
    path = _active_profile_local_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - fall back to default profile
        logger.warning("Failed to read local active profile file (%s): %s", path, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("Invalid local active profile payload: %s", path)
        return None
    return str(payload.get("profile_name") or "").strip() or None


def _save_active_profile_name_local(profile_name: str) -> None:
    path = _active_profile_local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile_name": profile_name,
        "updated_at": _now_iso(),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _resolve_profiles_dir() -> Optional[Path]:
    env_override = os.environ.get("VLABOR_PROFILES_DIR")
    candidates = [
        Path(env_override).expanduser() if env_override else None,
        Path.home() / ".vlabor" / "profiles",
        get_project_root() / "ros2_ws" / "src" / "vlabor_ros2" / "vlabor_launch" / "config" / "profiles",
        Path.home() / "ros2_ws" / "src" / "vlabor_ros2" / "vlabor_launch" / "config" / "profiles",
        Path("/home/aspa/ros2_ws/src/vlabor_ros2/vlabor_launch/config/profiles"),
        Path.home() / "vlabor_ros2" / "vlabor_launch" / "config" / "profiles",
        Path("/home/aspa/vlabor_ros2/vlabor_launch/config/profiles"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.is_dir() and list(candidate.glob("*.yaml")):
            return candidate
    return None


def _resolve_defaults_path() -> Optional[Path]:
    env_override = os.environ.get("VLABOR_DEFAULTS_FILE")
    candidates = [
        Path(env_override).expanduser() if env_override else None,
        Path.home() / ".vlabor" / "vlabor_profiles.yaml",
        get_project_root() / "ros2_ws" / "src" / "vlabor_ros2" / "vlabor_launch" / "config" / "vlabor_profiles.yaml",
        Path.home() / "ros2_ws" / "src" / "vlabor_ros2" / "vlabor_launch" / "config" / "vlabor_profiles.yaml",
        Path("/home/aspa/ros2_ws/src/vlabor_ros2/vlabor_launch/config/vlabor_profiles.yaml"),
        Path.home() / "vlabor_ros2" / "vlabor_launch" / "config" / "vlabor_profiles.yaml",
        Path("/home/aspa/vlabor_ros2/vlabor_launch/config/vlabor_profiles.yaml"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=64)
def _resolve_package_share_dir(package_name: str) -> Optional[Path]:
    normalized = str(package_name or "").strip()
    if not normalized:
        return None
    search_roots = [
        get_project_root() / "ros2_ws" / "src",
        Path.home() / "ros2_ws" / "src",
    ]
    for root in search_roots:
        if not root.is_dir():
            continue
        for package_xml in root.rglob("package.xml"):
            package_dir = package_xml.parent
            if package_dir.name == normalized:
                return package_dir
    return None


def _resolve_share_references(value: object) -> str:
    text = str(value or "").strip()
    if not text or "${share:" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        package_dir = _resolve_package_share_dir(match.group(1))
        return str(package_dir) if package_dir else match.group(0)

    return _SHARE_REF_PATTERN.sub(replace, text)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - surfaced as API detail
        raise HTTPException(status_code=500, detail=f"Failed to load profile yaml: {path}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"Invalid yaml format: {path}")
    return payload


def _build_profile_snapshot(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        profile = {}

    name = str(profile.get("name") or path.stem).strip()
    if not name:
        name = path.stem
    description = str(profile.get("description") or "").strip()

    return {
        "name": name,
        "description": description,
        "profile": profile,
        "raw": payload,
        "source_path": str(path),
        "loaded_at": _now_iso(),
    }


def list_vlabor_profiles() -> list[VlaborProfileSpec]:
    profiles_dir = _resolve_profiles_dir()
    if not profiles_dir:
        return []

    profiles: list[VlaborProfileSpec] = []
    for path in sorted(profiles_dir.glob("*.yaml")):
        payload = _load_yaml(path)
        snapshot = _build_profile_snapshot(path, payload)
        profiles.append(
            VlaborProfileSpec(
                name=str(snapshot.get("name") or path.stem),
                description=str(snapshot.get("description") or ""),
                snapshot=snapshot,
                source_path=str(path),
                updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            )
        )
    return profiles


def _default_profile_name(available_names: list[str]) -> Optional[str]:
    if not available_names:
        return None
    if "so101_dual_teleop" in available_names:
        return "so101_dual_teleop"
    return sorted(available_names)[0]


def _profile_by_name(profile_name: str) -> Optional[VlaborProfileSpec]:
    normalized = profile_name.strip()
    if not normalized:
        return None
    for profile in list_vlabor_profiles():
        if profile.name == normalized:
            return profile
    return None


def _load_default_settings() -> dict[str, Any]:
    path = _resolve_defaults_path()
    if not path:
        return {}
    payload = _load_yaml(path)
    defaults = payload.get("defaults")
    if isinstance(defaults, dict):
        return dict(defaults)
    return {}


def build_profile_settings(snapshot: dict[str, Any]) -> dict[str, Any]:
    settings = _load_default_settings()
    profile = snapshot.get("profile")
    if isinstance(profile, dict):
        variables = profile.get("variables")
        if isinstance(variables, dict):
            settings.update(variables)
    return settings


def _render_setting(value: object, settings: dict[str, Any]) -> object:
    if not isinstance(value, str) or "${" not in value:
        return value
    rendered = value
    for key, current in settings.items():
        rendered = rendered.replace(f"${{{key}}}", str(current))
    return rendered


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _append_unique(items: list[str], value: object) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def _topic_candidates(topic: object) -> list[str]:
    text = str(topic or "").strip()
    if not text:
        return []
    candidates = [text]
    if text.endswith("/compressed"):
        raw = text[: -len("/compressed")]
        if raw:
            candidates.append(raw)
    else:
        candidates.append(f"{text}/compressed")
    return candidates


def extract_status_camera_specs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract camera specs for device status UI.

    This intentionally includes both operator-facing camera nodes and recorder
    camera topics so setup UI can show per-camera connectivity.
    """
    settings = build_profile_settings(snapshot)
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    order: list[str] = []
    merged: dict[str, dict[str, Any]] = {}

    def add_camera(
        name: object,
        *,
        enabled: object = True,
        topics: Optional[list[str]] = None,
        label: object = None,
    ) -> None:
        key = str(name or "").strip()
        if not key:
            return
        entry = merged.get(key)
        if entry is None:
            resolved_label = str(label or "").strip() or key
            entry = {
                "name": key,
                "label": resolved_label,
                "enabled": _as_bool(enabled),
                "topics": [],
            }
            merged[key] = entry
            order.append(key)
        else:
            entry["enabled"] = bool(entry.get("enabled", True) or _as_bool(enabled))
            label_text = str(label or "").strip()
            if label_text and entry.get("label") == key:
                entry["label"] = label_text

        for topic in topics or []:
            _append_unique(entry["topics"], topic)

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        cameras = lerobot.get("cameras")
        if isinstance(cameras, list):
            for camera in cameras:
                if not isinstance(camera, dict):
                    continue
                source_name = _render_setting(
                    camera.get("source") or camera.get("name") or "", settings
                )
                topic = _render_setting(camera.get("topic") or "", settings)
                add_camera(
                    source_name,
                    enabled=True,
                    topics=_topic_candidates(topic),
                    label=_render_setting(camera.get("name") or "", settings),
                )

    actions = profile.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("type") != "include":
                continue

            package = str(action.get("package") or "").strip()
            launch_name = str(action.get("launch") or "").strip().lower()
            if package not in {"fv_camera", "fv_realsense", "vlabor_launch"}:
                continue
            if package == "vlabor_launch" and "camera" not in launch_name:
                continue

            args = action.get("args")
            if not isinstance(args, dict):
                continue

            node_name = _render_setting(args.get("node_name"), settings)
            enabled = _render_setting(action.get("enabled", True), settings)
            if package == "fv_realsense":
                # fv_realsense publishes with underscore separator (e.g. /d405_color/image_raw),
                # not slash (e.g. /d405/color/image_raw). Read the actual topic from
                # the node's config file when available, otherwise use the underscore convention.
                config_path = _resolve_config_path(args.get("config_file"), settings)
                config_params = _config_parameters(config_path, str(node_name or "")) if config_path else {}
                config_topics = config_params.get("topics")
                color_topic = ""
                if isinstance(config_topics, dict):
                    color_topic = str(config_topics.get("color") or config_topics.get("color_compressed") or "").strip()
                if not color_topic:
                    color_topic = f"/{node_name}_color/image_raw"
                base_topic = color_topic
            else:
                base_topic = f"/{node_name}/image_raw"
            add_camera(node_name, enabled=enabled, topics=_topic_candidates(base_topic))

    results: list[dict[str, Any]] = []
    for key in order:
        entry = dict(merged[key])
        topics = list(entry.get("topics") or [])
        if not topics:
            topics = _topic_candidates(f"/{key}/image_raw")
        entry["topics"] = topics
        results.append(entry)
    return results


def extract_status_arm_specs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract arm specs for device status UI."""
    settings = build_profile_settings(snapshot)
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    order: list[str] = []
    merged: dict[str, dict[str, Any]] = {}

    def infer_role(namespace: str) -> Optional[str]:
        lowered = namespace.lower()
        if "leader" in lowered:
            return "leader"
        if "follower" in lowered:
            return "follower"
        return None

    def add_arm(
        namespace: object,
        *,
        enabled: object = True,
        label: object = None,
        role: object = None,
        topics: Optional[list[str]] = None,
    ) -> None:
        key = str(namespace or "").strip()
        if not key:
            return

        entry = merged.get(key)
        role_text = str(role or "").strip() or infer_role(key)
        label_text = str(label or "").strip() or key
        if entry is None:
            entry = {
                "name": key,
                "label": label_text,
                "role": role_text,
                "enabled": _as_bool(enabled),
                "topics": [],
            }
            merged[key] = entry
            order.append(key)
        else:
            entry["enabled"] = bool(entry.get("enabled", True) or _as_bool(enabled))
            if label_text and entry.get("label") == key:
                entry["label"] = label_text
            if role_text and not entry.get("role"):
                entry["role"] = role_text

        for topic in topics or []:
            _append_unique(entry["topics"], topic)

    dashboard = profile.get("dashboard")
    if isinstance(dashboard, dict):
        arms = dashboard.get("arms")
        if isinstance(arms, list):
            for arm in arms:
                if not isinstance(arm, dict):
                    continue
                add_arm(
                    _render_setting(arm.get("namespace"), settings),
                    label=_render_setting(arm.get("label"), settings),
                    role=_render_setting(arm.get("role"), settings),
                )

    teleop = profile.get("teleop")
    if isinstance(teleop, dict):
        follower_arms = teleop.get("follower_arms")
        if isinstance(follower_arms, list):
            for arm in follower_arms:
                if not isinstance(arm, dict):
                    continue
                add_arm(
                    _render_setting(arm.get("namespace"), settings),
                    label=_render_setting(arm.get("label"), settings),
                    role="follower",
                )

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        for key, value in lerobot.items():
            if key == "cameras" or not isinstance(value, dict):
                continue
            add_arm(_render_setting(value.get("namespace"), settings), role="follower")

    actions = profile.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("type") != "node":
                continue
            package = str(action.get("package") or "").strip()
            if package not in {"unity_robot_control", "piper"}:
                continue
            add_arm(_render_setting(action.get("namespace"), settings))

    results: list[dict[str, Any]] = []
    for key in order:
        entry = dict(merged[key])
        topics = list(entry.get("topics") or [])
        if not topics:
            _append_unique(topics, f"/{key}/joint_states")
            _append_unique(topics, f"/{key}/joint_states_single")
        entry["topics"] = topics
        results.append(entry)
    return results


def extract_camera_specs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    settings = build_profile_settings(snapshot)
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    lerobot = profile.get("lerobot")
    if not isinstance(lerobot, dict):
        return []
    cameras = lerobot.get("cameras")
    if not isinstance(cameras, list):
        return []

    results: list[dict[str, Any]] = []
    for camera in cameras:
        if not isinstance(camera, dict):
            continue
        name = str(
            _render_setting(camera.get("name") or camera.get("source") or "", settings)
        ).strip()
        topic = str(_render_setting(camera.get("topic") or "", settings)).strip()
        source = str(_render_setting(camera.get("source") or name or "", settings)).strip() or name
        enabled = _as_bool(_render_setting(camera.get("enabled", True), settings))
        if not name or not topic:
            continue
        results.append(
            {
                "name": name,
                "topic": topic,
                "source": source,
                "enabled": enabled,
                "package": "lerobot",
            }
        )
    return results


def extract_arm_namespaces(snapshot: dict[str, Any]) -> list[str]:
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    namespaces: list[str] = []

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        for key, value in lerobot.items():
            if key == "cameras" or not isinstance(value, dict):
                continue
            namespace = str(value.get("namespace") or "").strip()
            if namespace and namespace not in namespaces:
                namespaces.append(namespace)
        if namespaces:
            return namespaces

    teleop = profile.get("teleop")
    if isinstance(teleop, dict):
        follower_arms = teleop.get("follower_arms")
        if isinstance(follower_arms, list):
            for arm in follower_arms:
                if not isinstance(arm, dict):
                    continue
                namespace = str(arm.get("namespace") or "").strip()
                if namespace and namespace not in namespaces:
                    namespaces.append(namespace)
            if namespaces:
                return namespaces

    dashboard = profile.get("dashboard")
    if isinstance(dashboard, dict):
        arms = dashboard.get("arms")
        if isinstance(arms, list):
            for arm in arms:
                if not isinstance(arm, dict):
                    continue
                namespace = str(arm.get("namespace") or "").strip()
                if namespace and namespace not in namespaces:
                    namespaces.append(namespace)
    return namespaces


def _resolved_topic(value: object, settings: dict[str, Any]) -> str:
    return str(_render_setting(value, settings) or "").strip()


def _is_absolute_ros_topic(topic: str) -> bool:
    return bool(topic) and topic.startswith("/")


def _normalize_node_name(name: object) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    if not text.startswith("/"):
        text = f"/{text}"
    return text.rstrip("/") or "/"


def _compose_node_name(namespace: object, name: object) -> str:
    namespace_text = str(namespace or "").strip().strip("/")
    name_text = str(name or "").strip().strip("/")
    if not name_text:
        return ""
    if namespace_text:
        return f"/{namespace_text}/{name_text}"
    return f"/{name_text}"


def _extract_action_topic_values(value: object, sink: list[str], settings: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _extract_action_topic_values(nested, sink, settings)
        return
    if isinstance(value, list):
        for nested in value:
            _extract_action_topic_values(nested, sink, settings)
        return
    topic = _resolved_topic(value, settings)
    if _is_absolute_ros_topic(topic):
        _append_unique(sink, topic)


def _enabled_actions(snapshot: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []
    actions = profile.get("actions")
    if not isinstance(actions, list):
        return []
    enabled_actions: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        enabled = _as_bool(_render_setting(action.get("enabled", True), settings))
        if enabled:
            enabled_actions.append(action)
    return enabled_actions


def _action_node_name(action: dict[str, Any], settings: dict[str, Any]) -> str:
    action_type = str(action.get("type") or "").strip()
    if action_type == "node":
        namespace = _render_setting(action.get("namespace"), settings)
        name = _render_setting(action.get("name"), settings)
        return _compose_node_name(namespace, name)
    if action_type == "include":
        args = action.get("args")
        if isinstance(args, dict):
            return _normalize_node_name(_render_setting(args.get("node_name"), settings))
    return ""


def _action_published_topics(action: dict[str, Any], settings: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    for key in ("parameters", "remappings"):
        value = action.get(key)
        _extract_action_topic_values(value, topics, settings)
    return topics


def _append_publisher_spec(
    sink: list[ProfileHealthPublisherSpec],
    *,
    node: object,
    publishes: list[str] | tuple[str, ...] | None = None,
    publishes_any: list[str] | tuple[str, ...] | None = None,
    required: bool = True,
) -> None:
    node_name = _normalize_node_name(node)
    exact = tuple(dict.fromkeys(str(topic).strip() for topic in (publishes or []) if str(topic).strip()))
    any_of = tuple(
        dict.fromkeys(str(topic).strip() for topic in (publishes_any or []) if str(topic).strip())
    )
    if not node_name:
        return
    spec = ProfileHealthPublisherSpec(
        node=node_name,
        publishes=exact,
        publishes_any=any_of,
        required=required,
    )
    if spec not in sink:
        sink.append(spec)


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _load_yaml_file(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _resolve_config_path(raw_value: object, settings: dict[str, Any]) -> Optional[Path]:
    rendered = _resolve_share_references(_render_setting(raw_value, settings))
    if not rendered:
        return None
    path = Path(rendered).expanduser()
    return path if path.is_file() else None


def _manifest_default_parameters(package_name: str) -> dict[str, Any]:
    package_dir = _resolve_package_share_dir(package_name)
    if not package_dir:
        return {}
    manifest_path = package_dir / "config" / "node_manifest.yaml"
    if not manifest_path.is_file():
        return {}
    payload = _load_yaml_file(manifest_path)
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return {}
    first = nodes[0]
    if not isinstance(first, dict):
        return {}
    defaults = first.get("default_parameters")
    return dict(defaults) if isinstance(defaults, dict) else {}


def _config_parameters(config_path: Path, node_name: str) -> dict[str, Any]:
    payload = _load_yaml_file(config_path)
    candidates = [
        node_name,
        _normalize_node_name(node_name),
        "/**",
        "**",
    ]
    for key in candidates:
        entry = payload.get(key)
        if isinstance(entry, dict):
            params = entry.get("ros__parameters")
            if isinstance(params, dict):
                return dict(params)
    if len(payload) == 1:
        only = next(iter(payload.values()))
        if isinstance(only, dict):
            params = only.get("ros__parameters")
            if isinstance(params, dict):
                return dict(params)
    return {}


def _node_topics_from_parameters(parameters: dict[str, Any]) -> list[str]:
    topics = parameters.get("topics")
    if not isinstance(topics, dict):
        return []
    # Determine which streams are disabled so we can skip their topics.
    streams = parameters.get("streams")
    disabled_topic_keys: set[str] = set()
    if isinstance(streams, dict):
        _stream_to_topic_key = {
            "pointcloud_enabled": "pointcloud",
            "depth_colormap_enabled": "depth_colormap",
            "infrared_enabled": "infrared",
        }
        for stream_flag, topic_key in _stream_to_topic_key.items():
            if stream_flag in streams and not _as_bool(streams[stream_flag]):
                disabled_topic_keys.add(topic_key)
    results: list[str] = []
    for key, value in topics.items():
        if key in disabled_topic_keys:
            continue
        topic = str(value or "").strip()
        if not topic:
            continue
        results.append(topic)
    return results


def _qualify_private_topic(node_name: str, topic: str) -> str:
    text = str(topic or "").strip()
    if not text:
        return ""
    if text.startswith("/"):
        return text
    return f"{_normalize_node_name(node_name)}/{text.lstrip('/')}"


def _resolve_include_publishers(
    action: dict[str, Any],
    settings: dict[str, Any],
) -> list[ProfileHealthPublisherSpec]:
    package = str(action.get("package") or "").strip()
    launch_name = str(action.get("launch") or "").strip()
    args = action.get("args")
    if not isinstance(args, dict):
        return []

    if (package, launch_name) == ("unity_robot_control", "vr_dual_arm_teleop_direct.launch.py"):
        return [
            ProfileHealthPublisherSpec(
                node="/follower_left/so101_control_node",
                publishes=("/follower_left/joint_states_single",),
            ),
            ProfileHealthPublisherSpec(
                node="/follower_right/so101_control_node",
                publishes=("/follower_right/joint_states_single",),
            ),
        ]

    node_name = _render_setting(args.get("node_name"), settings)
    normalized_node_name = _normalize_node_name(node_name)
    if not normalized_node_name:
        return []

    manifest_package: str | None = None
    if (package, launch_name) in {
        ("fv_camera", "fv_camera_launch.py"),
        ("vlabor_launch", "fv_camera_wrapper.launch.py"),
    }:
        manifest_package = "fv_camera"
    elif (package, launch_name) == ("fv_realsense", "fv_realsense_launch.py"):
        manifest_package = "fv_realsense"

    if not manifest_package:
        return []

    parameters = _manifest_default_parameters(manifest_package)
    config_path = _resolve_config_path(args.get("config_file"), settings)
    if config_path:
        parameters = _deep_merge_dict(parameters, _config_parameters(config_path, str(node_name or "")))

    topics = [
        _qualify_private_topic(str(node_name or ""), topic)
        for topic in _node_topics_from_parameters(parameters)
    ]
    resolved_topics = [topic for topic in topics if topic]
    if not resolved_topics:
        return []
    return [
        ProfileHealthPublisherSpec(
            node=normalized_node_name,
            publishes=tuple(dict.fromkeys(resolved_topics)),
        )
    ]


def classify_include_health_resolution(package: object, launch_name: object) -> str:
    key = (str(package or "").strip(), str(launch_name or "").strip())
    if key in _INCLUDE_PUBLISHER_RESOLVER_KEYS:
        return "supported"
    if key in _IGNORED_INCLUDE_KEYS:
        return "ignored"
    return "unknown"


def extract_recorder_arm_streams(
    snapshot: dict[str, Any],
    *,
    arm_namespaces: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Extract recorder arm stream config from profile snapshot.

    Each entry contains:
    - namespace
    - state_topic
    - action_topic
    - joint_names
    """
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    settings = build_profile_settings(snapshot)

    target_namespaces: list[str] = []
    for namespace in arm_namespaces or extract_arm_namespaces(snapshot):
        text = str(_render_setting(namespace, settings) or "").strip()
        if text and text not in target_namespaces:
            target_namespaces.append(text)
    if not target_namespaces:
        return []
    target_namespace_set = set(target_namespaces)

    lerobot = profile.get("lerobot")
    if not isinstance(lerobot, dict):
        return []

    streams_by_namespace: dict[str, dict[str, Any]] = {}
    for key, value in lerobot.items():
        if key == "cameras" or not isinstance(value, dict):
            continue
        namespace = str(_render_setting(value.get("namespace"), settings) or "").strip()
        if namespace not in target_namespace_set:
            continue
        if namespace in streams_by_namespace:
            return []

        state_topic = _resolved_topic(value.get("topic"), settings)
        action_topic = _resolved_topic(value.get("action_topic"), settings)
        raw_joints = value.get("joints")
        if not isinstance(raw_joints, list):
            continue
        joint_names = [
            str(_render_setting(name, settings) or "").strip()
            for name in raw_joints
            if str(_render_setting(name, settings) or "").strip()
        ]
        if not _is_absolute_ros_topic(state_topic):
            continue
        if not _is_absolute_ros_topic(action_topic):
            continue
        if not joint_names:
            continue
        if len(joint_names) != len(set(joint_names)):
            return []
        streams_by_namespace[namespace] = {
            "namespace": namespace,
            "state_topic": state_topic,
            "action_topic": action_topic,
            "joint_names": joint_names,
        }

    if any(namespace not in streams_by_namespace for namespace in target_namespaces):
        return []
    return [streams_by_namespace[namespace] for namespace in target_namespaces]


def build_inference_bridge_config(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build inference bridge stream config from VLAbor profile snapshot.

    This uses the same profile-derived source of truth as recording:
    arm stream topics and lerobot camera definitions.
    """
    arm_streams = extract_recorder_arm_streams(snapshot)

    camera_streams: list[dict[str, str]] = []
    seen_camera_names: set[str] = set()
    for spec in extract_camera_specs(snapshot):
        if not _as_bool(spec.get("enabled", True)):
            continue
        topic = str(spec.get("topic") or "").strip()
        # Inference worker alias mapping is based on "source" camera names.
        # Prefer source and fallback to display name when source is not present.
        name = str(spec.get("source") or spec.get("name") or "").strip()
        if not name or not topic or name in seen_camera_names:
            continue
        seen_camera_names.add(name)
        camera_streams.append({"name": name, "topic": topic})

    return {
        "arm_streams": arm_streams,
        "camera_streams": camera_streams,
    }


def build_inference_joint_names(snapshot: dict[str, Any]) -> list[str]:
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return []

    lerobot = profile.get("lerobot")
    if isinstance(lerobot, dict):
        names: list[str] = []
        for key, value in lerobot.items():
            if key == "cameras" or not isinstance(value, dict):
                continue
            namespace = str(value.get("namespace") or "").strip()
            joints = value.get("joints")
            if namespace and isinstance(joints, list):
                for joint in joints:
                    joint_name = str(joint).strip()
                    if not joint_name:
                        continue
                    names.append(f"{namespace}_{joint_name}")
        if names:
            return names

    names: list[str] = []
    for namespace in extract_arm_namespaces(snapshot):
        names.extend(f"{namespace}_{suffix}" for suffix in _SO101_DEFAULT_JOINT_SUFFIXES)
    return names


def build_inference_camera_aliases(snapshot: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for spec in extract_camera_specs(snapshot):
        if not _as_bool(spec.get("enabled", True)):
            continue
        source_name = str(spec.get("source") or "").strip()
        camera_name = str(spec.get("name") or "").strip()
        if not source_name or not camera_name:
            continue
        aliases[source_name] = camera_name
    return aliases


def build_profile_health_contract(snapshot: dict[str, Any]) -> ProfileHealthContract:
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return ProfileHealthContract(
            profile_name=str(snapshot.get("name") or "").strip(),
            required_topics=(),
            optional_topics=(),
            required_camera_topics=(),
            required_robot_topics=(),
            required_publishers=(),
            optional_publishers=(),
        )

    settings = build_profile_settings(snapshot)
    enabled_actions = _enabled_actions(snapshot, settings)
    include_publishers = [
        publisher
        for action in enabled_actions
        if str(action.get("type") or "").strip() == "include"
        for publisher in _resolve_include_publishers(action, settings)
    ]

    required_topics: list[str] = []
    required_camera_topics: list[str] = []
    required_robot_topics: list[str] = []
    required_publishers: list[ProfileHealthPublisherSpec] = []
    optional_topics: list[str] = []
    optional_publishers: list[ProfileHealthPublisherSpec] = []

    arm_streams = extract_recorder_arm_streams(snapshot)
    for stream in arm_streams:
        state_topic = str(stream.get("state_topic") or "").strip()
        namespace = str(stream.get("namespace") or "").strip()
        if not state_topic:
            continue
        _append_unique(required_topics, state_topic)
        _append_unique(required_robot_topics, state_topic)

        matched_node = ""
        for action in enabled_actions:
            action_type = str(action.get("type") or "").strip()
            node_name = _action_node_name(action, settings)
            if not node_name:
                continue
            action_namespace = str(_render_setting(action.get("namespace"), settings) or "").strip()
            if action_type == "node" and action_namespace == namespace:
                matched_node = node_name
                break
            published_topics = _action_published_topics(action, settings)
            if state_topic in published_topics:
                matched_node = node_name
                break
        if matched_node:
            _append_publisher_spec(
                required_publishers,
                node=matched_node,
                publishes=[state_topic],
                required=True,
            )
            continue

        for publisher in include_publishers:
            if state_topic in publisher.publishes:
                _append_publisher_spec(
                    required_publishers,
                    node=publisher.node,
                    publishes=[state_topic],
                    required=True,
                )
                break

    for spec in extract_camera_specs(snapshot):
        if not _as_bool(spec.get("enabled", True)):
            continue
        topic = str(spec.get("topic") or "").strip()
        source = str(spec.get("source") or spec.get("name") or "").strip()
        if not topic:
            continue
        _append_unique(required_topics, topic)
        _append_unique(required_camera_topics, topic)

        matched_node = ""
        topic_candidates = _topic_candidates(topic)
        for action in enabled_actions:
            if str(action.get("type") or "").strip() == "include":
                continue
            node_name = _action_node_name(action, settings)
            if not node_name:
                continue
            args = action.get("args")
            action_source = ""
            if isinstance(args, dict):
                action_source = str(_render_setting(args.get("node_name"), settings) or "").strip()
            if source and (
                node_name == _normalize_node_name(source)
                or action_source == source
                or node_name.endswith(f"/{source}")
            ):
                matched_node = node_name
                break
        if matched_node:
            _append_publisher_spec(
                required_publishers,
                node=matched_node,
                publishes_any=topic_candidates,
                required=True,
            )
            continue

        for publisher in include_publishers:
            published_topics = list(publisher.publishes)
            if source and publisher.node == _normalize_node_name(source):
                _append_publisher_spec(
                    required_publishers,
                    node=publisher.node,
                    publishes=published_topics,
                    required=True,
                )
                break
            if any(candidate in published_topics for candidate in topic_candidates):
                _append_publisher_spec(
                    required_publishers,
                    node=publisher.node,
                    publishes=published_topics,
                    required=True,
                )
                break
        else:
            if source:
                _append_publisher_spec(
                    required_publishers,
                    node=_normalize_node_name(source),
                    publishes_any=topic_candidates,
                    required=True,
                )

    return ProfileHealthContract(
        profile_name=str(snapshot.get("name") or profile.get("name") or "").strip(),
        required_topics=tuple(required_topics),
        optional_topics=tuple(optional_topics),
        required_camera_topics=tuple(required_camera_topics),
        required_robot_topics=tuple(required_robot_topics),
        required_publishers=tuple(required_publishers),
        optional_publishers=tuple(optional_publishers),
    )


async def get_active_profile_spec() -> VlaborProfileSpec:
    profiles = list_vlabor_profiles()
    if not profiles:
        raise HTTPException(status_code=404, detail="VLAbor profiles not found")

    by_name = {profile.name: profile for profile in profiles}
    selected_name = _load_active_profile_name_local()

    if selected_name and selected_name in by_name:
        return by_name[selected_name]

    fallback_name = _default_profile_name(list(by_name.keys()))
    if not fallback_name:
        raise HTTPException(status_code=404, detail="VLAbor profiles not found")
    return by_name[fallback_name]


async def set_active_profile_spec(profile_name: str) -> VlaborProfileSpec:
    profile = _profile_by_name(profile_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"VLAbor profile not found: {profile_name}")

    try:
        _save_active_profile_name_local(profile.name)
    except Exception as exc:  # noqa: BLE001 - surfaced as API detail
        raise HTTPException(status_code=500, detail=f"Failed to save active profile locally: {exc}") from exc
    return profile


async def save_session_profile_binding(
    *,
    session_kind: str,
    session_id: str,
    profile: VlaborProfileSpec,
) -> None:
    user_id = get_current_user_id()
    if not session_id:
        return

    client = await get_supabase_async_client()
    now = _now_iso()
    existing = (
        await client.table(_SESSION_PROFILE_TABLE)
        .select("session_id")
        .eq("owner_user_id", user_id)
        .eq("session_kind", session_kind)
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    ).data or []

    payload = {
        "profile_name": profile.name,
        "profile_snapshot": profile.snapshot,
        "profile_source_path": profile.source_path,
        "updated_at": now,
    }
    if existing:
        await (
            client.table(_SESSION_PROFILE_TABLE)
            .update(payload)
            .eq("owner_user_id", user_id)
            .eq("session_kind", session_kind)
            .eq("session_id", session_id)
            .execute()
        )
    else:
        await client.table(_SESSION_PROFILE_TABLE).insert(
            {
                "owner_user_id": user_id,
                "session_kind": session_kind,
                "session_id": session_id,
                "profile_name": profile.name,
                "profile_snapshot": profile.snapshot,
                "profile_source_path": profile.source_path,
                "created_at": now,
                "updated_at": now,
            }
        ).execute()


def resolve_profile_spec(profile_name: Optional[str]) -> VlaborProfileSpec:
    if profile_name:
        profile = _profile_by_name(profile_name)
        if profile:
            return profile
        raise HTTPException(status_code=404, detail=f"VLAbor profile not found: {profile_name}")

    profiles = list_vlabor_profiles()
    if not profiles:
        raise HTTPException(status_code=404, detail="VLAbor profiles not found")
    by_name = {profile.name: profile for profile in profiles}
    fallback_name = _default_profile_name(list(by_name.keys()))
    if not fallback_name:
        raise HTTPException(status_code=404, detail="VLAbor profiles not found")
    return by_name[fallback_name]

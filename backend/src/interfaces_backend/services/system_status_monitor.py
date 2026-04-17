"""Central status monitor for system snapshots."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from interfaces_backend.models.status_monitor import (
    ContainerStatusSnapshot,
    GpuDeviceSnapshot,
    GpuSnapshot,
    InferenceStatusSnapshot,
    OverallStatus,
    RecorderStatusSnapshot,
    Ros2StatusSnapshot,
    ServicesStatus,
    StatusAlert,
    StatusSnapshot,
    VlaborStatusSnapshot,
)
from interfaces_backend.services.dataset_lifecycle import get_dataset_lifecycle
from interfaces_backend.services.inference_runtime import get_inference_runtime_manager
from interfaces_backend.services.inference_session import get_inference_session_manager
from interfaces_backend.services.recorder_bridge import get_recorder_bridge
from interfaces_backend.services.vlabor_profiles import (
    ProfileHealthContract,
    ProfileHealthPublisherSpec,
    build_profile_health_contract,
    get_active_profile_spec,
)
from interfaces_backend.utils.docker_compose import (
    build_compose_command,
    get_vlabor_compose_file,
    get_vlabor_env_file,
)
from interfaces_backend.utils.docker_services import get_docker_service_summary

_GPU_INTERVAL_S = 2.0
_RECORDER_INTERVAL_S = 1.0
_INFERENCE_INTERVAL_S = 1.0
_VLABOR_INTERVAL_S = 5.0
_ROS2_INTERVAL_S = 3.0


@dataclass
class _Ros2ContractState:
    profile_name: str | None = None
    contract: ProfileHealthContract | None = None
    cameras_ready: bool | None = None
    robot_ready: bool | None = None
    optional_issue_summary: str | None = None
    missing_required_topics: list[str] = field(default_factory=list)
    missing_required_nodes: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "data" / ".env").exists():
            return candidate
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd()


class SystemStatusMonitor:
    def __init__(self, root_dir: Path | None = None) -> None:
        self._root_dir = (root_dir or _find_repo_root()).resolve()
        self._recorder = get_recorder_bridge()
        self._lock = threading.RLock()
        self._started = False
        self._tasks: list[asyncio.Task[None]] = []
        self._services = ServicesStatus()
        self._gpu = GpuSnapshot()
        self._ros2_contract_state = _Ros2ContractState()
        self._ros2_all_topics: list[str] = []
        self._snapshot = self._build_snapshot_locked()
        self._last_published_payload = ""

    def ensure_started(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._tasks = [
            asyncio.create_task(self._gpu_loop(), name="system-status-gpu"),
            asyncio.create_task(self._recorder_loop(), name="system-status-recorder"),
            asyncio.create_task(self._inference_loop(), name="system-status-inference"),
            asyncio.create_task(self._vlabor_loop(), name="system-status-vlabor"),
            asyncio.create_task(self._ros2_loop(), name="system-status-ros2"),
        ]

    async def shutdown(self) -> None:
        with self._lock:
            tasks = list(self._tasks)
            self._tasks = []
            self._started = False
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    def get_snapshot(self) -> StatusSnapshot:
        with self._lock:
            return self._snapshot.model_copy(deep=True)

    def get_cached_ros2_topics(self) -> list[str]:
        with self._lock:
            return list(self._ros2_all_topics)

    async def publish_snapshot(self) -> None:
        snapshot = self.get_snapshot()
        encoded = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        with self._lock:
            if encoded == self._last_published_payload:
                return
            self._last_published_payload = encoded
        return None

    async def _gpu_loop(self) -> None:
        while True:
            try:
                gpu_info = await asyncio.to_thread(self._probe_gpu)
                gpus = [
                    GpuDeviceSnapshot(
                        index=int(item.get("index", 0)),
                        name=str(item.get("name") or ""),
                        memory_total_mb=item.get("memory_total_mb"),
                        memory_used_mb=item.get("memory_used_mb"),
                        utilization_gpu_pct=item.get("utilization_gpu_pct"),
                        temperature_c=item.get("temperature_c"),
                    )
                    for item in gpu_info.get("gpus", [])
                ]
                level = "healthy" if gpu_info.get("available") else "unknown"
                gpu = GpuSnapshot(
                    level=level,
                    driver_version=gpu_info.get("driver_version"),
                    cuda_version=gpu_info.get("cuda_version"),
                    gpus=gpus,
                )
                with self._lock:
                    self._gpu = gpu
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._gpu = GpuSnapshot(level="error", gpus=[])
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            await asyncio.sleep(_GPU_INTERVAL_S)

    async def _recorder_loop(self) -> None:
        while True:
            try:
                recorder_status = await asyncio.to_thread(self._recorder.status)
                active_profile = await get_active_profile_spec()
                with self._lock:
                    ros2_state = _Ros2ContractState(
                        profile_name=self._ros2_contract_state.profile_name,
                        contract=self._ros2_contract_state.contract,
                        cameras_ready=self._ros2_contract_state.cameras_ready,
                        robot_ready=self._ros2_contract_state.robot_ready,
                        optional_issue_summary=self._ros2_contract_state.optional_issue_summary,
                        missing_required_topics=list(self._ros2_contract_state.missing_required_topics),
                        missing_required_nodes=list(self._ros2_contract_state.missing_required_nodes),
                    )
                snapshot = self._evaluate_recorder_health(
                    recorder_status=recorder_status,
                    ros2_state=ros2_state,
                    active_profile_name=active_profile.name if active_profile else None,
                )
                with self._lock:
                    self._services.recorder = snapshot
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            except asyncio.CancelledError:
                raise
            except HTTPException as exc:
                with self._lock:
                    self._services.recorder = RecorderStatusSnapshot(
                        level="error",
                        state="error",
                        process_alive=False,
                        last_error=str(exc.detail),
                    )
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._services.recorder = RecorderStatusSnapshot(
                        level="error",
                        state="error",
                        process_alive=False,
                        last_error=str(exc),
                    )
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            await asyncio.sleep(_RECORDER_INTERVAL_S)

    def _evaluate_recorder_health(
        self,
        *,
        recorder_status: dict[str, object],
        ros2_state: _Ros2ContractState,
        active_profile_name: str | None,
    ) -> RecorderStatusSnapshot:
        state = str(recorder_status.get("state") or "unknown").strip().lower() or "unknown"
        dataset_id = str(recorder_status.get("dataset_id") or "").strip() or None
        last_error = str(recorder_status.get("error") or "").strip() or None
        write_ok = recorder_status.get("write_ok") if isinstance(recorder_status.get("write_ok"), bool) else None
        disk_ok = recorder_status.get("disk_ok") if isinstance(recorder_status.get("disk_ok"), bool) else None

        storage_ready: bool | None
        if write_ok is False or disk_ok is False:
            storage_ready = False
        elif write_ok is True or disk_ok is True:
            storage_ready = True
        else:
            storage_ready = None

        dependency_errors: list[str] = []
        if ros2_state.cameras_ready is False:
            dependency_errors.append("required camera topics unavailable")
        if ros2_state.robot_ready is False:
            dependency_errors.append("required robot state topics unavailable")
        if storage_ready is False:
            dependency_errors.append("recorder storage is not writable")

        degraded_reasons: list[str] = []
        if ros2_state.optional_issue_summary:
            degraded_reasons.append(ros2_state.optional_issue_summary)
        if state == "recording" and not recorder_status.get("last_frame_at"):
            degraded_reasons.append("recording session has no recent frame timestamp")
        if state == "recording" and storage_ready is None:
            degraded_reasons.append("recorder storage readiness is unknown")

        if last_error:
            level = "error"
        elif dependency_errors:
            level = "error"
            last_error = "; ".join(dependency_errors)
        elif state in {"recording", "warming", "paused", "resetting", "resetting_paused", "idle", "completed"}:
            level = "degraded" if degraded_reasons else "healthy"
            if degraded_reasons:
                last_error = "; ".join(degraded_reasons)
        else:
            level = "degraded"
            if not last_error:
                last_error = f"recorder state is {state}"

        return RecorderStatusSnapshot(
            level=level,
            state=state,
            process_alive=True,
            session_id=dataset_id,
            active_profile=active_profile_name,
            dataset_id=dataset_id,
            output_path=str(recorder_status.get("output_path") or "") or None,
            last_frame_at=str(recorder_status.get("last_frame_at") or "") or None,
            write_ok=write_ok,
            disk_ok=disk_ok,
            dependencies={
                "cameras_ready": ros2_state.cameras_ready,
                "robot_ready": ros2_state.robot_ready,
                "storage_ready": storage_ready,
            },
            last_error=last_error,
        )

    async def _inference_loop(self) -> None:
        while True:
            try:
                status = await asyncio.to_thread(self._probe_inference)
                runner = status["runner_status"]
                gpu_host = status["gpu_host_status"]
                runtime_context = status["runtime_context"]
                if gpu_host["status"] == "error" or runner.get("last_error"):
                    level = "error"
                elif runner["active"] or gpu_host["status"] in {"running", "idle"}:
                    level = "healthy"
                else:
                    level = "unknown"
                state = "running" if runner["active"] else (gpu_host["status"] or "unknown")
                snapshot = InferenceStatusSnapshot(
                    level=level,
                    state=state,
                    session_id=runner.get("session_id"),
                    policy_type=self._optional_str(runtime_context.get("policy_type")),
                    model_id=self._optional_str(runtime_context.get("model_id")),
                    device=self._optional_str(runtime_context.get("device")),
                    env_name=self._optional_str(runtime_context.get("env_name")),
                    queue_length=runner.get("queue_length"),
                    worker_alive=gpu_host["status"] in {"running", "idle"},
                    last_error=runner.get("last_error") or gpu_host.get("last_error"),
                )
                with self._lock:
                    self._services.inference = snapshot
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._services.inference = InferenceStatusSnapshot(
                        level="error",
                        state="error",
                        worker_alive=False,
                        last_error=str(exc),
                    )
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            await asyncio.sleep(_INFERENCE_INTERVAL_S)

    async def _vlabor_loop(self) -> None:
        while True:
            try:
                raw = await asyncio.to_thread(self._probe_vlabor)
                state = str(raw.get("status") or "unknown").strip().lower() or "unknown"
                with self._lock:
                    ros2_status = self._services.ros2.model_copy(deep=True)

                last_error = str(raw.get("error") or "").strip() or None
                if state in {"stopped", "error"}:
                    level = "error"
                elif state == "restarting":
                    level = "degraded"
                elif state == "running":
                    if ros2_status.level == "healthy":
                        level = "healthy"
                    elif ros2_status.level in {"degraded", "error"}:
                        level = "degraded"
                        if not last_error and ros2_status.last_error:
                            last_error = ros2_status.last_error
                    else:
                        level = "unknown"
                else:
                    level = "unknown"
                snapshot = VlaborStatusSnapshot(
                    level=level,
                    state=state,
                    containers=[
                        ContainerStatusSnapshot(
                            name=str(raw.get("service") or "vlabor"),
                            state=str(raw.get("state") or state),
                        )
                    ],
                    last_error=last_error,
                )
                with self._lock:
                    self._services.vlabor = snapshot
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._services.vlabor = VlaborStatusSnapshot(
                        level="error",
                        state="error",
                        last_error=str(exc),
                    )
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            await asyncio.sleep(_VLABOR_INTERVAL_S)

    async def _ros2_loop(self) -> None:
        while True:
            try:
                active_profile = await get_active_profile_spec()
                contract = build_profile_health_contract(active_profile.snapshot)
                graph = await asyncio.to_thread(self._probe_ros2_graph, contract)
                snapshot, contract_state = self._evaluate_ros2_health(contract, graph)
                with self._lock:
                    self._services.ros2 = snapshot
                    self._ros2_contract_state = contract_state
                    all_topics = graph.get("all_topics")
                    self._ros2_all_topics = [
                        item
                        for item in (
                            [self._optional_str(value) for value in all_topics]
                            if isinstance(all_topics, list)
                            else []
                        )
                        if item
                    ]
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._services.ros2 = Ros2StatusSnapshot(
                        level="error",
                        state="error",
                        last_error=str(exc),
                    )
                    self._ros2_contract_state = _Ros2ContractState()
                    self._ros2_all_topics = []
                    self._refresh_snapshot_locked()
                await self.publish_snapshot()
            await asyncio.sleep(_ROS2_INTERVAL_S)

    def _probe_gpu(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "available": False,
            "cuda_version": None,
            "driver_version": None,
            "gpus": [],
        }
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                payload["driver_version"] = result.stdout.strip().splitlines()[0].strip()
                payload["available"] = True
        except Exception:
            pass

        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                gpus: list[dict[str, object]] = []
                for line in result.stdout.strip().splitlines():
                    parts = [part.strip() for part in line.split(",")]
                    if len(parts) < 6:
                        continue
                    gpus.append(
                        {
                            "index": int(parts[0]),
                            "name": parts[1],
                            "memory_total_mb": self._parse_float(parts[2]),
                            "memory_used_mb": self._parse_float(parts[3]),
                            "utilization_gpu_pct": self._parse_float(parts[4]),
                            "temperature_c": self._parse_float(parts[5]),
                        }
                    )
                payload["gpus"] = gpus
                if gpus:
                    payload["available"] = True
        except Exception:
            pass

        return payload

    def _probe_inference(self) -> dict[str, dict[str, object]]:
        runtime_manager = get_inference_runtime_manager()
        runtime_status = runtime_manager.get_status()
        runtime_context = runtime_manager.get_runtime_context()
        recording_status = get_inference_session_manager().get_active_recording_status()
        runner_status = runtime_status.runner_status.model_copy(update=recording_status)
        model_sync = get_dataset_lifecycle().get_model_sync_status()
        return {
            "runner_status": runner_status.model_dump(mode="json"),
            "gpu_host_status": runtime_status.gpu_host_status.model_dump(mode="json"),
            "model_sync": model_sync.model_dump(mode="json"),
            "runtime_context": runtime_context,
        }

    def _probe_vlabor(self) -> dict[str, str]:
        compose_file = get_vlabor_compose_file()
        if not compose_file.exists():
            return {"status": "unknown", "service": "vlabor"}
        entry = get_docker_service_summary("vlabor")
        if not entry:
            return {"status": "unknown", "service": "vlabor"}
        state_raw = str(entry.get("state") or "").lower()
        if "restarting" in state_raw:
            status = "restarting"
        elif "running" in state_raw:
            status = "running"
        elif "exited" in state_raw or "stopped" in state_raw:
            status = "stopped"
        else:
            status = "unknown"
        return {
            "status": status,
            "service": "vlabor",
            "state": str(entry.get("state") or status),
            "status_detail": str(entry.get("status_detail") or ""),
            "dashboard_url": f"http://{socket.gethostname()}.local:8888",
        }

    def _probe_ros2_graph(self, contract: ProfileHealthContract) -> dict[str, object]:
        compose_file = get_vlabor_compose_file()
        if not compose_file.exists():
            return {"nodes": [], "topics": {}, "all_topics": []}
        compose_cmd = build_compose_command(compose_file, get_vlabor_env_file())
        topics = sorted(
            {
                topic
                for topic in (
                    list(contract.required_topics)
                    + list(contract.optional_topics)
                    + [
                        item
                        for publisher in list(contract.required_publishers)
                        + list(contract.optional_publishers)
                        for item in (*publisher.publishes, *publisher.publishes_any)
                    ]
                )
                if str(topic).strip()
            }
        )
        script = """
import json
import time

import rclpy
from rclpy.node import Node

TOPICS = __TOPICS__


def _full_node_name(namespace: str, name: str) -> str:
    namespace_text = (namespace or "").strip()
    name_text = (name or "").strip()
    if not name_text:
        return ""
    if not namespace_text or namespace_text == "/":
        return f"/{name_text}"
    return f"{namespace_text.rstrip('/')}/{name_text}"


rclpy.init(args=None)
node = Node("system_status_probe")
time.sleep(0.75)

topic_names = sorted(name for name, _ in node.get_topic_names_and_types())
nodes = sorted(
    _full_node_name(namespace, name)
    for name, namespace in node.get_node_names_and_namespaces()
    if _full_node_name(namespace, name)
)
topics = {}
for topic in TOPICS:
    publishers = sorted(
        {
            _full_node_name(info.node_namespace, info.node_name)
            for info in node.get_publishers_info_by_topic(topic)
        }
    )
    topics[topic] = {
        "exists": topic in topic_names,
        "publisher_nodes": publishers,
        "publisher_count": len(publishers),
    }

node.destroy_node()
rclpy.shutdown()
print(json.dumps({"nodes": nodes, "topics": topics, "all_topics": topic_names}))
""".replace("__TOPICS__", json.dumps(topics))
        result = subprocess.run(
            [
                *compose_cmd,
                "exec",
                "-T",
                "vlabor",
                "bash",
                "-lc",
                "source /opt/ros/humble/setup.sh && python3 -",
            ],
            input=script,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip() or "ROS2 graph probe failed"
            raise RuntimeError(detail)
        try:
            payload = json.loads(result.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("ROS2 graph probe output parse failed") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("ROS2 graph probe returned invalid payload")
        return payload

    def _evaluate_ros2_health(
        self,
        contract: ProfileHealthContract,
        graph: dict[str, object],
    ) -> tuple[Ros2StatusSnapshot, _Ros2ContractState]:
        nodes = {
            self._optional_str(item)
            for item in graph.get("nodes", [])
            if self._optional_str(item)
        }
        topics = graph.get("topics")
        topic_statuses = topics if isinstance(topics, dict) else {}
        all_topics = graph.get("all_topics")
        all_topic_set = {
            item
            for item in (
                [self._optional_str(value) for value in all_topics]
                if isinstance(all_topics, list)
                else []
            )
            if item
        }

        missing_required_topics: list[str] = []
        missing_optional_topics: list[str] = []
        missing_required_nodes: list[str] = []
        missing_optional_nodes: list[str] = []

        def topic_has_publisher(topic: str) -> bool:
            data = topic_statuses.get(topic)
            if not isinstance(data, dict):
                return False
            if isinstance(data.get("publisher_count"), int):
                return data["publisher_count"] > 0
            publishers = data.get("publisher_nodes")
            return bool(publishers) if isinstance(publishers, list) else False

        def publisher_nodes_for_topic(topic: str) -> set[str]:
            data = topic_statuses.get(topic)
            if not isinstance(data, dict):
                return set()
            publishers = data.get("publisher_nodes")
            if not isinstance(publishers, list):
                return set()
            return {item for item in (self._optional_str(value) for value in publishers) if item}

        for topic in contract.required_topics:
            if topic not in all_topic_set or not topic_has_publisher(topic):
                missing_required_topics.append(topic)

        for topic in contract.optional_topics:
            if topic not in all_topic_set or not topic_has_publisher(topic):
                missing_optional_topics.append(topic)

        def evaluate_publishers(
            publishers: tuple[ProfileHealthPublisherSpec, ...],
            sink: list[str],
        ) -> None:
            for publisher in publishers:
                node_name = publisher.node
                if node_name not in nodes:
                    sink.append(node_name)
                    continue
                exact_ok = all(
                    node_name in publisher_nodes_for_topic(topic)
                    for topic in publisher.publishes
                )
                any_ok = True
                if publisher.publishes_any:
                    any_ok = any(
                        node_name in publisher_nodes_for_topic(topic)
                        for topic in publisher.publishes_any
                    )
                if not exact_ok or not any_ok:
                    sink.append(node_name)

        evaluate_publishers(contract.required_publishers, missing_required_nodes)
        evaluate_publishers(contract.optional_publishers, missing_optional_nodes)

        cameras_ready = None if not contract.required_camera_topics else not any(
            topic in set(missing_required_topics) for topic in contract.required_camera_topics
        )
        robot_ready = None if not contract.required_robot_topics else not any(
            topic in set(missing_required_topics) for topic in contract.required_robot_topics
        )

        required_topics_ok = None if not contract.required_topics else not missing_required_topics
        required_nodes_ok = None if not contract.required_publishers else not missing_required_nodes

        optional_issue_parts: list[str] = []
        if missing_optional_topics:
            optional_issue_parts.append(
                "optional topics missing: " + ", ".join(sorted(dict.fromkeys(missing_optional_topics)))
            )
        if missing_optional_nodes:
            optional_issue_parts.append(
                "optional publishers missing: " + ", ".join(sorted(dict.fromkeys(missing_optional_nodes)))
            )
        optional_issue_summary = "; ".join(optional_issue_parts) or None

        required_issue_parts: list[str] = []
        if missing_required_topics:
            required_issue_parts.append(
                "required topics missing: " + ", ".join(sorted(dict.fromkeys(missing_required_topics)))
            )
        if missing_required_nodes:
            required_issue_parts.append(
                "required publishers missing: " + ", ".join(sorted(dict.fromkeys(missing_required_nodes)))
            )

        if required_issue_parts:
            snapshot = Ros2StatusSnapshot(
                level="error",
                state="partial",
                required_nodes_ok=required_nodes_ok,
                required_topics_ok=required_topics_ok,
                missing_nodes=sorted(dict.fromkeys(missing_required_nodes)),
                missing_topics=sorted(dict.fromkeys(missing_required_topics)),
                last_error="; ".join(required_issue_parts),
            )
        elif optional_issue_summary:
            snapshot = Ros2StatusSnapshot(
                level="degraded",
                state="partial",
                required_nodes_ok=required_nodes_ok,
                required_topics_ok=required_topics_ok,
                last_error=optional_issue_summary,
            )
        elif contract.required_topics or contract.required_publishers:
            snapshot = Ros2StatusSnapshot(
                level="healthy",
                state="running",
                required_nodes_ok=required_nodes_ok,
                required_topics_ok=required_topics_ok,
            )
        elif all_topic_set or nodes:
            snapshot = Ros2StatusSnapshot(
                level="healthy",
                state="running",
            )
        else:
            snapshot = Ros2StatusSnapshot(
                level="unknown",
                state="unknown",
            )

        contract_state = _Ros2ContractState(
            profile_name=contract.profile_name or None,
            contract=contract,
            cameras_ready=cameras_ready,
            robot_ready=robot_ready,
            optional_issue_summary=optional_issue_summary,
            missing_required_topics=sorted(dict.fromkeys(missing_required_topics)),
            missing_required_nodes=sorted(dict.fromkeys(missing_required_nodes)),
        )
        return snapshot, contract_state

    @staticmethod
    def _parse_float(value: str) -> float | None:
        text = str(value or "").strip()
        if not text or text in {"[N/A]", "N/A"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _refresh_snapshot_locked(self) -> None:
        self._snapshot = self._build_snapshot_locked()

    def _build_snapshot_locked(self) -> StatusSnapshot:
        overall = self._build_overall_locked()
        return StatusSnapshot(
            generated_at=_now_iso(),
            overall=overall,
            services=self._services.model_copy(deep=True),
            gpu=self._gpu.model_copy(deep=True),
        )

    def _build_overall_locked(self) -> OverallStatus:
        alerts: list[StatusAlert] = []

        for name, status in [
            ("recorder", self._services.recorder),
            ("inference", self._services.inference),
            ("vlabor", self._services.vlabor),
            ("ros2", self._services.ros2),
        ]:
            if status.level in {"degraded", "error"}:
                message = getattr(status, "last_error", None) or f"{name} is {status.level}"
                alerts.append(
                    StatusAlert(
                        code=name,
                        level=status.level,
                        summary=str(message),
                        source=name,
                    )
                )

        if self._gpu.level in {"degraded", "error"}:
            alerts.append(
                StatusAlert(
                    code="gpu",
                    level=self._gpu.level,
                    summary="GPU status is degraded" if self._gpu.level == "degraded" else "GPU status error",
                    source="gpu",
                )
            )

        if any(item.level == "error" for item in alerts):
            level = "error"
            summary = "One or more services are in error state."
        elif any(item.level == "degraded" for item in alerts):
            level = "degraded"
            summary = "One or more services are degraded."
        elif self._gpu.gpus:
            level = "healthy"
            summary = "System status is healthy."
        else:
            level = "unknown"
            summary = "System status has not been observed yet."
        return OverallStatus(level=level, summary=summary, active_alerts=alerts)

    @staticmethod
    def _optional_str(value: object) -> str | None:
        text = str(value or "").strip()
        return text or None


_system_status_monitor: SystemStatusMonitor | None = None
_system_status_monitor_lock = threading.Lock()


def get_system_status_monitor() -> SystemStatusMonitor:
    global _system_status_monitor
    with _system_status_monitor_lock:
        if _system_status_monitor is None:
            _system_status_monitor = SystemStatusMonitor()
    return _system_status_monitor

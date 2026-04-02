"""Typed source registry for tab-session realtime streams."""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException, Response
from paramiko.channel import Channel

from percus_ai.training.ssh.client import SSHConnection
from interfaces_backend.models.realtime import (
    ProfilesActiveSubscription,
    ProfilesVlaborSubscription,
    OperateStatusSubscription,
    RecordingUploadStatusSubscription,
    StorageDatasetMergeSubscription,
    StorageDatasetSyncSubscription,
    StorageModelSyncSubscription,
    StartupOperationSubscription,
    SystemBundledTorchSubscription,
    SystemRuntimeEnvsSubscription,
    SystemStatusSubscription,
    TabSessionSubscription,
    TrainingProvisionOperationSubscription,
    TrainingJobCoreSubscription,
    TrainingJobLogsSubscription,
    TrainingJobMetricsSubscription,
    TrainingJobOperationSubscription,
    TrainingJobProvisionSubscription,
)


@dataclass(frozen=True)
class RealtimeSourcePollResult:
    op: Literal["snapshot", "append", "control"] = "snapshot"
    payload: dict[str, Any] | None = None
    error: str | None = None
    cursor: str | None = None
    next_state: Any | None = None
    close_state: bool = False


@dataclass
class TrainingJobLogStreamState:
    ssh_conn: SSHConnection
    channel: Channel
    partial_line: str = ""
    cursor: int = 0
    last_status_poll_mono: float = 0.0


class TabRealtimeSourceRegistry:
    """Resolves supported subscriptions to typed async source handlers."""

    def interval_for(self, subscription: TabSessionSubscription) -> float:
        if isinstance(subscription, ProfilesActiveSubscription):
            return 5.0
        if isinstance(subscription, ProfilesVlaborSubscription):
            return 2.0
        if isinstance(subscription, SystemStatusSubscription):
            return 2.0
        if isinstance(subscription, OperateStatusSubscription):
            return 2.0
        if isinstance(subscription, SystemRuntimeEnvsSubscription):
            return 2.0
        if isinstance(subscription, SystemBundledTorchSubscription):
            return 2.0
        if isinstance(subscription, RecordingUploadStatusSubscription):
            return 1.0
        if isinstance(subscription, StartupOperationSubscription):
            return 0.5
        if isinstance(subscription, TrainingProvisionOperationSubscription):
            return 0.5
        if isinstance(subscription, TrainingJobOperationSubscription):
            return 0.5
        if isinstance(subscription, StorageModelSyncSubscription):
            return 0.5
        if isinstance(subscription, StorageDatasetSyncSubscription):
            return 0.5
        if isinstance(subscription, StorageDatasetMergeSubscription):
            return 0.5
        if isinstance(subscription, TrainingJobProvisionSubscription):
            return 2.0
        if isinstance(subscription, TrainingJobCoreSubscription):
            return 5.0
        if isinstance(subscription, TrainingJobMetricsSubscription):
            return 5.0
        if isinstance(subscription, TrainingJobLogsSubscription):
            return 0.1
        raise RuntimeError(f"Unsupported subscription type: {type(subscription).__name__}")

    async def poll(
        self,
        subscription: TabSessionSubscription,
        state: Any | None = None,
    ) -> RealtimeSourcePollResult:
        try:
            if isinstance(subscription, ProfilesActiveSubscription):
                from interfaces_backend.api.profiles import get_active_profile_status

                snapshot = await get_active_profile_status()
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, ProfilesVlaborSubscription):
                from interfaces_backend.api.profiles import get_vlabor_status

                snapshot = await get_vlabor_status()
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, SystemStatusSubscription):
                from interfaces_backend.services.system_status_monitor import (
                    get_system_status_monitor,
                )

                monitor = get_system_status_monitor()
                monitor.ensure_started()
                snapshot = monitor.get_snapshot()
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, OperateStatusSubscription):
                from interfaces_backend.api.inference import get_inference_runner_status
                from interfaces_backend.api.operate import get_operate_status
                from interfaces_backend.api.profiles import get_vlabor_status

                vlabor_status = await get_vlabor_status()
                inference_runner_status = await get_inference_runner_status()
                operate_status = await get_operate_status()
                return RealtimeSourcePollResult(
                    payload={
                        "vlabor_status": vlabor_status.model_dump(mode="json"),
                        "inference_runner_status": inference_runner_status.model_dump(mode="json"),
                        "operate_status": operate_status.model_dump(mode="json"),
                    }
                )

            if isinstance(subscription, SystemRuntimeEnvsSubscription):
                from interfaces_backend.services.runtime_env_service import (
                    get_runtime_env_service,
                )

                service = get_runtime_env_service()
                await service.refresh_snapshot()
                snapshot = service.get_snapshot()
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, SystemBundledTorchSubscription):
                from interfaces_backend.services.bundled_torch_build_service import (
                    get_bundled_torch_build_service,
                )

                service = get_bundled_torch_build_service()
                await service.refresh_snapshot()
                snapshot = service.get_snapshot()
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, RecordingUploadStatusSubscription):
                from interfaces_backend.services.dataset_lifecycle import get_dataset_lifecycle

                lifecycle = get_dataset_lifecycle()
                snapshot = lifecycle.get_dataset_upload_status(subscription.params.session_id)
                return RealtimeSourcePollResult(payload=dict(snapshot))

            if isinstance(subscription, StartupOperationSubscription):
                from interfaces_backend.services.session_manager import require_user_id
                from interfaces_backend.services.startup_operations import (
                    get_startup_operations_service,
                )

                user_id = require_user_id()
                snapshot = get_startup_operations_service().get(
                    user_id=user_id,
                    operation_id=subscription.params.operation_id,
                )
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, TrainingProvisionOperationSubscription):
                from percus_ai.db import get_current_user_id
                from interfaces_backend.services.training_provision_operations import (
                    get_training_provision_operations_service,
                )

                user_id = get_current_user_id()
                snapshot = await get_training_provision_operations_service().get(
                    user_id=user_id,
                    operation_id=subscription.params.operation_id,
                )
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, TrainingJobOperationSubscription):
                from percus_ai.db import get_current_user_id
                from interfaces_backend.services.training_job_operations import (
                    get_training_job_operations_service,
                )

                user_id = get_current_user_id()
                snapshot = get_training_job_operations_service().get(
                    user_id=user_id,
                    operation_id=subscription.params.operation_id,
                )
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, StorageModelSyncSubscription):
                from interfaces_backend.services.session_manager import require_user_id
                from interfaces_backend.services.model_sync_jobs import (
                    get_model_sync_jobs_service,
                )

                user_id = require_user_id()
                snapshot = get_model_sync_jobs_service().get(
                    user_id=user_id,
                    job_id=subscription.params.job_id,
                )
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, StorageDatasetSyncSubscription):
                from interfaces_backend.services.session_manager import require_user_id
                from interfaces_backend.services.dataset_sync_jobs import (
                    get_dataset_sync_jobs_service,
                )

                user_id = require_user_id()
                snapshot = get_dataset_sync_jobs_service().get(
                    user_id=user_id,
                    job_id=subscription.params.job_id,
                )
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, StorageDatasetMergeSubscription):
                from interfaces_backend.services.session_manager import require_user_id
                from interfaces_backend.services.dataset_merge_jobs import (
                    get_dataset_merge_jobs_service,
                )

                user_id = require_user_id()
                snapshot = get_dataset_merge_jobs_service().get(
                    user_id=user_id,
                    job_id=subscription.params.job_id,
                )
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, TrainingJobCoreSubscription):
                from interfaces_backend.api.training import get_job

                snapshot = await get_job(subscription.params.job_id)
                payload = snapshot.model_dump(mode="json")
                payload.pop("provision_operation", None)
                return RealtimeSourcePollResult(payload=payload)

            if isinstance(subscription, TrainingJobProvisionSubscription):
                from interfaces_backend.api.training import get_job_provision_operation

                try:
                    snapshot = await get_job_provision_operation(subscription.params.job_id)
                except HTTPException as exc:
                    if exc.status_code == 404:
                        return RealtimeSourcePollResult(payload={"provision_operation": None})
                    raise
                return RealtimeSourcePollResult(
                    payload={"provision_operation": snapshot.model_dump(mode="json")}
                )

            if isinstance(subscription, TrainingJobMetricsSubscription):
                from interfaces_backend.api.training import get_job_metrics

                snapshot = await get_job_metrics(
                    job_id=subscription.params.job_id,
                    response=Response(),
                    limit=subscription.params.limit or 1000,
                )
                return RealtimeSourcePollResult(payload=snapshot.model_dump(mode="json"))

            if isinstance(subscription, TrainingJobLogsSubscription):
                return await self._poll_training_job_logs(subscription, state)
        except HTTPException as exc:
            return RealtimeSourcePollResult(error=f"{exc.status_code}: {exc.detail}")
        except Exception as exc:  # noqa: BLE001
            return RealtimeSourcePollResult(error=str(exc), next_state=state, close_state=True)

        return RealtimeSourcePollResult(error=f"Unsupported subscription kind: {subscription.kind}")

    def cleanup(self, subscription: TabSessionSubscription, state: Any | None) -> None:
        if not isinstance(subscription, TrainingJobLogsSubscription):
            return
        if not isinstance(state, TrainingJobLogStreamState):
            return
        try:
            state.channel.close()
        except Exception:
            pass
        try:
            state.ssh_conn.disconnect()
        except Exception:
            pass

    async def _poll_training_job_logs(
        self,
        subscription: TrainingJobLogsSubscription,
        state: Any | None,
    ) -> RealtimeSourcePollResult:
        from interfaces_backend.api.training import (
            RUNNING_STATUSES,
            _get_setup_log_file_path,
            _get_ssh_connection_for_job,
            _get_training_log_file_path,
            _load_job,
        )

        log_state = state if isinstance(state, TrainingJobLogStreamState) else None
        if log_state is None:
            job_data = await _load_job(subscription.params.job_id)
            if not job_data:
                return RealtimeSourcePollResult(
                    op="control",
                    payload={"type": "job_missing"},
                    close_state=True,
                )
            if not job_data.get("ip"):
                return RealtimeSourcePollResult(
                    op="control",
                    payload={"type": "ip_missing"},
                    close_state=True,
                )

            loop = asyncio.get_running_loop()
            ssh_conn = await loop.run_in_executor(
                None,
                lambda: _get_ssh_connection_for_job(job_data, timeout=30),
            )
            if not ssh_conn:
                return RealtimeSourcePollResult(error="SSH connection failed", close_state=True)

            log_file = (
                _get_setup_log_file_path(job_data)
                if subscription.params.log_type == "setup"
                else _get_training_log_file_path(job_data)
            )
            channel = ssh_conn.client.get_transport().open_session()
            tail_lines = subscription.params.tail_lines or 400
            channel.exec_command(
                f"tail -n {tail_lines} -F {shlex.quote(log_file)} 2>/dev/null"
            )
            channel.setblocking(0)
            next_state = TrainingJobLogStreamState(
                ssh_conn=ssh_conn,
                channel=channel,
                last_status_poll_mono=asyncio.get_running_loop().time(),
            )
            return RealtimeSourcePollResult(
                op="control",
                payload={
                    "type": "connected",
                    "job_id": subscription.params.job_id,
                    "log_type": subscription.params.log_type,
                },
                next_state=next_state,
            )

        emitted_lines: list[str] = []
        while log_state.channel.recv_ready():
            data = log_state.channel.recv(4096)
            if not data:
                break
            decoded = data.decode("utf-8", errors="replace")
            buffer = f"{log_state.partial_line}{decoded}"
            parts = buffer.split("\n")
            if buffer.endswith("\n"):
                log_state.partial_line = ""
                if parts and parts[-1] == "":
                    parts.pop()
            else:
                log_state.partial_line = parts.pop()
            emitted_lines.extend(parts)

        if emitted_lines:
            log_state.cursor += len(emitted_lines)
            return RealtimeSourcePollResult(
                op="append",
                payload={
                    "job_id": subscription.params.job_id,
                    "log_type": subscription.params.log_type,
                    "lines": emitted_lines,
                },
                cursor=str(log_state.cursor),
                next_state=log_state,
            )

        if log_state.channel.exit_status_ready():
            return RealtimeSourcePollResult(
                op="control",
                payload={
                    "type": "stream_ended",
                    "job_id": subscription.params.job_id,
                    "log_type": subscription.params.log_type,
                },
                next_state=log_state,
                close_state=True,
            )

        now_mono = asyncio.get_running_loop().time()
        if (now_mono - log_state.last_status_poll_mono) >= 5.0:
            log_state.last_status_poll_mono = now_mono
            current_job = await _load_job(subscription.params.job_id, include_deleted=True)
            if current_job is None:
                return RealtimeSourcePollResult(
                    op="control",
                    payload={
                        "type": "job_deleted",
                        "job_id": subscription.params.job_id,
                        "log_type": subscription.params.log_type,
                    },
                    next_state=log_state,
                    close_state=True,
                )
            current_status = str(current_job.get("status") or "").strip()
            if current_status and current_status not in RUNNING_STATUSES:
                return RealtimeSourcePollResult(
                    op="control",
                    payload={
                        "type": "job_status",
                        "job_id": subscription.params.job_id,
                        "log_type": subscription.params.log_type,
                        "status": current_status,
                    },
                    next_state=log_state,
                    close_state=True,
                )

        return RealtimeSourcePollResult(next_state=log_state)


_tab_realtime_source_registry: TabRealtimeSourceRegistry | None = None


def get_tab_realtime_source_registry() -> TabRealtimeSourceRegistry:
    global _tab_realtime_source_registry
    if _tab_realtime_source_registry is None:
        _tab_realtime_source_registry = TabRealtimeSourceRegistry()
    return _tab_realtime_source_registry

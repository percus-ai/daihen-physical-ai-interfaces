"""Training jobs API router."""

import asyncio
import inspect
import json
import logging
import os
import re
import shlex
import stat
import tempfile
import textwrap
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Literal, Optional, TypeVar

from verda import VerdaClient
from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import PlainTextResponse
from postgrest.exceptions import APIError
from supabase._async.client import AsyncClient

from interfaces_backend.core.request_auth import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    build_session_from_tokens,
    is_session_expired,
    refresh_session_from_refresh_token,
)
from interfaces_backend.models.training import (
    BulkActionRequest,
    BulkActionResponse,
    BulkActionResult,
    JobInfo,
    JobListResponse,
    JobListSortBy,
    TrainingOwnerFilterOption,
    TrainingValueFilterOption,
    JobDetailResponse,
    LastTrainingConfigResponse,
    JobLogsResponse,
    JobProgressResponse,
    JobActionResponse,
    JobUpdateRequest,
    JobStatusCheckResponse,
    JobStatusUpdate,
    JobCreateRequest,
    JobCreateResponse,
    TrainingProvisionOperationAcceptedResponse,
    TrainingProvisionOperationStatusResponse,
    TrainingJobOperationAcceptedResponse,
    TrainingJobOperationStatusResponse,
    JobMetricsResponse,
    InstanceStatusResponse,
    # Checkpoint models
    CheckpointDatasetInfo,
    CheckpointInfo,
    CheckpointListResponse,
    CheckpointDetailResponse,
    CheckpointDownloadRequest,
    CheckpointDownloadResponse,
    DatasetCompatibilityCheckRequest,
    DatasetCompatibilityCheckResponse,
    # Continue training models
    JobCreateContinueRequest,
    EarlyStoppingConfig,
    ValidationConfig,
    # GPU availability
    GpuAvailabilityInfo,
    GpuAvailabilityResponse,
    TrainingInstanceCandidate,
    TrainingInstanceCandidatesResponse,
    TrainingProviderCapabilityResponse,
    VerdaStorageActionFailure,
    VerdaStorageActionRequest,
    VerdaStorageActionResult,
    VerdaStorageItem,
    VerdaStorageListResponse,
    VastStorageActionRequest,
    VastStorageActionResult,
    VastStorageItem,
    VastStorageListResponse,
    RescueCPUResponse,
    RemoteCheckpointListResponse,
    RemoteCheckpointUploadRequest,
    RemoteCheckpointUploadResponse,
    SortOrder,
)
from interfaces_backend.services.profile_snapshot import extract_profile_name
from percus_ai.storage import (
    CheckpointDatasetInfo as StorageCheckpointDatasetInfo,
    get_models_dir,
    get_project_root,
)
from percus_ai.db import (
    get_current_user_id,
    get_supabase_async_client,
    get_supabase_service_client,
    get_supabase_session,
    reset_request_session,
    set_request_session,
    upsert_with_owner,
)
from percus_ai.training.ssh.client import SSHConnection
from percus_ai.training.ssh.executor import RemoteExecutor, run_remote_command
from percus_ai.training.features_repo import resolve_features_repo_config
from interfaces_backend.services.settings_service import resolve_huggingface_token_for_user
from interfaces_backend.services.training_provision_operations import (
    cleanup_provision_instance,
    get_training_provision_operations_service,
)
from interfaces_backend.services.training_job_operations import (
    get_training_job_operations_service,
)
from interfaces_backend.services.user_directory import resolve_user_directory_entries

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def _is_jwt_expired_error(exc: Exception) -> bool:
    text = str(exc)
    return "JWT expired" in text or "PGRST303" in text


def _is_invalid_uuid_error(exc: Exception) -> bool:
    if isinstance(exc, APIError):
        code = str(getattr(exc, "code", "") or "").strip()
        if code == "22P02":
            return True
        details = getattr(exc, "details", None)
        if isinstance(details, str) and "invalid input syntax for type uuid" in details.lower():
            return True
    text = str(exc).lower()
    return "invalid input syntax for type uuid" in text


_ISO_FRACTION_TZ_PATTERN = re.compile(r"^(?P<prefix>.+?T\d{2}:\d{2}:\d{2})(?:\.(?P<fraction>\d+))?(?P<tz>Z|[+-]\d{2}:\d{2})?$")


def _parse_job_created_at(value: str) -> datetime:
    normalized = value.strip()
    if len(normalized) == 10:
        return datetime.fromisoformat(f"{normalized}T00:00:00+00:00")
    match = _ISO_FRACTION_TZ_PATTERN.match(normalized)
    if not match:
        raise ValueError(f"Unsupported created_at format: {value!r}")

    prefix = match.group("prefix")
    fraction = match.group("fraction") or ""
    tz = match.group("tz") or ""
    if tz == "Z":
        tz = "+00:00"
    if fraction:
        fraction = fraction[:6].ljust(6, "0")
        normalized = f"{prefix}.{fraction}{tz}"
    else:
        normalized = f"{prefix}{tz}"
    return datetime.fromisoformat(normalized)


async def _get_service_db_client() -> Optional[AsyncClient]:
    return await get_supabase_service_client()


async def _with_training_service_role_retry(
    *,
    action: str,
    target: str,
    operation: Callable[[AsyncClient], Awaitable[_T]],
) -> _T:
    client = await get_supabase_async_client()
    try:
        return await operation(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning("JWT expired while %s %s; retrying with service key", action, target)
        return await operation(service_client)


def _default_author_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError:
        return "unknown"


def _build_bulk_action_response(
    results: list[BulkActionResult], requested: int | None = None
) -> BulkActionResponse:
    succeeded = sum(1 for result in results if result.status == "succeeded")
    failed = sum(1 for result in results if result.status == "failed")
    skipped = sum(1 for result in results if result.status == "skipped")
    return BulkActionResponse(
        requested=requested if requested is not None else len(results),
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        results=results,
    )


def _resolve_websocket_supabase_session(websocket: WebSocket) -> Optional[dict]:
    """Resolve and refresh Supabase session for WebSocket requests."""
    access_token = websocket.query_params.get("access_token")
    auth_header = websocket.headers.get("authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            access_token = parts[1]
    if not access_token:
        access_token = websocket.cookies.get(ACCESS_COOKIE_NAME)
    refresh_token = websocket.cookies.get(REFRESH_COOKIE_NAME)
    supabase_session = build_session_from_tokens(access_token, refresh_token)
    if not supabase_session or is_session_expired(supabase_session):
        refreshed_session = refresh_session_from_refresh_token(refresh_token)
        if refreshed_session:
            supabase_session = refreshed_session
    if not supabase_session or not supabase_session.get("user_id"):
        return None
    return supabase_session


router = APIRouter(prefix="/api/training", tags=["training"])

# Thread pool for WebSocket operations
_executor = ThreadPoolExecutor(max_workers=2)

DB_TABLE = "training_jobs"

RUNNING_STATUSES = {"running", "starting", "deploying"}
RUNNING_STATUSES_WITH_PENDING = {"running", "starting", "deploying", "pending"}
_REQUIRED_VAST_ENV_VARS = ("VAST_API_KEY", "VAST_SSH_PRIVATE_KEY")


def _first_dict(*values: object) -> Optional[dict]:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _extract_record(payload: object) -> Optional[dict]:
    if isinstance(payload, dict):
        record = _first_dict(payload.get("new"), payload.get("record"))
        if record:
            return record
        data = payload.get("data")
        if isinstance(data, dict):
            record = _first_dict(data.get("record"), data.get("new"))
            if record:
                return record
        record = _first_dict(payload.get("old"), payload.get("old_record"))
        if record:
            return record
        return None

    for attr in ("new", "record", "old"):
        record = getattr(payload, attr, None)
        if isinstance(record, dict):
            return record

    data = getattr(payload, "data", None) or getattr(payload, "payload", None)
    if isinstance(data, dict):
        record = _first_dict(data.get("record"), data.get("new"), data.get("old"))
        if record:
            return record

    return None


def _extract_event_type(payload: object) -> str:
    if isinstance(payload, dict):
        event_type = (
            payload.get("eventType") or payload.get("event_type") or payload.get("type")
        )
        if isinstance(event_type, str):
            return event_type.upper()
        data = payload.get("data")
        if isinstance(data, dict):
            event_type = (
                data.get("eventType") or data.get("event_type") or data.get("type")
            )
            if isinstance(event_type, str):
                return event_type.upper()

    for attr in ("event_type", "eventType", "type"):
        event_type = getattr(payload, attr, None)
        if isinstance(event_type, str):
            return event_type.upper()

    return ""


def _extract_status_update(payload: object) -> tuple[Optional[str], Optional[str]]:
    record = _extract_record(payload)
    job_id = record.get("job_id") if isinstance(record, dict) else None
    status = record.get("status") if isinstance(record, dict) else None
    if not status:
        event_type = _extract_event_type(payload)
        if event_type == "DELETE":
            status = "deleted"
    return job_id, status


def _drain_latest_status(queue: "asyncio.Queue") -> Optional[str]:
    latest_status = None
    while True:
        try:
            update = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if isinstance(update, dict):
            status = update.get("status")
            if status:
                latest_status = status
    return latest_status


async def _maybe_await(result: object) -> None:
    if inspect.isawaitable(result):
        await result


class _TrainingJobRealtimeSubscriber:
    def __init__(
        self, job_id: str, loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue"
    ) -> None:
        self.job_id = job_id
        self.loop = loop
        self.queue = queue


class TrainingJobRealtimeManager:
    def __init__(self) -> None:
        self._client = None
        self._channel = None
        self._realtime = None
        self._channel_lock = asyncio.Lock()
        self._subscribers: dict[str, _TrainingJobRealtimeSubscriber] = {}
        self._subscribers_lock = threading.Lock()

    async def subscribe(
        self,
        job_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[str, "asyncio.Queue"]:
        await self._ensure_channel()
        queue: asyncio.Queue = asyncio.Queue()
        subscriber_id = uuid.uuid4().hex
        with self._subscribers_lock:
            self._subscribers[subscriber_id] = _TrainingJobRealtimeSubscriber(
                job_id, loop, queue
            )
        return subscriber_id, queue

    def unsubscribe(self, subscriber_id: str) -> None:
        with self._subscribers_lock:
            self._subscribers.pop(subscriber_id, None)

    async def _ensure_channel(self) -> None:
        async with self._channel_lock:
            if self._channel:
                return

            self._client = await get_supabase_async_client()
            realtime = getattr(self._client, "realtime", None) or getattr(
                self._client,
                "realtime_client",
                None,
            )
            if realtime is None:
                raise RuntimeError(
                    "Supabase Realtime client is not available (async client required)"
                )

            channel_factory = getattr(realtime, "channel", None) or getattr(
                self._client, "channel", None
            )
            if channel_factory is None or not callable(channel_factory):
                raise RuntimeError("Supabase Realtime channel API is not available")

            channel = channel_factory(DB_TABLE)
            on_changes = getattr(channel, "on_postgres_changes", None)
            if on_changes is not None and callable(on_changes):
                on_changes(
                    event="*",
                    schema="public",
                    table=DB_TABLE,
                    callback=self._handle_change,
                )
            else:
                on_method = getattr(channel, "on", None)
                if on_method is None or not callable(on_method):
                    raise RuntimeError(
                        "Supabase Realtime channel handler is not available"
                    )
                on_method(
                    "postgres_changes",
                    {"event": "*", "schema": "public", "table": DB_TABLE},
                    self._handle_change,
                )

            connect = getattr(realtime, "connect", None)
            if connect is not None and callable(connect):
                await _maybe_await(connect())

            subscribe = getattr(channel, "subscribe", None)
            if subscribe is None or not callable(subscribe):
                raise RuntimeError(
                    "Supabase Realtime channel.subscribe is not available"
                )

            await _maybe_await(subscribe())

            self._realtime = realtime
            self._channel = channel

    def _handle_change(self, payload: object) -> None:
        job_id, status = _extract_status_update(payload)
        if not job_id or not status:
            return

        with self._subscribers_lock:
            subscribers = [
                subscriber
                for subscriber in self._subscribers.values()
                if subscriber.job_id == job_id
            ]

        for subscriber in subscribers:
            if subscriber.loop.is_closed():
                continue
            try:
                subscriber.loop.call_soon_threadsafe(
                    subscriber.queue.put_nowait,
                    {"job_id": job_id, "status": status},
                )
            except Exception as exc:
                logger.debug("Failed to enqueue training job update: %s", exc)


_training_job_realtime_manager: Optional[TrainingJobRealtimeManager] = None


def _get_training_job_realtime_manager() -> TrainingJobRealtimeManager:
    global _training_job_realtime_manager
    if _training_job_realtime_manager is None:
        _training_job_realtime_manager = TrainingJobRealtimeManager()
    return _training_job_realtime_manager


# Remote scripts directory - contains setup_env.sh, run_training.sh, entry.py, etc.
# These scripts are deployed to remote instances for training
REMOTE_SCRIPTS_DIR = (
    Path(__file__).parent.parent.parent.parent.parent.parent
    / "features"
    / "percus_ai"
    / "training"
    / "remote"
)
REPO_ROOT = REMOTE_SCRIPTS_DIR.parents[4]


# --- SSH utilities for remote deployment ---
# Uses SSHConnection from percus_ai.training.ssh.client for consistency with executor.py


def _create_ssh_connection(
    ip: str,
    user: str,
    private_key_path: str,
    timeout: int = 30,
) -> SSHConnection:
    """Create and connect an SSHConnection to the remote host.

    Args:
        ip: Remote host IP address
        user: SSH username
        private_key_path: Path to SSH private key file
        timeout: Connection timeout in seconds

    Returns:
        Connected SSHConnection instance
    """
    key_path = Path(private_key_path).expanduser()
    if not key_path.exists():
        raise RuntimeError(f"SSH鍵が見つかりません: {key_path}")
    if not key_path.is_file():
        raise RuntimeError(f"SSH鍵パスが不正です: {key_path}")
    conn = SSHConnection(host=ip, user=user, private_key_path=key_path)
    try:
        conn.connect(timeout_sec=timeout)
    except SystemExit as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    return conn


def _get_default_ssh_user() -> str:
    return (
        os.environ.get("VAST_SSH_USER")
        or os.environ.get("VERDA_SSH_USER")
        or "root"
    ).strip() or "root"


def _build_ssh_user_candidates(primary_user: str) -> list[str]:
    candidates: list[str] = []
    for user in (primary_user, "root", "ubuntu"):
        user_normalized = (user or "").strip()
        if user_normalized and user_normalized not in candidates:
            candidates.append(user_normalized)
    return candidates or ["root", "ubuntu"]


def _resolve_private_key_candidate_paths(raw_path: Optional[str]) -> list[Path]:
    normalized = str(raw_path or "").strip()
    if not normalized:
        return []

    base = Path(normalized).expanduser()
    candidates: list[Path] = [base]
    if not base.is_absolute():
        candidates.append(get_project_root() / base)

    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    return resolved


def _discover_common_private_keys() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path.resolve(strict=False))
        if key in seen:
            return
        seen.add(key)
        if path.exists() and path.is_file():
            candidates.append(path)

    for path in Path.home().glob(".ssh/id_*"):
        if path.name.endswith(".pub"):
            continue
        add(path)

    data_dir_raw = str(os.environ.get("PHYSICAL_AI_DATA_DIR") or "").strip()
    if data_dir_raw:
        for data_dir in _resolve_private_key_candidate_paths(data_dir_raw):
            if not data_dir.exists() or not data_dir.is_dir():
                continue
            for path in data_dir.glob("id_*"):
                if path.name.endswith(".pub"):
                    continue
                add(path)

    return candidates


def _build_ssh_private_key_candidates(primary_path: Optional[str]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    explicit_paths: list[str] = [
        os.environ.get("VAST_SSH_PRIVATE_KEY"),
        os.environ.get("VERDA_SSH_PRIVATE_KEY"),
        primary_path,
        str(Path.home() / ".ssh" / "id_rsa"),
        str(Path.home() / ".ssh" / "id_ed25519"),
    ]
    explicit_extra = str(os.environ.get("VERDA_SSH_PRIVATE_KEYS") or "").strip()
    if explicit_extra:
        explicit_paths.extend(
            [item.strip() for item in explicit_extra.split(",") if item.strip()]
        )

    for raw in explicit_paths:
        for expanded in _resolve_private_key_candidate_paths(raw):
            key = str(expanded.resolve(strict=False))
            if key in seen:
                continue
            seen.add(key)
            if expanded.exists() and expanded.is_file():
                candidates.append(expanded)

    for expanded in _discover_common_private_keys():
        key = str(expanded.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(expanded)
    return candidates


def _select_preferred_ssh_private_key(primary_path: Optional[str]) -> str:
    candidates = _build_ssh_private_key_candidates(primary_path)
    if candidates:
        return str(candidates[0])
    fallback = str(primary_path or "").strip() or str(Path.home() / ".ssh" / "id_rsa")
    return str(Path(fallback).expanduser())


def _resolve_ssh_private_key_path(private_key_path: str) -> str:
    candidates = _resolve_private_key_candidate_paths(private_key_path)
    for key_path in candidates:
        if key_path.exists() and key_path.is_file():
            return str(key_path)
    display = ", ".join(str(p) for p in candidates) or private_key_path
    raise RuntimeError(
        f"SSH鍵が見つかりません: {display} "
        "(バックエンド実行環境に鍵ファイルを配置してください)"
    )


def _build_pipeline_config(request: "JobCreateRequest", job_id: str) -> dict:
    """Build TrainingPipeline JSON config from JobCreateRequest."""
    dataset = request.dataset
    policy = request.policy

    training = {k: v for k, v in request.training.model_dump().items() if v is not None}
    training.setdefault("save_checkpoint", True)

    validation = {
        k: v for k, v in request.validation.model_dump().items() if v is not None
    }
    early_stopping = {
        k: v for k, v in request.early_stopping.model_dump().items() if v is not None
    }
    if early_stopping.get("enable"):
        validation.setdefault("enable", True)
        if not training.get("save_checkpoint", True):
            training["save_checkpoint"] = True
    if validation.get("enable") and validation.get("eval_freq") is None:
        validation["eval_freq"] = training.get("save_freq") or 20_000

    config = {
        "dataset": {
            "id": dataset.id,
        },
        "policy": {
            "type": policy.type,
            "push_to_hub": False,
        },
        "training": training,
        "validation": validation or {"enable": False},
        "early_stopping": early_stopping or {"enable": False},
        "output": {
            "job_name": str(request.job_name or "").strip() or job_id,
        },
        "rename_map": {},
        "seed": 1000,
    }

    if policy.initialization:
        config["policy"]["initialization"] = policy.initialization
    if policy.pretrained_path:
        config["policy"]["pretrained_path"] = policy.pretrained_path
    if policy.base_model_path:
        config["policy"]["base_model_path"] = policy.base_model_path
    if policy.dtype:
        config["policy"]["dtype"] = policy.dtype
    if policy.compile_model is not None:
        config["policy"]["compile_model"] = policy.compile_model
    if policy.gradient_checkpointing is not None:
        config["policy"]["gradient_checkpointing"] = policy.gradient_checkpointing
    if policy.use_amp is not None:
        config["policy"]["use_amp"] = policy.use_amp
    if config["policy"].get("dtype") in ("bfloat16", "bf16") and config["policy"].get(
        "use_amp"
    ):
        config["policy"]["use_amp"] = False
    if dataset.video_backend:
        config["dataset"]["video_backend"] = dataset.video_backend
    if dataset.split:
        config["dataset"]["split"] = {
            "train_ratio": dataset.split.train_ratio,
            "seed": dataset.split.seed,
        }

    return config


def _load_env_file_vars() -> dict[str, str]:
    env_paths = [
        REPO_ROOT / ".env",
        REPO_ROOT / "data" / ".env",
    ]
    data: dict[str, str] = {}
    for path in env_paths:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data.setdefault(key.strip(), value.strip())
        except Exception:
            continue
    return data


def _generate_env_file(
    job_id: str,
    instance_id: str,
    policy_type: Optional[str],
    user_id: Optional[str] = None,
    auto_delete: bool = True,
    supabase_access_token: Optional[str] = None,
    supabase_refresh_token: Optional[str] = None,
    supabase_user_id: Optional[str] = None,
) -> str:
    """Generate .env file content with required credentials."""
    lines = []
    env_fallback = _load_env_file_vars()

    # HuggingFace token
    hf_token = resolve_huggingface_token_for_user(user_id) if user_id else None
    if hf_token:
        lines.append(f"HF_TOKEN={hf_token}")

    # WandB API key
    wandb_key = os.environ.get("WANDB_API_KEY")
    if wandb_key:
        lines.append(f"WANDB_API_KEY={wandb_key}")

    # DataCrunch credentials
    dc_client_id = os.environ.get("DATACRUNCH_CLIENT_ID")
    dc_client_secret = os.environ.get("DATACRUNCH_CLIENT_SECRET")
    if dc_client_id:
        lines.append(f"DATACRUNCH_CLIENT_ID={dc_client_id}")
    if dc_client_secret:
        lines.append(f"DATACRUNCH_CLIENT_SECRET={dc_client_secret}")

    # R2/S3 credentials
    r2_endpoint = (
        os.environ.get("R2_ENDPOINT_URL")
        or os.environ.get("S3_ENDPOINT_URL")
        or env_fallback.get("R2_ENDPOINT_URL")
        or env_fallback.get("S3_ENDPOINT_URL")
    )
    r2_access_key = (
        os.environ.get("R2_ACCESS_KEY_ID")
        or os.environ.get("S3_ACCESS_KEY_ID")
        or env_fallback.get("R2_ACCESS_KEY_ID")
        or env_fallback.get("S3_ACCESS_KEY_ID")
    )
    r2_secret_key = (
        os.environ.get("R2_SECRET_ACCESS_KEY")
        or os.environ.get("S3_SECRET_ACCESS_KEY")
        or env_fallback.get("R2_SECRET_ACCESS_KEY")
        or env_fallback.get("S3_SECRET_ACCESS_KEY")
    )
    if r2_endpoint:
        lines.append(f"S3_ENDPOINT_URL={r2_endpoint}")
        lines.append(f"R2_ENDPOINT_URL={r2_endpoint}")
    if r2_access_key:
        lines.append(f"S3_ACCESS_KEY_ID={r2_access_key}")
        lines.append(f"R2_ACCESS_KEY_ID={r2_access_key}")
    if r2_secret_key:
        lines.append(f"S3_SECRET_ACCESS_KEY={r2_secret_key}")
        lines.append(f"R2_SECRET_ACCESS_KEY={r2_secret_key}")

    # R2/S3 bucket name
    r2_bucket = (
        os.environ.get("R2_BUCKET")
        or os.environ.get("S3_BUCKET")
        or env_fallback.get("R2_BUCKET")
        or env_fallback.get("S3_BUCKET")
    )
    if r2_bucket:
        lines.append(f"R2_BUCKET={r2_bucket}")
        lines.append(f"S3_BUCKET={r2_bucket}")

    r2_version = (
        os.environ.get("R2_VERSION")
        or os.environ.get("S3_VERSION")
        or env_fallback.get("R2_VERSION")
        or env_fallback.get("S3_VERSION")
    )
    if r2_version:
        lines.append(f"R2_VERSION={r2_version}")
        lines.append(f"S3_VERSION={r2_version}")

    # Use remote user's home to avoid path mismatch across SSH users
    lines.append("PHYSICAL_AI_DATA_DIR=$HOME/.physical-ai")

    features_repo = resolve_features_repo_config()
    repo_url = str(features_repo.repo_url or "").strip()
    if repo_url:
        lines.append(f"PERCUS_AI_REPO_URL={repo_url}")
    repo_ref = str(features_repo.repo_ref or "").strip()
    if repo_ref:
        lines.append(f"PERCUS_AI_REPO_REF={repo_ref}")
    repo_commit = str(features_repo.repo_commit or "").strip()
    if repo_commit:
        lines.append(f"PERCUS_AI_REPO_COMMIT={repo_commit}")

    if policy_type:
        lines.append(f"PERCUS_AI_POLICY_TYPE={policy_type}")

    # GitHub token for private repo access (physical-ai-features)
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if gh_token:
        lines.append(f"GH_TOKEN={gh_token}")

    # Supabase credentials for remote status updates
    supabase_url = os.environ.get("SUPABASE_URL") or env_fallback.get("SUPABASE_URL")
    supabase_secret_key = os.environ.get("SUPABASE_SECRET_KEY") or env_fallback.get(
        "SUPABASE_SECRET_KEY"
    )
    supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY") or env_fallback.get(
        "SUPABASE_ANON_KEY"
    )
    if supabase_url and (supabase_secret_key or supabase_anon_key):
        lines.append(f"SUPABASE_URL={supabase_url}")
        if supabase_secret_key:
            lines.append(f"SUPABASE_SECRET_KEY={supabase_secret_key}")
        if supabase_anon_key:
            lines.append(f"SUPABASE_ANON_KEY={supabase_anon_key}")
    if supabase_access_token:
        lines.append(f"SUPABASE_ACCESS_TOKEN={supabase_access_token}")
    if supabase_refresh_token:
        lines.append(f"SUPABASE_REFRESH_TOKEN={supabase_refresh_token}")
    if supabase_user_id:
        lines.append(f"SUPABASE_USER_ID={supabase_user_id}")

    return "\n".join(lines) + "\n"


def _generate_instance_info_env(
    job_id: str, instance_id: str, auto_delete: bool = True
) -> str:
    """Generate instance_info.env content."""
    lines = [
        f"DATACRUNCH_INSTANCE_ID={instance_id}",
        f"JOB_ID={job_id}",
        f"AUTO_DELETE_INSTANCE={'true' if auto_delete else 'false'}",
    ]
    return "\n".join(lines) + "\n"


# --- Verda/DataCrunch API utilities ---


def _extract_gpu_count(instance_type: str) -> Optional[int]:
    """Extract GPU count from instance type name.

    Instance types follow the pattern: <count><model>.<memory><suffix>
    e.g., "1H100.80S" -> 1, "8A100.80" -> 8

    Args:
        instance_type: Instance type string (e.g., "1H100.80S")

    Returns:
        GPU count as integer, or None if extraction fails
    """
    digits = []
    for ch in instance_type:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return None
    try:
        return int("".join(digits))
    except ValueError:
        return None


def _get_verda_client() -> Optional[VerdaClient]:
    """Get Verda/DataCrunch client (if available)."""
    client_id = os.environ.get("DATACRUNCH_CLIENT_ID")
    client_secret = os.environ.get("DATACRUNCH_CLIENT_SECRET")

    if not client_id or not client_secret:
        return None

    return VerdaClient(client_id, client_secret)


def _missing_vast_env_vars() -> list[str]:
    missing: list[str] = []
    for env_name in _REQUIRED_VAST_ENV_VARS:
        if not str(os.environ.get(env_name) or "").strip():
            missing.append(env_name)
    return missing


def _assert_provider_configured(provider: str) -> None:
    provider_name = str(provider or "").strip().lower()
    if provider_name != "vast":
        return

    missing = _missing_vast_env_vars()
    if missing:
        required = ", ".join(missing)
        raise HTTPException(
            status_code=400,
            detail=f"Vast.ai設定が不足しています: {required}",
        )


def _build_verda_storage_item(volume: object, state: str) -> VerdaStorageItem:
    """Convert Verda volume to API response model."""
    return VerdaStorageItem(
        id=getattr(volume, "id", ""),
        name=getattr(volume, "name", None),
        size_gb=int(getattr(volume, "size", 0) or 0),
        status=getattr(volume, "status", "unknown"),
        state=state,
        is_os_volume=bool(getattr(volume, "is_os_volume", False)),
        volume_type=getattr(volume, "type", None),
        location=getattr(volume, "location", None),
        instance_id=getattr(volume, "instance_id", None),
        created_at=getattr(volume, "created_at", None),
        deleted_at=getattr(volume, "deleted_at", None),
    )


def _collect_verda_volumes(client: VerdaClient) -> dict[str, tuple[str, object]]:
    """Collect Verda volumes and map by ID."""
    volumes_by_id: dict[str, tuple[str, object]] = {}
    active_volumes = client.volumes.get()
    for volume in active_volumes:
        volumes_by_id[getattr(volume, "id", "")] = ("active", volume)
    trash_volumes = client.volumes.get_in_trash()
    for volume in trash_volumes:
        volumes_by_id[getattr(volume, "id", "")] = ("deleted", volume)
    return volumes_by_id


def _gpu_count_from_instance_type(instance_type: object) -> int:
    gpu = getattr(instance_type, "gpu", None) or {}
    count = gpu.get("count") or gpu.get("number_of_gpus") or gpu.get("gpu_count") or 0
    try:
        return int(count)
    except (TypeError, ValueError):
        return 0


def _select_cpu_instance_type(client: VerdaClient) -> str:
    instance_types = client.instance_types.get()
    cpu_types = [t for t in instance_types if _gpu_count_from_instance_type(t) == 0]
    if not cpu_types:
        raise HTTPException(
            status_code=503, detail="CPUインスタンスタイプが見つかりません"
        )
    cpu_types.sort(key=lambda t: getattr(t, "price_per_hour", float("inf")))
    return cpu_types[0].instance_type


def _pick_os_volume_for_instance(
    volumes_by_id: dict[str, tuple[str, object]],
    instance_id: str,
) -> Optional[tuple[str, object]]:
    candidates: list[tuple[str, object]] = []
    os_candidates: list[tuple[str, object]] = []
    for _, (state, volume) in volumes_by_id.items():
        if getattr(volume, "instance_id", None) != instance_id:
            continue
        item = (state, volume)
        candidates.append(item)
        if getattr(volume, "is_os_volume", False):
            os_candidates.append(item)
    if os_candidates:
        return os_candidates[0]
    if candidates:
        return candidates[0]
    return None


def _volume_state_from_detail(volume: object) -> str:
    status = str(getattr(volume, "status", "") or "").strip().lower()
    deleted_at = str(getattr(volume, "deleted_at", "") or "").strip()
    if status in {"deleted", "deleting", "trash"} or deleted_at:
        return "deleted"
    return "active"


def _pick_os_volume_from_instance_record(
    client: VerdaClient,
    volumes_by_id: dict[str, tuple[str, object]],
    instance_id: str,
) -> Optional[tuple[str, object]]:
    normalized_instance_id = str(instance_id or "").strip()
    if not normalized_instance_id:
        return None

    try:
        instance = client.instances.get_by_id(normalized_instance_id)
    except Exception:
        return None

    volume_id = str(getattr(instance, "os_volume_id", "") or "").strip()
    if not volume_id:
        return None

    cached = volumes_by_id.get(volume_id)
    if cached:
        return cached

    try:
        volume = client.volumes.get_by_id(volume_id)
    except Exception:
        return None

    return _volume_state_from_detail(volume), volume


def _pick_os_volume_for_job(
    volumes_by_id: dict[str, tuple[str, object]],
    job_id: str,
) -> Optional[tuple[str, object]]:
    job_prefix = f"train-{job_id[:16]}"
    matches: list[tuple[str, object]] = []
    os_matches: list[tuple[str, object]] = []
    for _, (state, volume) in volumes_by_id.items():
        name = getattr(volume, "name", None) or ""
        if job_prefix not in name:
            continue
        item = (state, volume)
        matches.append(item)
        if getattr(volume, "is_os_volume", False):
            os_matches.append(item)
    candidates = os_matches or matches
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: getattr(item[1], "created_at", "") or "", reverse=True
    )
    return candidates[0]


def _wait_for_volume_restore(
    client: VerdaClient, volume_id: str, timeout_sec: int = 120
) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            volume = client.volumes.get_by_id(volume_id)
            status = getattr(volume, "status", "") or ""
            if status.lower() not in ("deleted", "deleting", "trash"):
                return
        except Exception:
            pass
        time.sleep(5)
    raise HTTPException(
        status_code=504, detail="ストレージ復活の完了待ちがタイムアウトしました"
    )


def _ensure_volume_detached(
    client: VerdaClient, volume_id: str, timeout_sec: int = 120
) -> None:
    try:
        volume = client.volumes.get_by_id(volume_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"ストレージ取得に失敗しました: {exc}"
        ) from exc

    status = str(getattr(volume, "status", "") or "").strip().lower()
    if getattr(volume, "instance_id", None) is None and status == "detached":
        return

    if getattr(volume, "instance_id", None) is not None:
        try:
            client.volumes.detach(volume_id)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"ストレージのデタッチに失敗しました: {exc}"
            ) from exc

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            volume = client.volumes.get_by_id(volume_id)
            status = str(getattr(volume, "status", "") or "").strip().lower()
            if getattr(volume, "instance_id", None) is None and status == "detached":
                return
        except Exception:
            pass
        time.sleep(5)

    raise HTTPException(
        status_code=504, detail="ストレージのデタッチ完了待ちがタイムアウトしました"
    )


def _wait_for_volume_detached(
    client: VerdaClient, volume_id: str, timeout_sec: int = 180
) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            volume = client.volumes.get_by_id(volume_id)
        except Exception as exc:
            raise HTTPException(
                status_code=404, detail=f"ストレージ取得に失敗しました: {exc}"
            ) from exc
        status = str(getattr(volume, "status", "") or "").strip().lower()
        if getattr(volume, "instance_id", None) is None and status == "detached":
            return
        time.sleep(5)

    raise HTTPException(
        status_code=504, detail="ストレージのデタッチ完了待ちがタイムアウトしました"
    )


def _wait_for_instance_offline(
    client: VerdaClient,
    instance_id: str,
    timeout_sec: int = 120,
    allowed_statuses: Optional[set[str]] = None,
) -> None:
    if allowed_statuses is None:
        allowed_statuses = {"offline", "discontinued", "deleted"}
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            instance = client.instances.get_by_id(instance_id)
            status = getattr(instance, "status", "") or ""
            if status in allowed_statuses:
                return
        except Exception:
            return
        time.sleep(5)

    raise HTTPException(
        status_code=504, detail="インスタンス停止の完了待ちがタイムアウトしました"
    )


def _restore_verda_volumes(client: VerdaClient, volume_ids: list[str]) -> None:
    """Restore volumes from trash via Verda API."""
    payload = {"action": "restore", "id": volume_ids}
    client._http_client.put("/volumes", json=payload)


def _shutdown_verda_instance(instance_id: str, wait_timeout: int = 60) -> bool:
    """Shutdown Verda instance and wait until it is safe for volume detach."""
    client = _get_verda_client()
    if not client:
        logger.warning(
            "Cannot shutdown instance %s: Verda client not available",
            instance_id,
        )
        return False

    try:
        instance = client.instances.get_by_id(instance_id)
        current_status = str(getattr(instance, "status", "") or "").strip().lower()
        logger.info("Instance %s current status before shutdown: %s", instance_id, current_status)
        if current_status in {"offline", "deleted", "deleting", "discontinued"}:
            return True

        client.instances.action(instance_id, client.constants.instance_actions.SHUTDOWN)
        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            time.sleep(2)
            try:
                instance = client.instances.get_by_id(instance_id)
            except Exception:
                return True
            new_status = str(getattr(instance, "status", "") or "").strip().lower()
            logger.info("Instance %s status after shutdown request: %s", instance_id, new_status)
            if new_status in {"offline", "deleted", "deleting", "discontinued"}:
                return True
        logger.warning(
            "Instance %s shutdown not confirmed within %ss, proceeding with current state",
            instance_id,
            wait_timeout,
        )
        return True
    except Exception as exc:
        logger.error("Failed to shutdown instance %s: %s", instance_id, exc)
        return False


def _chunk_list(items: list[str], chunk_size: int = 20) -> list[list[str]]:
    """Split items into smaller chunks."""
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def _ensure_volume_active_and_detached(
    client: VerdaClient,
    volume_id: str,
    *,
    emit_progress: Callable[[dict], None] | None = None,
) -> object:
    try:
        volume = client.volumes.get_by_id(volume_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"ストレージ取得に失敗しました: {exc}"
        ) from exc

    status = str(getattr(volume, "status", "") or "").strip().lower()
    if status in {"deleted", "deleting", "trash"}:
        if emit_progress is not None:
            emit_progress(
                {
                    "type": "restore_storage",
                    "message": "ストレージを復活中...",
                    "volume_id": volume_id,
                }
            )
        _restore_verda_volumes(client, [volume_id])
        _wait_for_volume_restore(client, volume_id)
        if emit_progress is not None:
            emit_progress(
                {
                    "type": "restore_complete",
                    "message": "ストレージ復活完了",
                    "volume_id": volume_id,
                }
            )
        volume = client.volumes.get_by_id(volume_id)

    _ensure_volume_detached(client, volume_id)
    _wait_for_volume_detached(client, volume_id)
    return client.volumes.get_by_id(volume_id)


_verda_client_local = threading.local()


def _get_thread_verda_client() -> Optional[VerdaClient]:
    """Get thread-local Verda client."""
    client = getattr(_verda_client_local, "client", None)
    if client is None:
        client = _get_verda_client()
        _verda_client_local.client = client
    return client


def _perform_verda_volume_action(
    action: str, volume_id: str, is_permanent: bool
) -> None:
    """Perform a Verda volume action for a single volume."""
    client = _get_thread_verda_client()
    if not client:
        raise RuntimeError(
            "Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)"
        )

    if action == "delete":
        client.volumes.delete(volume_id, is_permanent=is_permanent)
    elif action == "restore":
        _restore_verda_volumes(client, [volume_id])
    else:
        raise ValueError(f"Unsupported action: {action}")


def _perform_verda_volume_action_batch(
    action: str,
    volume_ids: list[str],
    is_permanent: bool,
) -> None:
    """Perform a Verda volume action for a batch of volumes."""
    client = _get_thread_verda_client()
    if not client:
        raise RuntimeError(
            "Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)"
        )

    if action == "delete":
        client.volumes.delete(volume_ids, is_permanent=is_permanent)
    elif action == "restore":
        _restore_verda_volumes(client, volume_ids)
    else:
        raise ValueError(f"Unsupported action: {action}")


def _check_instance_via_api(instance_id: str) -> Optional[str]:
    """Check instance status via Verda API.

    Returns:
        Instance status string or None if unavailable
    """
    client = _get_verda_client()
    if not client:
        return "unavailable"

    try:
        instance = client.instances.get_by_id(instance_id)
        status = str(getattr(instance, "status", "") or "").strip().lower()
        return status or "unavailable"
    except Exception as exc:
        message = str(exc).lower()
        if "not found" in message or "404" in message:
            return None
        logger.warning("Failed to check Verda instance status %s: %s", instance_id, exc)
        return "unavailable"


def _get_job_provider(job_data: dict) -> str:
    training_cfg = job_data.get("training_config")
    if isinstance(training_cfg, dict):
        cloud_cfg = training_cfg.get("cloud")
        if isinstance(cloud_cfg, dict):
            provider = str(cloud_cfg.get("provider") or "").strip().lower()
            if provider in {"verda", "vast"}:
                return provider
    return "verda"


def _check_instance_status(job_data: dict) -> Optional[str]:
    instance_id = str(job_data.get("instance_id") or "").strip()
    if not instance_id:
        return None

    provider = _get_job_provider(job_data)
    if provider == "vast":
        from percus_ai.training.providers.vast import get_instance

        try:
            instance = get_instance(instance_id)
        except Exception as exc:
            message = str(exc).lower()
            if "not found" in message or "404" in message:
                return None
            logger.warning("Failed to check Vast instance status %s: %s", instance_id, exc)
            return "unavailable"

        status = str(instance.status or "").strip().lower()
        if status:
            return status
        if instance.ip or instance.ssh_port:
            return "running"
        return "unavailable"

    return _check_instance_via_api(instance_id)


async def _check_instance_status_async(job_data: dict) -> Optional[str]:
    return await asyncio.to_thread(_check_instance_status, job_data)


def _is_terminated_instance_status(status: str) -> bool:
    return status in {
        "offline",
        "error",
        "discontinued",
        "deleted",
        "terminated",
        "stopped",
        "exited",
        "dead",
    }


def _parse_optional_utc_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = _parse_job_created_at(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _vast_termination_metrics_grace_period() -> timedelta:
    raw = str(os.environ.get("TRAINING_VAST_TERMINATION_METRICS_GRACE_MINUTES") or "").strip()
    if not raw:
        return timedelta(minutes=15)
    try:
        return timedelta(minutes=max(int(raw), 1))
    except ValueError:
        logger.warning(
            "Invalid TRAINING_VAST_TERMINATION_METRICS_GRACE_MINUTES=%r; fallback to 15",
            raw,
        )
        return timedelta(minutes=15)


async def _has_recent_training_metrics(job_id: str) -> bool:
    normalized_job_id = str(job_id or "").strip()
    if not normalized_job_id:
        return False

    async def _fetch_with(client: AsyncClient) -> list[dict]:
        response = (
            await client.table("training_job_metrics")
            .select("ts")
            .eq("job_id", normalized_job_id)
            .order("ts", desc=True)
            .limit(1)
            .execute()
        )
        return response.data or []

    data = await _with_training_service_role_retry(
        action="loading latest metric timestamp for training job",
        target=normalized_job_id,
        operation=_fetch_with,
    )
    if not data:
        return False

    latest_ts = _parse_optional_utc_datetime(data[0].get("ts"))
    if latest_ts is None:
        return False

    return latest_ts >= (datetime.now(timezone.utc) - _vast_termination_metrics_grace_period())


async def _should_preserve_job_from_remote_status(
    job_data: dict,
    instance_status: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Prefer remote reachability and recent metrics over flaky provider status for Vast."""
    provider = _get_job_provider(job_data)
    if provider != "vast":
        return None, None

    if instance_status not in {None, "unavailable"} and not _is_terminated_instance_status(instance_status):
        return None, None

    await _refresh_job_ssh_target_if_needed(job_data)
    remote_status = await _check_remote_status_async(job_data)
    if remote_status in {"running", "starting"}:
        return remote_status, f"Provider status stale; remote process is {remote_status}"

    preserved_status = str(job_data.get("status") or "").strip().lower() or "running"
    if remote_status != "unreachable":
        return (
            preserved_status,
            f"Provider status stale; SSH reachable and remote process is {remote_status}",
        )

    if await _has_recent_training_metrics(str(job_data.get("job_id") or "").strip()):
        return preserved_status, "Provider status stale; recent metrics activity detected"

    return None, None


async def _refresh_job_status_from_instance(job_data: dict) -> Optional[str]:
    instance_id = job_data.get("instance_id")
    if not instance_id:
        return None
    instance_status = await _check_instance_status_async(job_data)
    preserved_remote_status, _ = await _should_preserve_job_from_remote_status(job_data, instance_status)
    if preserved_remote_status:
        return preserved_remote_status
    if instance_status is None:
        job_data["status"] = "terminated"
        job_data["termination_reason"] = "INSTANCE_NOT_FOUND"
        job_data["completed_at"] = datetime.now().isoformat()
        await _save_job(job_data)
        return instance_status
    if _is_terminated_instance_status(instance_status):
        job_data["status"] = "terminated"
        job_data["termination_reason"] = "INSTANCE_TERMINATED"
        job_data["completed_at"] = datetime.now().isoformat()
        await _save_job(job_data)
        return instance_status
    return instance_status


def _find_latest_running_rescue_cpu_instance(client: VerdaClient, job_id: str):
    """Find latest running rescue CPU instance for a job."""
    target_hostname = f"rescue-cpu-{job_id[:8]}"
    try:
        instances = client.instances.get()
    except Exception:
        return None

    candidates = []
    for inst in instances:
        hostname = str(getattr(inst, "hostname", "") or "").strip()
        status = str(getattr(inst, "status", "") or "").strip().lower()
        ip = str(getattr(inst, "ip", "") or "").strip()
        if hostname != target_hostname:
            continue
        if status != "running":
            continue
        if not ip:
            continue
        candidates.append(inst)

    if not candidates:
        return None

    def _created_at_key(inst) -> str:
        return str(getattr(inst, "created_at", "") or "")

    return max(candidates, key=_created_at_key)


async def _refresh_job_ssh_target_if_needed(job_data: dict) -> dict:
    """Refresh job SSH target to running rescue CPU instance when stale."""
    job_id = str(job_data.get("job_id") or "").strip()
    if not job_id:
        return job_data

    provider = _get_job_provider(job_data)
    if provider == "vast":
        instance_id = str(job_data.get("instance_id") or "").strip()
        if not instance_id:
            return job_data

        try:
            from percus_ai.training.providers.vast import get_instance

            current = await asyncio.to_thread(get_instance, instance_id)
        except Exception:
            return job_data

        new_ip = str(getattr(current, "ip", "") or "").strip()
        try:
            new_port = int(getattr(current, "ssh_port", None) or 0)
        except (TypeError, ValueError):
            new_port = 0
        if not new_ip:
            return job_data

        old_ip = str(job_data.get("ip") or "").strip()
        old_port = 22
        try:
            old_port = int(job_data.get("ssh_port") or 22)
        except (TypeError, ValueError):
            old_port = 22
        training_cfg = job_data.get("training_config")
        cloud_cfg: dict | None = None
        if isinstance(training_cfg, dict):
            maybe_cloud = training_cfg.get("cloud")
            if isinstance(maybe_cloud, dict):
                cloud_cfg = maybe_cloud
                try:
                    cloud_port = int(cloud_cfg.get("ssh_port") or 0)
                except (TypeError, ValueError):
                    cloud_port = 0
                if cloud_port > 0:
                    old_port = cloud_port

        changed = False
        if new_ip != old_ip:
            job_data["ip"] = new_ip
            changed = True
        if new_port > 0 and new_port != old_port:
            job_data["ssh_port"] = new_port
            if cloud_cfg is not None:
                cloud_cfg["ssh_port"] = new_port
            changed = True
        if not changed:
            return job_data

        await _save_job(job_data)
        logger.info(
            "Refreshed Vast SSH target: job_id=%s instance_id=%s old_ip=%s old_port=%s new_ip=%s new_port=%s",
            job_id,
            instance_id,
            old_ip or "none",
            old_port,
            new_ip,
            new_port or 22,
        )
        return job_data

    if provider != "verda":
        return job_data

    instance_id = str(job_data.get("instance_id") or "").strip()
    ip = str(job_data.get("ip") or "").strip()
    if instance_id:
        current_status = await _check_instance_status_async(job_data)
    else:
        current_status = None

    stale_statuses = {"offline", "error", "discontinued", "deleted"}
    needs_refresh = (not ip) or (current_status in stale_statuses)
    if not needs_refresh:
        return job_data

    client = _get_verda_client()
    if not client:
        return job_data
    rescue_instance = await asyncio.to_thread(
        _find_latest_running_rescue_cpu_instance,
        client,
        job_id,
    )
    if not rescue_instance:
        return job_data

    rescue_instance_id = str(getattr(rescue_instance, "id", "") or "").strip()
    rescue_ip = str(getattr(rescue_instance, "ip", "") or "").strip()
    if not rescue_instance_id or not rescue_ip:
        return job_data

    old_instance_id = instance_id or "none"
    old_ip = ip or "none"
    ssh_private_key = _select_preferred_ssh_private_key(job_data.get("ssh_private_key"))
    ssh_user = str(job_data.get("ssh_user") or "").strip() or _get_default_ssh_user()

    job_data["instance_id"] = rescue_instance_id
    job_data["ip"] = rescue_ip
    job_data["ssh_user"] = ssh_user
    job_data["ssh_private_key"] = ssh_private_key
    await _save_job(job_data)
    logger.info(
        "Rebound job SSH target to rescue CPU instance: job_id=%s old_instance_id=%s old_ip=%s new_instance_id=%s new_ip=%s",
        job_id,
        old_instance_id,
        old_ip,
        rescue_instance_id,
        rescue_ip,
    )
    return job_data


async def _load_job(job_id: str, include_deleted: bool = False) -> Optional[dict]:
    """Load job from DB."""
    async def _fetch_with(client: AsyncClient) -> list[dict]:
        response = await client.table(DB_TABLE).select("*").eq("job_id", job_id).execute()
        return response.data or []

    client = await get_supabase_async_client()
    try:
        records = await _fetch_with(client)
    except Exception as exc:
        if _is_invalid_uuid_error(exc):
            return None
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning(
            "JWT expired while loading training job %s; retrying with service key",
            job_id,
        )
        records = await _fetch_with(service_client)

    if not records:
        return None
    record = records[0]
    if not include_deleted and record.get("deleted_at"):
        return None
    return record


async def _save_job(job_data: dict) -> None:
    """Upsert job into DB."""
    job_data["updated_at"] = datetime.now().isoformat()

    fixed_fields = {
        "job_id",
        "job_name",
        "model_id",
        "policy_type",
        "dataset_id",
        "profile_instance_id",
        "profile_snapshot",
        "status",
        "failure_reason",
        "termination_reason",
        "cleanup_status",
        "deleted_at",
        "training_config",
        "author",
        "base_checkpoint",
        "notes",
        "instance_id",
        "ip",
        "mode",
        "ssh_user",
        "ssh_private_key",
        "remote_base_dir",
        "checkpoint_repo_id",
        "gpu_model",
        "gpus_per_instance",
        "exit_code",
        "completed_at",
        "created_at",
        "updated_at",
        "started_at",
        "summary",
        "early_stopping",
        "provision_operation_id",
    }
    record = {k: job_data.get(k) for k in fixed_fields if k in job_data}
    job_id = record.get("job_id")
    if not job_id:
        raise ValueError("Missing job_id in record")

    owner_user_id = (
        str(job_data.get("owner_user_id") or "").strip()
        or str((get_supabase_session() or {}).get("user_id") or "").strip()
    )

    async def _upsert_with(client: AsyncClient) -> None:
        existing = (
            await client.table(DB_TABLE).select("job_id").eq("job_id", job_id).execute()
        ).data or []
        if existing:
            update_record = {
                k: v
                for k, v in record.items()
                if k not in {"job_id", "owner_user_id"}
            }
            if update_record:
                await client.table(DB_TABLE).update(update_record).eq("job_id", job_id).execute()
            return

        insert_record = dict(record)
        if "owner_user_id" not in insert_record or not insert_record.get("owner_user_id"):
            if not owner_user_id:
                raise ValueError("owner_user_id is required for new training job insert")
            insert_record["owner_user_id"] = owner_user_id
        await client.table(DB_TABLE).insert(insert_record).execute()

    client = await get_supabase_async_client()
    try:
        await _upsert_with(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning(
            "JWT expired while saving training job %s; retrying with service key",
            job_id,
        )
        await _upsert_with(service_client)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("Async job helper called from running event loop.")


def _load_job_sync(job_id: str, include_deleted: bool = False) -> Optional[dict]:
    return _run_async(_load_job(job_id, include_deleted=include_deleted))


def _save_job_sync(job_data: dict) -> None:
    _run_async(_save_job(job_data))


async def _resolve_job_provision_operation(job_data: dict) -> Optional[TrainingProvisionOperationStatusResponse]:
    operations = get_training_provision_operations_service()
    operation_id = str(job_data.get("provision_operation_id") or "").strip()
    snapshot: Optional[TrainingProvisionOperationStatusResponse] = None
    if operation_id:
        snapshot = await operations.get_system(operation_id=operation_id)
    if snapshot is None:
        job_id = str(job_data.get("job_id") or "").strip()
        if job_id:
            snapshot = await operations.get_for_job_system(job_id=job_id)
    if snapshot is None:
        return None

    job_status = str(job_data.get("status") or "").strip().lower()
    if snapshot.state == "completed" and job_status != "starting":
        return None
    return snapshot


def _update_cleanup_status_sync(job_id: str, status: str) -> None:
    _run_async(_update_cleanup_status(job_id, status))


def _resolve_profile_info_sync(
    dataset_id: Optional[str],
) -> tuple[Optional[str], Optional[dict]]:
    return _run_async(_resolve_profile_info(dataset_id))


async def _update_cleanup_status(job_id: str, status: str) -> None:
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        return
    job_data["cleanup_status"] = status
    await _save_job(job_data)


async def _resolve_profile_info(
    dataset_id: Optional[str],
) -> tuple[Optional[str], Optional[dict]]:
    if not dataset_id:
        return None, None

    async def _fetch_with(client: AsyncClient) -> list[dict]:
        return (
            await client.table("datasets")
            .select("profile_instance_id,profile_snapshot")
            .eq("id", dataset_id)
            .execute()
        ).data or []

    client = await get_supabase_async_client()
    try:
        rows = await _fetch_with(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning(
            "JWT expired while resolving dataset profile info %s; retrying with service key",
            dataset_id,
        )
        rows = await _fetch_with(service_client)

    if rows:
        return rows[0].get("profile_instance_id"), rows[0].get("profile_snapshot")
    return None, None


async def _load_existing_model_name(model_id: str) -> Optional[str]:
    async def _fetch_with(client: AsyncClient) -> list[dict]:
        return (
            await client.table("models").select("name").eq("id", model_id).limit(1).execute()
        ).data or []

    client = await get_supabase_async_client()
    try:
        rows = await _fetch_with(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning(
            "JWT expired while loading model name %s; retrying with service key",
            model_id,
        )
        rows = await _fetch_with(service_client)

    if not rows:
        return None
    name = rows[0].get("name")
    if not isinstance(name, str):
        return None
    normalized = name.strip()
    return normalized or None


def _parse_optional_int(value: object) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _build_rescue_checkpoint_model_identity(
    job_id: str,
    checkpoint_job_name: str,
    step: int,
) -> tuple[str, str]:
    normalized_job_id = str(job_id or "").strip()
    normalized_job_name = str(checkpoint_job_name or "").strip()
    step_suffix = f"step_{step:06d}"

    try:
        namespace = uuid.UUID(normalized_job_id)
    except (ValueError, TypeError, AttributeError):
        namespace = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"daihen-physical-ai:training-job:{normalized_job_id or normalized_job_name}",
        )

    model_id = str(uuid.uuid5(namespace, f"rescue-checkpoint:{step_suffix}"))
    model_name_base = normalized_job_name or normalized_job_id or model_id
    return model_id, f"{model_name_base}_{step_suffix}"


async def _upsert_model_for_job(job_data: dict) -> None:
    model_id_raw = job_data.get("model_id") or job_data.get("job_id")
    model_id = str(model_id_raw or "").strip()
    profile_instance_id = job_data.get("profile_instance_id")
    profile_snapshot = job_data.get("profile_snapshot")
    if not profile_instance_id:
        profile_instance_id, profile_snapshot = await _resolve_profile_info(
            job_data.get("dataset_id")
        )
    if not model_id:
        logger.warning("Model upsert skipped (model_id missing)")
        return

    training_cfg = job_data.get("training_config") or {}
    training_params = (
        training_cfg.get("training") if isinstance(training_cfg, dict) else {}
    )
    policy_type = job_data.get("policy_type")
    if not policy_type and isinstance(training_cfg, dict):
        policy = training_cfg.get("policy") or {}
        policy_type = policy.get("type")

    checkpoint_entry = None
    try:
        checkpoint_mgr = _get_checkpoint_index_manager()
        lookup_names: list[str] = []
        for candidate in (
            str(job_data.get("job_name") or "").strip(),
            str(job_data.get("job_id") or "").strip(),
            str(job_data.get("model_id") or "").strip(),
            str(model_id or "").strip(),
        ):
            if candidate and candidate not in lookup_names:
                lookup_names.append(candidate)
        for lookup_name in lookup_names:
            checkpoint_entry = checkpoint_mgr.get_job_info(lookup_name)
            if checkpoint_entry is not None:
                break
    except Exception as exc:
        logger.debug("Failed to resolve checkpoint entry for model upsert %s: %s", model_id, exc)

    now = datetime.now().isoformat()
    job_name = str(job_data.get("job_name") or "").strip()
    explicit_model_name = str(job_data.get("model_name") or "").strip()
    default_model_name = explicit_model_name or job_name or model_id
    existing_model_name = await _load_existing_model_name(model_id)
    if existing_model_name and existing_model_name != model_id:
        resolved_model_name = existing_model_name
    else:
        resolved_model_name = default_model_name

    explicit_training_steps = _parse_optional_int(job_data.get("model_training_steps"))
    training_steps = (
        explicit_training_steps
        if explicit_training_steps is not None
        else training_params.get("steps")
    )
    if checkpoint_entry is not None and explicit_training_steps is None:
        latest_step = int(getattr(checkpoint_entry, "latest_step", 0) or 0)
        if latest_step > 0:
            training_steps = latest_step
    payload = {
        "id": model_id,
        "name": resolved_model_name,
        "dataset_id": job_data.get("dataset_id"),
        "profile_instance_id": profile_instance_id,
        "profile_name": extract_profile_name(profile_snapshot),
        "profile_snapshot": profile_snapshot,
        "policy_type": policy_type,
        "training_steps": training_steps,
        "batch_size": training_params.get("batch_size"),
        "source": "r2",
        "status": "active",
        "created_at": job_data.get("created_at") or now,
        "updated_at": now,
    }
    explicit_size = job_data.get("model_size_bytes")
    if explicit_size is not None:
        try:
            payload["size_bytes"] = max(int(explicit_size), 0)
        except (TypeError, ValueError):
            pass
    elif checkpoint_entry is not None:
        size_mb = float(getattr(checkpoint_entry, "size_mb", 0.0) or 0.0)
        if size_mb >= 0:
            payload["size_bytes"] = int(size_mb * 1024 * 1024)
    content_hash = str(job_data.get("model_content_hash") or "").strip()
    if content_hash:
        payload["content_hash"] = content_hash
    await upsert_with_owner("models", "id", payload)


async def _save_job_with_registered_model(job_data: dict) -> None:
    model_id = str(job_data.get("model_id") or job_data.get("job_id") or "").strip()
    if not model_id:
        raise ValueError("Missing model_id for job model registration")
    job_data["model_id"] = model_id
    await _upsert_model_for_job(job_data)
    await _save_job(job_data)


async def _archive_job_metrics(job_id: str) -> bool:
    """Archive job metrics from DB to R2, then delete DB records.

    Returns True if archive succeeded or no metrics to archive.
    """
    client = await get_supabase_async_client()
    try:
        response = (
            await client.table("training_job_metrics")
            .select("job_id,split,step,ts,loss,metrics")
            .eq("job_id", job_id)
            .order("split", desc=False)
            .order("step", desc=False)
            .execute()
        )
    except Exception as exc:
        logger.warning("Failed to fetch metrics for archival (%s): %s", job_id, exc)
        return False
    metrics = response.data or []
    if not metrics:
        return True

    r2 = _get_logs_r2_sync_service()
    if not r2:
        logger.warning("R2 service unavailable; skipping metrics archival for %s", job_id)
        return False

    payload = json.dumps(metrics, ensure_ascii=False, default=str)
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_metrics/{job_id}/metrics.json"
    try:
        r2.s3.client.put_object(
            Bucket=r2.bucket,
            Key=key,
            Body=payload.encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("Archived %d metrics records to R2 for %s", len(metrics), job_id)
    except Exception as exc:
        logger.warning("Failed to upload metrics to R2 for %s: %s", job_id, exc)
        return False

    try:
        await client.table("training_job_metrics").delete().eq("job_id", job_id).execute()
        logger.info("Deleted archived metrics from DB for %s", job_id)
    except Exception as exc:
        logger.warning("Failed to delete archived metrics from DB for %s: %s", job_id, exc)

    return True


def _get_metrics_from_r2(job_id: str) -> Optional[list[dict]]:
    """Fetch archived metrics JSON from R2."""
    r2 = _get_logs_r2_sync_service()
    if not r2:
        return None
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_metrics/{job_id}/metrics.json"
    try:
        obj = r2.s3.client.get_object(Bucket=r2.bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        data = json.loads(body)
        return data if isinstance(data, list) else None
    except Exception:
        return None


async def _mark_job_completed(
    job_id: str, termination_reason: str = "REMOTE_EXIT"
) -> None:
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        return
    if job_data.get("status") not in ("running", "starting", "deploying"):
        return
    job_data["status"] = "completed"
    job_data["termination_reason"] = termination_reason
    job_data["completed_at"] = datetime.now().isoformat()
    await _save_job_with_registered_model(job_data)
    await _archive_job_metrics(job_id)


def _normalize_query_text(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _build_training_owner_filter_options(
    all_jobs: list[dict],
    available_jobs: list[dict],
    owner_directory,
) -> list[TrainingOwnerFilterOption]:
    total_counts: dict[str, int] = {}
    available_counts: dict[str, int] = {}

    for job in all_jobs:
        owner_id = str(job.get("owner_user_id") or "").strip()
        if not owner_id:
            continue
        total_counts[owner_id] = total_counts.get(owner_id, 0) + 1

    for job in available_jobs:
        owner_id = str(job.get("owner_user_id") or "").strip()
        if not owner_id:
            continue
        available_counts[owner_id] = available_counts.get(owner_id, 0) + 1

    options: list[TrainingOwnerFilterOption] = []
    for owner_id, total_count in total_counts.items():
        owner_entry = owner_directory.get(owner_id)
        label = ((owner_entry.name or "").strip() if owner_entry else "") or ((owner_entry.email or "").strip() if owner_entry else "") or owner_id
        options.append(
            TrainingOwnerFilterOption(
                user_id=owner_id,
                label=label,
                owner_name=owner_entry.name or None if owner_entry else None,
                owner_email=owner_entry.email or None if owner_entry else None,
                total_count=total_count,
                available_count=available_counts.get(owner_id, 0),
            )
        )

    options.sort(key=lambda option: (option.label.lower(), option.user_id))
    return options


def _build_training_value_filter_options(
    all_jobs: list[dict],
    available_jobs: list[dict],
    *,
    value_getter,
    label_getter=None,
) -> list[TrainingValueFilterOption]:
    total_counts: dict[str, int] = {}
    available_counts: dict[str, int] = {}

    for job in all_jobs:
        value = str(value_getter(job) or "").strip()
        if not value:
            continue
        total_counts[value] = total_counts.get(value, 0) + 1

    for job in available_jobs:
        value = str(value_getter(job) or "").strip()
        if not value:
            continue
        available_counts[value] = available_counts.get(value, 0) + 1

    options = [
        TrainingValueFilterOption(
            value=value,
            label=label_getter(value) if label_getter else value,
            total_count=total_count,
            available_count=available_counts.get(value, 0),
        )
        for value, total_count in total_counts.items()
    ]
    options.sort(key=lambda option: (option.label.lower(), option.value))
    return options


async def _list_jobs(
    days: int = 365,
    owner_user_id: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    policy_type: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    sort_by: JobListSortBy = "created_at",
    sort_order: SortOrder = "desc",
    limit: Optional[int] = None,
    offset: int = 0,
) -> tuple[
    list[dict],
    int,
    list[TrainingOwnerFilterOption],
    list[TrainingValueFilterOption],
    list[TrainingValueFilterOption],
]:
    """List jobs from DB.

    Args:
        days: Return jobs from past N days.
              Running/starting jobs are always included.
    """
    async def _fetch_with(client: AsyncClient) -> list[dict]:
        query = client.table(DB_TABLE).select("*").is_("deleted_at", "null")
        response = await query.execute()
        return response.data or []

    client = await get_supabase_async_client()
    try:
        jobs = await _fetch_with(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning("JWT expired while listing training jobs; retrying with service key")
        jobs = await _fetch_with(service_client)

    cutoff_date = datetime.now() - timedelta(days=days)
    filtered = []
    for job in jobs:
        job_status = job.get("status")
        if job_status in ("running", "starting"):
            filtered.append(job)
            continue
        created_at = job.get("created_at")
        if not created_at:
            continue
        try:
            created = _parse_job_created_at(created_at)
            if created.tzinfo:
                created = created.replace(tzinfo=None)
            if created >= cutoff_date:
                filtered.append(job)
        except Exception:
            continue

    owner_directory = await resolve_user_directory_entries(
        [str(job.get("owner_user_id") or "").strip() for job in filtered]
    )
    dataset_name_map = await _resolve_dataset_names(
        [str(job.get("dataset_id") or "").strip() for job in filtered]
    )

    normalized_status = _normalize_query_text(status)
    normalized_policy_type = _normalize_query_text(policy_type)
    created_from_dt = _parse_job_created_at(created_from) if created_from else None
    created_to_dt = _parse_job_created_at(created_to) if created_to else None
    if created_to_dt and len(str(created_to or "").strip()) == 10:
        created_to_dt = created_to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    enriched_jobs: list[dict] = []
    normalized_search = _normalize_query_text(search)
    for job in filtered:
        owner_id = str(job.get("owner_user_id") or "").strip()
        dataset_id = str(job.get("dataset_id") or "").strip()
        owner_entry = owner_directory.get(owner_id)

        enriched_job = dict(job)
        enriched_job["owner_email"] = owner_entry.email or None if owner_entry else None
        enriched_job["owner_name"] = owner_entry.name or None if owner_entry else None
        enriched_job["dataset_name"] = dataset_name_map.get(dataset_id) or None

        enriched_jobs.append(enriched_job)

    def _matches(job: dict, *, skip_owner: bool = False, skip_status: bool = False, skip_policy: bool = False) -> bool:
        if normalized_search and normalized_search not in _normalize_query_text(job.get("job_name")):
            return False
        if not skip_owner and owner_user_id and str(job.get("owner_user_id") or "").strip() != str(owner_user_id).strip():
            return False
        if not skip_status and normalized_status and _normalize_query_text(job.get("status")) != normalized_status:
            return False
        if not skip_policy and normalized_policy_type and _normalize_query_text(job.get("policy_type")) != normalized_policy_type:
            return False
        if created_from_dt or created_to_dt:
            created_at = job.get("created_at")
            if not created_at:
                return False
            try:
                created = _parse_job_created_at(str(created_at))
            except Exception:
                return False
            if created_from_dt and created < created_from_dt:
                return False
            if created_to_dt and created > created_to_dt:
                return False
        return True

    available_jobs = [job for job in enriched_jobs if _matches(job, skip_owner=True)]
    status_available_jobs = [job for job in enriched_jobs if _matches(job, skip_status=True)]
    policy_available_jobs = [job for job in enriched_jobs if _matches(job, skip_policy=True)]

    owner_options = _build_training_owner_filter_options(filtered, available_jobs, owner_directory)
    status_options = _build_training_value_filter_options(
        enriched_jobs,
        status_available_jobs,
        value_getter=lambda job: job.get("status"),
    )
    policy_options = _build_training_value_filter_options(
        enriched_jobs,
        policy_available_jobs,
        value_getter=lambda job: job.get("policy_type"),
    )
    enriched = [job for job in enriched_jobs if _matches(job)]

    reverse = sort_order == "desc"

    def _sort_key(record: dict) -> tuple[object, str]:
        if sort_by == "job_name":
            primary = _normalize_query_text(record.get("job_name") or record.get("job_id"))
        elif sort_by == "owner_name":
            primary = _normalize_query_text(record.get("owner_name") or record.get("owner_email") or record.get("owner_user_id"))
        elif sort_by == "policy_type":
            primary = _normalize_query_text(record.get("policy_type"))
        elif sort_by == "status":
            primary = _normalize_query_text(record.get("status"))
        elif sort_by == "updated_at":
            primary = str(record.get("updated_at") or "")
        else:
            primary = str(record.get("created_at") or "")
        return primary, str(record.get("job_id") or "")

    enriched.sort(key=_sort_key, reverse=reverse)
    total = len(enriched)
    if offset > 0:
        enriched = enriched[offset:]
    if limit is not None:
        enriched = enriched[:limit]
    return enriched, total, owner_options, status_options, policy_options


async def _resolve_dataset_names(dataset_ids: list[str]) -> dict[str, str]:
    normalized_ids = [str(dataset_id).strip() for dataset_id in dataset_ids if str(dataset_id).strip()]
    if not normalized_ids:
        return {}

    async def _fetch_with(client: AsyncClient) -> list[dict]:
        response = (
            await client.table("datasets")
            .select("id,name")
            .in_("id", list(dict.fromkeys(normalized_ids)))
            .execute()
        )
        return response.data or []

    client = await get_supabase_async_client()
    try:
        rows = await _fetch_with(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning("JWT expired while resolving dataset names; retrying with service key")
        rows = await _fetch_with(service_client)

    return {
        str(row.get("id") or "").strip(): str(row.get("name") or row.get("id") or "").strip()
        for row in rows
        if str(row.get("id") or "").strip()
    }


# --- SSH utilities for job monitoring (uses SSHConnection) ---

# tmux session names for setup and training
TMUX_SETUP_SESSION_NAME = "instance_setup"
TMUX_TRAIN_SESSION_NAME = "training_run"

# Timeout constants
IP_WAIT_TIMEOUT_SEC = 900  # 15 minutes to wait for IP assignment
SSH_WAIT_TIMEOUT_SEC = 300  # 5 minutes to wait for SSH to be ready
INSTANCE_RUNNING_WAIT_TIMEOUT_SEC = 600  # 10 minutes to wait for instance running
SETUP_TIMEOUT_SEC = 3600  # Max time to run setup_env.sh
IP_POLL_INTERVAL_SEC = 15
INSTANCE_STATUS_POLL_INTERVAL_SEC = 10
SSH_CONNECT_ATTEMPT_TIMEOUT_SEC = 30
SSH_CONNECT_RETRY_INTERVAL_SEC = 10
INSTANCE_TERMINAL_STATUSES = {"offline", "error", "discontinued", "deleted"}


def _get_setup_log_file_path(job_data: dict) -> str:
    """Get the remote setup log file path for a job.

    Args:
        job_data: Job data dict containing remote_base_dir and mode

    Returns:
        Full path to the setup log file on the remote instance
    """
    mode = job_data.get("mode", "train")
    remote_base_dir = job_data.get("remote_base_dir", "/root/.physical-ai")
    return f"{remote_base_dir}/run/setup_env_{mode}.log"


def _get_training_log_file_path(job_data: dict) -> str:
    """Get the remote training log file path for a job.

    Args:
        job_data: Job data dict containing remote_base_dir and mode

    Returns:
        Full path to the training log file on the remote instance
    """
    mode = job_data.get("mode", "train")
    remote_base_dir = job_data.get("remote_base_dir", "/root/.physical-ai")
    return f"{remote_base_dir}/run/training_{mode}.log"


def _get_remote_checkpoint_root(job_data: dict) -> str:
    """Get remote checkpoints directory for a training job."""
    remote_base_dir = str(job_data.get("remote_base_dir") or "/root/.physical-ai").strip()
    job_id = str(job_data.get("job_id") or job_data.get("id") or "").strip()
    if not job_id:
        raise RuntimeError("job_id is missing")

    training_config = job_data.get("training_config")
    if isinstance(training_config, dict):
        output_cfg = training_config.get("output")
        if isinstance(output_cfg, dict):
            output_dir = str(output_cfg.get("output_dir") or "").strip()
            if output_dir:
                if output_dir.startswith("/"):
                    return f"{output_dir.rstrip('/')}/checkpoints"
                normalized = output_dir.lstrip("./")
                return f"{remote_base_dir.rstrip('/')}/{normalized.rstrip('/')}/checkpoints"

    return f"{remote_base_dir.rstrip('/')}/outputs/train/{job_id}/checkpoints"


def _list_remote_checkpoint_dirs(job_data: dict) -> tuple[list[str], str]:
    """List numeric checkpoint directory names on remote instance."""
    checkpoint_root = _get_remote_checkpoint_root(job_data)
    conn = _get_ssh_connection_for_job(job_data, timeout=30)
    if not conn:
        raise RuntimeError("SSH接続に失敗しました。インスタンス状態を確認してください。")

    try:
        root_quoted = shlex.quote(checkpoint_root)
        command = (
            f"if [ ! -d {root_quoted} ]; then exit 3; fi; "
            f"find {root_quoted} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' "
            "| grep -E '^[0-9]+$' | sort -n"
        )
        exit_code, stdout, stderr = conn.exec_command(command, timeout=30)
        if exit_code == 3:
            raise RuntimeError(f"チェックポイントディレクトリが見つかりません: {checkpoint_root}")
        if exit_code != 0:
            msg = (stderr or stdout or "unknown error").strip()
            raise RuntimeError(f"チェックポイント一覧の取得に失敗しました: {msg}")
        names = [line.strip() for line in stdout.splitlines() if line.strip().isdigit()]
        return names, checkpoint_root
    finally:
        conn.disconnect()


def _register_job_for_checkpoint_if_needed(
    checkpoint_mgr: "CheckpointIndexManager", job_data: dict
) -> None:
    job_id = str(job_data.get("job_id") or job_data.get("id") or "").strip()
    if not job_id:
        raise RuntimeError("job_id is missing")
    job_name = str(job_data.get("job_name") or "").strip() or job_id

    existing = checkpoint_mgr.get_job_info(job_name)
    if existing:
        return

    training_config = job_data.get("training_config")
    config = training_config if isinstance(training_config, dict) else {}
    policy_cfg = config.get("policy") if isinstance(config.get("policy"), dict) else {}
    dataset_cfg = config.get("dataset") if isinstance(config.get("dataset"), dict) else {}

    policy_type = str(job_data.get("policy_type") or policy_cfg.get("type") or "").strip()
    dataset_id = str(job_data.get("dataset_id") or dataset_cfg.get("id") or "").strip()
    if not policy_type or not dataset_id:
        raise RuntimeError(
            "ジョブメタデータ不足のためcheckpointを登録できません。"
            "policy_type/dataset_id を確認してください。"
        )

    pretrained_path = policy_cfg.get("pretrained_path") or policy_cfg.get("base_model_path")
    author = str(job_data.get("author") or _default_author_user_id()).strip() or "unknown"
    dataset_info = _get_storage_dataset_info_from_manifest(dataset_id)

    ok = checkpoint_mgr.register_job(
        job_name=job_name,
        policy_type=policy_type,
        dataset_id=dataset_id,
        pretrained_path=pretrained_path,
        dataset_info=dataset_info,
        author=author,
        training_config=config,
    )
    if not ok:
        raise RuntimeError("checkpoint index へのジョブ登録に失敗しました")


def _list_r2_file_objects(s3_manager: object, s3_path: str) -> list[dict]:
    objects = s3_manager.list_objects(s3_path)
    files: list[dict] = []
    for obj in objects:
        key = str(obj.get("Key") or "").strip()
        if not key or key.endswith("/"):
            continue
        files.append(obj)
    return files


def _ensure_model_artifact_in_r2_from_checkpoint(
    checkpoint_mgr: "CheckpointIndexManager",
    *,
    checkpoint_job_name: str,
    model_id: str,
    step: int,
) -> tuple[str, int, bool]:
    """Ensure models/{model_id} exists by copying from checkpoint pretrained_model."""
    sync = checkpoint_mgr.sync
    bucket = sync.bucket
    prefix = sync._get_prefix()
    source_prefix = f"{prefix}checkpoints/{checkpoint_job_name}/step_{step:06d}/pretrained_model/"
    target_prefix = f"{prefix}models/{model_id}/"
    source_path = f"s3://{bucket}/{source_prefix}"
    target_path = f"s3://{bucket}/{target_prefix}"

    existing_target_files = _list_r2_file_objects(sync.s3, target_path)
    if existing_target_files:
        size_bytes = sum(max(int(obj.get("Size") or 0), 0) for obj in existing_target_files)
        return target_path.rstrip("/"), size_bytes, False

    source_files = _list_r2_file_objects(sync.s3, source_path)
    if not source_files:
        raise RuntimeError(
            f"モデル生成元が見つかりません: {source_path} (pretrained_model が必要です)"
        )

    for obj in source_files:
        source_key = str(obj.get("Key") or "").strip()
        if not source_key.startswith(source_prefix):
            continue
        relative = source_key[len(source_prefix):].lstrip("/")
        if not relative:
            continue
        target_key = f"{target_prefix}{relative}"
        sync.s3.client.copy(
            {"Bucket": bucket, "Key": source_key},
            bucket,
            target_key,
        )

    size_bytes = sum(max(int(obj.get("Size") or 0), 0) for obj in source_files)
    return target_path.rstrip("/"), size_bytes, True


def _format_byte_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(max(size_bytes, 0))
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{int(max(size_bytes, 0))} B"


def _coerce_int(value: object) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _clamp_progress_percent(value: float) -> float:
    return round(min(max(float(value), 0.0), 100.0), 2)


def _interpolate_progress(
    *,
    current_bytes: int,
    total_bytes: int,
    start_percent: float,
    end_percent: float,
) -> float:
    if total_bytes <= 0:
        return _clamp_progress_percent(start_percent)
    ratio = min(max(float(current_bytes) / float(total_bytes), 0.0), 1.0)
    return _clamp_progress_percent(start_percent + ((end_percent - start_percent) * ratio))


def _decorate_checkpoint_upload_progress(payload: dict) -> dict:
    decorated = dict(payload)
    event_type = str(decorated.get("type") or "").strip()
    phase = "uploading_checkpoint"
    progress_percent = 0.0

    if event_type in {"start", "connecting_ssh"}:
        phase = "connecting_ssh"
        progress_percent = 5.0 if event_type == "start" else 10.0
    elif event_type == "validating":
        phase = "validating"
        progress_percent = 15.0
    elif event_type in {"downloading", "registering", "direct_upload", "direct_upload_fallback", "scanning"}:
        phase = "scanning"
        progress_percent = 20.0
    elif event_type in {"uploading", "uploading_file", "uploaded", "direct_upload_complete"}:
        phase = "uploading_checkpoint"
        current_bytes = _coerce_int(
            decorated.get("transferred_bytes") or decorated.get("bytes_done_total")
        )
        total_bytes = _coerce_int(decorated.get("total_bytes") or decorated.get("total_size"))
        if event_type in {"uploaded", "direct_upload_complete"}:
            progress_percent = 80.0
        else:
            progress_percent = _interpolate_progress(
                current_bytes=current_bytes,
                total_bytes=total_bytes,
                start_percent=20.0,
                end_percent=80.0,
            )
    elif event_type == "updating_last":
        phase = "updating_checkpoint_index"
        progress_percent = 85.0
    elif event_type in {"uploading_model", "model_uploaded"}:
        phase = "copying_model_artifact"
        progress_percent = 90.0 if event_type == "uploading_model" else 95.0
    elif event_type in {"registering_model", "model_registered"}:
        phase = "registering_model"
        progress_percent = 97.0 if event_type == "registering_model" else 100.0
    elif event_type == "complete":
        phase = "completed"
        progress_percent = 100.0
    elif event_type == "error":
        phase = "failed"
        progress_percent = 100.0

    decorated["phase"] = phase
    decorated["progress_percent"] = progress_percent
    return decorated


def _decorate_rescue_cpu_progress(payload: dict) -> dict:
    decorated = dict(payload)
    event_type = str(decorated.get("type") or "").strip()
    phase = "loading_storage"
    progress_percent = 0.0

    if event_type == "start":
        phase = "loading_storage"
        progress_percent = 2.0
    elif event_type == "loading_storage":
        phase = "loading_storage"
        progress_percent = 8.0
    elif event_type in {
        "detaching_from_other",
        "stopping_old_instance",
        "detaching_storage",
        "detached_storage",
        "waiting_detach_propagation",
    }:
        phase = "detaching_storage"
        detaching_map = {
            "detaching_from_other": 18.0,
            "stopping_old_instance": 24.0,
            "detaching_storage": 34.0,
            "waiting_detach_propagation": 40.0,
            "detached_storage": 45.0,
        }
        progress_percent = detaching_map.get(event_type, 25.0)
    elif event_type in {"select_instance", "creating_instance"}:
        phase = "creating_instance"
        progress_percent = 55.0 if event_type == "select_instance" else 65.0
    elif event_type == "waiting_ip":
        phase = "waiting_ip"
        progress_percent = 75.0
    elif event_type == "waiting_ssh":
        phase = "waiting_ssh"
        progress_percent = 88.0
    elif event_type == "switching_job_target":
        phase = "switching_job_target"
        progress_percent = 96.0
    elif event_type == "complete":
        phase = "completed"
        progress_percent = 100.0
    elif event_type == "error":
        phase = "failed"
        progress_percent = 100.0

    decorated["phase"] = phase
    decorated["progress_percent"] = progress_percent
    return decorated


def _normalize_env_value(value: object) -> str:
    return str(value or "").strip().strip("\"'")


def _resolve_r2_upload_settings() -> dict[str, str]:
    env_fallback = _load_env_file_vars()

    def pick(*names: str) -> str:
        for name in names:
            value = _normalize_env_value(os.environ.get(name))
            if value:
                return value
            value = _normalize_env_value(env_fallback.get(name))
            if value:
                return value
        return ""

    endpoint = pick("R2_ENDPOINT_URL", "S3_ENDPOINT_URL")
    access_key = pick("R2_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID")
    secret_key = pick("R2_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY")
    bucket = pick("R2_BUCKET", "S3_BUCKET")
    version = pick("R2_VERSION", "S3_VERSION")

    if not endpoint or not access_key or not secret_key or not bucket:
        raise HTTPException(
            status_code=503,
            detail="R2アップロード設定が不足しています",
        )

    return {
        "endpoint": endpoint,
        "access_key": access_key,
        "secret_key": secret_key,
        "bucket": bucket,
        "version": version,
    }


def _build_remote_checkpoint_upload_script() -> str:
    return textwrap.dedent(
        """
        import json
        import os
        import sys
        import time
        import threading
        from pathlib import Path

        import boto3
        from boto3.s3.transfer import TransferConfig
        from botocore.config import Config


        _emit_lock = threading.Lock()


        def emit(event_type: str, message: str, **extra) -> None:
            payload = {"type": event_type, "message": message}
            payload.update(extra)
            with _emit_lock:
                print(json.dumps(payload, ensure_ascii=False), flush=True)


        def format_size(size_bytes: int) -> str:
            units = ["B", "KB", "MB", "GB", "TB"]
            value = float(max(size_bytes, 0))
            for unit in units:
                if value < 1024.0 or unit == units[-1]:
                    if unit == "B":
                        return f"{int(value)} {unit}"
                    return f"{value:.1f} {unit}"
                value /= 1024.0
            return f"{int(max(size_bytes, 0))} B"


        def main() -> int:
            checkpoint_dir = Path(os.environ["CHECKPOINT_DIR"]).expanduser()
            if not checkpoint_dir.exists():
                emit("error", f"Remote checkpoint not found: {checkpoint_dir}")
                return 4

            bucket = os.environ["R2_BUCKET"]
            endpoint = os.environ["R2_ENDPOINT_URL"]
            access_key = os.environ["R2_ACCESS_KEY_ID"]
            secret_key = os.environ["R2_SECRET_ACCESS_KEY"]
            step_prefix = os.environ["R2_STEP_PREFIX"].strip("/")

            transfer_max_concurrency = max(int(os.environ.get("S3_TRANSFER_MAX_CONCURRENCY", "10") or "10"), 1)
            transfer_threshold_mb = max(int(os.environ.get("S3_TRANSFER_MULTIPART_THRESHOLD_MB", "8") or "8"), 1)
            transfer_chunksize_mb = max(int(os.environ.get("S3_TRANSFER_MULTIPART_CHUNKSIZE_MB", "8") or "8"), 1)

            emit("scanning", f"checkpoint内容を走査中... {checkpoint_dir}")
            files = sorted(path for path in checkpoint_dir.rglob("*") if path.is_file())
            if not files:
                emit("error", f"Remote checkpoint is empty: {checkpoint_dir}")
                return 5

            total_bytes = sum(path.stat().st_size for path in files)
            emit(
                "uploading",
                f"R2へ直接転送を開始します ({format_size(total_bytes)})",
                total_bytes=total_bytes,
                file_count=len(files),
            )

            config = Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                max_pool_connections=max(transfer_max_concurrency * 2, 16),
            )
            transfer_config = TransferConfig(
                max_concurrency=transfer_max_concurrency,
                multipart_threshold=transfer_threshold_mb * 1024 * 1024,
                multipart_chunksize=transfer_chunksize_mb * 1024 * 1024,
                use_threads=True,
            )
            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name="auto",
                config=config,
            )

            transferred_bytes = 0
            current_file: str | None = None
            last_emit_time = 0.0
            last_emit_bytes = 0
            progress_lock = threading.Lock()
            reporter_stop = threading.Event()

            def emit_progress(*, force: bool = False, override_file: str | None = None) -> None:
                nonlocal last_emit_time, last_emit_bytes
                with progress_lock:
                    now = time.time()
                    byte_delta = transferred_bytes - last_emit_bytes
                    if not force and byte_delta < 128 * 1024 * 1024 and (now - last_emit_time) < 1.0:
                        return
                    active_file = override_file if override_file is not None else current_file
                    detail = f"{format_size(transferred_bytes)} / {format_size(total_bytes)}"
                    message = f"R2へ直接転送中... ({detail})"
                    if active_file:
                        message = f"{message} {active_file}"
                    payload = {
                        "transferred_bytes": transferred_bytes,
                        "total_bytes": total_bytes,
                    }
                    last_emit_time = now
                    last_emit_bytes = transferred_bytes
                emit("uploading", message, **payload)

            def progress_reporter() -> None:
                while not reporter_stop.wait(1.0):
                    emit_progress()

            reporter = threading.Thread(target=progress_reporter, daemon=True)
            reporter.start()
            emit_progress(force=True)

            try:
                for index, file_path in enumerate(files, start=1):
                    relative_path = file_path.relative_to(checkpoint_dir).as_posix()
                    key = f"{step_prefix}/{relative_path}".lstrip("/")
                    file_size = file_path.stat().st_size
                    with progress_lock:
                        current_file = relative_path
                    emit(
                        "uploading_file",
                        f"R2へ転送中 {index}/{len(files)}: {relative_path} ({format_size(file_size)})",
                        path=relative_path,
                        file_bytes=file_size,
                    )

                    def callback(bytes_amount: int) -> None:
                        nonlocal transferred_bytes
                        with progress_lock:
                            transferred_bytes += max(int(bytes_amount or 0), 0)

                    client.upload_file(
                        str(file_path),
                        bucket,
                        key,
                        Config=transfer_config,
                        Callback=callback,
                    )
                    emit_progress(force=True, override_file=relative_path)
            finally:
                reporter_stop.set()
                reporter.join(timeout=2.0)

            emit(
                "uploaded",
                "R2への直接転送が完了しました",
                total_bytes=total_bytes,
                transferred_bytes=transferred_bytes,
                file_count=len(files),
            )
            print(
                json.dumps(
                    {
                        "type": "result",
                        "ok": True,
                        "total_bytes": total_bytes,
                        "file_count": len(files),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return 0


        if __name__ == "__main__":
            sys.exit(main())
        """
    ).strip() + "\n"


def _ensure_remote_checkpoint_upload_script(
    conn: SSHConnection,
    *,
    remote_base_dir: str,
) -> str:
    run_dir = f"{remote_base_dir.rstrip('/')}/run"
    conn.mkdir_p(run_dir)
    script_path = f"{run_dir}/rescue_checkpoint_upload.py"
    conn.upload_content(_build_remote_checkpoint_upload_script(), script_path)
    conn.exec_command(f"chmod 700 {shlex.quote(script_path)}")
    return script_path


def _upload_remote_checkpoint_to_r2_direct(
    checkpoint_mgr: "CheckpointIndexManager",
    conn: SSHConnection,
    *,
    job_data: dict,
    checkpoint_job_name: str,
    step: int,
    remote_checkpoint_path: str,
    emit_progress: Callable[[dict], None],
) -> int:
    remote_base_dir = str(job_data.get("remote_base_dir") or "/root/.physical-ai").strip() or "/root/.physical-ai"
    script_path = _ensure_remote_checkpoint_upload_script(conn, remote_base_dir=remote_base_dir)
    step_path = checkpoint_mgr._get_step_path(checkpoint_job_name, step)
    bucket, step_prefix = checkpoint_mgr.sync.s3.parse_s3_path(step_path)
    settings = _resolve_r2_upload_settings()

    framework_python = f"{remote_base_dir.rstrip('/')}/envs/framework/bin/python"
    env_exports = {
        "CHECKPOINT_DIR": remote_checkpoint_path,
        "R2_BUCKET": bucket or settings["bucket"],
        "R2_ENDPOINT_URL": settings["endpoint"],
        "R2_ACCESS_KEY_ID": settings["access_key"],
        "R2_SECRET_ACCESS_KEY": settings["secret_key"],
        "R2_STEP_PREFIX": step_prefix,
        "S3_TRANSFER_MAX_CONCURRENCY": str(
            max(int(os.environ.get("S3_TRANSFER_MAX_CONCURRENCY") or "10"), 1)
        ),
        "S3_TRANSFER_MULTIPART_THRESHOLD_MB": str(
            max(int(os.environ.get("S3_TRANSFER_MULTIPART_THRESHOLD_MB") or "8"), 1)
        ),
        "S3_TRANSFER_MULTIPART_CHUNKSIZE_MB": str(
            max(int(os.environ.get("S3_TRANSFER_MULTIPART_CHUNKSIZE_MB") or "8"), 1)
        ),
    }
    export_lines = " ".join(
        f"{name}={shlex.quote(value)}" for name, value in env_exports.items()
    )
    command = (
        f"if [ -x {shlex.quote(framework_python)} ]; then PYTHON_BIN={shlex.quote(framework_python)}; "
        "elif command -v python3 >/dev/null 2>&1; then PYTHON_BIN=python3; "
        "elif command -v python >/dev/null 2>&1; then PYTHON_BIN=python; "
        "else echo '{\"type\":\"error\",\"message\":\"Python runtime not found on current SSH target\"}'; exit 127; fi; "
        f"{export_lines} \"$PYTHON_BIN\" {shlex.quote(script_path)}"
    )

    result_payload: dict[str, object] = {}
    last_error: str | None = None

    def _on_stdout(line: str) -> None:
        nonlocal last_error
        stripped = line.strip()
        if not stripped:
            return
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            emit_progress({"type": "remote_log", "message": stripped, "step": step})
            return
        if not isinstance(payload, dict):
            emit_progress({"type": "remote_log", "message": stripped, "step": step})
            return
        payload.setdefault("step", step)
        payload_type = str(payload.get("type") or "").strip()
        if payload_type == "result":
            result_payload.update(payload)
            return
        if payload_type == "error":
            last_error = str(payload.get("message") or payload.get("error") or "").strip() or stripped
        emit_progress(payload)

    exit_code = run_remote_command(
        conn,
        command,
        stream_output=False,
        on_stdout=_on_stdout,
    )
    if exit_code != 0:
        detail = last_error or f"remote direct upload failed with exit code {exit_code}"
        raise RuntimeError(detail)

    total_bytes = int(result_payload.get("total_bytes") or 0)
    if total_bytes <= 0:
        raise RuntimeError("remote direct upload completed without total_bytes result")

    emit_progress(
        {
            "type": "updating_last",
            "message": "last ポインタ用オブジェクトを更新中...",
            "step": step,
        }
    )
    checkpoint_mgr._copy_to_last(checkpoint_job_name, step)
    checkpoint_mgr._update_index_step(checkpoint_job_name, step, total_bytes)
    return total_bytes


def _create_verda_instance_from_volume(
    client: VerdaClient,
    *,
    volume_id: str,
    instance_type: str,
    ssh_key_id: str,
    location: str,
    hostname: str,
    description: str,
    emit_progress: Callable[[dict], None] | None = None,
    retry_timeout_sec: int = 120,
) -> object:
    deadline = time.time() + retry_timeout_sec
    last_exc: Exception | None = None
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            return client.instances.create(
                instance_type=instance_type,
                image=volume_id,
                hostname=hostname,
                description=description,
                ssh_key_ids=[ssh_key_id],
                location=location,
                is_spot=False,
            )
        except Exception as exc:
            last_exc = exc
            detail = str(exc)
            if "OS volume must be detached" not in detail:
                raise
            logger.warning(
                "Volume %s still not reusable while creating instance (attempt %s): %s",
                volume_id,
                attempt,
                detail,
            )
            if emit_progress is not None:
                emit_progress(
                    {
                        "type": "waiting_detach_propagation",
                        "message": "ストレージの分離反映待ち...",
                        "volume_id": volume_id,
                    }
                )
            try:
                _wait_for_volume_detached(client, volume_id, timeout_sec=20)
            except HTTPException:
                pass
            time.sleep(5)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("instance creation retry timeout")


def _list_remote_checkpoint_files(
    conn: SSHConnection,
    remote_path: str,
    *,
    relative_prefix: str = "",
) -> list[tuple[str, str, int]]:
    files: list[tuple[str, str, int]] = []
    for attr in sorted(conn.sftp.listdir_attr(remote_path), key=lambda item: item.filename):
        name = str(getattr(attr, "filename", "") or "").strip()
        if not name:
            continue
        child_remote_path = f"{remote_path.rstrip('/')}/{name}"
        child_relative_path = f"{relative_prefix}/{name}".lstrip("/")
        mode = int(getattr(attr, "st_mode", 0) or 0)
        if stat.S_ISDIR(mode):
            files.extend(
                _list_remote_checkpoint_files(
                    conn,
                    child_remote_path,
                    relative_prefix=child_relative_path,
                )
            )
            continue
        size = max(int(getattr(attr, "st_size", 0) or 0), 0)
        files.append((child_remote_path, child_relative_path, size))
    return files


def _upload_remote_checkpoint_to_r2(
    checkpoint_mgr: "CheckpointIndexManager",
    conn: SSHConnection,
    *,
    checkpoint_job_name: str,
    step: int,
    remote_checkpoint_path: str,
    emit_progress: Callable[[dict], None],
) -> int:
    remote_files = _list_remote_checkpoint_files(conn, remote_checkpoint_path)
    if not remote_files:
        raise HTTPException(
            status_code=404,
            detail=f"Remote checkpoint is empty: {remote_checkpoint_path}",
        )

    step_path = checkpoint_mgr._get_step_path(checkpoint_job_name, step)
    bucket, step_prefix = checkpoint_mgr.sync.s3.parse_s3_path(step_path)
    total_bytes = sum(size for _, _, size in remote_files)
    transferred_bytes = 0
    last_emit_time = 0.0
    last_emit_bytes = 0

    def emit_transfer_progress(*, current_file: str | None = None, force: bool = False) -> None:
        nonlocal last_emit_time, last_emit_bytes
        now = time.time()
        byte_delta = transferred_bytes - last_emit_bytes
        if not force and byte_delta < 128 * 1024 * 1024 and (now - last_emit_time) < 1.0:
            return

        detail = (
            f"{_format_byte_size(transferred_bytes)} / {_format_byte_size(total_bytes)}"
            if total_bytes > 0
            else _format_byte_size(transferred_bytes)
        )
        message = f"checkpointをR2へ転送中... ({detail})"
        if current_file:
            message = f"{message} {current_file}"
        emit_progress(
            {
                "type": "uploading",
                "message": message,
                "step": step,
                "transferred_bytes": transferred_bytes,
                "total_bytes": total_bytes,
            }
        )
        last_emit_time = now
        last_emit_bytes = transferred_bytes

    emit_transfer_progress(force=True)

    for index, (remote_file_path, relative_path, file_size) in enumerate(remote_files, start=1):
        emit_progress(
            {
                "type": "uploading_file",
                "message": (
                    f"R2へ転送中 {index}/{len(remote_files)}: "
                    f"{relative_path} ({_format_byte_size(file_size)})"
                ),
                "step": step,
            }
        )
        target_key = f"{step_prefix.rstrip('/')}/{relative_path}".lstrip("/")
        with conn.sftp.file(remote_file_path, "rb") as remote_file:
            prefetch = getattr(remote_file, "prefetch", None)
            if callable(prefetch):
                try:
                    prefetch(file_size if file_size > 0 else None)
                except TypeError:
                    try:
                        prefetch()
                    except Exception:
                        pass
                except Exception:
                    pass

            def _callback(bytes_transferred: int) -> None:
                nonlocal transferred_bytes
                transferred_bytes += max(int(bytes_transferred or 0), 0)
                emit_transfer_progress(current_file=relative_path)

            checkpoint_mgr.sync.s3.upload_fileobj(
                remote_file,
                bucket,
                target_key,
                callback=_callback,
                use_threads=False,
            )
        emit_transfer_progress(current_file=relative_path, force=True)

    emit_progress(
        {
            "type": "updating_last",
            "message": "last ポインタ用オブジェクトを更新中...",
            "step": step,
        }
    )
    checkpoint_mgr._copy_to_last(checkpoint_job_name, step)
    checkpoint_mgr._update_index_step(checkpoint_job_name, step, total_bytes)
    return total_bytes


async def _upload_selected_remote_checkpoint_with_progress(
    job_id: str,
    checkpoint_name: str,
    emit_progress: Callable[[dict], None],
) -> dict:
    def emit_checkpoint_progress(payload: dict) -> None:
        emit_progress(_decorate_checkpoint_upload_progress(payload))

    emit_checkpoint_progress({"type": "start", "message": "チェックポイント登録を開始しました"})

    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    job_data = await _refresh_job_ssh_target_if_needed(job_data)

    checkpoint_name = str(checkpoint_name or "").strip()
    if not checkpoint_name.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"checkpoint_name must be numeric: {checkpoint_name}",
        )

    step = int(checkpoint_name)
    checkpoint_job_name = str(job_data.get("job_name") or "").strip() or job_id
    model_id, model_name = _build_rescue_checkpoint_model_identity(
        job_id,
        checkpoint_job_name,
        step,
    )
    if not model_id:
        raise HTTPException(
            status_code=500,
            detail="model_id を生成できないためDB登録できませんでした。",
        )
    checkpoint_mgr = _get_checkpoint_index_manager()
    existing_steps = checkpoint_mgr.get_job_steps(checkpoint_job_name)

    if step not in existing_steps:
        checkpoint_root = _get_remote_checkpoint_root(job_data)
        remote_checkpoint_path = f"{checkpoint_root.rstrip('/')}/{checkpoint_name}"

        emit_checkpoint_progress({"type": "connecting_ssh", "message": "インスタンスへ接続中..."})
        conn = _get_ssh_connection_for_job(job_data, timeout=30)
        if not conn:
            raise HTTPException(
                status_code=503,
                detail="SSH接続に失敗しました。インスタンスが起動中か確認してください。",
            )

        try:
            emit_checkpoint_progress({"type": "validating", "message": "checkpoint存在を確認中..."})
            check_cmd = f"test -d {shlex.quote(remote_checkpoint_path)}"
            exit_code, _, _ = conn.exec_command(check_cmd, timeout=15)
            if exit_code != 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Remote checkpoint not found: {remote_checkpoint_path}",
                )

            emit_checkpoint_progress(
                {
                    "type": "downloading",
                    "message": "checkpointの転送準備中...",
                    "checkpoint_name": checkpoint_name,
                }
            )

            emit_checkpoint_progress({"type": "registering", "message": "checkpoint index登録中..."})
            _register_job_for_checkpoint_if_needed(checkpoint_mgr, job_data)

            direct_upload_error: Exception | None = None
            try:
                emit_checkpoint_progress(
                    {
                        "type": "direct_upload",
                        "message": "現在の SSH 接続先から R2 へ直接転送します...",
                        "step": step,
                    }
                )
                _upload_remote_checkpoint_to_r2_direct(
                    checkpoint_mgr,
                    conn,
                    job_data=job_data,
                    checkpoint_job_name=checkpoint_job_name,
                    step=step,
                    remote_checkpoint_path=remote_checkpoint_path,
                    emit_progress=emit_checkpoint_progress,
                )
            except Exception as exc:
                direct_upload_error = exc
                logger.warning(
                    "Remote direct checkpoint upload failed; falling back to backend relay: job_id=%s step=%s error=%s",
                    job_id,
                    step,
                    exc,
                )
                emit_checkpoint_progress(
                    {
                        "type": "direct_upload_fallback",
                        "message": (
                            "現在の SSH 接続先からの直接転送に失敗したため、"
                            "バックエンド経由転送に切り替えます..."
                        ),
                        "step": step,
                    }
                )
                _upload_remote_checkpoint_to_r2(
                    checkpoint_mgr,
                    conn,
                    checkpoint_job_name=checkpoint_job_name,
                    step=step,
                    remote_checkpoint_path=remote_checkpoint_path,
                    emit_progress=emit_checkpoint_progress,
                )
            if direct_upload_error is None:
                emit_checkpoint_progress(
                    {
                        "type": "direct_upload_complete",
                        "message": "現在の SSH 接続先からの直接転送が完了しました",
                        "step": step,
                    }
                )
        finally:
            conn.disconnect()
    else:
        emit_checkpoint_progress(
            {
                "type": "uploaded",
                "message": "R2には既に登録済みのためアップロードをスキップしました",
                "checkpoint_name": checkpoint_name,
                "step": step,
            }
        )

    prefix = checkpoint_mgr.sync._get_prefix()
    r2_step_path = (
        f"s3://{checkpoint_mgr.sync.bucket}/{prefix}checkpoints/{checkpoint_job_name}/step_{step:06d}"
    )
    emit_checkpoint_progress(
        {
            "type": "uploaded",
            "message": "R2登録が完了しました",
            "checkpoint_name": checkpoint_name,
            "step": step,
        }
    )
    emit_checkpoint_progress(
        {
            "type": "uploading_model",
            "message": "推論モデルをR2へ反映中...",
        }
    )
    try:
        model_r2_path, model_size_bytes, copied_model = _ensure_model_artifact_in_r2_from_checkpoint(
            checkpoint_mgr,
            checkpoint_job_name=checkpoint_job_name,
            model_id=model_id,
            step=step,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"モデルアーティファクトのR2反映に失敗しました: {exc}",
        ) from exc
    emit_checkpoint_progress(
        {
            "type": "model_uploaded",
            "message": (
                "推論モデルをR2へ反映しました"
                if copied_model
                else "推論モデルは既にR2に存在します"
            ),
            "model_id": model_id,
            "model_r2_path": model_r2_path,
        }
    )
    emit_checkpoint_progress(
        {
            "type": "registering_model",
            "message": "モデルをDBへ登録中...",
        }
    )
    job_data["model_id"] = model_id
    job_data["model_name"] = model_name
    job_data["model_training_steps"] = step
    job_data["model_size_bytes"] = model_size_bytes
    try:
        await _save_job_with_registered_model(job_data)
    except Exception as exc:
        logger.exception(
            "Remote checkpoint upload succeeded but model DB registration failed: job_id=%s step=%s",
            job_id,
            step,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "R2登録は完了しましたが、モデルのDB登録またはジョブ関連付けに失敗しました: "
                f"{exc}. 同じチェックポイントで再実行してください。"
            ),
        ) from exc
    emit_checkpoint_progress(
        {
            "type": "model_registered",
            "message": "モデルDB登録が完了しました",
            "model_id": model_id,
        }
    )
    return RemoteCheckpointUploadResponse(
        job_id=job_id,
        checkpoint_name=checkpoint_name,
        step=step,
        r2_step_path=r2_step_path,
        model_id=model_id,
        db_registered=True,
        message="チェックポイントをR2/DBに登録し、推論モデルも反映しました",
    ).model_dump()


def _get_ssh_connection_for_job(
    job_data: dict, timeout: int = 30
) -> Optional[SSHConnection]:
    """Get SSHConnection for job instance.

    Args:
        job_data: Job data dict containing ip, ssh_user, ssh_private_key
        timeout: Connection timeout in seconds

    Returns:
        Connected SSHConnection or None if connection fails
    """
    ip = job_data.get("ip")
    if not ip:
        return None
    ssh_port = 22
    try:
        ssh_port = int(job_data.get("ssh_port") or 22)
    except (TypeError, ValueError):
        ssh_port = 22
    training_cfg = job_data.get("training_config")
    if isinstance(training_cfg, dict):
        cloud_cfg = training_cfg.get("cloud")
        if isinstance(cloud_cfg, dict):
            try:
                cloud_port = int(cloud_cfg.get("ssh_port") or 0)
            except (TypeError, ValueError):
                cloud_port = 0
            if cloud_port > 0:
                ssh_port = cloud_port

    users = _build_ssh_user_candidates(job_data.get("ssh_user", _get_default_ssh_user()))
    key_candidates = _build_ssh_private_key_candidates(job_data.get("ssh_private_key"))
    if not key_candidates:
        logger.warning(
            "No usable SSH private key found for job %s (saved=%s, env=%s)",
            job_data.get("job_id"),
            job_data.get("ssh_private_key"),
            os.environ.get("VERDA_SSH_PRIVATE_KEY"),
        )
        return None

    last_error: Optional[Exception] = None
    for user in users:
        for key_path in key_candidates:
            try:
                conn = SSHConnection(
                    host=ip,
                    user=user,
                    private_key_path=key_path,
                    port=ssh_port,
                )
                conn.connect(timeout_sec=timeout)
                return conn
            except SystemExit as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc

    if last_error:
        logger.warning(
            "SSH connection failed for job %s (ip=%s, port=%s, users=%s, keys=%s): %s",
            job_data.get("job_id"),
            ip,
            ssh_port,
            ",".join(users),
            ",".join(str(p) for p in key_candidates),
            last_error,
        )
        logger.debug(
            "Failed to connect SSH for job %s with all key/user candidates: %s",
            job_data.get("job_id"),
            last_error,
        )
    return None


def _check_remote_status(job_data: dict) -> str:
    """Check remote process status via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return "unreachable"

    try:
        train_cmd = f"tmux has-session -t {TMUX_TRAIN_SESSION_NAME} 2>/dev/null && echo 'running' || echo 'stopped'"
        exit_code, stdout, stderr = conn.exec_command(train_cmd)
        train_status = stdout.strip()
        if train_status == "running":
            return "running"

        setup_cmd = f"tmux has-session -t {TMUX_SETUP_SESSION_NAME} 2>/dev/null && echo 'running' || echo 'stopped'"
        exit_code, stdout, stderr = conn.exec_command(setup_cmd)
        setup_status = stdout.strip()
        if setup_status == "running":
            return "starting"
        return "stopped"
    except Exception:
        return "error"
    finally:
        conn.disconnect()


async def _check_remote_status_async(job_data: dict) -> str:
    return await asyncio.to_thread(_check_remote_status, job_data)


def _get_remote_logs(
    job_data: dict, lines: int = 100, log_type: str = "training"
) -> Optional[str]:
    """Get remote logs via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return None

    try:
        if log_type == "setup":
            log_file = _get_setup_log_file_path(job_data)
        else:
            log_file = _get_training_log_file_path(job_data)
        cmd = f"tail -n {lines} {log_file} 2>/dev/null || echo '[Log file not found]'"
        exit_code, stdout, stderr = conn.exec_command(cmd)
        return stdout
    except Exception:
        return None
    finally:
        conn.disconnect()


async def _get_remote_logs_async(
    job_data: dict,
    lines: int = 100,
    log_type: str = "training",
) -> Optional[str]:
    return await asyncio.to_thread(_get_remote_logs, job_data, lines, log_type)


def _get_remote_log_file(
    job_data: dict,
    log_type: str = "training",
    timeout: int = 15,
) -> Optional[str]:
    try:
        conn = _get_ssh_connection_for_job(job_data, timeout=timeout)
    except SystemExit:
        return None
    if not conn:
        return None
    try:
        if log_type == "setup":
            log_file = _get_setup_log_file_path(job_data)
        else:
            log_file = _get_training_log_file_path(job_data)
        cmd = f"cat {log_file} 2>/dev/null || echo '[Log file not found]'"
        exit_code, stdout, stderr = conn.exec_command(cmd)
        return stdout
    except Exception:
        return None
    finally:
        conn.disconnect()


async def _get_remote_log_file_async(
    job_data: dict,
    log_type: str = "training",
    timeout: int = 15,
) -> Optional[str]:
    return await asyncio.to_thread(
        _get_remote_log_file,
        job_data,
        log_type,
        timeout,
    )


def _should_try_r2_first(job_data: dict) -> bool:
    cleanup_status = job_data.get("cleanup_status")
    if cleanup_status in ("running", "done"):
        return True
    if job_data.get("status") in ("completed", "failed", "stopped", "terminated"):
        return True
    if not job_data.get("ip"):
        return True
    return False


def _get_log_file_name(job_data: dict, log_type: str) -> str:
    mode = job_data.get("mode", "train")
    if log_type == "setup":
        return f"setup_env_{mode}.log"
    return f"training_{mode}.log"


def _get_logs_r2_sync_service() -> Optional["R2SyncService"]:
    try:
        from percus_ai.storage import ManifestManager, R2SyncService

        manifest = ManifestManager()
        manifest.init_directories()
        bucket = os.getenv("R2_BUCKET", "percus-data")
        version = os.getenv("R2_VERSION", "v2")
        return R2SyncService(manifest, bucket, version=version)
    except Exception as e:
        logger.warning(f"Failed to init R2 sync service for logs: {e}")
        return None


def _upload_log_file_to_r2(r2: "R2SyncService", local_path: Path, job_id: str) -> bool:
    try:
        prefix = f"{r2.version}/" if r2.version else ""
        key = f"{prefix}training_logs/{job_id}/{local_path.name}"
        r2.s3.upload_file(str(local_path), r2.bucket, key)
        return True
    except Exception as e:
        logger.warning(f"Failed to upload log to R2: {e}")
        return False


async def _upload_remote_logs_to_r2(conn: SSHConnection, job_data: dict) -> None:
    r2 = _get_logs_r2_sync_service()
    if not r2:
        return
    job_id = job_data.get("job_id") or job_data.get("id")
    if not job_id:
        return
    remote_base_dir = job_data.get("remote_base_dir", "/root/.physical-ai")
    remote_run_dir = f"{remote_base_dir}/run"
    job_data["log_r2_prefix"] = f"training_logs/{job_id}/"
    await _save_job(job_data)

    for log_type in ("setup", "training"):
        log_name = _get_log_file_name(job_data, log_type)
        remote_path = f"{remote_run_dir}/{log_name}"
        local_path = Path("/tmp") / f"{job_id}_{log_name}"
        try:
            conn.download_file(remote_path, local_path)
        except Exception as e:
            logger.warning(f"Failed to download log {remote_path}: {e}")
            continue
        _upload_log_file_to_r2(r2, local_path, job_id)
        try:
            local_path.unlink()
        except Exception:
            pass


def _tail_text_lines(text: str, lines: int) -> str:
    if lines <= 0:
        return ""
    parts = text.splitlines()
    if len(parts) <= lines:
        return "\n".join(parts) + ("\n" if text.endswith("\n") else "")
    return "\n".join(parts[-lines:]) + "\n"


def _get_logs_from_r2(job_data: dict, lines: int, log_type: str) -> Optional[str]:
    r2 = _get_logs_r2_sync_service()
    if not r2:
        return None
    job_id = job_data.get("job_id") or job_data.get("id")
    if not job_id:
        return None
    log_name = _get_log_file_name(job_data, log_type)
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_logs/{job_id}/{log_name}"
    try:
        obj = r2.s3.client.get_object(Bucket=r2.bucket, Key=key)
        body = obj["Body"].read().decode("utf-8", errors="replace")
        return _tail_text_lines(body, lines)
    except Exception as e:
        logger.warning(f"Failed to fetch log from R2: {e}")
        return None


async def _get_logs_from_r2_async(
    job_data: dict,
    lines: int,
    log_type: str,
) -> Optional[str]:
    return await asyncio.to_thread(_get_logs_from_r2, job_data, lines, log_type)


def _get_full_logs_from_r2(job_data: dict, log_type: str) -> Optional[str]:
    r2 = _get_logs_r2_sync_service()
    if not r2:
        return None
    job_id = job_data.get("job_id") or job_data.get("id")
    if not job_id:
        return None
    log_name = _get_log_file_name(job_data, log_type)
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_logs/{job_id}/{log_name}"
    try:
        obj = r2.s3.client.get_object(Bucket=r2.bucket, Key=key)
        return obj["Body"].read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Failed to fetch full log from R2: {e}")
        return None


async def _get_full_logs_from_r2_async(
    job_data: dict,
    log_type: str,
) -> Optional[str]:
    return await asyncio.to_thread(_get_full_logs_from_r2, job_data, log_type)


def _check_logs_in_r2(job_data: dict, log_type: str) -> dict:
    r2 = _get_logs_r2_sync_service()
    job_id = job_data.get("job_id") or job_data.get("id")
    if not r2 or not job_id:
        return {"exists": False, "key": None, "error": "r2_unavailable"}
    log_name = _get_log_file_name(job_data, log_type)
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_logs/{job_id}/{log_name}"
    try:
        r2.s3.client.head_object(Bucket=r2.bucket, Key=key)
        return {"exists": True, "key": key, "error": None}
    except Exception as e:
        return {"exists": False, "key": key, "error": str(e)}


async def _check_logs_in_r2_async(job_data: dict, log_type: str) -> dict:
    return await asyncio.to_thread(_check_logs_in_r2, job_data, log_type)


async def _get_remote_progress(job_id: str) -> Optional[dict]:
    """Get training progress from Supabase metrics."""
    async def _fetch_with(client: AsyncClient) -> list[dict]:
        response = (
            await client.table("training_job_metrics")
            .select("step,loss,metrics")
            .eq("job_id", job_id)
            .eq("split", "train")
            .order("step", desc=True)
            .limit(1)
            .execute()
        )
        return response.data or []

    data = await _with_training_service_role_retry(
        action="loading remote progress for training job",
        target=job_id,
        operation=_fetch_with,
    )
    if not data:
        return None
    latest = data[0]
    step = latest.get("step")
    loss = latest.get("loss")
    return {
        "step": str(step) if step is not None else "N/A",
        "loss": str(loss) if loss is not None else "N/A",
    }


async def _get_latest_metric(job_id: str, split: str) -> Optional[dict]:
    async def _fetch_with(client: AsyncClient) -> list[dict]:
        response = (
            await client.table("training_job_metrics")
            .select("step,loss,ts,metrics")
            .eq("job_id", job_id)
            .eq("split", split)
            .order("step", desc=True)
            .limit(1)
            .execute()
        )
        return response.data or []

    data = await _with_training_service_role_retry(
        action=f"loading latest {split} metrics for training job",
        target=job_id,
        operation=_fetch_with,
    )
    if not data:
        return None
    return data[0]


async def _get_latest_metrics(job_id: str) -> tuple[Optional[dict], Optional[dict]]:
    train_metric, val_metric = await asyncio.gather(
        _get_latest_metric(job_id, "train"),
        _get_latest_metric(job_id, "val"),
    )
    return train_metric, val_metric


async def _get_metrics_series(job_id: str, split: str, limit: int) -> list[dict]:
    async def _fetch_with(client: AsyncClient) -> list[dict]:
        response = (
            await client.table("training_job_metrics")
            .select("step,loss,ts")
            .eq("job_id", job_id)
            .eq("split", split)
            .order("step", desc=False)
            .limit(limit)
            .execute()
        )
        return response.data or []

    return await _with_training_service_role_retry(
        action=f"loading {split} metric series for training job",
        target=job_id,
        operation=_fetch_with,
    )


def _stop_remote_job(job_data: dict) -> bool:
    """Stop remote training job via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return False

    try:
        conn.exec_command(
            f"tmux kill-session -t {TMUX_SETUP_SESSION_NAME} 2>/dev/null || true"
        )
        conn.exec_command(
            f"tmux kill-session -t {TMUX_TRAIN_SESSION_NAME} 2>/dev/null || true"
        )
        return True
    except Exception:
        return False
    finally:
        conn.disconnect()


def _terminate_job_instance(job_data: dict) -> tuple[bool, str]:
    """Terminate the cloud instance associated with a job without deleting the job record."""
    instance_id = str(job_data.get("instance_id") or "").strip()
    if not instance_id:
        return False, "No instance associated with this job"

    current_status = _check_instance_status(job_data)
    if current_status is None:
        return True, "Instance already deleted"
    if _is_terminated_instance_status(current_status):
        return True, f"Instance already stopped ({current_status})"

    provider = _get_job_provider(job_data)
    if provider == "vast":
        from percus_ai.training.providers.vast import destroy_instance

        try:
            destroy_instance(instance_id)
        except Exception as exc:
            logger.warning("Failed to delete Vast instance %s: %s", instance_id, exc)
            return False, f"Failed to stop instance: {exc}"
        return True, "Instance stopped"

    if not _delete_verda_instance(instance_id):
        return False, "Failed to stop instance"
    return True, "Instance stopped"


# --- API Endpoints ---


# Known GPU models to check (in priority order)
GPU_MODELS_QUICK = ["B300", "B200", "H200", "H100", "A100"]
GPU_COUNTS_QUICK = [1]  # Only check count=1 for speed
KNOWN_LOCATIONS = ["FIN-01", "FIN-02", "FIN-03", "ICE-01"]

# Cache for GPU availability (TTL: 10 minutes)
_gpu_availability_cache: dict = {}
_gpu_availability_cache_time: dict[str, float] = {}
_GPU_CACHE_TTL = 600  # 10 minutes
_instance_candidates_cache: dict[str, list[TrainingInstanceCandidate]] = {}
_instance_candidates_cache_time: dict[str, float] = {}
_INSTANCE_CANDIDATES_CACHE_TTL = 60


def _extract_availability_entry(item: object) -> tuple[Optional[str], list[str]]:
    if not isinstance(item, dict):
        return None, []

    location_code_raw = item.get("location_code") or item.get("locationCode")
    location_code = (
        location_code_raw
        if isinstance(location_code_raw, str) and location_code_raw
        else None
    )

    availabilities = item.get("availabilities")
    if not isinstance(availabilities, list):
        return location_code, []

    instance_types = [
        instance_type
        for instance_type in availabilities
        if isinstance(instance_type, str) and instance_type
    ]
    return location_code, instance_types


def _extract_gpu_model(instance_type: str) -> str:
    prefix = instance_type.split(".", 1)[0]
    idx = 0
    while idx < len(prefix) and prefix[idx].isdigit():
        idx += 1
    return prefix[idx:] or prefix


def _build_quick_configs(
    instance_types: list[object],
) -> list[tuple[str, int, str, Optional[float]]]:
    configs_to_check = []
    for gpu_model in GPU_MODELS_QUICK:
        for gpu_count in GPU_COUNTS_QUICK:
            for item in instance_types:
                instance_type = getattr(item, "instance_type", None)
                if not isinstance(instance_type, str):
                    continue

                count = _extract_gpu_count(instance_type)
                if count is None:
                    continue

                if count == gpu_count and gpu_model.upper() in instance_type.upper():
                    spot_price = getattr(item, "spot_price_per_hour", None)
                    configs_to_check.append(
                        (gpu_model, gpu_count, instance_type, spot_price)
                    )
                    break

    return configs_to_check


def _build_all_configs(
    instance_types: list[object],
) -> list[tuple[str, int, str, Optional[float]]]:
    configs_to_check: list[tuple[str, int, str, Optional[float]]] = []

    for item in instance_types:
        instance_type = getattr(item, "instance_type", None)
        if not isinstance(instance_type, str) or not instance_type:
            continue

        gpu_count = _extract_gpu_count(instance_type)
        if gpu_count is None or gpu_count <= 0:
            continue

        gpu_model = _extract_gpu_model(instance_type)
        if not gpu_model or gpu_model.upper() == "CPU":
            continue

        spot_price = getattr(item, "spot_price_per_hour", None)
        configs_to_check.append((gpu_model, gpu_count, instance_type, spot_price))

    configs_to_check.sort(key=lambda item: (item[0], item[1], item[2]))
    return configs_to_check


def _ordered_availability_locations(
    preferred_locations: list[str],
    *availability_maps: dict[str, set[str]],
) -> list[str]:
    known = []
    for location in preferred_locations:
        if location not in known:
            known.append(location)

    extras = sorted(
        {
            location
            for availability_map in availability_maps
            for location in availability_map
            if location not in known
        }
    )
    return known + extras


def _get_location_codes(client: VerdaClient) -> list[str]:
    try:
        items = client.locations.get() or []
    except Exception:
        return list(KNOWN_LOCATIONS)

    codes = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if isinstance(code, str) and code:
            codes.append(code)

    return codes or list(KNOWN_LOCATIONS)


def _fetch_availability_sets(
    client: VerdaClient,
    preferred_locations: list[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    spot_available_by_loc = {loc: set() for loc in preferred_locations}
    ondemand_available_by_loc = {loc: set() for loc in preferred_locations}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(client.instances.get_availabilities, True, None): True,
            executor.submit(client.instances.get_availabilities, False, None): False,
        }

        for future in as_completed(futures, timeout=30):
            is_spot = futures[future]
            try:
                items = future.result() or []
            except Exception:
                continue
            target = spot_available_by_loc if is_spot else ondemand_available_by_loc
            for item in items:
                location_code, instance_types = _extract_availability_entry(item)
                if (
                    not location_code
                    or location_code not in preferred_locations
                    or not instance_types
                ):
                    continue

                target.setdefault(location_code, set()).update(instance_types)

    return spot_available_by_loc, ondemand_available_by_loc


def _coerce_float(value: object) -> Optional[float]:
    try:
        parsed = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _extract_vast_offer_id(offer: dict) -> Optional[int]:
    raw = offer.get("id") or offer.get("offer_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _extract_vast_offer_price(offer: dict) -> Optional[float]:
    for key in ("dph_total", "discounted_dph_total", "dph", "min_bid"):
        value = _coerce_float(offer.get(key))
        if value is not None:
            return value
    return None


def _format_verda_candidate_detail(instance_type: str, location: str) -> str:
    del location
    suffix = instance_type.split(".", 1)[1] if "." in instance_type else instance_type
    suffix = suffix.replace(".", " ")
    return suffix


def _coerce_resource_float(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _read_mapping_value(container: object, key: str) -> object:
    if isinstance(container, dict):
        return container.get(key)
    return getattr(container, key, None)


def _extract_nested_number(container: object, keys: tuple[str, ...]) -> Optional[float]:
    if container is None:
        return None
    if isinstance(container, (int, float, str)):
        return _coerce_resource_float(container)
    for key in keys:
        value = _read_mapping_value(container, key)
        coerced = _coerce_resource_float(value)
        if coerced is not None:
            return coerced
    return None


def _normalize_gb_value(value: Optional[float]) -> Optional[float]:
    if value is None or value <= 0:
        return None
    return round(value, 1)


def _extract_verda_candidate_resources(instance_type_item: object) -> tuple[Optional[float], Optional[float], Optional[float]]:
    gpu_memory_total = _extract_nested_number(
        getattr(instance_type_item, "gpu_memory", None),
        ("size_in_gigabytes", "value", "size", "gb", "memory", "amount"),
    )
    gpu_count = _extract_nested_number(
        getattr(instance_type_item, "gpu", None),
        ("number_of_gpus", "count", "cores", "core_count", "vcpus", "value"),
    )
    cpu_cores = _extract_nested_number(
        getattr(instance_type_item, "cpu", None),
        ("number_of_cores", "count", "cores", "core_count", "vcpus", "value"),
    )
    system_memory = _extract_nested_number(
        getattr(instance_type_item, "memory", None) or getattr(instance_type_item, "ram", None),
        ("size_in_gigabytes", "value", "size", "gb", "memory", "amount"),
    )
    gpu_memory = gpu_memory_total
    if gpu_memory_total is not None and gpu_count and gpu_count > 0:
        gpu_memory = gpu_memory_total / gpu_count
    return _normalize_gb_value(gpu_memory), cpu_cores, _normalize_gb_value(system_memory)


def _extract_vast_candidate_resources(offer: dict, gpu_count: int) -> tuple[Optional[float], Optional[float], Optional[float]]:
    gpu_ram_total = _coerce_float(offer.get("gpu_ram"))
    gpu_memory = None
    if gpu_ram_total is not None and gpu_count > 0:
        gpu_memory = _normalize_gb_value((gpu_ram_total / 1024.0) / gpu_count)
    cpu_cores = _coerce_float(offer.get("cpu_cores_effective")) or _coerce_float(offer.get("cpu_cores"))
    system_memory_raw = _coerce_float(offer.get("cpu_ram")) or _coerce_float(offer.get("ram"))
    system_memory = _normalize_gb_value((system_memory_raw / 1024.0) if system_memory_raw is not None else None)
    return gpu_memory, cpu_cores, system_memory


def _format_candidate_resources(
    gpu_memory_gb: Optional[float],
    cpu_cores: Optional[float],
    system_memory_gb: Optional[float],
) -> str:
    parts: list[str] = []
    if gpu_memory_gb is not None:
        gpu_memory_text = str(int(gpu_memory_gb)) if float(gpu_memory_gb).is_integer() else f"{gpu_memory_gb:.1f}"
        parts.append(f"{gpu_memory_text}GB VRAM")
    if cpu_cores is not None:
        cpu_text = str(int(cpu_cores)) if float(cpu_cores).is_integer() else f"{cpu_cores:.1f}"
        parts.append(f"{cpu_text} vCPU")
    if system_memory_gb is not None:
        memory_text = (
            str(int(system_memory_gb))
            if float(system_memory_gb).is_integer()
            else f"{system_memory_gb:.1f}"
        )
        parts.append(f"{memory_text}GB RAM")
    return " / ".join(parts)


def _format_vast_candidate_title(offer: dict, gpu_model: str, gpu_count: int, offer_id: int) -> str:
    del offer
    del offer_id
    return f"{gpu_model} x{gpu_count}" if gpu_count > 0 else gpu_model


def _format_vast_candidate_detail(offer: dict) -> str:
    region = str(
        offer.get("geolocation")
        or offer.get("region")
        or offer.get("location")
        or ""
    ).strip()
    parts: list[str] = []
    if region:
        parts.append(region)
    return " / ".join(parts)


def _build_verda_instance_candidates(
    client: VerdaClient,
    gpu_model: Optional[str],
    gpu_count: Optional[int],
    mode: Optional[str],
    storage_size: Optional[int],
) -> list[TrainingInstanceCandidate]:
    instance_types = client.instance_types.get()
    preferred_locations = _get_location_codes(client)
    configs_to_check = _build_all_configs(instance_types)
    spot_available_by_loc, ondemand_available_by_loc = _fetch_availability_sets(
        client, preferred_locations
    )
    availability_locations = _ordered_availability_locations(
        preferred_locations,
        spot_available_by_loc,
        ondemand_available_by_loc,
    )

    gpu_model_normalized = str(gpu_model or "").strip().upper()
    requested_mode = str(mode or "").strip().lower() or None
    candidates: list[TrainingInstanceCandidate] = []
    seen_ids: set[str] = set()

    for item_gpu_model, item_gpu_count, instance_type, spot_price in configs_to_check:
        if gpu_model_normalized and item_gpu_model.upper() != gpu_model_normalized:
            continue
        if gpu_count is not None and item_gpu_count != gpu_count:
            continue

        for candidate_mode, available_map in (
            ("spot", spot_available_by_loc),
            ("ondemand", ondemand_available_by_loc),
        ):
            if requested_mode and candidate_mode != requested_mode:
                continue
            locations = [
                loc
                for loc in availability_locations
                if instance_type in available_map.get(loc, set())
            ]
            if not locations:
                continue
            location = locations[0]
            candidate_id = f"verda:{instance_type}:{candidate_mode}:{location}"
            if candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)

            ondemand_price = None
            matched_type = None
            if candidate_mode == "ondemand":
                matched_type = next(
                    (t for t in instance_types if getattr(t, "instance_type", None) == instance_type),
                    None,
                )
                ondemand_price = _coerce_float(getattr(matched_type, "price_per_hour", None))
            else:
                matched_type = next(
                    (t for t in instance_types if getattr(t, "instance_type", None) == instance_type),
                    None,
                )

            gpu_memory_gb, cpu_cores, system_memory_gb = _extract_verda_candidate_resources(matched_type)
            detail = _format_candidate_resources(gpu_memory_gb, cpu_cores, system_memory_gb)

            candidates.append(
                TrainingInstanceCandidate(
                    provider="verda",
                    candidate_id=candidate_id,
                    title=instance_type,
                    instance_type=instance_type,
                    gpu_model=item_gpu_model,
                    gpu_count=item_gpu_count,
                    mode=candidate_mode,
                    route=location,
                    location=location,
                    price_per_hour=spot_price if candidate_mode == "spot" else ondemand_price,
                    detail=detail or _format_verda_candidate_detail(instance_type, location),
                    storage_gb=storage_size,
                    gpu_memory_gb=gpu_memory_gb,
                    cpu_cores=cpu_cores,
                    system_memory_gb=system_memory_gb,
                )
            )

    return candidates


def _build_vast_instance_candidates(
    gpu_model: Optional[str],
    gpu_count: Optional[int],
    mode: Optional[str],
    storage_size: Optional[int],
    max_price: Optional[float],
) -> list[TrainingInstanceCandidate]:
    from percus_ai.training.providers.vast import search_offers_minimal

    requested_mode = str(mode or "").strip().lower()
    mode_filters = [requested_mode] if requested_mode in {"spot", "ondemand"} else ["spot", "ondemand"]

    models = [str(gpu_model).strip()] if str(gpu_model or "").strip() else [
        "B300",
        "B200",
        "H200",
        "H100",
        "A100",
        "L40S",
        "RTX6000ADA",
        "RTXA6000",
    ]
    counts = [gpu_count] if gpu_count is not None else [1, 2, 4, 8]
    disk_gb = max(10, int(storage_size or 120))

    ranked: list[tuple[float, TrainingInstanceCandidate]] = []
    for model_name in models:
        for count_value in counts:
            for mode_filter in mode_filters:
                offers = search_offers_minimal(
                    gpu_model=model_name,
                    gpu_count=count_value,
                    interruptible=mode_filter == "spot",
                    max_price=max_price,
                    min_disk_gb=disk_gb,
                    limit=40,
                )
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    offer_id = _extract_vast_offer_id(offer)
                    if offer_id is None:
                        continue
                    disk_space = _coerce_float(offer.get("disk_space"))
                    if disk_space is not None and disk_space < disk_gb:
                        continue
                    price = _extract_vast_offer_price(offer)
                    gpu_memory_gb, cpu_cores, system_memory_gb = _extract_vast_candidate_resources(offer, count_value)
                    detail = _format_candidate_resources(gpu_memory_gb, cpu_cores, system_memory_gb)
                    route = _format_vast_candidate_detail(offer)
                    candidate = TrainingInstanceCandidate(
                        provider="vast",
                        candidate_id=f"vast:{offer_id}",
                        title=_format_vast_candidate_title(offer, model_name, count_value, offer_id),
                        offer_id=offer_id,
                        gpu_model=model_name,
                        gpu_count=count_value,
                        mode=mode_filter,
                        route=route or ("Interruptible" if mode_filter == "spot" else "オンデマンド"),
                        location=None,
                        price_per_hour=price,
                        detail=detail,
                        storage_gb=disk_gb,
                        gpu_memory_gb=gpu_memory_gb,
                        cpu_cores=cpu_cores,
                        system_memory_gb=system_memory_gb,
                    )
                    ranked.append((price if price is not None else float("inf"), candidate))

    ranked.sort(key=lambda item: (item[0], item[1].offer_id or 0))
    return [candidate for _, candidate in ranked]


@router.get("/provider-capabilities", response_model=TrainingProviderCapabilityResponse)
def get_training_provider_capabilities():
    """Return cloud provider availability for training UI."""
    missing_vast_env = _missing_vast_env_vars()
    return TrainingProviderCapabilityResponse(
        verda_enabled=_get_verda_client() is not None,
        vast_enabled=len(missing_vast_env) == 0,
        missing_vast_env=missing_vast_env,
    )


@router.get("/instance-candidates", response_model=TrainingInstanceCandidatesResponse)
def get_instance_candidates(
    provider: str = Query(..., pattern="^(verda|vast)$"),
    gpu_model: Optional[str] = None,
    gpu_count: Optional[int] = Query(None, ge=1, le=8),
    mode: Optional[str] = Query(None, pattern="^(spot|ondemand)$"),
    storage_size: Optional[int] = Query(None, ge=10, le=5000),
    max_price: Optional[float] = Query(None, ge=0),
):
    """Return selectable concrete instance candidates for the training UI."""
    global _instance_candidates_cache, _instance_candidates_cache_time

    gpu_model_key = str(gpu_model or "").strip().upper()
    cache_key = (
        f"instance_candidates:{provider}:"
        f"{gpu_model_key or 'any'}:{gpu_count or 'any'}:{mode or 'any'}:{storage_size or 'any'}:{max_price or 'any'}"
    )
    cache_time = _instance_candidates_cache_time.get(cache_key, 0.0)
    if (
        time.time() - cache_time < _INSTANCE_CANDIDATES_CACHE_TTL
        and cache_key in _instance_candidates_cache
    ):
        return TrainingInstanceCandidatesResponse(
            candidates=_instance_candidates_cache[cache_key],
            checked_at=datetime.fromtimestamp(cache_time),
        )

    try:
        if provider == "verda":
            client = _get_verda_client()
            if not client:
                raise HTTPException(
                    status_code=503,
                    detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
                )
            candidates = _build_verda_instance_candidates(
                client=client,
                gpu_model=gpu_model_key or None,
                gpu_count=gpu_count,
                mode=mode,
                storage_size=storage_size,
            )
        else:
            _assert_provider_configured(provider)
            candidates = _build_vast_instance_candidates(
                gpu_model=gpu_model_key or None,
                gpu_count=gpu_count,
                mode=mode,
                storage_size=storage_size,
                max_price=max_price,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to build %s instance candidates", provider)
        raise HTTPException(status_code=503, detail=f"候補取得に失敗: {exc}") from exc

    _instance_candidates_cache[cache_key] = candidates
    _instance_candidates_cache_time[cache_key] = time.time()
    return TrainingInstanceCandidatesResponse(candidates=candidates)


@router.get("/gpu-availability", response_model=GpuAvailabilityResponse)
def get_gpu_availability(
    provider: str = Query(..., pattern="^(verda|vast)$"),
    scan: Literal["quick", "all"] = "all",
):
    """Check GPU availability.

    scan="quick": checks main configurations only (B300, B200, H200, H100, A100 x1)
    scan="all": checks all GPU instance types and all locations
    """
    global _gpu_availability_cache, _gpu_availability_cache_time

    cache_key = f"gpu_availability:{provider}:{scan}"
    should_use_cache = True

    # Check cache
    cache_time = _gpu_availability_cache_time.get(cache_key, 0.0)
    if (
        should_use_cache
        and time.time() - cache_time < _GPU_CACHE_TTL
        and cache_key in _gpu_availability_cache
    ):
        return GpuAvailabilityResponse(
            available=_gpu_availability_cache[cache_key],
            checked_at=datetime.fromtimestamp(cache_time),
        )

    available: list[GpuAvailabilityInfo] = []

    if provider == "verda":
        client = _get_verda_client()
        if not client:
            raise HTTPException(
                status_code=503,
                detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
            )
        try:
            instance_types = client.instance_types.get()

            if scan == "all":
                preferred_locations = _get_location_codes(client)
                configs_to_check = _build_all_configs(instance_types)
            else:
                preferred_locations = list(KNOWN_LOCATIONS)
                configs_to_check = _build_quick_configs(instance_types)

            spot_available_by_loc, ondemand_available_by_loc = _fetch_availability_sets(
                client, preferred_locations
            )

            availability_locations = _ordered_availability_locations(
                preferred_locations,
                spot_available_by_loc,
                ondemand_available_by_loc,
            )

            for gpu_model, gpu_count, instance_type, spot_price in configs_to_check:
                spot_locs = [
                    loc
                    for loc in availability_locations
                    if instance_type in spot_available_by_loc.get(loc, set())
                ]
                ondemand_locs = [
                    loc
                    for loc in availability_locations
                    if instance_type in ondemand_available_by_loc.get(loc, set())
                ]
                available.append(
                    GpuAvailabilityInfo(
                        gpu_model=gpu_model,
                        gpu_count=gpu_count,
                        instance_type=instance_type,
                        spot_available=len(spot_locs) > 0,
                        ondemand_available=len(ondemand_locs) > 0,
                        spot_locations=spot_locs,
                        ondemand_locations=ondemand_locs,
                        spot_price_per_hour=spot_price,
                    )
                )

        except Exception as e:
            logger.exception("Failed to check Verda GPU availability")
            raise HTTPException(status_code=503, detail=f"GPU空き状況の確認に失敗: {e}")

    else:
        _assert_provider_configured(provider)
        from percus_ai.training.providers.vast import search_offers_minimal

        gpu_models = ["B300", "B200", "H200", "H100", "A100", "L40S", "RTX6000ADA", "RTXA6000"]
        gpu_counts = [1, 2, 4, 8]
        if scan == "quick":
            combos = [(m, 1) for m in gpu_models[:5]]
        else:
            combos = [(m, c) for m in gpu_models for c in gpu_counts]

        try:
            for model, count in combos:
                spot_offers = search_offers_minimal(
                    gpu_model=model,
                    gpu_count=count,
                    interruptible=True,
                    max_price=None,
                    limit=1,
                )
                ondemand_offers = search_offers_minimal(
                    gpu_model=model,
                    gpu_count=count,
                    interruptible=False,
                    max_price=None,
                    limit=1,
                )
                spot_price = None
                if spot_offers:
                    dph = spot_offers[0].get("dph") if isinstance(spot_offers[0], dict) else None
                    try:
                        spot_price = float(dph) if dph is not None else None
                    except (TypeError, ValueError):
                        spot_price = None
                available.append(
                    GpuAvailabilityInfo(
                        gpu_model=model,
                        gpu_count=count,
                        instance_type=f"vast:{model}x{count}",
                        spot_available=bool(spot_offers),
                        ondemand_available=bool(ondemand_offers),
                        spot_locations=[],
                        ondemand_locations=[],
                        spot_price_per_hour=spot_price,
                    )
                )
        except Exception as e:
            logger.exception("Failed to check Vast GPU availability")
            raise HTTPException(status_code=503, detail=f"GPU空き状況の確認に失敗: {e}")

    if should_use_cache:
        _gpu_availability_cache[cache_key] = available
        _gpu_availability_cache_time[cache_key] = time.time()

    return GpuAvailabilityResponse(available=available)


@router.get("/verda/storage", response_model=VerdaStorageListResponse)
async def list_verda_storage():
    """List Verda storage volumes (active + deleted)."""
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes")
        raise HTTPException(
            status_code=502, detail=f"Verda APIに接続できません: {e}"
        ) from e

    items = [
        _build_verda_storage_item(volume, state)
        for _, (state, volume) in volumes_by_id.items()
        if getattr(volume, "id", "")
    ]
    items.sort(key=lambda item: (item.state != "deleted", item.created_at or ""))
    return VerdaStorageListResponse(items=items, total=len(items))


@router.post("/verda/storage/delete", response_model=VerdaStorageActionResult)
async def delete_verda_storage(request: VerdaStorageActionRequest):
    """Delete Verda storage volumes (logical delete)."""
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    logger.info(f"Verda storage delete requested: {request.volume_ids}")
    result = VerdaStorageActionResult()
    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes for delete")
        raise HTTPException(
            status_code=502, detail=f"Verda APIに接続できません: {e}"
        ) from e

    eligible_ids: list[str] = []
    for volume_id in request.volume_ids:
        state_volume = volumes_by_id.get(volume_id)
        if not state_volume:
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="対象が見つかりません（既に削除済みの可能性）",
                )
            )
            continue

        state, _ = state_volume
        if state != "active":
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="既に削除済みのストレージです",
                )
            )
            continue

        eligible_ids.append(volume_id)

    for chunk in _chunk_list(eligible_ids):
        try:
            client.volumes.delete(chunk, is_permanent=False)
            result.success_ids.extend(chunk)
        except Exception as e:
            logger.exception(f"Failed to delete volume chunk: {chunk}")
            for volume_id in chunk:
                result.failed.append(
                    VerdaStorageActionFailure(
                        id=volume_id,
                        reason=str(e),
                    )
                )

    logger.info(
        "Verda storage delete result: success=%s failed=%s skipped=%s",
        len(result.success_ids),
        len(result.failed),
        len(result.skipped),
    )
    return result


@router.post("/verda/storage/restore", response_model=VerdaStorageActionResult)
async def restore_verda_storage(request: VerdaStorageActionRequest):
    """Restore Verda storage volumes from trash."""
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    logger.info(f"Verda storage restore requested: {request.volume_ids}")
    result = VerdaStorageActionResult()
    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes for restore")
        raise HTTPException(
            status_code=502, detail=f"Verda APIに接続できません: {e}"
        ) from e

    eligible_ids: list[str] = []
    for volume_id in request.volume_ids:
        state_volume = volumes_by_id.get(volume_id)
        if not state_volume:
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="対象が見つかりません（既に削除済みの可能性）",
                )
            )
            continue

        state, _ = state_volume
        if state != "deleted":
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="削除済みではありません",
                )
            )
            continue

        eligible_ids.append(volume_id)

    for chunk in _chunk_list(eligible_ids):
        try:
            _restore_verda_volumes(client, chunk)
            result.success_ids.extend(chunk)
        except Exception as e:
            logger.exception(f"Failed to restore volume chunk: {chunk}")
            for volume_id in chunk:
                result.failed.append(
                    VerdaStorageActionFailure(
                        id=volume_id,
                        reason=str(e),
                    )
                )

    logger.info(
        "Verda storage restore result: success=%s failed=%s skipped=%s",
        len(result.success_ids),
        len(result.failed),
        len(result.skipped),
    )
    return result


@router.post("/verda/storage/purge", response_model=VerdaStorageActionResult)
async def purge_verda_storage(request: VerdaStorageActionRequest):
    """Permanently delete Verda storage volumes from trash."""
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    logger.info(f"Verda storage purge requested: {request.volume_ids}")
    result = VerdaStorageActionResult()
    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes for purge")
        raise HTTPException(
            status_code=502, detail=f"Verda APIに接続できません: {e}"
        ) from e

    eligible_ids: list[str] = []
    for volume_id in request.volume_ids:
        state_volume = volumes_by_id.get(volume_id)
        if not state_volume:
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="対象が見つかりません（既に削除済みの可能性）",
                )
            )
            continue

        state, _ = state_volume
        if state != "deleted":
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="削除済みではありません",
                )
            )
            continue

        eligible_ids.append(volume_id)

    for chunk in _chunk_list(eligible_ids):
        try:
            client.volumes.delete(chunk, is_permanent=True)
            result.success_ids.extend(chunk)
        except Exception as e:
            logger.exception(f"Failed to purge volume chunk: {chunk}")
            for volume_id in chunk:
                result.failed.append(
                    VerdaStorageActionFailure(
                        id=volume_id,
                        reason=str(e),
                    )
                )

    logger.info(
        "Verda storage purge result: success=%s failed=%s skipped=%s",
        len(result.success_ids),
        len(result.failed),
        len(result.skipped),
    )
    return result


@router.get("/vast/storage", response_model=VastStorageListResponse)
async def list_vast_storage():
    """List Vast storage volumes."""
    _assert_provider_configured("vast")
    from percus_ai.training.providers.vast import list_volumes

    try:
        volumes = list_volumes(type_="all")
    except Exception as e:
        logger.exception("Failed to list Vast volumes")
        raise HTTPException(status_code=502, detail=f"Vast APIに接続できません: {e}") from e

    items = [
        VastStorageItem(
            id=v.volume_id,
            label=v.label,
            size_gb=v.size_gb,
            state=v.state,
            instance_id=v.instance_id,
        )
        for v in volumes
    ]
    return VastStorageListResponse(items=items, total=len(items))


@router.post("/vast/storage/delete", response_model=VastStorageActionResult)
async def delete_vast_storage(request: VastStorageActionRequest):
    """Delete Vast storage volumes."""
    _assert_provider_configured("vast")
    from percus_ai.training.providers.vast import delete_volumes

    result = VastStorageActionResult()
    failures: list[VerdaStorageActionFailure] = []
    success: list[str] = []

    for raw in request.volume_ids:
        vid = str(raw or "").strip()
        if not vid:
            continue
        try:
            delete_volumes([vid])
            success.append(vid)
        except Exception as e:
            failures.append(VerdaStorageActionFailure(id=vid, reason=str(e)))

    result.success_ids = success
    result.failed = failures
    return result


@router.websocket("/ws/gpu-availability")
async def websocket_gpu_availability(websocket: WebSocket):
    """Stream GPU availability check results in real-time.

    Each GPU result is sent as it becomes available:
    - {"type": "checking", "gpu_model": "H100", "message": "H100を確認中..."}
    - {"type": "result", "gpu_model": "H100", "gpu_count": 1, "spot_available": true, ...}
    - {"type": "complete", "message": "確認完了"}
    - {"type": "cached", "message": "キャッシュから取得"}
    """
    await websocket.accept()

    global _gpu_availability_cache, _gpu_availability_cache_time

    try:
        provider = websocket.query_params.get("provider", "").strip()
        if provider not in {"verda", "vast"}:
            await websocket.send_json({"type": "error", "error": "provider must be verda|vast"})
            await websocket.close()
            return
        try:
            _assert_provider_configured(provider)
        except HTTPException as exc:
            await websocket.send_json({"type": "error", "error": str(exc.detail)})
            await websocket.close()
            return
        scan = websocket.query_params.get("scan", "all")
        if scan not in {"quick", "all"}:
            scan = "all"
        cache_key = f"gpu_availability:{provider}:{scan}"
        should_use_cache = True

        # Check cache first
        cache_time = _gpu_availability_cache_time.get(cache_key, 0.0)
        if (
            should_use_cache
            and time.time() - cache_time < _GPU_CACHE_TTL
            and cache_key in _gpu_availability_cache
        ):
            await websocket.send_json(
                {"type": "cached", "message": "キャッシュから取得"}
            )
            for item in _gpu_availability_cache[cache_key]:
                await websocket.send_json(
                    {
                        "type": "result",
                        "gpu_model": item.gpu_model,
                        "gpu_count": item.gpu_count,
                        "spot_available": item.spot_available,
                        "ondemand_available": item.ondemand_available,
                    }
                )
            await websocket.send_json({"type": "complete", "message": "確認完了"})
            await websocket.close()
            return

        await websocket.send_json({"type": "start", "message": "GPU空き状況を確認中..."})

        loop = asyncio.get_event_loop()
        available: list[GpuAvailabilityInfo] = []

        if provider == "verda":
            client = _get_verda_client()
            if not client:
                await websocket.send_json(
                    {"type": "error", "error": "Verda認証情報が設定されていません"}
                )
                await websocket.close()
                return

            instance_types = await loop.run_in_executor(_executor, client.instance_types.get)
            if scan == "all":
                preferred_locations = await loop.run_in_executor(_executor, _get_location_codes, client)
                configs_to_check = _build_all_configs(instance_types)
            else:
                preferred_locations = list(KNOWN_LOCATIONS)
                configs_to_check = _build_quick_configs(instance_types)

                for gpu_model, _, _, _ in configs_to_check:
                    await websocket.send_json(
                    {"type": "checking", "gpu_model": gpu_model, "message": f"{gpu_model}を確認中..."}
                    )

            spot_available_by_loc, ondemand_available_by_loc = await loop.run_in_executor(
                _executor, _fetch_availability_sets, client, preferred_locations
            )
            availability_locations = _ordered_availability_locations(
                preferred_locations,
                spot_available_by_loc,
                ondemand_available_by_loc,
            )

            for gpu_model, gpu_count, instance_type, spot_price in configs_to_check:
                spot_locs = [
                    loc
                    for loc in availability_locations
                    if instance_type in spot_available_by_loc.get(loc, set())
                ]
                ondemand_locs = [
                    loc
                    for loc in availability_locations
                    if instance_type in ondemand_available_by_loc.get(loc, set())
                ]
                spot_available = len(spot_locs) > 0
                ondemand_available = len(ondemand_locs) > 0

                await websocket.send_json(
                    {
                        "type": "result",
                        "gpu_model": gpu_model,
                        "gpu_count": gpu_count,
                        "spot_available": spot_available,
                        "ondemand_available": ondemand_available,
                    }
                )

                available.append(
                    GpuAvailabilityInfo(
                        gpu_model=gpu_model,
                        gpu_count=gpu_count,
                        instance_type=instance_type,
                        spot_available=spot_available,
                        ondemand_available=ondemand_available,
                        spot_locations=spot_locs,
                        ondemand_locations=ondemand_locs,
                        spot_price_per_hour=spot_price,
                    )
                )

        else:
            from percus_ai.training.providers.vast import search_offers_minimal

            gpu_models = ["B300", "B200", "H200", "H100", "A100", "L40S", "RTX6000ADA", "RTXA6000"]
            gpu_counts = [1, 2, 4, 8]
            if scan == "quick":
                combos = [(m, 1) for m in gpu_models[:5]]
            else:
                combos = [(m, c) for m in gpu_models for c in gpu_counts]

            for model, count in combos:
                await websocket.send_json(
                    {"type": "checking", "gpu_model": model, "message": f"{model}を確認中..."}
                )
                spot_offers = await loop.run_in_executor(
                    _executor,
                    lambda: search_offers_minimal(
                        gpu_model=model,
                        gpu_count=count,
                        interruptible=True,
                        max_price=None,
                        limit=1,
                    ),
                )
                ondemand_offers = await loop.run_in_executor(
                    _executor,
                    lambda: search_offers_minimal(
                        gpu_model=model,
                        gpu_count=count,
                        interruptible=False,
                        max_price=None,
                        limit=1,
                    ),
                )
                spot_price = None
                if spot_offers:
                    dph = spot_offers[0].get("dph") if isinstance(spot_offers[0], dict) else None
                    try:
                        spot_price = float(dph) if dph is not None else None
                    except (TypeError, ValueError):
                        spot_price = None

                await websocket.send_json(
                    {
                        "type": "result",
                        "gpu_model": model,
                        "gpu_count": count,
                        "spot_available": bool(spot_offers),
                        "ondemand_available": bool(ondemand_offers),
                    }
                )
                available.append(
                    GpuAvailabilityInfo(
                        gpu_model=model,
                        gpu_count=count,
                        instance_type=f"vast:{model}x{count}",
                        spot_available=bool(spot_offers),
                        ondemand_available=bool(ondemand_offers),
                        spot_locations=[],
                        ondemand_locations=[],
                        spot_price_per_hour=spot_price,
                    )
                )

        # Update cache
        if should_use_cache:
            _gpu_availability_cache[cache_key] = available
            _gpu_availability_cache_time[cache_key] = time.time()

        await websocket.send_json({"type": "complete", "message": "確認完了"})

    except Exception as e:
        logger.exception("WebSocket GPU availability check failed")
        await websocket.send_json({"type": "error", "error": str(e)})

    await websocket.close()


@router.websocket("/ws/verda/storage")
async def websocket_verda_storage(websocket: WebSocket):
    """Run Verda storage actions with progress via WebSocket."""
    await websocket.accept()

    try:
        request = await websocket.receive_json()
    except Exception:
        await websocket.send_json({"type": "error", "error": "Invalid request"})
        await websocket.close()
        return

    action = request.get("action")
    volume_ids = request.get("volume_ids", [])
    if action not in ("delete", "restore", "purge"):
        await websocket.send_json({"type": "error", "error": "Unsupported action"})
        await websocket.close()
        return

    client = _get_verda_client()
    if not client:
        await websocket.send_json(
            {
                "type": "error",
                "error": "Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
            }
        )
        await websocket.close()
        return

    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes for WS action")
        await websocket.send_json(
            {"type": "error", "error": f"Verda APIに接続できません: {e}"}
        )
        await websocket.close()
        return

    required_state = "active" if action == "delete" else "deleted"
    is_permanent = action == "purge"

    skipped: list[dict] = []
    eligible_ids: list[str] = []
    for volume_id in volume_ids:
        state_volume = volumes_by_id.get(volume_id)
        if not state_volume:
            skipped.append(
                {
                    "id": volume_id,
                    "reason": "対象が見つかりません（既に削除済みの可能性）",
                }
            )
            continue
        state, _ = state_volume
        if state != required_state:
            skipped.append(
                {
                    "id": volume_id,
                    "reason": "削除済みではありません"
                    if required_state == "deleted"
                    else "既に削除済みのストレージです",
                }
            )
            continue
        eligible_ids.append(volume_id)

    total = len(volume_ids)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue()
    done_count = {"value": 0}
    done_lock = threading.Lock()

    def emit_progress(
        volume_id: str, status: str, reason: Optional[str] = None
    ) -> None:
        with done_lock:
            done_count["value"] += 1
            current = done_count["value"]
        payload = {
            "type": "progress",
            "id": volume_id,
            "status": status,
            "done": current,
            "total": total,
        }
        if reason:
            payload["reason"] = reason
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    loop.call_soon_threadsafe(
        queue.put_nowait,
        {"type": "start", "total": total, "eligible": len(eligible_ids)},
    )

    for item in skipped:
        emit_progress(item["id"], "skipped", item["reason"])

    def worker() -> None:
        result = {
            "success_ids": [],
            "failed": [],
            "skipped": skipped,
        }
        try:
            batch_action = "delete" if action == "purge" else action
            chunks = _chunk_list(eligible_ids, chunk_size=5)
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(
                        _perform_verda_volume_action_batch,
                        batch_action,
                        chunk,
                        is_permanent,
                    ): chunk
                    for chunk in chunks
                }
                for future in as_completed(futures):
                    chunk = futures[future]
                    try:
                        future.result()
                        result["success_ids"].extend(chunk)
                        for volume_id in chunk:
                            emit_progress(volume_id, "success")
                    except Exception as e:
                        reason = str(e)
                        for volume_id in chunk:
                            result["failed"].append({"id": volume_id, "reason": reason})
                            emit_progress(volume_id, "failed", reason)
        finally:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "complete", "result": result}
            )

    threading.Thread(target=worker, daemon=True).start()

    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("type") == "complete":
                break
    except WebSocketDisconnect:
        return
    finally:
        await websocket.close()


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    days: int = Query(365, ge=1, le=365),
    owner_user_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Search job name"),
    status: Optional[str] = Query(None, description="Filter by job status"),
    policy_type: Optional[str] = Query(None, description="Filter by policy type"),
    created_from: Optional[str] = Query(None, description="Created-at lower bound"),
    created_to: Optional[str] = Query(None, description="Created-at upper bound"),
    sort_by: JobListSortBy = Query("created_at", description="Sort field"),
    sort_order: SortOrder = Query("desc", description="Sort direction"),
    limit: Optional[int] = Query(None, ge=1, le=500, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
):
    """List training jobs.

    Args:
        days: Return jobs from past N days (running jobs always included)
    """
    jobs_data, total, owner_options, status_options, policy_options = await _list_jobs(
        days,
        owner_user_id=owner_user_id,
        search=search,
        status=status,
        policy_type=policy_type,
        created_from=created_from,
        created_to=created_to,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )

    def _coerce_jobinfo_fields(record: dict) -> dict:
        coerced = dict(record or {})
        # DB rows may contain explicit NULLs; Pydantic defaults don't apply if the key exists with None.
        if coerced.get("instance_id") is None:
            coerced["instance_id"] = ""
        if coerced.get("ssh_user") is None:
            coerced["ssh_user"] = "root"
        if coerced.get("ssh_private_key") is None:
            coerced["ssh_private_key"] = "~/.ssh/id_rsa"
        if coerced.get("remote_base_dir") is None:
            coerced["remote_base_dir"] = "/root/.physical-ai"
        if coerced.get("ssh_port") is None:
            cloud_cfg = (coerced.get("training_config") or {}).get("cloud") or {}
            cloud_port = cloud_cfg.get("ssh_port")
            if cloud_port is not None:
                coerced["ssh_port"] = cloud_port
        return coerced

    jobs = [JobInfo(**_coerce_jobinfo_fields(j)) for j in jobs_data]
    return JobListResponse(
        jobs=jobs,
        total=total,
        owner_options=owner_options,
        status_options=status_options,
        policy_options=policy_options,
    )


def _sanitize_training_config_for_restore(training_config: object) -> dict | None:
    if not isinstance(training_config, dict):
        return None

    restored = {
        "job_name": training_config.get("job_name"),
        "dataset": training_config.get("dataset"),
        "policy": training_config.get("policy"),
        "training": training_config.get("training"),
        "validation": training_config.get("validation"),
        "early_stopping": training_config.get("early_stopping"),
        "cloud": training_config.get("cloud"),
    }

    cloud_cfg = restored.get("cloud")
    if isinstance(cloud_cfg, dict):
        sanitized_cloud = dict(cloud_cfg)
        sanitized_cloud.pop("ssh_port", None)
        restored["cloud"] = sanitized_cloud

    return {key: value for key, value in restored.items() if value is not None}


@router.get("/jobs/last-config", response_model=LastTrainingConfigResponse)
async def get_last_training_config():
    """Return the current user's latest new-training config for form restoration."""
    user_id = get_current_user_id()

    async def _fetch_with(client: AsyncClient) -> dict | None:
        response = (
            await client.table(DB_TABLE)
            .select("job_id,job_name,created_at,training_config")
            .eq("owner_user_id", user_id)
            .eq("mode", "train")
            .is_("deleted_at", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        records = response.data or []
        return records[0] if records else None

    client = await get_supabase_async_client()
    try:
        record = await _fetch_with(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning("JWT expired while loading last training config; retrying with service key")
        record = await _fetch_with(service_client)

    if not record:
        return LastTrainingConfigResponse()

    return LastTrainingConfigResponse(
        job_id=record.get("job_id"),
        job_name=record.get("job_name"),
        created_at=_parse_job_created_at(record.get("created_at")) if record.get("created_at") else None,
        training_config=_sanitize_training_config_for_restore(record.get("training_config")),
    )


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str):
    """Get job details with remote status."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job_data.get("status") in ("running", "starting", "deploying"):
        await _refresh_job_status_from_instance(job_data)

    job_coerced = dict(job_data or {})
    if job_coerced.get("instance_id") is None:
        job_coerced["instance_id"] = ""
    if job_coerced.get("ssh_user") is None:
        job_coerced["ssh_user"] = "root"
    if job_coerced.get("ssh_private_key") is None:
        job_coerced["ssh_private_key"] = "~/.ssh/id_rsa"
    if job_coerced.get("remote_base_dir") is None:
        job_coerced["remote_base_dir"] = "/root/.physical-ai"
    if job_coerced.get("ssh_port") is None:
        cloud_cfg = (job_coerced.get("training_config") or {}).get("cloud") or {}
        cloud_port = cloud_cfg.get("ssh_port")
        if cloud_port is not None:
            job_coerced["ssh_port"] = cloud_port
    job = JobInfo(**job_coerced)
    remote_status = None
    progress = None
    summary = job_data.get("summary")
    early_stopping = job_data.get("early_stopping")
    training_config = job_data.get("training_config")
    if job.status in ("running", "starting", "deploying"):
        (
            (latest_train_metrics, latest_val_metrics),
            provision_operation,
            progress,
        ) = await asyncio.gather(
            _get_latest_metrics(job_id),
            _resolve_job_provision_operation(job_data),
            _get_remote_progress(job_id),
        )
    else:
        (latest_train_metrics, latest_val_metrics), provision_operation = await asyncio.gather(
            _get_latest_metrics(job_id),
            _resolve_job_provision_operation(job_data),
        )
    return JobDetailResponse(
        job=job,
        provision_operation=provision_operation,
        remote_status=remote_status,
        progress=progress,
        latest_train_metrics=latest_train_metrics,
        latest_val_metrics=latest_val_metrics,
        summary=summary,
        early_stopping=early_stopping,
        training_config=training_config,
    )


@router.get("/jobs/{job_id}/logs", response_model=JobLogsResponse)
async def get_job_logs(
    job_id: str,
    lines: int = Query(100, ge=1, le=10000),
    log_type: str = Query("training", pattern="^(training|setup)$"),
):
    """Get job logs from remote instance."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_status = None
    if job_data.get("status") in ("running", "starting", "deploying"):
        instance_status = await _refresh_job_status_from_instance(job_data)

    remote_allowed = True
    if instance_status is None or _is_terminated_instance_status(instance_status):
        remote_allowed = False

    source = "remote"
    logs = None
    if remote_allowed:
        logs = await _get_remote_logs_async(job_data, lines, log_type=log_type)
    if logs is None:
        source = "r2"
        logs = await _get_logs_from_r2_async(job_data, lines, log_type)
    if logs is None:
        raise HTTPException(
            status_code=503, detail="Could not connect to remote instance"
        )

    return JobLogsResponse(job_id=job_id, logs=logs, lines=lines, source=source)


@router.get(
    "/jobs/{job_id}/provision-operation",
    response_model=TrainingProvisionOperationStatusResponse,
)
async def get_job_provision_operation(job_id: str):
    """Resolve the active provision operation for a training job."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    snapshot = await _resolve_job_provision_operation(job_data)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Provision operation not found for job: {job_id}")
    return snapshot


@router.get("/jobs/{job_id}/logs/download", response_class=PlainTextResponse)
async def download_job_logs(
    job_id: str,
    log_type: str = Query("training", pattern="^(training|setup)$"),
):
    """Download full job logs as plain text."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_status = None
    if job_data.get("status") in ("running", "starting", "deploying"):
        instance_status = await _refresh_job_status_from_instance(job_data)

    remote_allowed = True
    if instance_status is None or _is_terminated_instance_status(instance_status):
        remote_allowed = False

    if _should_try_r2_first(job_data):
        logs = await _get_full_logs_from_r2_async(job_data, log_type)
        if logs is None and remote_allowed:
            logs = await _get_remote_log_file_async(job_data, log_type=log_type, timeout=30)
            if logs is None:
                logs = await _get_remote_logs_async(job_data, lines=5000, log_type=log_type)
    else:
        logs = None
        if remote_allowed:
            logs = await _get_remote_log_file_async(job_data, log_type=log_type, timeout=30)
            if logs is None:
                logs = await _get_remote_logs_async(job_data, lines=5000, log_type=log_type)
        if logs is None:
            logs = await _get_full_logs_from_r2_async(job_data, log_type)
    if logs is None:
        r2_status = await _check_logs_in_r2_async(job_data, log_type)
        raise HTTPException(
            status_code=503,
            detail=(
                "Log fetch failed. "
                f"r2_exists={r2_status.get('exists')} key={r2_status.get('key')}"
            ),
        )
    return logs


@router.get("/jobs/{job_id}/logs/status")
async def get_job_logs_status(
    job_id: str,
    log_type: str = Query("training", pattern="^(training|setup)$"),
):
    """Check whether logs exist on R2 for this job."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    r2_status = await _check_logs_in_r2_async(job_data, log_type)
    return {
        "job_id": job_id,
        "log_type": log_type,
        "r2": r2_status,
    }


@router.get("/jobs/{job_id}/progress", response_model=JobProgressResponse)
async def get_job_progress(job_id: str):
    """Get training progress for a job."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    progress = await _get_remote_progress(job_id)
    if progress is None:
        return JobProgressResponse(job_id=job_id)

    return JobProgressResponse(job_id=job_id, **progress)


@router.get("/jobs/{job_id}/metrics", response_model=JobMetricsResponse)
async def get_job_metrics(
    job_id: str,
    response: Response,
    limit: int = Query(1000, ge=1, le=10000),
):
    """Get training/validation loss series for a job."""
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    train, val = await asyncio.gather(
        _get_metrics_series(job_id, "train", limit),
        _get_metrics_series(job_id, "val", limit),
    )

    # Fallback to R2 archive if DB has no metrics for a terminal job
    from_archive = False
    if not train and not val and job_data.get("status") in (
        "completed", "stopped", "terminated", "failed",
    ):
        archived = await asyncio.to_thread(_get_metrics_from_r2, job_id)
        if archived:
            train = [m for m in archived if m.get("split") == "train"][:limit]
            val = [m for m in archived if m.get("split") == "val"][:limit]
            from_archive = True

    if from_archive:
        response.headers["Cache-Control"] = "public, max-age=86400, immutable"

    return JobMetricsResponse(job_id=job_id, train=train, val=val)


@router.get("/jobs/{job_id}/instance-status", response_model=InstanceStatusResponse)
async def get_instance_status(job_id: str):
    """Get detailed instance status from provider API.

    This endpoint checks the actual cloud instance status and optionally
    the remote training process status via SSH.
    """
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_id = job_data.get("instance_id")
    job_status = job_data.get("status", "unknown")
    ip = job_data.get("ip")

    provider = _get_job_provider(job_data)
    provider_display = provider.upper()

    # Check instance status via provider API
    instance_status = None
    message = ""

    if instance_id:
        instance_status = await _check_instance_status_async(job_data)
        if instance_status is None:
            message = f"Instance not found in {provider_display} (may be deleted)"
        elif instance_status == "running":
            message = "Instance is running"
        elif _is_terminated_instance_status(instance_status):
            message = f"Instance is {instance_status} (terminated)"
        else:
            message = f"Instance is {instance_status}"
    else:
        message = "No instance ID associated with this job"

    # Check remote process status if instance is running and has IP
    remote_process_status = None
    if instance_status == "running" and ip:
        remote_process_status = await _check_remote_status_async(job_data)
        if remote_process_status == "running":
            message = "Instance running, training in progress"
        elif remote_process_status == "stopped":
            message = "Instance running, training process stopped"
        elif remote_process_status == "unreachable":
            message = "Instance running, but SSH unreachable"

    return InstanceStatusResponse(
        job_id=job_id,
        instance_id=instance_id or "",
        instance_status=instance_status,
        job_status=job_status,
        ip=ip,
        remote_process_status=remote_process_status,
        gpu_model=job_data.get("gpu_model"),
        gpus_per_instance=job_data.get("gpus_per_instance"),
        created_at=job_data.get("created_at"),
        message=message,
    )


@router.get(
    "/jobs/{job_id}/checkpoints/remote",
    response_model=RemoteCheckpointListResponse,
)
async def list_remote_job_checkpoints(job_id: str):
    """List checkpoint directories available on the remote instance."""
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    job_data = await _refresh_job_ssh_target_if_needed(job_data)
    checkpoint_root = _get_remote_checkpoint_root(job_data)

    try:
        checkpoint_names, checkpoint_root = await asyncio.to_thread(
            _list_remote_checkpoint_dirs, job_data
        )
    except RuntimeError as exc:
        detail = str(exc)
        ssh_available = "SSH接続に失敗" not in detail
        requires_rescue_cpu = (
            not ssh_available
            and _get_job_provider(job_data) == "verda"
            and str(job_data.get("status") or "").strip().lower()
            in {"completed", "failed", "stopped", "terminated"}
        )
        return RemoteCheckpointListResponse(
            job_id=job_id,
            checkpoint_names=[],
            checkpoint_root=checkpoint_root,
            ssh_available=ssh_available,
            requires_rescue_cpu=requires_rescue_cpu,
            message=detail,
        )

    return RemoteCheckpointListResponse(
        job_id=job_id,
        checkpoint_names=checkpoint_names,
        checkpoint_root=checkpoint_root,
        ssh_available=True,
        requires_rescue_cpu=False,
        message="",
    )


@router.post("/jobs/{job_id}/rescue-cpu", response_model=RescueCPUResponse)
async def rescue_job_cpu_instance(job_id: str):
    """Start a CPU rescue instance for checkpoint extraction."""
    result = await _rescue_cpu_job_with_progress(job_id, lambda _msg: None)
    return RescueCPUResponse(**result)


async def _rescue_cpu_job_with_progress(
    job_id: str, emit_progress: Callable[[dict], None]
) -> dict:
    def emit_rescue_progress(payload: dict) -> None:
        emit_progress(_decorate_rescue_cpu_progress(payload))

    emit_rescue_progress({"type": "start", "message": "CPU rescue を開始しました"})
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_id = job_data.get("instance_id")
    if not instance_id:
        raise HTTPException(status_code=400, detail="ジョブに instance_id がありません")
    if _get_job_provider(job_data) != "verda":
        raise HTTPException(
            status_code=400,
            detail="rescue-cpu は cloud.provider=verda のジョブのみ対応しています",
        )

    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    emit_rescue_progress({"type": "loading_storage", "message": "ストレージ情報を取得中..."})
    volumes_by_id = _collect_verda_volumes(client)
    picked = _pick_os_volume_from_instance_record(client, volumes_by_id, instance_id)
    if not picked:
        picked = _pick_os_volume_for_instance(volumes_by_id, instance_id)
    if not picked:
        picked = _pick_os_volume_for_job(volumes_by_id, job_id)
    if not picked:
        raise HTTPException(
            status_code=404,
            detail="対象インスタンスのストレージが見つかりません",
        )

    state, volume = picked
    volume_id = getattr(volume, "id", "") or ""
    if not volume_id:
        raise HTTPException(
            status_code=404, detail="ストレージIDが取得できませんでした"
        )

    detach_ready_statuses = {"offline", "discontinued", "deleted"}
    attached_instance_id = getattr(volume, "instance_id", None)
    if attached_instance_id and attached_instance_id != instance_id:
        emit_rescue_progress(
            {
                "type": "detaching_from_other",
                "message": "別インスタンスからデタッチ中...",
                "instance_id": attached_instance_id,
            }
        )
        attached_status = _check_instance_via_api(attached_instance_id)
        if attached_status is not None and attached_status not in detach_ready_statuses:
            _shutdown_verda_instance(attached_instance_id)
            _wait_for_instance_offline(
                client, attached_instance_id, allowed_statuses=detach_ready_statuses
            )

    instance_status = _check_instance_via_api(instance_id)
    if instance_status is not None and instance_status not in detach_ready_statuses:
        emit_rescue_progress(
            {
                "type": "stopping_old_instance",
                "message": "旧インスタンス停止中...",
                "instance_id": instance_id,
            }
        )
        _shutdown_verda_instance(instance_id)
        _wait_for_instance_offline(
            client, instance_id, allowed_statuses=detach_ready_statuses
        )

    emit_rescue_progress(
        {
            "type": "detaching_storage",
            "message": "ストレージをデタッチ中...",
            "volume_id": volume_id,
        }
    )
    volume = _ensure_volume_active_and_detached(
        client,
        volume_id,
        emit_progress=emit_rescue_progress,
    )
    emit_rescue_progress(
        {
            "type": "detached_storage",
            "message": "ストレージのデタッチ完了",
            "volume_id": volume_id,
        }
    )

    emit_rescue_progress({"type": "select_instance", "message": "CPUインスタンスを選択中..."})
    instance_type = _select_cpu_instance_type(client)
    ssh_key_name = os.environ.get("VERDA_SSH_KEY_NAME", "")
    if not ssh_key_name:
        raise HTTPException(
            status_code=400, detail="VERDA_SSH_KEY_NAMEが設定されていません"
        )
    ssh_key_id = _get_ssh_key_id(client, ssh_key_name)

    preferred_location = getattr(volume, "location", None) or "auto"
    location = _find_location(client, instance_type, preferred_location, is_spot=False)
    hostname = f"rescue-cpu-{job_id[:8]}"

    emit_rescue_progress(
        {"type": "creating_instance", "message": "CPUインスタンスを作成中..."}
    )
    instance = _create_verda_instance_from_volume(
        client,
        volume_id=volume_id,
        instance_type=instance_type,
        ssh_key_id=ssh_key_id,
        location=location,
        hostname=hostname,
        description=f"Rescue CPU job: {job_id}",
        emit_progress=emit_rescue_progress,
    )
    new_instance_id = instance.id

    ip = None
    start_time = time.time()
    deadline = start_time + IP_WAIT_TIMEOUT_SEC
    while time.time() < deadline:
        try:
            inst = client.instances.get_by_id(new_instance_id)
            if getattr(inst, "ip", None):
                ip = inst.ip
                break
        except Exception:
            pass
        emit_rescue_progress(
            {
                "type": "waiting_ip",
                "message": "IP割り当て待機中...",
                "elapsed": int(time.time() - start_time),
                "timeout": IP_WAIT_TIMEOUT_SEC,
            }
        )
        time.sleep(10)

    if not ip:
        raise HTTPException(status_code=504, detail="IP取得タイムアウト (15分)")

    ssh_private_key = _select_preferred_ssh_private_key(job_data.get("ssh_private_key"))
    ssh_user = job_data.get("ssh_user") or _get_default_ssh_user()
    ssh_port = 22
    try:
        ssh_port = int(job_data.get("ssh_port") or 22)
    except (TypeError, ValueError):
        ssh_port = 22

    rescue_job_data = dict(job_data)
    rescue_job_data["instance_id"] = new_instance_id
    rescue_job_data["ip"] = ip
    rescue_job_data["ssh_user"] = ssh_user
    rescue_job_data["ssh_private_key"] = ssh_private_key
    rescue_job_data["ssh_port"] = ssh_port

    ssh_conn: SSHConnection | None = None
    ssh_start_time = time.time()
    ssh_deadline = ssh_start_time + SSH_WAIT_TIMEOUT_SEC
    while time.time() < ssh_deadline:
        emit_rescue_progress(
            {
                "type": "waiting_ssh",
                "message": "SSH接続待機中...",
                "elapsed": int(time.time() - ssh_start_time),
                "timeout": SSH_WAIT_TIMEOUT_SEC,
            }
        )
        ssh_conn = _get_ssh_connection_for_job(rescue_job_data, timeout=20)
        if ssh_conn is not None:
            ssh_conn.disconnect()
            break
        time.sleep(10)

    if ssh_conn is None:
        raise HTTPException(status_code=504, detail="SSH接続タイムアウト (5分)")

    emit_rescue_progress(
        {
            "type": "switching_job_target",
            "message": "ジョブの接続先を rescue CPU instance に切り替え中...",
        }
    )

    result = RescueCPUResponse(
        job_id=job_id,
        old_instance_id=instance_id,
        volume_id=volume_id,
        instance_id=new_instance_id,
        instance_type=instance_type,
        ip=ip,
        ssh_user=ssh_user,
        ssh_private_key=ssh_private_key,
        ssh_port=ssh_port,
        location=location,
        message="CPU rescue instance を起動しました。checkpoint 抽出に利用できます。",
    )
    job_data["instance_id"] = new_instance_id
    job_data["ip"] = ip
    job_data["ssh_user"] = ssh_user
    job_data["ssh_private_key"] = ssh_private_key
    job_data["ssh_port"] = ssh_port
    await _save_job(job_data)
    return result.model_dump()


def _start_training_job_operation_thread(
    *,
    operation_id: str,
    supabase_session: dict,
    worker: Callable[[], dict],
    result_message_key: str = "message",
) -> None:
    operations = get_training_job_operations_service()

    def _runner() -> None:
        token = set_request_session(supabase_session)
        try:
            result = worker()
            message = str(result.get(result_message_key) or "完了しました。").strip() or "完了しました。"
            operations.complete(
                operation_id=operation_id,
                message=message,
                result=result,
            )
        except HTTPException as exc:
            operations.fail(
                operation_id=operation_id,
                message=str(exc.detail),
                error=str(exc.detail),
            )
        except Exception as exc:
            operations.fail(
                operation_id=operation_id,
                message=str(exc),
                error=str(exc),
            )
        finally:
            reset_request_session(token)

    threading.Thread(target=_runner, daemon=True).start()


@router.post(
    "/jobs/{job_id}/operations/checkpoint-upload",
    response_model=TrainingJobOperationAcceptedResponse,
    status_code=202,
)
async def start_checkpoint_upload_operation(job_id: str, request: RemoteCheckpointUploadRequest):
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    user_id = get_current_user_id()
    session = get_supabase_session() or {}
    operations = get_training_job_operations_service()
    accepted = operations.create(
        user_id=user_id,
        job_id=job_id,
        kind="checkpoint_upload",
        message="チェックポイント登録を開始しました。",
    )
    if accepted.reused:
        return accepted

    def emit_progress(payload: dict) -> None:
        operations.update_from_progress(operation_id=accepted.operation_id, progress=payload)

    def worker() -> dict:
        return asyncio.run(
            _upload_selected_remote_checkpoint_with_progress(
                job_id,
                request.checkpoint_name,
                emit_progress,
            )
        )

    _start_training_job_operation_thread(
        operation_id=accepted.operation_id,
        supabase_session=session,
        worker=worker,
    )
    return accepted


@router.post(
    "/jobs/{job_id}/operations/rescue-cpu",
    response_model=TrainingJobOperationAcceptedResponse,
    status_code=202,
)
async def start_rescue_cpu_operation(job_id: str):
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    user_id = get_current_user_id()
    session = get_supabase_session() or {}
    operations = get_training_job_operations_service()
    accepted = operations.create(
        user_id=user_id,
        job_id=job_id,
        kind="rescue_cpu",
        message="CPU rescue を開始しました。",
    )
    if accepted.reused:
        return accepted

    def emit_progress(payload: dict) -> None:
        operations.update_from_progress(operation_id=accepted.operation_id, progress=payload)

    def worker() -> dict:
        return asyncio.run(_rescue_cpu_job_with_progress(job_id, emit_progress))

    _start_training_job_operation_thread(
        operation_id=accepted.operation_id,
        supabase_session=session,
        worker=worker,
    )
    return accepted


@router.get(
    "/operations/{operation_id}",
    response_model=TrainingJobOperationStatusResponse,
)
async def get_training_job_operation(operation_id: str):
    user_id = get_current_user_id()
    operations = get_training_job_operations_service()
    return operations.get(user_id=user_id, operation_id=operation_id)


@router.post("/jobs/{job_id}/stop", response_model=JobActionResponse)
async def stop_job(job_id: str):
    """Stop a running training job."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    status = str(job_data.get("status") or "").strip().lower()
    if status in {"running", "starting", "deploying"}:
        success = _stop_remote_job(job_data)
        if success:
            job_data["status"] = "stopped"
            job_data["termination_reason"] = "USER_STOP"
            job_data["completed_at"] = datetime.now().isoformat()
            await _save_job(job_data)
            await _archive_job_metrics(job_id)
        return JobActionResponse(
            job_id=job_id,
            success=success,
            message="Job stopped" if success else "Failed to stop job",
        )

    success, message = _terminate_job_instance(job_data)
    if success:
        job_data["ip"] = None
        await _save_job(job_data)

    return JobActionResponse(
        job_id=job_id,
        success=success,
        message=message,
    )


@router.patch("/jobs/{job_id}", response_model=JobActionResponse)
async def update_job(job_id: str, request: JobUpdateRequest):
    """Update editable job fields."""
    get_current_user_id()
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    update_payload = request.model_dump(exclude_unset=True)
    if "job_name" in update_payload:
        next_name = str(update_payload.get("job_name") or "").strip()
        if not next_name:
            raise HTTPException(status_code=422, detail="job_name must not be empty")
        job_data["job_name"] = next_name

    if not update_payload:
        return JobActionResponse(job_id=job_id, success=True, message="更新する項目がありません")

    await _save_job(job_data)
    return JobActionResponse(job_id=job_id, success=True, message="学習ジョブを更新しました")


async def _archive_job_for_bulk(job_id: str) -> BulkActionResult:
    record = await _load_job(job_id, include_deleted=True)
    if not record:
        return BulkActionResult(id=job_id, status="failed", message="Job not found")
    if record.get("deleted_at"):
        return BulkActionResult(id=job_id, status="skipped", message="既にアーカイブ済みです")

    record["deleted_at"] = datetime.now().isoformat()
    await _save_job(record)
    return BulkActionResult(id=job_id, status="succeeded", message="アーカイブしました")


@router.post("/jobs/bulk/archive", response_model=BulkActionResponse)
async def bulk_archive_jobs(request: BulkActionRequest):
    get_current_user_id()
    results: list[BulkActionResult] = []
    for job_id in request.ids:
        results.append(await _archive_job_for_bulk(job_id))
    return _build_bulk_action_response(results, requested=len(request.ids))


def _delete_verda_instance(instance_id: str, wait_timeout: int = 30) -> bool:
    """Delete Verda instance and verify deletion.

    Args:
        instance_id: The Verda instance ID to delete
        wait_timeout: Maximum seconds to wait for deletion confirmation

    Returns:
        True if instance was deleted or is being deleted, False if deletion failed
    """
    client = _get_verda_client()
    if not client:
        logger.warning(
            f"Cannot delete instance {instance_id}: Verda client not available"
        )
        return False

    try:
        # Check if instance exists first
        instance = client.instances.get_by_id(instance_id)
        current_status = instance.status
        logger.info(f"Instance {instance_id} current status: {current_status}")

        if current_status in ("offline", "deleted", "deleting", "discontinued"):
            logger.info(
                f"Instance {instance_id} already terminated or deleting (status: {current_status})"
            )
            return True

        # Send delete request
        logger.info(f"Sending delete request for instance {instance_id}")
        client.instances.action(instance_id, client.constants.instance_actions.DELETE)

        # Wait and verify deletion status
        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            time.sleep(2)
            try:
                instance = client.instances.get_by_id(instance_id)
                new_status = instance.status
                logger.info(
                    f"Instance {instance_id} status after delete request: {new_status}"
                )

                if new_status in ("deleted", "deleting", "offline", "discontinued"):
                    logger.info(
                        f"Instance {instance_id} deletion confirmed (status: {new_status})"
                    )
                    return True
            except Exception as check_error:
                # Instance not found - likely deleted
                logger.info(
                    f"Instance {instance_id} no longer found (likely deleted): {check_error}"
                )
                return True

        # Timeout - deletion may still be in progress
        logger.warning(
            f"Instance {instance_id} deletion not confirmed within {wait_timeout}s, but request was sent"
        )
        return True

    except Exception as e:
        error_msg = str(e).lower()
        # Check if it's a "not found" error - instance already deleted
        if "not found" in error_msg or "404" in error_msg:
            logger.info(f"Instance {instance_id} not found (already deleted)")
            return True
        # Actual error - deletion failed
        logger.error(f"Failed to delete instance {instance_id}: {e}")
        return False


@router.delete("/jobs/{job_id}", response_model=JobActionResponse)
async def delete_job(job_id: str, terminate_instance: bool = True):
    """Delete a job record and optionally terminate the remote instance.

    Args:
        job_id: Job ID to delete
        terminate_instance: If True (default), also terminate the cloud instance
    """
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_id = job_data.get("instance_id")
    instance_deleted = False

    job_data["deleted_at"] = datetime.now().isoformat()
    job_data["status"] = "terminated"
    job_data["termination_reason"] = "USER_DELETE"

    provider = None
    training_cfg = job_data.get("training_config") or {}
    cloud_cfg = training_cfg.get("cloud") if isinstance(training_cfg, dict) else {}
    if isinstance(cloud_cfg, dict):
        provider = str(cloud_cfg.get("provider") or "").strip() or None

    if terminate_instance and instance_id:
        job_data["cleanup_status"] = "running"
        await _save_job(job_data)
        if provider == "vast":
            from percus_ai.training.providers.vast import destroy_instance

            try:
                destroy_instance(instance_id)
                instance_deleted = True
            except Exception as exc:
                logger.warning("Failed to delete Vast instance %s: %s", instance_id, exc)
                instance_deleted = False
        else:
            instance_deleted = _delete_verda_instance(instance_id)
        job_data["cleanup_status"] = "done" if instance_deleted else "failed"
    await _save_job(job_data)
    await _archive_job_metrics(job_id)

    if instance_id and terminate_instance:
        if instance_deleted:
            message = "ジョブを論理削除し、インスタンスを削除しました"
        else:
            message = "ジョブを論理削除しました（インスタンス終了に失敗）"
    else:
        message = "ジョブを論理削除しました"

    return JobActionResponse(
        job_id=job_id,
        success=True,
        message=message,
    )


@router.post("/jobs/check-status", response_model=JobStatusCheckResponse)
async def check_all_jobs_status():
    """Check and update status of all running jobs.

    This will connect to Verda API and SSH to verify job status.
    """
    jobs_data, _ = await _list_jobs()
    updates = []
    checked = 0

    for job_data in jobs_data:
        if job_data.get("status") not in ("running", "starting"):
            continue

        checked += 1
        old_status = job_data["status"]
        job_id = job_data["job_id"]
        instance_id = job_data.get("instance_id")

        # Check instance status via provider-specific API.
        instance_status = _check_instance_status(job_data) if instance_id else None
        preserved_remote_status, preserved_reason = await _should_preserve_job_from_remote_status(
            job_data,
            instance_status,
        )
        if preserved_remote_status:
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status=old_status,
                    instance_status=preserved_remote_status,
                    reason=preserved_reason or f"Provider status stale; remote process is {preserved_remote_status}",
                )
            )
            continue

        if instance_status is None:
            # Instance not found (deleted or API error)
            job_data["status"] = "terminated"
            job_data["termination_reason"] = "INSTANCE_NOT_FOUND"
            job_data["completed_at"] = datetime.now().isoformat()
            await _save_job(job_data)
            await _archive_job_metrics(job_id)
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status="terminated",
                    instance_status="not_found",
                    reason="Instance not found (deleted)",
                )
            )
            continue

        if _is_terminated_instance_status(instance_status):
            # Instance terminated (spot preemption, error, etc.)
            job_data["status"] = "terminated"
            job_data["termination_reason"] = "INSTANCE_TERMINATED"
            job_data["completed_at"] = datetime.now().isoformat()
            await _save_job(job_data)
            await _archive_job_metrics(job_id)
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status="terminated",
                    instance_status=instance_status,
                    reason=f"Instance is {instance_status}",
                )
            )
            continue

        if instance_status == "unavailable":
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status=old_status,
                    instance_status=instance_status,
                    reason="Instance status API unavailable",
                )
            )
            continue

        if instance_status != "running":
            # Still provisioning
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status=old_status,
                    instance_status=instance_status,
                    reason=f"Instance is {instance_status}",
                )
            )
            continue

        # Instance is running, check training process via SSH
        remote_status = _check_remote_status(job_data)

        if remote_status == "stopped":
            await _mark_job_completed(job_id, termination_reason="REMOTE_EXIT")
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status="completed",
                    instance_status=instance_status,
                    reason="Training process finished",
                )
            )
        elif remote_status == "unreachable":
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status=old_status,
                    instance_status=instance_status,
                    reason="Could not connect via SSH",
                )
            )
        else:
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status=old_status,
                    instance_status=instance_status,
                    reason=f"Process status: {remote_status}",
                )
            )

    return JobStatusCheckResponse(updates=updates, checked_count=checked)


async def _run_training_provision_operation(
    *,
    operation_id: str,
    request_data: dict,
    supabase_session: dict,
) -> None:
    from percus_ai.training.orchestrator import create_job_with_progress

    operations = get_training_provision_operations_service()
    loop = asyncio.get_running_loop()
    provider = str(((request_data.get("cloud") or {}).get("provider") or "")).strip().lower()
    latest: dict[str, Optional[str]] = {"instance_id": None, "job_id": None}

    def emit_progress(message: dict) -> None:
        payload = (
            message if isinstance(message, dict) else {"type": "status", "message": str(message)}
        )
        if payload.get("instance_id") is not None:
            latest["instance_id"] = str(payload.get("instance_id") or "").strip() or None
        if payload.get("job_id") is not None:
            latest["job_id"] = str(payload.get("job_id") or "").strip() or None
        loop.call_soon_threadsafe(
            asyncio.create_task,
            operations.update_from_progress(operation_id=operation_id, progress=payload),
        )

    def worker() -> dict:
        return create_job_with_progress(request_data, emit_progress, supabase_session)

    async def cleanup_failed_instance() -> str:
        if not latest["instance_id"]:
            return ""
        deleted, detail = await loop.run_in_executor(
            None,
            cleanup_provision_instance,
            provider,
            latest["instance_id"],
        )
        return (
            " 作成中インスタンスは削除しました。"
            if deleted
            else f" 作成中インスタンスの削除に失敗しました: {detail}"
        )

    try:
        await loop.run_in_executor(_executor, worker)
    except HTTPException as exc:
        cleanup_note = await cleanup_failed_instance()
        await operations.fail(
            operation_id=operation_id,
            message=f"学習インスタンス作成に失敗しました。{cleanup_note}".strip(),
            failure_reason=str(exc.detail),
        )
    except Exception as exc:
        cleanup_note = await cleanup_failed_instance()
        await operations.fail(
            operation_id=operation_id,
            message=f"学習インスタンス作成に失敗しました。{cleanup_note}".strip(),
            failure_reason=str(exc),
        )


@router.post(
    "/provision-operations",
    response_model=TrainingProvisionOperationAcceptedResponse,
    status_code=202,
)
async def start_training_provision_operation(request: JobCreateRequest):
    """Start a background training provision operation."""
    if not request.job_name:
        raise HTTPException(status_code=422, detail="job_name must be provided")
    if not request.dataset:
        raise HTTPException(status_code=422, detail="dataset must be provided")
    if not request.policy:
        raise HTTPException(status_code=422, detail="policy must be provided")
    _assert_provider_configured(request.cloud.provider)

    user_id = get_current_user_id()
    session = get_supabase_session() or {}
    operations = get_training_provision_operations_service()
    accepted = await operations.create(user_id=user_id, request=request)
    request_data = request.model_dump()
    request_data["job_id"] = str(uuid.uuid4())
    request_data["provision_operation_id"] = accepted.operation_id
    asyncio.create_task(
        _run_training_provision_operation(
            operation_id=accepted.operation_id,
            request_data=request_data,
            supabase_session=session,
        )
    )
    return accepted


@router.get(
    "/provision-operations/{operation_id}",
    response_model=TrainingProvisionOperationStatusResponse,
)
async def get_training_provision_operation(operation_id: str):
    user_id = get_current_user_id()
    operations = get_training_provision_operations_service()
    return await operations.get(user_id=user_id, operation_id=operation_id)


# --- Helper functions for job creation ---


def _select_instance_type(client, gpu_model: str, gpus_per_instance: int) -> str:
    """Select instance type from Verda."""
    gpu_model_upper = gpu_model.upper()
    types = client.instance_types.get()

    candidates = []
    for t in types:
        itype = t.instance_type
        count = _extract_gpu_count(itype)
        if count is None:
            continue

        if count != gpus_per_instance:
            continue
        if gpu_model_upper not in itype.upper():
            continue

        candidates.append(t)

    if not candidates:
        raise HTTPException(
            status_code=400,
            detail=f"No instance type found for {gpu_model} x {gpus_per_instance}",
        )

    candidates.sort(key=lambda t: t.spot_price_per_hour)
    return candidates[0].instance_type


def _get_ssh_key_id(client, key_name: str) -> str:
    """Get SSH key ID by name."""
    keys = client.ssh_keys.get()
    for k in keys:
        if k.name == key_name:
            return k.id
    raise HTTPException(
        status_code=400,
        detail=f"SSH key '{key_name}' not found in Verda account",
    )


def _find_location(
    client,
    instance_type: str,
    preferred: str,
    is_spot: bool,
) -> str:
    """Find available location."""
    known_locations = ["FIN-01", "FIN-02", "FIN-03", "ICE-01"]
    instance_mode = "Spot" if is_spot else "On-demand"

    if preferred and preferred.lower() != "auto":
        try:
            if client.instances.is_available(
                instance_type=instance_type,
                is_spot=is_spot,
                location_code=preferred,
            ):
                return preferred
        except Exception:
            pass
        raise HTTPException(
            status_code=400,
            detail=f"Location '{preferred}' not available for {instance_type} ({instance_mode})",
        )

    # Find any available location
    checked_locations = []
    for loc in known_locations:
        try:
            if client.instances.is_available(
                instance_type=instance_type,
                is_spot=is_spot,
                location_code=loc,
            ):
                return loc
            checked_locations.append(loc)
        except Exception:
            continue

    raise HTTPException(
        status_code=503,
        detail=(
            f"No {instance_mode} instance available for {instance_type}. "
            f"Checked locations: {', '.join(checked_locations) or 'none'}. "
            f"Try again later, use on-demand (is_spot: false), or choose a different GPU."
        ),
    )


def _create_instance(
    client,
    instance_type: str,
    ssh_key_id: str,
    location: str,
    is_spot: bool,
    storage_size: Optional[int],
    hostname: str,
) -> str:
    """Create Verda instance."""
    os_volume = None
    if storage_size:
        vol_name = f"os-{hostname}-{int(time.time())}"[:32]
        os_volume = {
            "size": storage_size,
            "type": "NVMe",
            "name": vol_name,
        }

    if is_spot:
        instance = client.instances.create(
            instance_type=instance_type,
            image="ubuntu-24.04-cuda-12.8-open-docker",
            hostname=hostname,
            description=f"Training job: {hostname}",
            ssh_key_ids=[ssh_key_id],
            location=location,
            os_volume=os_volume,
            is_spot=True,
            contract="SPOT",
        )
    else:
        instance = client.instances.create(
            instance_type=instance_type,
            image="ubuntu-24.04-cuda-12.8-open-docker",
            hostname=hostname,
            description=f"Training job: {hostname}",
            ssh_key_ids=[ssh_key_id],
            location=location,
            os_volume=os_volume,
            is_spot=False,
        )

    return instance.id




_checkpoint_index_manager = None


def _get_checkpoint_index_manager():
    """Get CheckpointIndexManager singleton."""
    global _checkpoint_index_manager
    if _checkpoint_index_manager is None:
        try:
            import os

            from percus_ai.storage import (
                CheckpointIndexManager,
                ManifestManager,
                R2SyncService,
            )

            manifest = ManifestManager()
            manifest.init_directories()
            bucket = os.getenv("R2_BUCKET", "percus-data")
            version = os.getenv("R2_VERSION", "v2")
            r2_service = R2SyncService(manifest, bucket, version=version)
            _checkpoint_index_manager = CheckpointIndexManager(r2_service)
        except Exception as e:
            raise HTTPException(
                status_code=503, detail=f"Failed to initialize checkpoint manager: {e}"
            )
    return _checkpoint_index_manager


def _get_dataset_info_from_manifest(dataset_id: str) -> CheckpointDatasetInfo:
    """Extract dataset info for compatibility checking."""
    try:
        from percus_ai.storage import ManifestManager, get_datasets_dir

        manifest = ManifestManager()
        datasets_dir = get_datasets_dir()
        dataset_path = datasets_dir / dataset_id

        camera_names = []
        action_dim = 0
        state_dim = 0

        # Read from dataset's meta/info.json if available
        info_path = dataset_path / "meta" / "info.json"
        if info_path.exists():
            with open(info_path) as f:
                info = json.load(f)

            # Extract camera names from features
            features = info.get("features", {})
            for key in features:
                if key.startswith("observation.images."):
                    cam_name = key.replace("observation.images.", "")
                    camera_names.append(cam_name)

            # Extract action/state dims
            if "action" in features:
                action_shape = features["action"].get("shape", [])
                action_dim = action_shape[0] if action_shape else 0

            if "observation.state" in features:
                state_shape = features["observation.state"].get("shape", [])
                state_dim = state_shape[0] if state_shape else 0

        return CheckpointDatasetInfo(
            camera_names=camera_names,
            action_dim=action_dim,
            state_dim=state_dim,
        )
    except Exception:
        return CheckpointDatasetInfo()


def _get_storage_dataset_info_from_manifest(dataset_id: str) -> StorageCheckpointDatasetInfo:
    dataset_info = _get_dataset_info_from_manifest(dataset_id)
    return StorageCheckpointDatasetInfo(**dataset_info.model_dump())


@router.get("/checkpoints", response_model=CheckpointListResponse)
async def list_checkpoints(
    policy_type: Optional[str] = Query(None, description="Filter by policy type"),
):
    """List all checkpoints with optional filtering.

    Returns all available checkpoints from R2 storage.
    Each checkpoint entry represents a training job with its latest step.
    """
    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # Load index from R2
        index = checkpoint_mgr.load_index()
        if not index:
            return CheckpointListResponse(checkpoints=[], total=0)

        checkpoints = []
        for entry in index.checkpoints:
            # Filter by policy_type if specified
            if policy_type and entry.policy_type != policy_type:
                continue

            # Convert dataset_info
            ds_info = CheckpointDatasetInfo(
                camera_names=entry.dataset_info.camera_names
                if entry.dataset_info
                else [],
                action_dim=entry.dataset_info.action_dim if entry.dataset_info else 0,
                state_dim=entry.dataset_info.state_dim if entry.dataset_info else 0,
            )

            checkpoints.append(
                CheckpointInfo(
                    job_name=entry.job_name,
                    policy_type=entry.policy_type,
                    step=entry.latest_step,
                    dataset_id=entry.dataset_id,
                    dataset_info=ds_info,
                    created_at=entry.created_at,
                    size_mb=entry.size_mb,
                    pretrained_path=entry.pretrained_path,
                    author=entry.author if hasattr(entry, "author") else None,
                )
            )

        # Sort by created_at descending
        checkpoints.sort(key=lambda c: c.created_at, reverse=True)

        return CheckpointListResponse(
            checkpoints=checkpoints,
            total=len(checkpoints),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to list checkpoints from R2: {e}"
        )


@router.get("/checkpoints/{job_name}", response_model=CheckpointDetailResponse)
async def get_checkpoint(job_name: str):
    """Get detailed information about a specific checkpoint job.

    Includes all available step numbers for the job.
    """
    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # Get job info
        entry = checkpoint_mgr.get_job_info(job_name)
        if not entry:
            raise HTTPException(
                status_code=404, detail=f"Checkpoint not found: {job_name}"
            )

        # Get available steps
        steps = checkpoint_mgr.get_job_steps(job_name)

        # Convert dataset_info
        ds_info = CheckpointDatasetInfo(
            camera_names=entry.dataset_info.camera_names if entry.dataset_info else [],
            action_dim=entry.dataset_info.action_dim if entry.dataset_info else 0,
            state_dim=entry.dataset_info.state_dim if entry.dataset_info else 0,
        )

        return CheckpointDetailResponse(
            job_name=entry.job_name,
            policy_type=entry.policy_type,
            dataset_id=entry.dataset_id,
            dataset_info=ds_info,
            pretrained_path=entry.pretrained_path,
            available_steps=steps,
            latest_step=entry.latest_step,
            created_at=entry.created_at,
            size_mb=entry.size_mb,
            author=entry.author if hasattr(entry, "author") else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to get checkpoint info: {e}"
        )


@router.post(
    "/checkpoints/{job_name}/download", response_model=CheckpointDownloadResponse
)
async def download_checkpoint(
    job_name: str,
    request: Optional[CheckpointDownloadRequest] = None,
):
    """Download a checkpoint to local storage.

    Downloads either a specific step or the latest checkpoint.
    """
    step = request.step if request else None
    target_path = request.target_path if request else None

    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # Verify checkpoint exists
        entry = checkpoint_mgr.get_job_info(job_name)
        if not entry:
            raise HTTPException(
                status_code=404, detail=f"Checkpoint not found: {job_name}"
            )

        # Determine target path
        if target_path:
            download_path = Path(target_path)
        else:
            # Use default models directory
            models_dir = get_models_dir()
            download_path = models_dir / job_name

        download_path.mkdir(parents=True, exist_ok=True)

        # Download checkpoint
        if step is not None:
            # Verify step exists
            available_steps = checkpoint_mgr.get_job_steps(job_name)
            if step not in available_steps:
                raise HTTPException(
                    status_code=404,
                    detail=f"Step {step} not found. Available steps: {available_steps}",
                )
            success, error = await asyncio.to_thread(
                checkpoint_mgr.download_step_checkpoint,
                job_name,
                step,
                download_path,
            )
            downloaded_step = step
        else:
            success, error = await asyncio.to_thread(
                checkpoint_mgr.download_latest_checkpoint,
                job_name,
                download_path,
            )
            downloaded_step = entry.latest_step

        if not success:
            raise HTTPException(status_code=500, detail=f"Download failed: {error}")

        return CheckpointDownloadResponse(
            success=True,
            job_name=job_name,
            step=downloaded_step,
            target_path=str(download_path),
            message=f"Downloaded checkpoint step {downloaded_step}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to download checkpoint: {e}"
        )


@router.post(
    "/checkpoints/compatibility-check", response_model=DatasetCompatibilityCheckResponse
)
async def check_dataset_compatibility(request: DatasetCompatibilityCheckRequest):
    """Check if a dataset is compatible with a checkpoint for continue training.

    Validates:
    - Camera configuration (names and count)
    - Action dimension
    - State dimension
    """
    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # Get checkpoint info
        entry = checkpoint_mgr.get_job_info(request.checkpoint_job_name)
        if not entry:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint not found: {request.checkpoint_job_name}",
            )

        # Get dataset info
        dataset_info = _get_dataset_info_from_manifest(request.dataset_id)

        # Perform compatibility check
        errors = []
        warnings = []

        checkpoint_ds_info = entry.dataset_info if entry.dataset_info else None

        if checkpoint_ds_info:
            # Camera check (critical)
            if set(checkpoint_ds_info.camera_names) != set(dataset_info.camera_names):
                errors.append(
                    f"Camera configuration mismatch. "
                    f"Checkpoint: {checkpoint_ds_info.camera_names}, "
                    f"Dataset: {dataset_info.camera_names}"
                )

            # Action dimension check (critical)
            if (
                checkpoint_ds_info.action_dim != dataset_info.action_dim
                and checkpoint_ds_info.action_dim > 0
            ):
                errors.append(
                    f"Action dimension mismatch. "
                    f"Checkpoint: {checkpoint_ds_info.action_dim}, "
                    f"Dataset: {dataset_info.action_dim}"
                )

            # State dimension check (warning only)
            if (
                checkpoint_ds_info.state_dim != dataset_info.state_dim
                and checkpoint_ds_info.state_dim > 0
            ):
                warnings.append(
                    f"State dimension differs. "
                    f"Checkpoint: {checkpoint_ds_info.state_dim}, "
                    f"Dataset: {dataset_info.state_dim}"
                )

            cp_info = CheckpointDatasetInfo(
                camera_names=checkpoint_ds_info.camera_names,
                action_dim=checkpoint_ds_info.action_dim,
                state_dim=checkpoint_ds_info.state_dim,
            )
        else:
            cp_info = CheckpointDatasetInfo()
            warnings.append("Checkpoint has no dataset info for comparison")

        return DatasetCompatibilityCheckResponse(
            is_compatible=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            checkpoint_info=cp_info,
            dataset_info=dataset_info,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Compatibility check failed: {e}")


@router.post("/jobs/continue", response_model=JobCreateResponse)
async def create_continue_job(
    request: JobCreateContinueRequest,
    background_tasks: BackgroundTasks,
):
    """Create a continue training job from checkpoint.

    Downloads checkpoint from R2 and starts training with additional steps.
    """
    checkpoint_config = request.checkpoint
    dataset_config = request.dataset
    training_config = request.training
    provider = str(request.cloud.provider or "").strip().lower()
    if provider != "verda":
        raise HTTPException(
            status_code=400,
            detail="jobs/continue は cloud.provider=verda のみ対応しています",
        )

    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # 1. Validate checkpoint exists
        checkpoint_entry = checkpoint_mgr.get_job_info(checkpoint_config.job_name)
        if not checkpoint_entry:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint not found: {checkpoint_config.job_name}",
            )

        # Determine step to use
        step = checkpoint_config.step or checkpoint_entry.latest_step

        # Verify step exists
        available_steps = checkpoint_mgr.get_job_steps(checkpoint_config.job_name)
        if step not in available_steps:
            raise HTTPException(
                status_code=400,
                detail=f"Step {step} not available. Available: {available_steps}",
            )

        # 2. Validate dataset compatibility if using different dataset
        if not dataset_config.use_original:
            compat_result = await check_dataset_compatibility(
                DatasetCompatibilityCheckRequest(
                    checkpoint_job_name=checkpoint_config.job_name,
                    dataset_id=dataset_config.id,
                )
            )
            if not compat_result.is_compatible:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dataset incompatible: {'; '.join(compat_result.errors)}",
                )

        # 3. Generate job name
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        author = request.author or _default_author_user_id()
        job_name = f"{checkpoint_config.job_name}_continue_{author}_{date_str}"
        job_id = str(uuid.uuid4())

        # 4. Prepare training config
        dataset_id = (
            checkpoint_entry.dataset_id
            if dataset_config.use_original
            else dataset_config.id
        )

        # Calculate total steps
        total_steps = step + training_config.additional_steps

        # Check if Verda credentials are available
        client = _get_verda_client()
        if not client:
            raise HTTPException(
                status_code=503,
                detail="Verda/DataCrunch credentials not configured.",
            )

        now = datetime.now().isoformat()

        if request.cloud.provider != "verda":
            raise HTTPException(status_code=400, detail="Continue training は現在 Verda のみ対応です。")

        instance_type = str(request.cloud.selected_instance_type or "").strip()
        if not instance_type:
            raise HTTPException(status_code=400, detail="cloud.selected_instance_type is required")
        selected_mode = str(request.cloud.selected_mode or "").strip().lower()
        if selected_mode not in {"spot", "ondemand"}:
            raise HTTPException(status_code=400, detail="cloud.selected_mode is required")
        is_spot = selected_mode == "spot"
        gpu_model = str(request.cloud.gpu_model or "").strip() or _extract_gpu_model(instance_type)
        gpus_per_instance = request.cloud.gpus_per_instance or _extract_gpu_count(instance_type)

        # Get SSH key
        ssh_key_name = os.environ.get("VERDA_SSH_KEY_NAME", "")
        ssh_private_key = os.environ.get(
            "VERDA_SSH_PRIVATE_KEY",
            str(Path.home() / ".ssh" / "id_rsa"),
        )
        ssh_user = _get_default_ssh_user()
        try:
            ssh_private_key = _resolve_ssh_private_key_path(ssh_private_key)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        if not ssh_key_name:
            raise HTTPException(
                status_code=503,
                detail="SSH key not configured. Set VERDA_SSH_KEY_NAME.",
            )

        ssh_key_id = _get_ssh_key_id(client, ssh_key_name)

        # Find available location
        location = _find_location(
            client,
            instance_type,
            request.cloud.location,
            is_spot,
        )

        # Create instance
        instance_id = _create_instance(
            client,
            instance_type=instance_type,
            ssh_key_id=ssh_key_id,
            location=location,
            is_spot=is_spot,
            storage_size=request.cloud.storage_size,
            hostname=f"train-{job_id[:16]}",
        )

        # Save job info (status: starting)
        profile_instance_id, profile_snapshot = await _resolve_profile_info(dataset_id)
        job_data = {
            "job_id": job_id,
            "job_name": job_name,
            "instance_id": instance_id,
            "ip": None,
            "status": "starting",
            "mode": "resume_local",
            "profile_instance_id": profile_instance_id,
            "profile_snapshot": profile_snapshot,
            "continue_from": {
                "job_name": checkpoint_config.job_name,
                "step": step,
            },
            "dataset_id": dataset_id,
            "policy_type": checkpoint_entry.policy_type,
            "ssh_user": ssh_user,
            "ssh_private_key": ssh_private_key,
            "remote_base_dir": "/root/.physical-ai",
            "created_at": now,
            "updated_at": now,
            "gpu_model": gpu_model,
            "gpus_per_instance": gpus_per_instance,
            "total_steps": total_steps,
            "additional_steps": training_config.additional_steps,
            "author": author,
            "training_config": {
                "dataset": request.dataset.model_dump(),
                "policy": policy_payload,
                "training": training_payload,
                "validation": validation_payload or {"enable": False},
                "early_stopping": early_stopping_payload or {"enable": False},
                "checkpoint": {
                    "job_name": checkpoint_config.job_name,
                    "step": step,
                },
            },
        }
        await _save_job(job_data)

        # TODO: Start background task to wait for IP and deploy continue training
        # For now, return the job info

        return JobCreateResponse(
            job_id=job_id,
            instance_id=instance_id,
            status="starting",
            message=f"Continue training job created from {checkpoint_config.job_name} step {step}",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create continue job: {e}"
        )


# --- WebSocket Log Streaming ---


@router.websocket("/ws/jobs/{job_id}/logs")
async def websocket_stream_logs(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time log streaming via SSH.

    Connects to the remote instance via SSH and streams logs using tail -f.
    Client receives log lines as they arrive.

    Messages sent to client:
    - {"type": "connected", "message": "SSH接続完了"}
    - {"type": "log", "line": "..."}
    - {"type": "status", "status": "completed|failed|stopped"}
    - {"type": "error", "error": "..."}
    - {"type": "heartbeat"}
    """
    await websocket.accept()
    log_type = websocket.query_params.get("log_type", "training")
    if log_type not in ("training", "setup"):
        await websocket.send_json(
            {"type": "error", "error": f"Invalid log_type: {log_type}"}
        )
        await websocket.close()
        return
    logger.info(f"WebSocket log stream client connected for job {job_id}")

    supabase_session = _resolve_websocket_supabase_session(websocket)
    if not supabase_session:
        await websocket.send_json(
            {
                "type": "error",
                "error": "認証情報がありません。ログインし直してください。",
            }
        )
        await websocket.close()
        return

    status_subscription_id = None
    status_queue = None
    realtime_manager = None
    ssh_conn: Optional[SSHConnection] = None
    session_token = set_request_session(supabase_session)
    try:
        job_data = await _load_job(job_id)
        if not job_data:
            await websocket.send_json(
                {"type": "error", "error": f"Job not found: {job_id}"}
            )
            await websocket.close()
            return

        # Check job has IP
        ip = job_data.get("ip")
        if not ip:
            await websocket.send_json({"type": "error", "error": "Job has no IP address"})
            await websocket.close()
            return

        try:
            try:
                realtime_manager = _get_training_job_realtime_manager()
                status_subscription_id, status_queue = await realtime_manager.subscribe(
                    job_id,
                    asyncio.get_running_loop(),
                )
            except Exception as e:
                await websocket.send_json(
                    {"type": "error", "error": f"Realtime購読に失敗しました: {e}"}
                )
                await websocket.close()
                return

            # Connect SSH in thread pool
            loop = asyncio.get_event_loop()
            ssh_conn = await loop.run_in_executor(
                _executor, lambda: _get_ssh_connection_for_job(job_data, timeout=30)
            )

            if not ssh_conn:
                await websocket.send_json(
                    {"type": "error", "error": "SSH接続に失敗しました"}
                )
                await websocket.close()
                return

            await websocket.send_json({"type": "connected", "message": "SSH接続完了"})

            # Determine log file path
            if log_type == "setup":
                log_file = _get_setup_log_file_path(job_data)
            else:
                log_file = _get_training_log_file_path(job_data)

            # Start tail -f in a channel
            transport = ssh_conn.client.get_transport()
            channel = transport.open_session()
            channel.exec_command(f"tail -f {log_file} 2>/dev/null")
            channel.setblocking(0)

            last_heartbeat = asyncio.get_event_loop().time()

            while True:
                # Check for incoming data from SSH
                try:
                    if channel.recv_ready():
                        data = channel.recv(4096)
                        if data:
                            lines = data.decode("utf-8", errors="replace").split("\n")
                            for line in lines:
                                if line.strip():
                                    await websocket.send_json({"type": "log", "line": line})

                    # Check if channel closed (process ended)
                    if channel.exit_status_ready():
                        await websocket.send_json(
                            {
                                "type": "status",
                                "status": "stream_ended",
                                "message": "ログストリーム終了",
                            }
                        )
                        await _mark_job_completed(job_id)
                        break

                except Exception as e:
                    logger.debug(f"SSH recv error: {e}")

                # Send heartbeat every 5 seconds
                now = asyncio.get_event_loop().time()
                if now - last_heartbeat > 5:
                    await websocket.send_json({"type": "heartbeat"})
                    last_heartbeat = now

                status = _drain_latest_status(status_queue) if status_queue else None
                if status and status not in RUNNING_STATUSES:
                    await websocket.send_json(
                        {
                            "type": "status",
                            "status": status,
                            "message": f"ジョブ状態: {status}",
                        }
                    )
                    break

                # Small delay to avoid busy loop
                await asyncio.sleep(0.1)

        except WebSocketDisconnect:
            logger.info(f"WebSocket log stream client disconnected for job {job_id}")
        except Exception as e:
            logger.error(f"WebSocket log stream error for job {job_id}: {e}")
            try:
                await websocket.send_json({"type": "error", "error": str(e)})
            except Exception:
                pass
        finally:
            if ssh_conn:
                try:
                    ssh_conn.disconnect()
                except Exception:
                    pass
            if status_subscription_id and realtime_manager:
                realtime_manager.unsubscribe(status_subscription_id)
    finally:
        reset_request_session(session_token)


@router.websocket("/ws/jobs/{job_id}/session")
async def websocket_job_session(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for unified job session with progressive loading.

    This endpoint maintains a single SSH connection for the entire session,
    providing immediate local job info followed by SSH-dependent data.

    Server -> Client messages:
    - {"type": "job_info", "data": {...}}     # Immediate (from local JSON)
    - {"type": "ssh_connecting"}               # SSH connection starting
    - {"type": "ssh_connected"}                # SSH connection established
    - {"type": "ssh_error", "error": "..."}    # SSH connection failed
    - {"type": "remote_status", "status": "running|stopped|error|unreachable"}
    - {"type": "progress", "step": "...", "loss": "..."}
    - {"type": "log", "line": "..."}           # Log line (when streaming)
    - {"type": "log_stream_started"}           # Log streaming started
    - {"type": "log_stream_stopped"}           # Log streaming stopped
    - {"type": "heartbeat"}                    # Every 5 seconds

    Client -> Server messages:
    - {"action": "start_logs"}                 # Start log streaming
    - {"action": "stop_logs"}                  # Stop log streaming
    - {"action": "refresh"}                    # Refresh status/progress
    """
    await websocket.accept()
    logger.info(f"WebSocket job session connected for job {job_id}")

    supabase_session = _resolve_websocket_supabase_session(websocket)
    if not supabase_session:
        await websocket.send_json(
            {
                "type": "error",
                "error": "認証情報がありません。ログインし直してください。",
            }
        )
        await websocket.close()
        return

    status_subscription_id = None
    status_queue = None
    realtime_manager = None
    session_token = set_request_session(supabase_session)
    try:
        # Load job data immediately
        job_data = await _load_job(job_id)
        if not job_data:
            await websocket.send_json(
                {
                    "type": "error",
                    "error": f"Job not found: {job_id}",
                }
            )
            await websocket.close()
            return

        try:
            realtime_manager = _get_training_job_realtime_manager()
            status_subscription_id, status_queue = await realtime_manager.subscribe(
                job_id,
                asyncio.get_running_loop(),
            )
        except Exception as e:
            await websocket.send_json(
                {"type": "error", "error": f"Realtime購読に失敗しました: {e}"}
            )
            await websocket.close()
            return

        # Send job info immediately (no SSH needed)
        await websocket.send_json(
            {
                "type": "job_info",
                "data": {
                    "job_id": job_data.get("job_id"),
                    "job_name": job_data.get("job_name"),
                    "status": job_data.get("status"),
                    "mode": job_data.get("mode"),
                    "gpu_model": job_data.get("gpu_model"),
                    "gpus_per_instance": job_data.get("gpus_per_instance"),
                    "ip": job_data.get("ip"),
                    "instance_id": job_data.get("instance_id"),
                    "created_at": job_data.get("created_at"),
                    "started_at": job_data.get("started_at"),
                    "failure_reason": job_data.get("failure_reason"),
                    "termination_reason": job_data.get("termination_reason"),
                    "cleanup_status": job_data.get("cleanup_status"),
                    "deleted_at": job_data.get("deleted_at"),
                },
            }
        )

        ssh_conn: Optional[SSHConnection] = None
        log_channel = None
        is_streaming_logs = False

        try:
            # Check if job has IP (needed for SSH)
            ip = job_data.get("ip")
            if not ip:
                await websocket.send_json(
                    {
                        "type": "ssh_error",
                        "error": "Job has no IP address (instance may not be ready)",
                    }
                )
                # Continue without SSH - user can still see local info
                await _run_session_loop_no_ssh(websocket, status_queue, job_id)
                return

            # Start SSH connection
            await websocket.send_json({"type": "ssh_connecting"})

            # Connect SSH in thread pool
            loop = asyncio.get_event_loop()
            ssh_conn = await loop.run_in_executor(
                _executor, lambda: _get_ssh_connection_for_job(job_data, timeout=30)
            )

            if not ssh_conn:
                await websocket.send_json(
                    {"type": "ssh_error", "error": "SSH接続に失敗しました"}
                )
                await _run_session_loop_no_ssh(websocket, status_queue, job_id)
                return

            await websocket.send_json({"type": "ssh_connected"})

            # Get initial remote status and progress (pass raw paramiko client to helper functions)
            await _send_remote_status(websocket, ssh_conn.client)
            await _send_progress(websocket, job_id)

            # Determine log file path for later use
            log_file = _get_training_log_file_path(job_data)

            last_heartbeat = asyncio.get_event_loop().time()
            last_progress_update = asyncio.get_event_loop().time()

            while True:
                now = asyncio.get_event_loop().time()

                # Handle incoming client messages (non-blocking)
                try:
                    # Use wait_for with short timeout to check for messages
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                    action = message.get("action")

                    if action == "start_logs" and not is_streaming_logs:
                        # Start log streaming using same SSH connection
                        transport = ssh_conn.client.get_transport()
                        if transport and transport.is_active():
                            log_channel = transport.open_session()
                            log_channel.exec_command(f"tail -f {log_file} 2>/dev/null")
                            log_channel.setblocking(0)
                            is_streaming_logs = True
                            await websocket.send_json({"type": "log_stream_started"})

                    elif action == "stop_logs" and is_streaming_logs:
                        # Stop log streaming
                        if log_channel:
                            try:
                                log_channel.close()
                            except Exception:
                                pass
                            log_channel = None
                        is_streaming_logs = False
                        await websocket.send_json({"type": "log_stream_stopped"})

                    elif action == "refresh":
                        # Refresh status and progress
                        await _send_remote_status(websocket, ssh_conn.client)
                        await _send_progress(websocket, job_id)

                except asyncio.TimeoutError:
                    pass  # No message received, continue

                # If streaming logs, read from channel
                if is_streaming_logs and log_channel:
                    try:
                        if log_channel.recv_ready():
                            data = log_channel.recv(4096)
                            if data:
                                lines = data.decode("utf-8", errors="replace").split("\n")
                                for line in lines:
                                    if line.strip():
                                        await websocket.send_json(
                                            {"type": "log", "line": line}
                                        )

                        # Check if log process ended
                        if log_channel.exit_status_ready():
                            is_streaming_logs = False
                            await websocket.send_json({"type": "log_stream_stopped"})
                            log_channel = None

                    except Exception as e:
                        logger.debug(f"Log channel read error: {e}")

                # Send heartbeat every 5 seconds
                if now - last_heartbeat > 5:
                    await websocket.send_json({"type": "heartbeat"})
                    last_heartbeat = now

                # Update progress every 10 seconds (if not streaming logs)
                if not is_streaming_logs and now - last_progress_update > 10:
                    await _send_progress(websocket, job_id)
                    last_progress_update = now

                status = _drain_latest_status(status_queue) if status_queue else None
                if status and status not in RUNNING_STATUSES:
                    await websocket.send_json(
                        {"type": "job_status_changed", "status": status}
                    )
                    break

                await asyncio.sleep(0.05)

        except WebSocketDisconnect:
            logger.info(f"WebSocket job session disconnected for job {job_id}")
        except Exception as e:
            logger.error(f"WebSocket job session error for job {job_id}: {e}")
            try:
                await websocket.send_json({"type": "error", "error": str(e)})
            except Exception:
                pass
        finally:
            if log_channel:
                try:
                    log_channel.close()
                except Exception:
                    pass
            if ssh_conn:
                try:
                    ssh_conn.disconnect()
                except Exception:
                    pass
            if status_subscription_id and realtime_manager:
                realtime_manager.unsubscribe(status_subscription_id)
    finally:
        reset_request_session(session_token)


async def _run_session_loop_no_ssh(
    websocket: WebSocket,
    status_queue: "asyncio.Queue",
    job_id: str,
) -> None:
    """Run session loop without SSH connection (local data only)."""
    last_heartbeat = asyncio.get_event_loop().time()
    last_progress_update = asyncio.get_event_loop().time()

    try:
        while True:
            now = asyncio.get_event_loop().time()

            # Handle incoming client messages
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                action = message.get("action")

                if action == "start_logs":
                    await websocket.send_json(
                        {
                            "type": "ssh_error",
                            "error": "SSH接続がないためログを取得できません",
                        }
                    )

            except asyncio.TimeoutError:
                pass

            # Send heartbeat every 5 seconds
            if now - last_heartbeat > 5:
                await websocket.send_json({"type": "heartbeat"})
                last_heartbeat = now

            if now - last_progress_update > 10:
                await _send_progress(websocket, job_id)
                last_progress_update = now

            status = _drain_latest_status(status_queue) if status_queue else None
            if status and status not in RUNNING_STATUSES_WITH_PENDING:
                await websocket.send_json(
                    {"type": "job_status_changed", "status": status}
                )
                break

            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        logger.info(f"WebSocket job session (no SSH) disconnected for job {job_id}")
    except Exception as e:
        logger.error(f"WebSocket job session (no SSH) error: {e}")


async def _send_remote_status(websocket: WebSocket, ssh_client) -> None:
    """Send remote process status via existing SSH connection."""
    try:
        loop = asyncio.get_event_loop()
        status = await loop.run_in_executor(
            _executor,
            lambda: _exec_ssh_command(
                ssh_client,
                (
                    f"tmux has-session -t {TMUX_TRAIN_SESSION_NAME} 2>/dev/null && echo 'running' "
                    f"|| (tmux has-session -t {TMUX_SETUP_SESSION_NAME} 2>/dev/null && echo 'starting' || echo 'stopped')"
                ),
            ),
        )
        await websocket.send_json(
            {"type": "remote_status", "status": status.strip() if status else "unknown"}
        )
    except Exception as e:
        logger.debug(f"Failed to get remote status: {e}")
        await websocket.send_json({"type": "remote_status", "status": "error"})


async def _send_progress(websocket: WebSocket, job_id: str) -> None:
    """Send training progress from Supabase metrics."""
    try:
        loop = asyncio.get_event_loop()
        latest_train, latest_val = await loop.run_in_executor(
            _executor,
            lambda: _get_latest_metrics(job_id),
        )
        latest = latest_train or latest_val
        step = latest.get("step") if latest else None
        loss = latest.get("loss") if latest else None
        await websocket.send_json(
            {
                "type": "progress",
                "step": str(step) if step is not None else "N/A",
                "loss": str(loss) if loss is not None else "N/A",
                "train": latest_train,
                "val": latest_val,
            }
        )
    except Exception as e:
        logger.debug(f"Failed to get progress: {e}")


def _exec_ssh_command(ssh_client, command: str) -> Optional[str]:
    """Execute SSH command and return stdout."""
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=10)
        return stdout.read().decode()
    except Exception:
        return None

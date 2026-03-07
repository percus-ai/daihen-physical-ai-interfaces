"""Runtime helpers for controlling the lerobot_ros2 Docker stack."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

from interfaces_backend.utils.docker_compose import get_lerobot_compose_file
from interfaces_backend.utils.docker_services import get_docker_service_summary
from percus_ai.storage.paths import get_project_root

logger = logging.getLogger(__name__)

_DEFAULT_SCRIPT_TIMEOUT_S = int(os.environ.get("LEROBOT_SCRIPT_TIMEOUT_S", "180"))
_LEROBOT_LOCK = threading.Lock()


class LerobotCommandError(RuntimeError):
    """Raised when a lerobot stack command fails."""


def _failed_result(cmd: list[str], message: str, exit_code: int = 1) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=cmd, returncode=exit_code, stdout="", stderr=message)


def _lerobot_script_path(script_name: str) -> Path:
    return get_project_root() / "docker" / "lerobot_ros2" / script_name


def _run_lerobot_script(
    script_name: str,
    *,
    strict: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    script_path = _lerobot_script_path(script_name)
    cmd = [str(script_path)]

    if not script_path.exists():
        message = f"lerobot script not found: {script_path}"
        if strict:
            raise LerobotCommandError(message)
        return _failed_result(cmd, message)

    if not os.access(script_path, os.X_OK):
        message = f"lerobot script is not executable: {script_path}"
        if strict:
            raise LerobotCommandError(message)
        return _failed_result(cmd, message)

    try:
        with _LEROBOT_LOCK:
            result = subprocess.run(
                cmd,
                cwd=get_project_root(),
                capture_output=True,
                text=True,
                timeout=timeout or _DEFAULT_SCRIPT_TIMEOUT_S,
            )
    except subprocess.TimeoutExpired as exc:
        message = f"lerobot script timeout ({script_name}): {exc}"
        if strict:
            raise LerobotCommandError(message) from exc
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else message
        return subprocess.CompletedProcess(args=cmd, returncode=124, stdout=stdout, stderr=stderr)

    if result.returncode != 0 and strict:
        detail = (result.stderr or result.stdout).strip() or f"exit code={result.returncode}"
        raise LerobotCommandError(f"lerobot script failed ({script_name}): {detail}")

    return result


def start_lerobot(*, strict: bool = True) -> subprocess.CompletedProcess[str]:
    """Start the lerobot_ros2 Docker stack."""
    return _run_lerobot_script("up", strict=strict)


def stop_lerobot(*, strict: bool = True) -> subprocess.CompletedProcess[str]:
    """Stop the lerobot_ros2 Docker stack."""
    return _run_lerobot_script("down", strict=strict)


def get_lerobot_service_state(service: str) -> dict:
    """Return docker service state as a dict (empty on failure)."""
    compose_file = get_lerobot_compose_file()
    if not compose_file.exists():
        return {}
    result = get_docker_service_summary(service)
    if not result:
        return {}
    return {
        "State": result.get("state"),
        "Status": result.get("status_detail"),
        "RunningFor": result.get("running_for"),
        "ID": result.get("container_id"),
        "CreatedAt": result.get("created_at"),
        "Service": result.get("service"),
    }


def stop_lerobot_on_backend_startup(logger: logging.Logger | None = None) -> None:
    """Best-effort shutdown of stale lerobot containers on backend startup."""
    active_logger = logger or logging.getLogger(__name__)
    result = stop_lerobot(strict=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit code={result.returncode}"
        active_logger.warning("lerobot startup cleanup failed: %s", detail)


def start_lerobot_on_backend_startup(logger: logging.Logger | None = None) -> None:
    """Start lerobot_ros2 in the background during backend startup."""
    active_logger = logger or logging.getLogger(__name__)
    if shutil.which("docker") is None:
        active_logger.warning("docker command not found; skip lerobot startup")
        return

    def _runner() -> None:
        result = start_lerobot(strict=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or f"exit code={result.returncode}"
            active_logger.warning("Failed to start lerobot stack on backend startup: %s", detail)
        else:
            active_logger.info("lerobot stack started on backend startup")

    threading.Thread(target=_runner, name="lerobot-startup", daemon=True).start()

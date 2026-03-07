"""Services for machine-scoped settings and user-scoped secrets."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from interfaces_backend.models.settings import (
    BundledTorchDefaultsModel,
    FeaturesRepoSettingsModel,
    HuggingFaceSecretStatusModel,
    SystemSettingsModel,
)
from percus_ai.storage import get_system_settings_path, get_user_secrets_path


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_token(token: str) -> str:
    if len(token) <= 10:
        return "*" * len(token)
    return f"{token[:6]}...{token[-4:]}"


class SystemSettingsService:
    """Machine-scoped settings persistence."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or get_system_settings_path()
        self._lock = threading.RLock()

    def get_settings(self) -> SystemSettingsModel:
        with self._lock:
            data = self._read()
        bundled = data.get("bundled_torch") or {}
        return SystemSettingsModel(
            bundled_torch=BundledTorchDefaultsModel(
                pytorch_version=str(bundled.get("pytorch_version") or "v2.8.0"),
                torchvision_version=str(bundled.get("torchvision_version") or "v0.23.0"),
            ),
            features_repo=FeaturesRepoSettingsModel(
                repo_url=str(
                    ((data.get("features_repo") or {}).get("repo_url"))
                    or "https://github.com/percus-ai/physical-ai-features.git"
                ),
                repo_ref=str(
                    ((data.get("features_repo") or {}).get("repo_ref"))
                    or "main"
                ),
                repo_commit=str(((data.get("features_repo") or {}).get("repo_commit")) or "").strip() or None,
            ),
            updated_at=data.get("updated_at"),
        )

    def update_settings(
        self,
        *,
        pytorch_version: str | None = None,
        torchvision_version: str | None = None,
        features_repo_url: str | None = None,
        features_repo_ref: str | None = None,
        features_repo_commit: str | None = None,
    ) -> SystemSettingsModel:
        with self._lock:
            data = self._read()
            bundled = data.setdefault("bundled_torch", {})
            features_repo = data.setdefault("features_repo", {})
            if pytorch_version is not None:
                bundled["pytorch_version"] = pytorch_version
            if torchvision_version is not None:
                bundled["torchvision_version"] = torchvision_version
            if features_repo_url is not None:
                features_repo["repo_url"] = features_repo_url
            if features_repo_ref is not None:
                features_repo["repo_ref"] = features_repo_ref
            if features_repo_commit is not None:
                features_repo["repo_commit"] = features_repo_commit or None
            data["updated_at"] = _utcnow_iso()
            self._write(data)
        return self.get_settings()

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class UserSecretsService:
    """User-scoped secret persistence."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or get_user_secrets_path()
        self._lock = threading.RLock()

    def get_huggingface_status(self, user_id: str) -> HuggingFaceSecretStatusModel:
        record = self._get_user_record(user_id)
        token = str(record.get("huggingface_token") or "").strip()
        updated_at = record.get("updated_at")
        return HuggingFaceSecretStatusModel(
            has_token=bool(token),
            token_preview=_mask_token(token) if token else None,
            updated_at=updated_at,
        )

    def get_huggingface_token(self, user_id: str) -> str | None:
        record = self._get_user_record(user_id)
        token = str(record.get("huggingface_token") or "").strip()
        return token or None

    def set_huggingface_token(self, user_id: str, token: str | None, *, clear: bool = False) -> HuggingFaceSecretStatusModel:
        with self._lock:
            data = self._read()
            users = data.setdefault("users", {})
            if clear:
                users[user_id] = {"updated_at": _utcnow_iso()}
            else:
                normalized = (token or "").strip()
                if not normalized:
                    raise ValueError("huggingface_token is required")
                users[user_id] = {
                    "huggingface_token": normalized,
                    "updated_at": _utcnow_iso(),
                }
            self._write(data)
        return self.get_huggingface_status(user_id)

    def _get_user_record(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._read()
        return dict((data.get("users") or {}).get(user_id) or {})

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass


_system_settings_service: SystemSettingsService | None = None
_user_secrets_service: UserSecretsService | None = None


def get_system_settings_service() -> SystemSettingsService:
    global _system_settings_service
    if _system_settings_service is None:
        _system_settings_service = SystemSettingsService()
    return _system_settings_service


def get_user_secrets_service() -> UserSecretsService:
    global _user_secrets_service
    if _user_secrets_service is None:
        _user_secrets_service = UserSecretsService()
    return _user_secrets_service


def resolve_huggingface_token_for_user(user_id: str) -> str | None:
    """Resolve HF token for a specific authenticated user."""
    return get_user_secrets_service().get_huggingface_token(user_id)

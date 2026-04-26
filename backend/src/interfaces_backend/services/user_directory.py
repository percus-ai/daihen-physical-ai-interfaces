from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from supabase._async.client import AsyncClient

from percus_ai.db import get_supabase_async_client, get_supabase_service_client
from percus_ai.storage import get_storage_root
_directory_cache: dict[str, "UserDirectoryEntry"] = {}

_USERNAME_INVALID_CHARS = re.compile(r"[^a-z0-9._-]+")
_USERNAME_EDGE_CHARS = "._-"
_MAX_USERNAME_LENGTH = 64
_MAX_NAME_LENGTH = 64


@dataclass(frozen=True, slots=True)
class UserDirectoryEntry:
    user_id: str
    email: str = ""
    username: str = ""
    first_name: str = ""
    last_name: str = ""
    name: str = ""
    updated_at: str | None = None


def normalize_username(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    normalized = _USERNAME_INVALID_CHARS.sub("-", normalized)
    normalized = normalized.strip(_USERNAME_EDGE_CHARS)
    normalized = normalized[:_MAX_USERNAME_LENGTH].strip(_USERNAME_EDGE_CHARS)
    return normalized


def normalize_person_name(value: str | None) -> str:
    return str(value or "").strip()[:_MAX_NAME_LENGTH]


def validate_username_input(value: str | None) -> None:
    if value is None:
        return
    raw = str(value).strip()
    if not raw:
        return
    if not normalize_username(raw):
        raise ValueError("username is invalid")


def username_from_email(email: str | None) -> str:
    local_part = str(email or "").strip().split("@", 1)[0]
    normalized = normalize_username(local_part)
    return normalized or "user"


def build_user_name(
    *,
    user_id: str | None = None,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
) -> str:
    normalized_first_name = normalize_person_name(first_name)
    normalized_last_name = normalize_person_name(last_name)
    if normalized_last_name and normalized_first_name:
        return f"{normalized_last_name} {normalized_first_name}"
    if normalized_last_name:
        return normalized_last_name
    if normalized_first_name:
        return normalized_first_name

    normalized_username = normalize_username(username)
    if normalized_username:
        return normalized_username

    normalized_email = str(email or "").strip()
    if normalized_email:
        local_fallback = username_from_email(normalized_email)
        if local_fallback:
            return local_fallback
        return normalized_email

    return str(user_id or "").strip()


def clear_user_directory_cache(user_id: str | None = None) -> None:
    if user_id is None:
        _directory_cache.clear()
        return
    _directory_cache.pop(str(user_id).strip(), None)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_profiles_path() -> Path:
    return get_storage_root() / "user-profiles.json"


def _read_local_profiles() -> dict[str, dict[str, str | None]]:
    path = _local_profiles_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    users = data.get("users") if isinstance(data, dict) else {}
    if not isinstance(users, dict):
        return {}
    return {
        str(user_id).strip(): dict(record or {})
        for user_id, record in users.items()
        if str(user_id).strip()
    }


def _write_local_profiles(users: dict[str, dict[str, str | None]]) -> None:
    path = _local_profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"users": users}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


async def _get_service_client() -> Optional[AsyncClient]:
    return await get_supabase_service_client()


async def _fetch_profiles(user_ids: list[str]) -> dict[str, dict[str, str | None]]:
    normalized_ids = [str(user_id).strip() for user_id in user_ids if str(user_id).strip()]
    if not normalized_ids:
        return {}

    client = await _get_service_client()
    if client is None:
        local_profiles = _read_local_profiles()
        return {
            user_id: local_profiles.get(user_id, {})
            for user_id in normalized_ids
            if local_profiles.get(user_id)
        }

    try:
        rows = (
            await client.table("user_profiles")
            .select("user_id,username,first_name,last_name,updated_at")
            .in_("user_id", list(dict.fromkeys(normalized_ids)))
            .execute()
        ).data or []
    except Exception:
        return {}

    profiles: dict[str, dict[str, str | None]] = {}
    for row in rows:
        user_id = str(row.get("user_id") or "").strip()
        if not user_id:
            continue
        profiles[user_id] = {
            "username": normalize_username(row.get("username")),
            "first_name": normalize_person_name(row.get("first_name")),
            "last_name": normalize_person_name(row.get("last_name")),
            "updated_at": row.get("updated_at"),
        }
    return profiles


async def _fetch_emails(user_ids: list[str]) -> dict[str, str]:
    normalized_ids = [str(user_id).strip() for user_id in user_ids if str(user_id).strip()]
    if not normalized_ids:
        return {}

    client = await _get_service_client()
    if client is None:
        return {}

    emails: dict[str, str] = {}
    for user_id in normalized_ids:
        try:
            response = await client.auth.admin.get_user_by_id(user_id)
            email = str(response.user.email or "").strip()
            if email:
                emails[user_id] = email
        except Exception:
            continue
    return emails


async def resolve_user_directory_entries(user_ids: list[str]) -> dict[str, UserDirectoryEntry]:
    normalized_ids = [str(user_id).strip() for user_id in user_ids if str(user_id).strip()]
    ordered_ids = list(dict.fromkeys(normalized_ids))
    pending_ids = [user_id for user_id in ordered_ids if user_id not in _directory_cache]
    if pending_ids:
        profiles, emails = await asyncio.gather(_fetch_profiles(pending_ids), _fetch_emails(pending_ids))
        for user_id in pending_ids:
            profile = profiles.get(user_id) or {}
            email = emails.get(user_id, "")
            entry = UserDirectoryEntry(
                user_id=user_id,
                email=email,
                username=normalize_username(profile.get("username")),
                first_name=normalize_person_name(profile.get("first_name")),
                last_name=normalize_person_name(profile.get("last_name")),
                name=build_user_name(
                    user_id=user_id,
                    username=profile.get("username"),
                    first_name=profile.get("first_name"),
                    last_name=profile.get("last_name"),
                    email=email,
                ),
                updated_at=profile.get("updated_at"),
            )
            _directory_cache[user_id] = entry

    return {
        user_id: _directory_cache.get(user_id, UserDirectoryEntry(user_id=user_id, name=user_id))
        for user_id in ordered_ids
    }


async def get_user_directory_entry(user_id: str) -> UserDirectoryEntry:
    entries = await resolve_user_directory_entries([user_id])
    normalized_user_id = str(user_id).strip()
    return entries.get(normalized_user_id, UserDirectoryEntry(user_id=normalized_user_id, name=normalized_user_id))


async def update_user_profile(
    user_id: str,
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> UserDirectoryEntry:
    normalized_user_id = str(user_id).strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")
    validate_username_input(username)

    try:
        client = await get_supabase_async_client()
    except ValueError:
        users = _read_local_profiles()
        existing = users.get(normalized_user_id, {})
        normalized_username = (
            normalize_username(username)
            if username is not None
            else normalize_username(existing.get("username"))
        )
        normalized_first_name = (
            normalize_person_name(first_name)
            if first_name is not None
            else normalize_person_name(existing.get("first_name"))
        )
        normalized_last_name = (
            normalize_person_name(last_name)
            if last_name is not None
            else normalize_person_name(existing.get("last_name"))
        )
        users[normalized_user_id] = {
            "username": normalized_username or None,
            "first_name": normalized_first_name or None,
            "last_name": normalized_last_name or None,
            "updated_at": _utcnow_iso(),
        }
        _write_local_profiles(users)
        clear_user_directory_cache(normalized_user_id)
        return await get_user_directory_entry(normalized_user_id)

    existing_rows = (
        await client.table("user_profiles")
        .select("user_id,username,first_name,last_name")
        .eq("user_id", normalized_user_id)
        .execute()
    ).data or []
    existing = existing_rows[0] if existing_rows else {}

    normalized_username = (
        normalize_username(username)
        if username is not None
        else normalize_username(existing.get("username"))
    )
    normalized_first_name = (
        normalize_person_name(first_name)
        if first_name is not None
        else normalize_person_name(existing.get("first_name"))
    )
    normalized_last_name = (
        normalize_person_name(last_name)
        if last_name is not None
        else normalize_person_name(existing.get("last_name"))
    )

    payload = {
        "username": normalized_username or None,
        "first_name": normalized_first_name or None,
        "last_name": normalized_last_name or None,
        "updated_at": _utcnow_iso(),
    }
    if existing_rows:
        try:
            await client.table("user_profiles").update(payload).eq("user_id", normalized_user_id).execute()
        except Exception as exc:
            raise ValueError("user profile update failed") from exc
    else:
        insert_payload = {
            "user_id": normalized_user_id,
            "username": normalized_username or None,
            "first_name": normalized_first_name or None,
            "last_name": normalized_last_name or None,
        }
        try:
            await client.table("user_profiles").insert(insert_payload).execute()
        except Exception as exc:
            raise ValueError("user profile insert failed") from exc

    clear_user_directory_cache(normalized_user_id)
    return await get_user_directory_entry(normalized_user_id)

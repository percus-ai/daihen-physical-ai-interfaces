"""Supabase session management for local backend usage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from percus_ai.db import clear_supabase_session, get_supabase_session, set_supabase_session
from percus_ai.storage import get_storage_root


def _session_path() -> Path:
    return get_storage_root() / "supabase_session.json"


def load_supabase_session() -> Optional[dict[str, Any]]:
    path = _session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    set_supabase_session(data)
    return data


def save_supabase_session(session: dict[str, Any]) -> None:
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, ensure_ascii=True), encoding="utf-8")
    set_supabase_session(session)


def clear_supabase_session_file() -> None:
    path = _session_path()
    if path.exists():
        path.unlink()
    clear_supabase_session()


def get_cached_supabase_session() -> Optional[dict[str, Any]]:
    return get_supabase_session()

"""
Path utilities for Physical AI data directory management.

This module provides centralized path resolution for all data-related paths
in the interfaces backend. It mirrors the functionality in
percus_ai.core.paths for consistency.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file() -> None:
    """Load environment variables from .env file.

    Search order:
    1. {cwd}/data/.env (project-local)
    2. ~/.physical-ai/.env (user-global)
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    # Project's data/.env takes priority
    cwd_env = Path.cwd() / "data" / ".env"
    if cwd_env.exists():
        load_dotenv(cwd_env)
        return

    # Fallback: ~/.physical-ai/.env
    home_env = Path.home() / ".physical-ai" / ".env"
    if home_env.exists():
        load_dotenv(home_env)


# Load .env file on module import
load_env_file()


def get_data_dir() -> Path:
    """Get the data directory path.

    Returns the path specified by PHYSICAL_AI_DATA_DIR environment variable,
    or ~/.physical-ai if not set.
    """
    data_dir = os.environ.get("PHYSICAL_AI_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser().resolve()
    return Path.home() / ".physical-ai"


def get_venv_dir() -> Path:
    """Get the virtual environments directory path."""
    return get_data_dir() / "envs"


def get_cache_dir() -> Path:
    """Get the cache directory path."""
    return get_data_dir() / ".cache"


def get_datasets_dir() -> Path:
    """Get the datasets directory path."""
    return get_data_dir() / "datasets"


def get_models_dir() -> Path:
    """Get the models directory path."""
    return get_data_dir() / "models"


def get_projects_dir() -> Path:
    """Get the projects directory path."""
    return get_data_dir() / "projects"


def get_project_root() -> Path:
    """Get the project root directory.

    Search order:
    1. PHYSICAL_AI_PROJECT_ROOT environment variable
    2. Marker file search from current working directory
    3. Fallback to current working directory
    """
    root = os.environ.get("PHYSICAL_AI_PROJECT_ROOT")
    if root:
        return Path(root).resolve()

    # Search for marker files
    markers = ["envs/policy_map.yaml", "data/.env", ".gitmodules"]
    current = Path.cwd()
    for _ in range(10):
        for marker in markers:
            if (current / marker).exists():
                return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    return Path.cwd()


def get_features_path() -> Path:
    """Get the features submodule path."""
    return get_project_root() / "features"

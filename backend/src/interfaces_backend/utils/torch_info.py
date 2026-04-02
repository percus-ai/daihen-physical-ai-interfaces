"""Torch info utilities using subprocess to avoid numpy conflicts."""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from percus_ai.environment.torch_runtime_probe import run_torch_runtime_probe

# Cache for torch info
_torch_info_cache: Optional[Dict[str, Any]] = None


def get_torch_info(use_cache: bool = True) -> Dict[str, Any]:
    """Get PyTorch/CUDA information via subprocess.

    Args:
        use_cache: Whether to use cached result.

    Returns:
        Dictionary with torch_version, cuda_available, cuda_version,
        gpu_name, gpu_count, mps_available, cuda_memory_total,
        cuda_memory_free, error.
    """
    global _torch_info_cache
    if use_cache and _torch_info_cache is not None:
        return _torch_info_cache

    info: Dict[str, Any] = {
        "torch_version": None,
        "cuda_available": False,
        "cuda_version": None,
        "cuda_supported_arches": None,
        "gpu_capability": None,
        "cuda_compatible": None,
        "gpu_name": None,
        "gpu_count": 0,
        "mps_available": False,
        "cuda_memory_total": None,
        "cuda_memory_free": None,
        "error": None,
    }

    # Build PYTHONPATH with bundled-torch if it exists.
    # Note: bundled-torch extensions are Python-minor-version specific.
    bundled_torch = Path.home() / ".cache" / "daihen-physical-ai" / "bundled-torch"
    env = os.environ.copy()
    if (bundled_torch / "pytorch").is_dir():
        pytorch_path = str(bundled_torch / "pytorch")
        torchvision_path = str(bundled_torch / "torchvision")
        env["PYTHONPATH"] = f"{pytorch_path}:{torchvision_path}:{env.get('PYTHONPATH', '')}"

    # Prefer the bundled-torch build venv when present. The backend may run under a
    # different Python (e.g. system Python 3.12), which cannot import cp310
    # extensions built for bundled-torch.
    probe_python = bundled_torch / ".venv" / "bin" / "python"
    python_exe = str(probe_python) if probe_python.exists() else sys.executable

    try:
        ok, payload = run_torch_runtime_probe(
            python_path=python_exe,
            env=env,
            cwd=Path.cwd(),
            timeout=15,
        )
        if ok:
            info = payload
        else:
            info["error"] = (
                str(payload.get("stderr") or payload.get("stdout") or payload.get("error") or "").strip()
                or "Failed to get PyTorch info"
            )
    except Exception as e:
        info["error"] = str(e)

    if use_cache:
        _torch_info_cache = info
    return info


def clear_cache() -> None:
    """Clear the torch info cache."""
    global _torch_info_cache
    _torch_info_cache = None

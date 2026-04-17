"""Torch info utilities using subprocess."""

import sys
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

    try:
        ok, payload = run_torch_runtime_probe(
            python_path=sys.executable,
            env=None,
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

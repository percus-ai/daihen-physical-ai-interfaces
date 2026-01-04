"""Inference API router."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from interfaces_backend.models.inference import (
    InferenceModelInfo,
    InferenceModelsResponse,
    InferenceDeviceCompatibility,
    InferenceDeviceCompatibilityResponse,
    InferenceRunRequest,
    InferenceRunResponse,
)

router = APIRouter(prefix="/api/inference", tags=["inference"])

# Models directory (integrated with storage system)
DATA_DIR = Path(os.environ.get("PHI_DATA_DIR", Path.cwd() / "data"))
MODELS_DIR = DATA_DIR / "models"

# Archive scripts directory (for execute_policy_on_robot.py)
ARCHIVE_SCRIPTS_DIR = Path.cwd() / "archive" / "scripts" / "framework"


def _get_percus_inference():
    """Import percus_ai.inference if available."""
    try:
        from percus_ai.inference import PolicyExecutor, detect_device

        return PolicyExecutor, detect_device
    except ImportError:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.inference import PolicyExecutor, detect_device

                return PolicyExecutor, detect_device
            except ImportError:
                pass
    return None, None


def _detect_device() -> str:
    """Detect best available compute device."""
    _, detect_device = _get_percus_inference()
    if detect_device:
        return detect_device()

    # Fallback detection
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _list_models() -> list[dict]:
    """List available models for inference from storage directories."""
    import json

    if not MODELS_DIR.exists():
        return []

    models = []

    # Scan subdirectories: r2/, hub/, and direct models
    subdirs_to_scan = []

    # Add r2 models
    r2_dir = MODELS_DIR / "r2"
    if r2_dir.exists():
        subdirs_to_scan.extend(r2_dir.iterdir())

    # Add hub models
    hub_dir = MODELS_DIR / "hub"
    if hub_dir.exists():
        subdirs_to_scan.extend(hub_dir.iterdir())

    # Add direct models (for backward compatibility)
    for item in MODELS_DIR.iterdir():
        if item.is_dir() and item.name not in ("r2", "hub"):
            subdirs_to_scan.append(item)

    for model_dir in subdirs_to_scan:
        if not model_dir.is_dir():
            continue

        config_file = model_dir / "config.json"
        if not config_file.exists():
            continue

        try:
            with open(config_file) as f:
                config = json.load(f)

            # Determine source from path
            source = "local"
            if "r2" in model_dir.parts:
                source = "r2"
            elif "hub" in model_dir.parts:
                source = "hub"

            models.append({
                "model_id": model_dir.name,
                "name": model_dir.name,
                "policy_type": config.get("type", "unknown"),
                "local_path": str(model_dir),
                "source": source,
                "size_mb": sum(
                    f.stat().st_size for f in model_dir.rglob("*") if f.is_file()
                ) / (1024 * 1024),
            })
        except Exception:
            continue

    return models


@router.get("/models", response_model=InferenceModelsResponse)
async def list_inference_models():
    """List models available for inference."""
    models_data = _list_models()

    models = []
    for m in models_data:
        models.append(
            InferenceModelInfo(
                model_id=m.get("model_id", m.get("name", "")),
                name=m.get("name", ""),
                policy_type=m.get("policy_type", "unknown"),
                local_path=m.get("local_path"),
                size_mb=m.get("size_mb", 0.0),
                is_loaded=False,  # No longer tracking loaded state
            )
        )

    return InferenceModelsResponse(models=models, total=len(models))


@router.get("/device-compatibility", response_model=InferenceDeviceCompatibilityResponse)
async def get_device_compatibility():
    """Check device compatibility for inference."""
    devices = []

    # Check CUDA
    cuda_available = False
    cuda_memory_total = None
    cuda_memory_free = None
    try:
        import torch

        if torch.cuda.is_available():
            cuda_available = True
            cuda_memory_total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
            cuda_memory_free = (
                torch.cuda.get_device_properties(0).total_memory
                - torch.cuda.memory_allocated(0)
            ) / (1024 * 1024)
    except ImportError:
        pass

    devices.append(
        InferenceDeviceCompatibility(
            device="cuda",
            available=cuda_available,
            memory_total_mb=cuda_memory_total,
            memory_free_mb=cuda_memory_free,
        )
    )

    # Check MPS (Apple Silicon)
    mps_available = False
    try:
        import torch

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            mps_available = True
    except ImportError:
        pass

    devices.append(
        InferenceDeviceCompatibility(
            device="mps",
            available=mps_available,
            memory_total_mb=None,
            memory_free_mb=None,
        )
    )

    # CPU is always available
    devices.append(
        InferenceDeviceCompatibility(
            device="cpu",
            available=True,
            memory_total_mb=None,
            memory_free_mb=None,
        )
    )

    # Determine recommended device
    if cuda_available:
        recommended = "cuda"
    elif mps_available:
        recommended = "mps"
    else:
        recommended = "cpu"

    return InferenceDeviceCompatibilityResponse(
        devices=devices,
        recommended=recommended,
    )


def _find_model_path(model_id: str) -> Optional[Path]:
    """Find model path in storage directories."""
    # Check R2 models
    r2_path = MODELS_DIR / "r2" / model_id
    if r2_path.exists():
        return r2_path

    # Check Hub models
    hub_path = MODELS_DIR / "hub" / model_id
    if hub_path.exists():
        return hub_path

    # Check direct models directory
    direct_path = MODELS_DIR / model_id
    if direct_path.exists():
        return direct_path

    return None


@router.post("/run", response_model=InferenceRunResponse)
async def run_inference(request: InferenceRunRequest):
    """Run inference on robot with the specified model.

    This directly executes the policy on the robot using subprocess,
    similar to archive's ./daihen CLI.
    """
    model_id = request.model_id
    project = request.project
    episodes = request.episodes
    robot_type = request.robot_type
    device = request.device

    # Find model path
    model_path = _find_model_path(model_id)
    if not model_path:
        raise HTTPException(
            status_code=404,
            detail=f"Model not found: {model_id}. Check if it's downloaded in {MODELS_DIR}",
        )

    # Check if execute_policy_on_robot.py exists
    execute_script = ARCHIVE_SCRIPTS_DIR / "execute_policy_on_robot.py"
    if not execute_script.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Execute script not found: {execute_script}",
        )

    # Build command
    cmd = [
        "python",
        str(execute_script),
        "--project", project,
        "--policy-path", str(model_path),
        "--episodes", str(episodes),
        "--robot-type", robot_type,
    ]

    if device:
        cmd.extend(["--device", device])

    # Execute
    try:
        result = subprocess.run(
            cmd,
            cwd=Path.cwd(),
            capture_output=False,  # Let output flow to terminal
            text=True,
        )

        return InferenceRunResponse(
            success=result.returncode == 0,
            model_id=model_id,
            project=project,
            message="Inference completed" if result.returncode == 0 else "Inference failed",
            return_code=result.returncode,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run inference: {str(e)}",
        )

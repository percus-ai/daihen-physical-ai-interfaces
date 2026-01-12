from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from percus_ai.storage import (
    DatasetMetadata,
    DatasetType,
    DataSource,
    DataStatus,
    ManifestManager,
    ModelMetadata,
    ModelType,
    RecordingInfo,
    SyncInfo,
    TrainingInfo,
)


def write_project_yaml(base_dir: Path, project_id: str) -> Path:
    projects_dir = base_dir / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    content = "\n".join(
        [
            "project:",
            f"  name: {project_id}",
            f"  display_name: {project_id}",
            "  description: E2E test project",
            '  created_at: "2025-01-01"',
            "  version: 1.0",
            "  robot_type: so101",
            "recording:",
            "  episode_time_s: 20",
            "  reset_time_s: 10",
            "cameras: {}",
            "arms: {}",
            "",
        ]
    )

    project_path = projects_dir / f"{project_id}.yaml"
    project_path.write_text(content, encoding="utf-8")
    return project_path


def create_recording(base_dir: Path, project_id: str, episode_name: str) -> Path:
    episode_dir = base_dir / "datasets" / project_id / episode_name
    episode_dir.mkdir(parents=True, exist_ok=True)

    meta_path = episode_dir / "meta.json"
    meta_path.write_text(json.dumps({"episode": episode_name}), encoding="utf-8")
    return episode_dir


def create_dataset_metadata(
    base_dir: Path,
    dataset_id: str,
    project_id: str | None = None,
) -> DatasetMetadata:
    now = datetime.now(timezone.utc).isoformat()
    recording = RecordingInfo(
        robot_type="so101",
        cameras=[],
        fps=30,
        episode_count=1,
        total_frames=0,
        duration_seconds=0.0,
    )

    metadata = DatasetMetadata(
        id=dataset_id,
        short_id="test01",
        name=dataset_id.split("/")[-1],
        source=DataSource.R2,
        status=DataStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        dataset_type=DatasetType.RECORDED,
        project_id=project_id,
        recording=recording,
        sync=SyncInfo(size_bytes=0),
    )

    manifest = ManifestManager(base_dir)
    manifest.init_directories()
    manifest.register_dataset(metadata)
    return metadata


def create_model_metadata(base_dir: Path, model_id: str, dataset_id: str) -> ModelMetadata:
    now = datetime.now(timezone.utc).isoformat()
    metadata = ModelMetadata(
        id=model_id,
        name=model_id,
        source=DataSource.R2,
        status=DataStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        model_type=ModelType.TRAINED,
        policy_type="act",
        training=TrainingInfo(
            dataset_id=dataset_id,
            steps=1,
            created_at=now,
        ),
        sync=SyncInfo(size_bytes=0),
    )

    manifest = ManifestManager(base_dir)
    manifest.init_directories()
    manifest.register_model(metadata)
    return metadata


def write_inference_model_config(base_dir: Path, model_id: str) -> Path:
    model_dir = base_dir / "models" / model_id
    model_dir.mkdir(parents=True, exist_ok=True)

    config_path = model_dir / "config.json"
    config_path.write_text(json.dumps({"type": "act"}), encoding="utf-8")
    return model_dir

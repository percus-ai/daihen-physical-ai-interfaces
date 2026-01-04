"""Manifest management for datasets and models."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from interfaces_backend.models.storage import (
    DatasetMetadata,
    DataSource,
    DataStatus,
    Manifest,
    ManifestEntry,
    ModelMetadata,
    ProjectEntry,
    ProjectMetadata,
)
from interfaces_backend.services.storage.hash import compute_directory_hash, compute_directory_size

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


class ManifestManager:
    """Manages the global manifest and local storage structure."""

    def __init__(self, base_path: Optional[Path] = None):
        """Initialize manifest manager.

        Args:
            base_path: Base path for storage.
                       Defaults to PHI_DATA_DIR env var, or ./data
        """
        if base_path:
            self.base_path = base_path
        elif os.environ.get("PHI_DATA_DIR"):
            self.base_path = Path(os.environ["PHI_DATA_DIR"])
        else:
            # Default to ./data relative to current working directory
            self.base_path = Path.cwd() / "data"
        self.manifest_path = self.base_path / "manifest.json"

        self._manifest: Optional[Manifest] = None

    @property
    def manifest(self) -> Manifest:
        """Get or load the manifest."""
        if self._manifest is None:
            self._manifest = self._load_manifest()
        return self._manifest

    def reload(self) -> None:
        """Reload manifest from disk."""
        self._manifest = self._load_manifest()
        logger.debug("Reloaded manifest from disk")

    def _load_manifest(self) -> Manifest:
        """Load manifest from disk or create new one."""
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text())
                return Manifest(**data)
            except Exception as e:
                logger.warning(f"Failed to load manifest: {e}, creating new one")

        return Manifest(last_updated=_now_iso())

    def save(self) -> None:
        """Save manifest to disk."""
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(self.manifest.model_dump(), indent=2, ensure_ascii=False)
        )
        logger.debug(f"Saved manifest to {self.manifest_path}")

    def init_directories(self) -> None:
        """Initialize the directory structure."""
        dirs = [
            self.base_path / "projects",
            self.base_path / "datasets" / "r2",
            self.base_path / "datasets" / "hub",
            self.base_path / "models" / "r2",
            self.base_path / "models" / "hub",
            self.base_path / "archive" / "datasets",
            self.base_path / "archive" / "models",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created directory: {d}")

    # --- Dataset Operations ---

    def get_dataset_path(self, dataset_id: str, source: DataSource) -> Path:
        """Get the local path for a dataset."""
        subdir = "r2" if source == DataSource.R2 else "hub"
        return self.base_path / "datasets" / subdir / dataset_id

    def get_dataset(self, dataset_id: str) -> Optional[DatasetMetadata]:
        """Get dataset metadata by ID."""
        entry = self.manifest.datasets.get(dataset_id)
        if not entry:
            return None

        meta_path = self.base_path / entry.path / ".meta.json"
        if meta_path.exists():
            try:
                data = json.loads(meta_path.read_text())
                return DatasetMetadata(**data)
            except Exception as e:
                logger.error(f"Failed to load dataset metadata {dataset_id}: {e}")

        # Return minimal metadata from manifest entry for remote-only datasets
        from interfaces_backend.models.storage import DatasetType, SyncInfo
        return DatasetMetadata(
            id=dataset_id,
            name=dataset_id,
            source=entry.source,
            status=entry.status,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            dataset_type=DatasetType(entry.type) if entry.type else DatasetType.RECORDED,
            sync=SyncInfo(size_bytes=entry.size_bytes, hash=entry.hash),
        )

    def list_datasets(
        self,
        source: Optional[DataSource] = None,
        status: DataStatus = DataStatus.ACTIVE,
    ) -> List[DatasetMetadata]:
        """List all datasets matching criteria."""
        results = []
        for dataset_id, entry in self.manifest.datasets.items():
            if status and entry.status != status:
                continue
            if source and entry.source != source:
                continue

            metadata = self.get_dataset(dataset_id)
            if metadata:
                results.append(metadata)

        return results

    def register_dataset(self, metadata: DatasetMetadata) -> ManifestEntry:
        """Register a new dataset in the manifest (with local files)."""
        path = self.get_dataset_path(metadata.id, metadata.source)
        path.mkdir(parents=True, exist_ok=True)

        meta_path = path / ".meta.json"
        meta_path.write_text(
            json.dumps(metadata.model_dump(), indent=2, ensure_ascii=False)
        )

        entry = ManifestEntry(
            path=str(path.relative_to(self.base_path)),
            source=metadata.source,
            type=metadata.dataset_type.value,
            hash=metadata.sync.hash,
            size_bytes=metadata.sync.size_bytes,
            status=metadata.status,
        )
        self.manifest.datasets[metadata.id] = entry
        self.manifest.last_updated = _now_iso()
        self.save()

        logger.info(f"Registered dataset: {metadata.id}")
        return entry

    def register_dataset_remote(self, metadata: DatasetMetadata) -> ManifestEntry:
        """Register a remote-only dataset in the manifest (no local files).

        Used for datasets that exist on R2 but haven't been downloaded.
        """
        path = self.get_dataset_path(metadata.id, metadata.source)

        entry = ManifestEntry(
            path=str(path.relative_to(self.base_path)),
            source=metadata.source,
            type=metadata.dataset_type.value,
            hash=metadata.sync.hash,
            size_bytes=metadata.sync.size_bytes,
            status=metadata.status,
        )
        self.manifest.datasets[metadata.id] = entry
        self.manifest.last_updated = _now_iso()
        self.save()

        logger.info(f"Registered remote dataset: {metadata.id}")
        return entry

    def update_dataset(self, metadata: DatasetMetadata) -> None:
        """Update dataset metadata."""
        entry = self.manifest.datasets.get(metadata.id)
        if not entry:
            raise ValueError(f"Dataset not found: {metadata.id}")

        path = self.base_path / entry.path
        meta_path = path / ".meta.json"

        metadata.updated_at = _now_iso()
        meta_path.write_text(
            json.dumps(metadata.model_dump(), indent=2, ensure_ascii=False)
        )

        entry.hash = metadata.sync.hash
        entry.size_bytes = metadata.sync.size_bytes
        entry.status = metadata.status
        self.manifest.last_updated = _now_iso()
        self.save()

    def refresh_dataset_hash(self, dataset_id: str) -> Optional[str]:
        """Recalculate and update hash for a dataset."""
        metadata = self.get_dataset(dataset_id)
        if not metadata:
            return None

        entry = self.manifest.datasets.get(dataset_id)
        if not entry:
            return None

        path = self.base_path / entry.path
        new_hash = compute_directory_hash(path)
        new_size = compute_directory_size(path)

        metadata.sync.hash = new_hash
        metadata.sync.size_bytes = new_size
        metadata.sync.last_synced_at = _now_iso()
        self.update_dataset(metadata)

        return new_hash

    # --- Model Operations ---

    def get_model_path(self, model_id: str, source: DataSource) -> Path:
        """Get the local path for a model."""
        subdir = "r2" if source == DataSource.R2 else "hub"
        return self.base_path / "models" / subdir / model_id

    def _guess_policy_type(self, model_id: str) -> str:
        """Guess policy type from model ID."""
        model_id_lower = model_id.lower()
        if "act" in model_id_lower:
            return "act"
        elif "pi0" in model_id_lower or "pi05" in model_id_lower:
            return "pi0"
        elif "diffusion" in model_id_lower:
            return "diffusion"
        return "unknown"

    def get_model(self, model_id: str) -> Optional[ModelMetadata]:
        """Get model metadata by ID."""
        entry = self.manifest.models.get(model_id)
        if not entry:
            return None

        meta_path = self.base_path / entry.path / ".meta.json"
        if meta_path.exists():
            try:
                data = json.loads(meta_path.read_text())
                return ModelMetadata(**data)
            except Exception as e:
                logger.error(f"Failed to load model metadata {model_id}: {e}")

        # Return minimal metadata from manifest entry for remote-only models
        from interfaces_backend.models.storage import ModelType, SyncInfo
        return ModelMetadata(
            id=model_id,
            name=model_id,
            source=entry.source,
            status=entry.status,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            model_type=ModelType(entry.type) if entry.type else ModelType.TRAINED,
            policy_type=self._guess_policy_type(model_id),
            sync=SyncInfo(size_bytes=entry.size_bytes, hash=entry.hash),
        )

    def list_models(
        self,
        source: Optional[DataSource] = None,
        status: DataStatus = DataStatus.ACTIVE,
    ) -> List[ModelMetadata]:
        """List all models matching criteria."""
        results = []
        for model_id, entry in self.manifest.models.items():
            if status and entry.status != status:
                continue
            if source and entry.source != source:
                continue

            metadata = self.get_model(model_id)
            if metadata:
                results.append(metadata)

        return results

    def register_model(self, metadata: ModelMetadata) -> ManifestEntry:
        """Register a new model in the manifest (with local files)."""
        path = self.get_model_path(metadata.id, metadata.source)
        path.mkdir(parents=True, exist_ok=True)

        meta_path = path / ".meta.json"
        meta_path.write_text(
            json.dumps(metadata.model_dump(), indent=2, ensure_ascii=False)
        )

        entry = ManifestEntry(
            path=str(path.relative_to(self.base_path)),
            source=metadata.source,
            type=metadata.model_type.value,
            hash=metadata.sync.hash,
            size_bytes=metadata.sync.size_bytes,
            status=metadata.status,
        )
        self.manifest.models[metadata.id] = entry
        self.manifest.last_updated = _now_iso()
        self.save()

        logger.info(f"Registered model: {metadata.id}")
        return entry

    def register_model_remote(self, metadata: ModelMetadata) -> ManifestEntry:
        """Register a remote-only model in the manifest (no local files).

        Used for models that exist on R2 but haven't been downloaded.
        """
        path = self.get_model_path(metadata.id, metadata.source)

        entry = ManifestEntry(
            path=str(path.relative_to(self.base_path)),
            source=metadata.source,
            type=metadata.model_type.value,
            hash=metadata.sync.hash,
            size_bytes=metadata.sync.size_bytes,
            status=metadata.status,
        )
        self.manifest.models[metadata.id] = entry
        self.manifest.last_updated = _now_iso()
        self.save()

        logger.info(f"Registered remote model: {metadata.id}")
        return entry

    def update_model(self, metadata: ModelMetadata) -> None:
        """Update model metadata."""
        entry = self.manifest.models.get(metadata.id)
        if not entry:
            raise ValueError(f"Model not found: {metadata.id}")

        path = self.base_path / entry.path
        meta_path = path / ".meta.json"

        metadata.updated_at = _now_iso()
        meta_path.write_text(
            json.dumps(metadata.model_dump(), indent=2, ensure_ascii=False)
        )

        entry.hash = metadata.sync.hash
        entry.size_bytes = metadata.sync.size_bytes
        entry.status = metadata.status
        self.manifest.last_updated = _now_iso()
        self.save()

    def refresh_model_hash(self, model_id: str) -> Optional[str]:
        """Recalculate and update hash for a model."""
        metadata = self.get_model(model_id)
        if not metadata:
            return None

        entry = self.manifest.models.get(model_id)
        if not entry:
            return None

        path = self.base_path / entry.path
        new_hash = compute_directory_hash(path)
        new_size = compute_directory_size(path)

        metadata.sync.hash = new_hash
        metadata.sync.size_bytes = new_size
        metadata.sync.last_synced_at = _now_iso()
        self.update_model(metadata)

        return new_hash

    # --- Archive Operations ---

    def archive_dataset(self, dataset_id: str) -> bool:
        """Archive (soft delete) a dataset."""
        metadata = self.get_dataset(dataset_id)
        if not metadata:
            return False

        entry = self.manifest.datasets.get(dataset_id)
        if not entry:
            return False

        old_path = self.base_path / entry.path
        new_path = self.base_path / "archive" / "datasets" / dataset_id

        if old_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)

        metadata.status = DataStatus.ARCHIVED
        metadata.archived_at = _now_iso()
        entry.path = str(new_path.relative_to(self.base_path))
        entry.status = DataStatus.ARCHIVED
        self.manifest.last_updated = _now_iso()

        meta_path = new_path / ".meta.json"
        meta_path.write_text(
            json.dumps(metadata.model_dump(), indent=2, ensure_ascii=False)
        )
        self.save()

        logger.info(f"Archived dataset: {dataset_id}")
        return True

    def restore_dataset(self, dataset_id: str) -> bool:
        """Restore a dataset from archive."""
        entry = self.manifest.datasets.get(dataset_id)
        if not entry or entry.status != DataStatus.ARCHIVED:
            return False

        metadata = self.get_dataset(dataset_id)
        if not metadata:
            return False

        old_path = self.base_path / entry.path
        new_path = self.get_dataset_path(dataset_id, metadata.source)

        if old_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)

        metadata.status = DataStatus.ACTIVE
        metadata.archived_at = None
        entry.path = str(new_path.relative_to(self.base_path))
        entry.status = DataStatus.ACTIVE
        self.manifest.last_updated = _now_iso()

        meta_path = new_path / ".meta.json"
        meta_path.write_text(
            json.dumps(metadata.model_dump(), indent=2, ensure_ascii=False)
        )
        self.save()

        logger.info(f"Restored dataset: {dataset_id}")
        return True

    def archive_model(self, model_id: str) -> bool:
        """Archive (soft delete) a model."""
        metadata = self.get_model(model_id)
        if not metadata:
            return False

        entry = self.manifest.models.get(model_id)
        if not entry:
            return False

        old_path = self.base_path / entry.path
        new_path = self.base_path / "archive" / "models" / model_id

        if old_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)

        metadata.status = DataStatus.ARCHIVED
        metadata.archived_at = _now_iso()
        entry.path = str(new_path.relative_to(self.base_path))
        entry.status = DataStatus.ARCHIVED
        self.manifest.last_updated = _now_iso()

        meta_path = new_path / ".meta.json"
        meta_path.write_text(
            json.dumps(metadata.model_dump(), indent=2, ensure_ascii=False)
        )
        self.save()

        logger.info(f"Archived model: {model_id}")
        return True

    def restore_model(self, model_id: str) -> bool:
        """Restore a model from archive."""
        entry = self.manifest.models.get(model_id)
        if not entry or entry.status != DataStatus.ARCHIVED:
            return False

        metadata = self.get_model(model_id)
        if not metadata:
            return False

        old_path = self.base_path / entry.path
        new_path = self.get_model_path(model_id, metadata.source)

        if old_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)

        metadata.status = DataStatus.ACTIVE
        metadata.archived_at = None
        entry.path = str(new_path.relative_to(self.base_path))
        entry.status = DataStatus.ACTIVE
        self.manifest.last_updated = _now_iso()

        meta_path = new_path / ".meta.json"
        meta_path.write_text(
            json.dumps(metadata.model_dump(), indent=2, ensure_ascii=False)
        )
        self.save()

        logger.info(f"Restored model: {model_id}")
        return True

    # --- Project Operations ---

    def get_project_path(self, project_id: str) -> Path:
        """Get the local path for a project config file."""
        return self.base_path / "projects" / f"{project_id}.yaml"

    def get_project(self, project_id: str) -> Optional[ProjectMetadata]:
        """Get project metadata by ID."""
        import yaml

        entry = self.manifest.projects.get(project_id)
        yaml_path = self.get_project_path(project_id)

        if not yaml_path.exists():
            if entry:
                # Remote-only project
                return ProjectMetadata(
                    id=project_id,
                    name=project_id,
                    display_name=project_id,
                    source=entry.source,
                    hash=entry.hash,
                    size_bytes=entry.size_bytes,
                )
            return None

        try:
            with open(yaml_path, "r") as f:
                data = yaml.safe_load(f)

            project_info = data.get("project", {})
            recording = data.get("recording", {})
            cameras = data.get("cameras", {})
            arms = data.get("arms", {})

            return ProjectMetadata(
                id=project_id,
                name=project_info.get("name", project_id),
                display_name=project_info.get("display_name", project_id),
                description=project_info.get("description"),
                version=project_info.get("version", "1.0"),
                robot_type=project_info.get("robot_type", "so101"),
                episode_time_s=recording.get("episode_time_s", 20),
                reset_time_s=recording.get("reset_time_s", 10),
                cameras=cameras,
                arms=arms,
                source=entry.source if entry else DataSource.R2,
                hash=entry.hash if entry else None,
                size_bytes=entry.size_bytes if entry else yaml_path.stat().st_size,
            )
        except Exception as e:
            logger.error(f"Failed to load project {project_id}: {e}")
            return None

    def list_projects(self, status: DataStatus = DataStatus.ACTIVE) -> List[ProjectMetadata]:
        """List all projects matching criteria."""
        import yaml

        results = []

        # First, scan local projects directory
        projects_dir = self.base_path / "projects"
        if projects_dir.exists():
            for yaml_file in projects_dir.glob("*.yaml"):
                project_id = yaml_file.stem
                metadata = self.get_project(project_id)
                if metadata:
                    results.append(metadata)

        # Add remote-only projects from manifest
        for project_id, entry in self.manifest.projects.items():
            if entry.status != status:
                continue
            # Check if already in results
            if any(p.id == project_id for p in results):
                continue
            # Remote-only project
            results.append(ProjectMetadata(
                id=project_id,
                name=project_id,
                display_name=project_id,
                source=entry.source,
                hash=entry.hash,
                size_bytes=entry.size_bytes,
            ))

        return results

    def register_project(self, project_id: str, path: Optional[str] = None) -> ProjectEntry:
        """Register a local project in the manifest."""
        yaml_path = self.get_project_path(project_id)
        project_path = path or f"projects/{project_id}.yaml"

        size_bytes = yaml_path.stat().st_size if yaml_path.exists() else 0

        entry = ProjectEntry(
            path=project_path,
            source=DataSource.R2,
            size_bytes=size_bytes,
            status=DataStatus.ACTIVE,
        )
        self.manifest.projects[project_id] = entry
        self.manifest.last_updated = _now_iso()
        self.save()

        logger.info(f"Registered project: {project_id}")
        return entry

    def register_project_remote(self, project_id: str, size_bytes: int = 0, hash: Optional[str] = None) -> ProjectEntry:
        """Register a remote-only project in the manifest."""
        entry = ProjectEntry(
            path=f"projects/{project_id}.yaml",
            source=DataSource.R2,
            size_bytes=size_bytes,
            hash=hash,
            status=DataStatus.ACTIVE,
        )
        self.manifest.projects[project_id] = entry
        self.manifest.last_updated = _now_iso()
        self.save()

        logger.info(f"Registered remote project: {project_id}")
        return entry

    def link_dataset_to_project(self, dataset_id: str, project_id: str) -> bool:
        """Link a dataset to a project."""
        if project_id not in self.manifest.projects:
            return False
        if dataset_id not in self.manifest.datasets:
            return False

        project = self.manifest.projects[project_id]
        if dataset_id not in project.datasets:
            project.datasets.append(dataset_id)
            self.manifest.last_updated = _now_iso()
            self.save()

        return True

    def link_model_to_project(self, model_id: str, project_id: str) -> bool:
        """Link a model to a project."""
        if project_id not in self.manifest.projects:
            return False
        if model_id not in self.manifest.models:
            return False

        project = self.manifest.projects[project_id]
        if model_id not in project.models:
            project.models.append(model_id)
            self.manifest.last_updated = _now_iso()
            self.save()

        return True

    # --- Storage Stats ---

    def get_storage_stats(self) -> Dict:
        """Get storage usage statistics (local only - items that exist on disk)."""
        stats = {
            "datasets_count": 0,
            "datasets_size_bytes": 0,
            "models_count": 0,
            "models_size_bytes": 0,
            "archive_count": 0,
            "archive_size_bytes": 0,
            # Remote-only stats (not downloaded locally)
            "remote_datasets_count": 0,
            "remote_datasets_size_bytes": 0,
            "remote_models_count": 0,
            "remote_models_size_bytes": 0,
        }

        for dataset_id, entry in self.manifest.datasets.items():
            # Check if local path exists (has actual files)
            local_path = self.base_path / entry.path
            is_local = local_path.exists() and any(local_path.iterdir()) if local_path.exists() else False

            if entry.status == DataStatus.ACTIVE:
                if is_local:
                    stats["datasets_count"] += 1
                    stats["datasets_size_bytes"] += entry.size_bytes
                else:
                    stats["remote_datasets_count"] += 1
                    stats["remote_datasets_size_bytes"] += entry.size_bytes
            else:
                stats["archive_count"] += 1
                stats["archive_size_bytes"] += entry.size_bytes

        for model_id, entry in self.manifest.models.items():
            # Check if local path exists (has actual files beyond just .meta.json)
            local_path = self.base_path / entry.path
            is_local = False
            if local_path.exists():
                files = list(local_path.iterdir())
                # Has files beyond just .meta.json
                is_local = len(files) > 1 or (len(files) == 1 and files[0].name != ".meta.json")

            if entry.status == DataStatus.ACTIVE:
                if is_local:
                    stats["models_count"] += 1
                    stats["models_size_bytes"] += entry.size_bytes
                else:
                    stats["remote_models_count"] += 1
                    stats["remote_models_size_bytes"] += entry.size_bytes
            else:
                stats["archive_count"] += 1
                stats["archive_size_bytes"] += entry.size_bytes

        stats["total_size_bytes"] = (
            stats["datasets_size_bytes"]
            + stats["models_size_bytes"]
            + stats["archive_size_bytes"]
        )

        stats["remote_total_size_bytes"] = (
            stats["remote_datasets_size_bytes"]
            + stats["remote_models_size_bytes"]
        )

        return stats

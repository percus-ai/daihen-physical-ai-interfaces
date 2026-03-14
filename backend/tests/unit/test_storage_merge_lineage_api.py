import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


def _install_lerobot_stubs() -> None:
    lerobot_module = sys.modules.setdefault("lerobot", ModuleType("lerobot"))
    datasets_module = sys.modules.setdefault("lerobot.datasets", ModuleType("lerobot.datasets"))
    aggregate_module = sys.modules.setdefault(
        "lerobot.datasets.aggregate",
        ModuleType("lerobot.datasets.aggregate"),
    )
    lerobot_dataset_module = sys.modules.setdefault(
        "lerobot.datasets.lerobot_dataset",
        ModuleType("lerobot.datasets.lerobot_dataset"),
    )

    setattr(aggregate_module, "aggregate_datasets", lambda **kwargs: None)

    class _DummyLeRobotDatasetMetadata:
        def __init__(self, *_args, **_kwargs):
            self.total_episodes = 0

    setattr(lerobot_dataset_module, "LeRobotDatasetMetadata", _DummyLeRobotDatasetMetadata)
    setattr(datasets_module, "aggregate", aggregate_module)
    setattr(datasets_module, "lerobot_dataset", lerobot_dataset_module)
    setattr(lerobot_module, "datasets", datasets_module)


def _load_storage_api_module():
    repo_root = _find_repo_root(Path(__file__).resolve())
    module_path = repo_root / "interfaces" / "backend" / "src" / "interfaces_backend" / "api" / "storage.py"
    spec = importlib.util.spec_from_file_location("storage_api_merge_lineage_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load storage module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_install_lerobot_stubs()
storage_api = _load_storage_api_module()


def test_dataset_row_to_info_includes_source_datasets(monkeypatch, tmp_path: Path):
    datasets_dir = tmp_path / "datasets"
    (datasets_dir / "dataset-merged").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(storage_api, "get_datasets_dir", lambda: datasets_dir)

    info = storage_api._dataset_row_to_info(
        {
            "id": "dataset-merged",
            "name": "Merged Dataset",
            "dataset_type": "merged",
            "source_datasets": [
                {
                    "dataset_id": "dataset-a",
                    "name": "Dataset A",
                    "content_hash": "md5:aaaa",
                    "task_detail": "pick cube",
                },
            ],
        }
    )

    assert info.dataset_type == "merged"
    assert len(info.source_datasets) == 1
    assert info.source_datasets[0].dataset_id == "dataset-a"
    assert info.source_datasets[0].task_detail == "pick cube"


def test_write_dataset_metadata_file_persists_merge_lineage(tmp_path: Path):
    dataset_root = tmp_path / "dataset-merged"
    dataset_root.mkdir(parents=True, exist_ok=True)
    (dataset_root / "data.txt").write_text("payload", encoding="utf-8")

    size_bytes = storage_api._write_dataset_metadata_file(
        dataset_id="dataset-merged",
        dataset_name="Merged Dataset",
        dataset_root=dataset_root,
        profile_snapshot={"profile_name": "profile-a"},
        content_hash="md5:1234",
        source_datasets=[
            storage_api.DatasetSourceInfo(
                dataset_id="dataset-a",
                name="Dataset A",
                content_hash="md5:aaaa",
                task_detail="pick cube",
            ),
            storage_api.DatasetSourceInfo(
                dataset_id="dataset-b",
                name="Dataset B",
                content_hash="md5:bbbb",
                task_detail="place cube",
            ),
        ],
    )

    meta_path = dataset_root / ".meta.json"
    assert meta_path.exists()
    payload = json.loads(meta_path.read_text(encoding="utf-8"))

    assert payload["dataset_type"] == "merged"
    assert payload["sync"]["hash"] == "md5:1234"
    assert payload["sync"]["size_bytes"] == size_bytes
    assert payload["source_datasets"] == [
        {
            "dataset_id": "dataset-a",
            "name": "Dataset A",
            "content_hash": "md5:aaaa",
            "task_detail": "pick cube",
        },
        {
            "dataset_id": "dataset-b",
            "name": "Dataset B",
            "content_hash": "md5:bbbb",
            "task_detail": "place cube",
        },
    ]

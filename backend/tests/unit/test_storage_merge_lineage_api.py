import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

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


class _FakeQuery:
    def __init__(self, rows_by_table, table_name: str):
        self._rows_by_table = rows_by_table
        self._table_name = table_name
        self._eq_filters: list[tuple[str, object]] = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self._eq_filters.append((key, value))
        return self

    async def execute(self):
        rows = list(self._rows_by_table.get(self._table_name, []))
        for key, value in self._eq_filters:
            rows = [row for row in rows if row.get(key) == value]
        return SimpleNamespace(data=rows)


class _FakeClient:
    def __init__(self, rows_by_table):
        self._rows_by_table = rows_by_table

    def table(self, name: str):
        return _FakeQuery(self._rows_by_table, name)


def test_resolve_dataset_info_includes_integrated_local_detail(monkeypatch, tmp_path: Path):
    datasets_dir = tmp_path / "datasets"
    (datasets_dir / "dataset-main").mkdir(parents=True, exist_ok=True)
    (datasets_dir / "dataset-source").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(storage_api, "get_datasets_dir", lambda: datasets_dir)

    class _FakeMetadata:
        def __init__(self, dataset_id: str, *, total_episodes: int, total_frames: int):
            self.dataset_id = dataset_id
            self.total_episodes = total_episodes
            self.total_frames = total_frames
            self.fps = 30
            self.video_path = "videos"
            self.video_keys = ["observation.images.front"]
            self.features = {
                "observation.images.front": {
                    "dtype": "video",
                    "shape": [1],
                    "info": {
                        "video.width": 640,
                        "video.height": 480,
                        "video.fps": 30,
                        "video.codec": "h264",
                        "video.pix_fmt": "yuv420p",
                    },
                },
                "observation.state": {
                    "dtype": "float32",
                    "shape": [7],
                    "names": ["j1", "j2", "j3", "j4", "j5", "j6", "j7"],
                },
            }
            self.episodes = []

    def _fake_metadata(dataset_id: str, root=None):
        if dataset_id == "dataset-main":
            return _FakeMetadata(dataset_id, total_episodes=12, total_frames=3600)
        if dataset_id == "dataset-source":
            return _FakeMetadata(dataset_id, total_episodes=5, total_frames=900)
        raise AssertionError(f"unexpected dataset id: {dataset_id}")

    async def _fake_resolve_user_directory_entries(_ids):
        return {"user-1": SimpleNamespace(name="Owner One", email="owner@example.com")}

    monkeypatch.setattr(storage_api, "LeRobotDatasetMetadata", _fake_metadata)
    monkeypatch.setattr(storage_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)

    client = _FakeClient(
        {
            "datasets": [
                {
                    "id": "dataset-main",
                    "name": "Dataset Main",
                    "owner_user_id": "user-1",
                    "status": "active",
                    "dataset_type": "merged",
                    "task_detail": "pick and place cubes",
                    "content_hash": "md5:main",
                    "episode_count": 12,
                    "size_bytes": 2048,
                    "source_datasets": [
                        {
                            "dataset_id": "dataset-source",
                            "name": "Dataset Source",
                            "content_hash": "md5:source",
                            "task_detail": "source task",
                        }
                    ],
                },
                {
                    "id": "dataset-source",
                    "name": "Dataset Source",
                    "status": "active",
                    "dataset_type": "recorded",
                    "task_detail": "source task",
                    "episode_count": 5,
                    "size_bytes": 1024,
                    "content_hash": "md5:source",
                },
            ]
        }
    )

    dataset = asyncio.run(
        storage_api._resolve_dataset_info(
            client,
            {
                "id": "dataset-main",
                "name": "Dataset Main",
                "owner_user_id": "user-1",
                "status": "active",
                "dataset_type": "merged",
                "task_detail": "pick and place cubes",
                "content_hash": "md5:main",
                "episode_count": 12,
                "size_bytes": 2048,
                "source_datasets": [
                    {
                        "dataset_id": "dataset-source",
                        "name": "Dataset Source",
                        "content_hash": "md5:source",
                        "task_detail": "source task",
                    }
                ],
            },
        )
    )

    assert dataset.owner_name == "Owner One"
    assert dataset.task_detail == "pick and place cubes"
    assert dataset.detail is not None
    assert dataset.detail.total_frames == 3600
    assert dataset.detail.fps == 30
    assert dataset.detail.camera_count == 1
    assert dataset.detail.signal_field_count == 1
    assert dataset.source_datasets[0].episode_count == 5
    assert dataset.source_datasets[0].total_frames == 900
    assert dataset.source_datasets[0].is_local is True


def test_resolve_dataset_info_keeps_local_detail_empty_when_dataset_is_not_synced(monkeypatch, tmp_path: Path):
    datasets_dir = tmp_path / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(storage_api, "get_datasets_dir", lambda: datasets_dir)

    async def _fake_resolve_user_directory_entries(_ids):
        return {}

    monkeypatch.setattr(storage_api, "resolve_user_directory_entries", _fake_resolve_user_directory_entries)

    dataset = asyncio.run(
        storage_api._resolve_dataset_info(
            _FakeClient({"datasets": []}),
            {
                "id": "dataset-remote",
                "name": "Dataset Remote",
                "status": "active",
                "dataset_type": "recorded",
                "episode_count": 3,
                "size_bytes": 512,
                "source_datasets": [],
            },
        )
    )

    assert dataset.is_local is False
    assert dataset.detail is None

import importlib.util
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


def _load_script_module():
    repo_root = _find_repo_root(Path(__file__).resolve())
    features_path = repo_root / "features"
    if str(features_path) not in sys.path:
        sys.path.insert(0, str(features_path))
    module_path = repo_root / "scripts" / "backfill_dataset_merge_lineage.py"
    spec = importlib.util.spec_from_file_location("backfill_dataset_merge_lineage_script_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load script module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backfill_script = _load_script_module()


def test_parse_dataset_ref_supports_name_and_explicit_id():
    parsed = backfill_script._parse_dataset_ref(
        "exp001_20260314_04 (cd858535-8cdb-4be6-b420-d371a39b675f)"
    )

    assert parsed.name == "exp001_20260314_04"
    assert parsed.dataset_id == "cd858535-8cdb-4be6-b420-d371a39b675f"


def test_looks_like_uuid_rejects_dataset_names():
    assert backfill_script._looks_like_uuid("cd858535-8cdb-4be6-b420-d371a39b675f") is True
    assert backfill_script._looks_like_uuid("exp001_20260314") is False


def test_choose_dataset_row_for_ref_rejects_ambiguous_exact_name_vs_id():
    ref = backfill_script.DatasetRef(
        raw="exp001_20260314",
        name="exp001_20260314",
        dataset_id=None,
    )

    id_rows = [{"id": "exp001_20260314", "name": "some-other-name"}]
    name_rows = [{"id": "uuid-target", "name": "exp001_20260314"}]

    try:
        backfill_script._choose_dataset_row_for_ref(ref, id_rows=id_rows, name_rows=name_rows)
    except RuntimeError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("Expected ambiguous resolution failure")


def test_update_metadata_payload_overwrites_dataset_type_and_lineage():
    payload = backfill_script._update_metadata_payload(
        {
            "id": "dataset-merged",
            "name": "Merged Dataset",
            "source": "r2",
            "status": "active",
            "created_by": "user-1",
            "created_at": "2026-03-13T00:00:00+00:00",
            "updated_at": "2026-03-13T00:00:00+00:00",
            "dataset_type": "recorded",
            "profile_snapshot": {"profile_name": "profile-a"},
            "source_datasets": [],
            "sync": {"hash": "md5:1234", "size_bytes": 42},
        },
        target_row={
            "id": "dataset-merged",
            "name": "Merged Dataset",
            "dataset_type": "recorded",
            "content_hash": "md5:1234",
            "size_bytes": 42,
            "profile_snapshot": {"profile_name": "profile-a"},
        },
        source_snapshots=[
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
        ],
        now="2026-03-14T00:00:00+00:00",
    )

    assert payload["dataset_type"] == "merged"
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
    assert payload["updated_at"] == "2026-03-14T00:00:00+00:00"

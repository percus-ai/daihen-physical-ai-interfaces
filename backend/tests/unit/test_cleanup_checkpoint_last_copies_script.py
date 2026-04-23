import importlib.util
import json
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


def _load_script_module():
    repo_root = _find_repo_root(Path(__file__).resolve())
    module_path = repo_root / "scripts" / "cleanup_checkpoint_last_copies.py"
    spec = importlib.util.spec_from_file_location(
        "cleanup_checkpoint_last_copies_script_test",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load script module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load_script_module()


class _Body:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _Paginator:
    def __init__(self, objects: dict[str, int]) -> None:
        self._objects = objects

    def paginate(self, *, Bucket: str, Prefix: str):
        del Bucket
        contents = [
            {"Key": key, "Size": size}
            for key, size in sorted(self._objects.items())
            if key.startswith(Prefix)
        ]
        yield {"Contents": contents}


class _FakeS3:
    def __init__(self, objects: dict[str, int], index: dict, log: list[str] | None = None) -> None:
        self.objects = dict(objects)
        self.index = index
        self.json_objects: dict[str, dict] = {}
        self.log = log if log is not None else []

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return _Paginator(self.objects)

    def get_object(self, *, Bucket: str, Key: str):
        del Bucket
        if Key.endswith("checkpoints/index.json"):
            return {"Body": _Body(self.index)}
        return {"Body": _Body(self.json_objects[Key])}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str):
        del Bucket, ContentType
        self.log.append(f"put:{Key}")
        self.json_objects[Key] = json.loads(Body.decode("utf-8"))
        return {}

    def delete_objects(self, *, Bucket: str, Delete: dict):
        del Bucket
        keys = [item["Key"] for item in Delete["Objects"]]
        self.log.append(f"delete:{','.join(keys)}")
        for key in keys:
            self.objects.pop(key, None)
        return {"Deleted": [{"Key": key} for key in keys]}


def test_build_cleanup_plan_targets_only_verified_legacy_last_copy():
    s3 = _FakeS3(
        objects={
            "v2/checkpoints/job-a/step_001000/config.json": 10,
            "v2/checkpoints/job-a/last/config.json": 10,
            "v2/checkpoints/job-b/last/config.json": 10,
        },
        index={
            "checkpoints": [
                {"job_name": "job-a", "latest_step": 1000},
                {"job_name": "job-b", "latest_step": 2000},
            ]
        },
    )

    plan = script._build_cleanup_plan(
        s3,
        bucket="daihen",
        prefix="v2/",
        entries=script._fetch_checkpoint_entries(s3, bucket="daihen", prefix="v2/"),
        limit=0,
    )

    assert len(plan.targets) == 1
    assert plan.targets[0].job_name == "job-a"
    assert plan.targets[0].last_object_keys == ["v2/checkpoints/job-a/last/config.json"]
    assert plan.skipped[0].job_name == "job-b"
    assert "latest step objects not found" in plan.skipped[0].reason


def test_apply_plan_writes_pointer_before_deleting_legacy_last_copy():
    log: list[str] = []
    s3 = _FakeS3(
        objects={
            "v2/checkpoints/job-a/step_001000/config.json": 10,
            "v2/checkpoints/job-a/last/config.json": 10,
        },
        index={"checkpoints": [{"job_name": "job-a", "latest_step": 1000}]},
        log=log,
    )
    plan = script._build_cleanup_plan(
        s3,
        bucket="daihen",
        prefix="v2/",
        entries=script._fetch_checkpoint_entries(s3, bucket="daihen", prefix="v2/"),
        limit=0,
    )

    script._apply_plan(s3, bucket="daihen", prefix="v2/", plan=plan)

    assert log == [
        "put:v2/checkpoints/job-a/last.json",
        "delete:v2/checkpoints/job-a/last/config.json",
    ]
    assert s3.json_objects["v2/checkpoints/job-a/last.json"]["step"] == 1000
    assert plan.targets[0].pointer_written is True
    assert plan.targets[0].deleted_objects == 1

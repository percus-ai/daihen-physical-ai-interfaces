import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


def _load_script_module():
    repo_root = _find_repo_root(Path(__file__).resolve())
    module_path = repo_root / "scripts" / "patch_checkpoint_model_artifacts.py"
    spec = importlib.util.spec_from_file_location(
        "patch_checkpoint_model_artifacts_script_test",
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
        self.log = log if log is not None else []

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return _Paginator(self.objects)

    def get_object(self, *, Bucket: str, Key: str):
        del Bucket
        assert Key.endswith("checkpoints/index.json")
        return {"Body": _Body(self.index)}

    def delete_objects(self, *, Bucket: str, Delete: dict):
        del Bucket
        keys = [item["Key"] for item in Delete["Objects"]]
        self.log.append(f"delete:{','.join(keys)}")
        for key in keys:
            self.objects.pop(key, None)
        return {"Deleted": [{"Key": key} for key in keys]}


class _FakeQuery:
    def __init__(self, client, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.update_payload = None
        self.eq_value = None

    def update(self, payload: dict):
        self.update_payload = payload
        return self

    def select(self, columns: str):
        del columns
        return self

    def eq(self, field: str, value: str):
        assert field == "id"
        self.eq_value = value
        return self

    def limit(self, value: int):
        del value
        return self

    def execute(self):
        assert self.table_name == "models"
        assert self.eq_value is not None
        if self.update_payload is not None:
            self.client.log.append(f"update:{self.eq_value}")
            self.client.rows[self.eq_value].update(self.update_payload)
            return SimpleNamespace(data=[dict(self.client.rows[self.eq_value])])
        self.client.log.append(f"select:{self.eq_value}")
        return SimpleNamespace(data=[dict(self.client.rows[self.eq_value])])


class _FakeSupabase:
    def __init__(self, rows: dict[str, dict], log: list[str]) -> None:
        self.rows = rows
        self.log = log

    def table(self, table_name: str):
        return _FakeQuery(self, table_name)


def test_build_patch_plan_prefers_model_training_step_and_marks_patch_delete():
    s3 = _FakeS3(
        objects={
            "v2/checkpoints/job-a/step_001000/pretrained_model/config.json": 100,
            "v2/models/model-1/config.json": 100,
        },
        index={
            "checkpoints": [
                {
                    "job_name": "job-a",
                    "latest_step": 2000,
                    "steps": [1000, 2000],
                }
            ]
        },
    )

    plan = script._build_patch_plan(
        s3,
        bucket="daihen",
        prefix="v2/",
        models=[
            {
                "id": "model-1",
                "name": "job-a",
                "source": "r2",
                "artifact_path": "s3://daihen/v2/models/model-1",
                "training_steps": 1000,
            }
        ],
        jobs=[
            {
                "job_id": "job-uuid",
                "job_name": "job-a",
                "model_id": "model-1",
                "training_config": {"training": {"steps": 2000}},
            }
        ],
        checkpoints_by_job_name=script._fetch_checkpoint_index(s3, bucket="daihen", prefix="v2/"),
        model_ids=set(),
        limit=0,
        allow_name_fallback=False,
    )

    assert len(plan.targets) == 1
    target = plan.targets[0]
    assert target.artifact_path == "s3://daihen/v2/checkpoints/job-a/step_001000/pretrained_model"
    assert target.patch_needed is True
    assert target.delete_needed is True
    assert target.resolution_reason == "model.training_steps"


def test_build_patch_plan_uses_existing_checkpoint_artifact_for_delete_without_patch():
    artifact_path = "s3://daihen/v2/checkpoints/job-a/step_001000/pretrained_model"
    s3 = _FakeS3(
        objects={
            "v2/checkpoints/job-a/step_001000/pretrained_model/config.json": 100,
            "v2/models/model-1/config.json": 100,
        },
        index={"checkpoints": []},
    )

    plan = script._build_patch_plan(
        s3,
        bucket="daihen",
        prefix="v2/",
        models=[
            {
                "id": "model-1",
                "name": "job-a",
                "source": "r2",
                "artifact_path": artifact_path,
                "training_steps": 1000,
            }
        ],
        jobs=[],
        checkpoints_by_job_name={},
        model_ids=set(),
        limit=0,
        allow_name_fallback=False,
    )

    assert len(plan.targets) == 1
    assert plan.targets[0].artifact_path == artifact_path
    assert plan.targets[0].patch_needed is False
    assert plan.targets[0].delete_needed is True


def test_build_patch_plan_skips_model_without_verified_checkpoint():
    s3 = _FakeS3(
        objects={"v2/models/model-1/config.json": 100},
        index={"checkpoints": []},
    )

    plan = script._build_patch_plan(
        s3,
        bucket="daihen",
        prefix="v2/",
        models=[
            {
                "id": "model-1",
                "name": "job-a",
                "source": "r2",
                "artifact_path": "s3://daihen/v2/models/model-1",
                "training_steps": 1000,
            }
        ],
        jobs=[],
        checkpoints_by_job_name={},
        model_ids=set(),
        limit=0,
        allow_name_fallback=False,
    )

    assert plan.targets == []
    assert plan.skipped[0].reason == "verified checkpoint pretrained_model not found"


def test_apply_plan_patches_db_before_deleting_model_prefix():
    log: list[str] = []
    db = _FakeSupabase(
        rows={"model-1": {"artifact_path": "s3://daihen/v2/models/model-1"}},
        log=log,
    )
    s3 = _FakeS3(
        objects={"v2/models/model-1/config.json": 100},
        index={"checkpoints": []},
        log=log,
    )
    target = script.ModelArtifactTarget(
        model_id="model-1",
        model_name="job-a",
        current_artifact_path="s3://daihen/v2/models/model-1",
        artifact_path="s3://daihen/v2/checkpoints/job-a/step_001000/pretrained_model",
        checkpoint_object_count=1,
        checkpoint_size_bytes=100,
        model_prefix="v2/models/model-1/",
        model_object_keys=["v2/models/model-1/config.json"],
        model_size_bytes=100,
        job_id="job-uuid",
        job_name="job-a",
        step=1000,
        resolution_reason="model.training_steps",
        patch_needed=True,
        delete_needed=True,
    )

    script._apply_plan(
        db,
        s3,
        bucket="daihen",
        prefix="v2/",
        plan=script.PatchPlan(targets=[target]),
        patch_only=False,
    )

    assert log == ["update:model-1", "select:model-1", "delete:v2/models/model-1/config.json"]
    assert db.rows["model-1"]["artifact_path"] == target.artifact_path
    assert target.deleted_objects == 1

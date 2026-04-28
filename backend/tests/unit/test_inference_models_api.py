import asyncio
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from fastapi import HTTPException

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


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
    utils_module = sys.modules.setdefault("lerobot.datasets.utils", ModuleType("lerobot.datasets.utils"))

    setattr(aggregate_module, "aggregate_datasets", lambda *_args, **_kwargs: None)
    setattr(datasets_module, "aggregate", aggregate_module)
    setattr(lerobot_dataset_module, "LeRobotDatasetMetadata", object)
    setattr(datasets_module, "lerobot_dataset", lerobot_dataset_module)
    setattr(utils_module, "load_tasks", lambda *_args, **_kwargs: {})
    setattr(datasets_module, "utils", utils_module)
    setattr(lerobot_module, "datasets", datasets_module)


_install_lerobot_stubs()

import interfaces_backend.api.inference as inference_api  # noqa: E402
from interfaces_backend.models.inference import (  # noqa: E402
    GpuHostStatus,
    InferenceModelInfo,
    InferenceModelSyncStatus,
    InferenceRuntimeTargetInfo,
    InferenceRuntimeTargetsResponse,
    InferenceRunnerStatus,
    InferenceRunnerStatusResponse,
    InferenceRunnerStartRequest,
)  # noqa: E402
from interfaces_backend.models.startup import StartupOperationAcceptedResponse  # noqa: E402


def test_list_models_merges_db_and_runtime(monkeypatch):
    class _FakeRuntime:
        def list_models(self):
            return [
                InferenceModelInfo(
                    model_id="model_shared",
                    name="model_shared",
                    policy_type="pi05",
                    source="local",
                    size_mb=64.0,
                    is_loaded=True,
                    is_local=True,
                ),
                InferenceModelInfo(
                    model_id="model_local_only",
                    name="model_local_only",
                    policy_type="act",
                    source="local",
                    size_mb=8.0,
                    is_loaded=False,
                    is_local=True,
                ),
            ]

    async def _fake_db_models(**_kwargs):
        return [
            InferenceModelInfo(
                model_id="model_shared",
                name="shared_display",
                created_at="2026-03-01T00:00:00Z",
                policy_type=None,
                source="r2",
                size_mb=0.0,
                is_loaded=False,
                is_local=False,
            ),
            InferenceModelInfo(
                model_id="model_remote_only",
                name="model_remote_only",
                created_at="2026-03-20T00:00:00Z",
                policy_type="pi0",
                source="r2",
                size_mb=12.0,
                is_loaded=False,
                is_local=False,
            ),
        ]

    monkeypatch.setattr(
        inference_api, "get_inference_runtime_manager", lambda: _FakeRuntime()
)
    monkeypatch.setattr(inference_api, "_list_db_models", _fake_db_models)

    response = asyncio.run(inference_api.list_models())
    models = {item.model_id: item for item in response.models}
    ordered_model_ids = [item.model_id for item in response.models]

    assert ordered_model_ids == [
        "model_remote_only",
        "model_shared",
        "model_local_only",
    ]

    assert "model_shared" in models
    assert models["model_shared"].is_local is True
    assert models["model_shared"].is_loaded is True
    assert models["model_shared"].policy_type == "pi05"
    assert models["model_shared"].created_at == "2026-03-01T00:00:00Z"

    assert "model_remote_only" in models
    assert models["model_remote_only"].is_local is False
    assert models["model_remote_only"].source == "r2"

    assert "model_local_only" in models
    assert models["model_local_only"].is_local is True


def test_list_models_includes_filter_options(monkeypatch):
    class _FakeRuntime:
        def list_models(self):
            return []

    async def _fake_db_models(**_kwargs):
        return [
            InferenceModelInfo(
                model_id="model-a",
                name="model-a",
                owner_user_id="user-1",
                owner_name="Alice",
                profile_name="lab-alpha",
                policy_type="pi0",
                training_steps=10000,
                batch_size=32,
                source="r2",
                size_mb=12.0,
                is_loaded=False,
                is_local=False,
            ),
            InferenceModelInfo(
                model_id="model-b",
                name="model-b",
                owner_user_id="user-2",
                owner_name="Bob",
                profile_name="lab-beta",
                policy_type="pi05",
                training_steps=20000,
                batch_size=16,
                source="r2",
                size_mb=24.0,
                is_loaded=False,
                is_local=False,
            ),
        ]

    monkeypatch.setattr(
        inference_api, "get_inference_runtime_manager", lambda: _FakeRuntime()
    )
    monkeypatch.setattr(inference_api, "_list_db_models", _fake_db_models)

    response = asyncio.run(inference_api.list_models())

    assert [item.label for item in response.owner_options] == ["Alice", "Bob"]
    assert [item.total_count for item in response.owner_options] == [1, 1]
    assert [item.value for item in response.profile_options] == [
        "lab-alpha",
        "lab-beta",
    ]
    assert [item.total_count for item in response.profile_options] == [1, 1]
    assert [item.value for item in response.training_steps_options] == [10000, 20000]
    assert [item.total_count for item in response.training_steps_options] == [1, 1]
    assert [item.value for item in response.batch_size_options] == [16, 32]
    assert [item.total_count for item in response.batch_size_options] == [1, 1]


def test_list_db_models_marks_unsynced_models(monkeypatch, tmp_path: Path):
    models_dir = tmp_path / "models"
    (models_dir / "model_local").mkdir(parents=True, exist_ok=True)

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows
            self._eq_filters: list[tuple[str, object]] = []
            self._order_key: str | None = None
            self._order_desc = False
            self._range: tuple[int, int] | None = None

        def select(self, _fields):
            return self

        def eq(self, key, value):
            self._eq_filters.append((key, value))
            return self

        def order(self, key, desc=False):
            self._order_key = key
            self._order_desc = desc
            return self

        def range(self, start, end):
            self._range = (start, end)
            return self

        async def execute(self):
            rows = list(self._rows)
            for key, value in self._eq_filters:
                rows = [row for row in rows if row.get(key) == value]
            if self._order_key:
                rows.sort(
                    key=lambda row: row.get(self._order_key) or "",
                    reverse=self._order_desc,
                )
            if self._range is not None:
                start, end = self._range
                rows = rows[start : end + 1]
            return type("Result", (), {"data": rows})()

    class _FakeClient:
        def __init__(self, rows):
            self._rows = rows

        def table(self, _name):
            return _FakeQuery(self._rows)

    async def _fake_db_client():
        return _FakeClient(
            [
                {
                    "id": "model_local",
                    "name": "model_local",
                    "created_at": "2026-03-01T00:00:00Z",
                    "profile_name": "lab-alpha",
                    "policy_type": "pi05",
                    "size_bytes": 0,
                    "source": "r2",
                    "status": "active",
                },
                {
                    "id": "model_remote",
                    "name": "model_remote",
                    "created_at": "2026-03-20T00:00:00Z",
                    "profile_name": "lab-beta",
                    "policy_type": "pi0",
                    "size_bytes": 0,
                    "source": "r2",
                    "status": "active",
                },
            ]
        )

    async def _fake_task_candidates(_client, _rows):
        return {
            "model_remote": ["pick and place"],
        }

    monkeypatch.setattr(inference_api, "get_supabase_async_client", _fake_db_client)
    monkeypatch.setattr(inference_api, "get_models_dir", lambda: models_dir)
    monkeypatch.setattr(
        inference_api, "_load_task_candidates_by_model", _fake_task_candidates
    )

    async def _fake_owner_directory(_ids):
        return {}

    monkeypatch.setattr(
        inference_api, "resolve_user_directory_entries", _fake_owner_directory
    )

    models = asyncio.run(inference_api._list_db_models())
    mapped = {item.model_id: item for item in models}

    assert mapped["model_local"].is_local is True
    assert mapped["model_local"].created_at == "2026-03-01T00:00:00Z"
    assert mapped["model_local"].profile_name == "lab-alpha"
    assert mapped["model_remote"].is_local is False
    assert mapped["model_remote"].created_at == "2026-03-20T00:00:00Z"
    assert mapped["model_remote"].profile_name == "lab-beta"
    assert mapped["model_remote"].task_candidates == ["pick and place"]


def test_list_db_models_applies_db_filters_order_range_and_column_projection(
    monkeypatch, tmp_path: Path
):
    models_dir = tmp_path / "models"
    queries: list["_FakeQuery"] = []

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows
            self.select_fields: str | None = None
            self.eq_filters: list[tuple[str, object]] = []
            self.orders: list[tuple[str, bool]] = []
            self.ranges: list[tuple[int, int]] = []

        def select(self, fields):
            self.select_fields = fields
            return self

        def eq(self, key, value):
            self.eq_filters.append((key, value))
            return self

        def order(self, key, desc=False):
            self.orders.append((key, desc))
            return self

        def range(self, start, end):
            self.ranges.append((start, end))
            return self

        async def execute(self):
            rows = list(self._rows)
            for key, value in self.eq_filters:
                rows = [row for row in rows if row.get(key) == value]
            for key, desc in reversed(self.orders):
                rows.sort(key=lambda row: row.get(key) or "", reverse=desc)
            for start, end in self.ranges:
                rows = rows[start : end + 1]
            return type("Result", (), {"data": rows})()

    class _FakeClient:
        def __init__(self, rows):
            self._rows = rows

        def table(self, name):
            assert name == "models"
            query = _FakeQuery(self._rows)
            queries.append(query)
            return query

    async def _fake_db_client():
        return _FakeClient(
            [
                {
                    "id": "model-new",
                    "name": "model-new",
                    "created_at": "2026-04-01T00:00:00Z",
                    "owner_user_id": "user-1",
                    "profile_name": "lab-alpha",
                    "policy_type": "pi0",
                    "training_steps": 1000,
                    "batch_size": 16,
                    "size_bytes": 1024,
                    "source": "r2",
                    "status": "active",
                },
                {
                    "id": "model-old",
                    "name": "model-old",
                    "created_at": "2026-03-01T00:00:00Z",
                    "owner_user_id": "user-1",
                    "profile_name": "lab-alpha",
                    "policy_type": "pi0",
                    "training_steps": 1000,
                    "batch_size": 16,
                    "size_bytes": 1024,
                    "source": "r2",
                    "status": "active",
                },
                {
                    "id": "model-other",
                    "name": "model-other",
                    "created_at": "2026-02-01T00:00:00Z",
                    "owner_user_id": "user-1",
                    "profile_name": "lab-beta",
                    "policy_type": "pi0",
                    "training_steps": 1000,
                    "batch_size": 16,
                    "size_bytes": 1024,
                    "source": "r2",
                    "status": "active",
                },
            ]
        )

    async def _fake_task_candidates(_client, _rows):
        return {}

    async def _fake_owner_directory(_ids):
        return {}

    monkeypatch.setattr(inference_api, "get_supabase_async_client", _fake_db_client)
    monkeypatch.setattr(inference_api, "get_models_dir", lambda: models_dir)
    monkeypatch.setattr(
        inference_api, "_load_task_candidates_by_model", _fake_task_candidates
    )
    monkeypatch.setattr(
        inference_api, "resolve_user_directory_entries", _fake_owner_directory
    )

    models = asyncio.run(
        inference_api._list_db_models(
            owner_user_id="user-1",
            profile_name="lab-alpha",
            policy_type="pi0",
            training_steps=1000,
            batch_size=16,
            limit=1,
            offset=1,
        )
    )

    query = queries[0]
    assert query.select_fields == inference_api._MODEL_LIST_COLUMNS
    assert "*" not in query.select_fields
    assert ("status", "active") in query.eq_filters
    assert ("owner_user_id", "user-1") in query.eq_filters
    assert ("profile_name", "lab-alpha") in query.eq_filters
    assert ("policy_type", "pi0") in query.eq_filters
    assert ("training_steps", 1000) in query.eq_filters
    assert ("batch_size", 16) in query.eq_filters
    assert query.orders == [("created_at", True)]
    assert query.ranges == [(1, 1)]
    assert [model.model_id for model in models] == ["model-old"]


def test_load_task_candidates_by_model_uses_related_active_datasets():
    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows
            self._eq_filters: list[tuple[str, object]] = []
            self._in_filters: list[tuple[str, set[object]]] = []
            self._order_key: str | None = None
            self._order_desc = False

        def select(self, _fields):
            return self

        def eq(self, key, value):
            self._eq_filters.append((key, value))
            return self

        def in_(self, key, values):
            self._in_filters.append((key, set(values)))
            return self

        def order(self, key, desc=False):
            self._order_key = key
            self._order_desc = desc
            return self

        async def execute(self):
            rows = list(self._rows)
            for key, value in self._eq_filters:
                rows = [row for row in rows if row.get(key) == value]
            for key, values in self._in_filters:
                rows = [row for row in rows if row.get(key) in values]
            if self._order_key:
                rows.sort(
                    key=lambda row: row.get(self._order_key) or "",
                    reverse=self._order_desc,
                )
            return type("Result", (), {"data": rows})()

    class _FakeClient:
        def __init__(self, rows_by_table):
            self._rows_by_table = rows_by_table

        def table(self, name):
            return _FakeQuery(self._rows_by_table.get(name, []))

    client = _FakeClient(
        {
            "training_jobs": [
                {
                    "model_id": "model-a",
                    "dataset_id": "dataset-b",
                    "updated_at": "2026-02-21T00:00:00Z",
                    "deleted_at": None,
                },
                {
                    "model_id": "model-a",
                    "dataset_id": "dataset-c",
                    "updated_at": "2026-02-20T00:00:00Z",
                    "deleted_at": None,
                },
                {
                    "model_id": "model-a",
                    "dataset_id": "dataset-d",
                    "updated_at": "2026-02-19T00:00:00Z",
                    "deleted_at": "2026-02-19T00:00:00Z",
                },
            ],
            "datasets": [
                {
                    "id": "dataset-a",
                    "task_detail": "pick and place",
                    "status": "active",
                },
                {"id": "dataset-b", "task_detail": "stack blocks", "status": "active"},
                {
                    "id": "dataset-c",
                    "task_detail": "archived task",
                    "status": "archived",
                },
                {
                    "id": "dataset-d",
                    "task_detail": "should not use",
                    "status": "active",
                },
            ],
        }
    )

    candidates = asyncio.run(
        inference_api._load_task_candidates_by_model(
            client,
            [
                {"id": "model-a", "dataset_id": "dataset-a"},
            ],
        )
    )

    assert candidates["model-a"] == ["pick and place", "stack blocks"]


def test_load_task_candidates_by_model_prefers_local_tasks_for_merged_dataset(
    monkeypatch,
):
    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows
            self._eq_filters: list[tuple[str, object]] = []
            self._in_filters: list[tuple[str, set[object]]] = []
            self._order_key: str | None = None
            self._order_desc = False

        def select(self, _fields):
            return self

        def eq(self, key, value):
            self._eq_filters.append((key, value))
            return self

        def in_(self, key, values):
            self._in_filters.append((key, set(values)))
            return self

        def order(self, key, desc=False):
            self._order_key = key
            self._order_desc = desc
            return self

        async def execute(self):
            rows = list(self._rows)
            for key, value in self._eq_filters:
                rows = [row for row in rows if row.get(key) == value]
            for key, values in self._in_filters:
                rows = [row for row in rows if row.get(key) in values]
            if self._order_key:
                rows.sort(
                    key=lambda row: row.get(self._order_key) or "",
                    reverse=self._order_desc,
                )
            return type("Result", (), {"data": rows})()

    class _FakeClient:
        def __init__(self, rows_by_table):
            self._rows_by_table = rows_by_table

        def table(self, name):
            return _FakeQuery(self._rows_by_table.get(name, []))

    client = _FakeClient(
        {
            "training_jobs": [],
            "datasets": [
                {
                    "id": "dataset-merged",
                    "task_detail": None,
                    "status": "active",
                    "dataset_type": "merged",
                    "source_datasets": [
                        {
                            "dataset_id": "dataset-a",
                            "name": "Dataset A",
                            "task_detail": "fallback task",
                        },
                    ],
                },
            ],
        }
    )
    monkeypatch.setattr(
        inference_api,
        "_load_local_dataset_task_candidates",
        lambda dataset_id: (
            ["pick cube", "place cube"] if dataset_id == "dataset-merged" else []
        ),
    )

    candidates = asyncio.run(
        inference_api._load_task_candidates_by_model(
            client,
            [
                {"id": "model-a", "dataset_id": "dataset-merged"},
            ],
        )
    )

    assert candidates["model-a"] == ["pick cube", "place cube"]


def test_load_task_candidates_by_model_falls_back_to_source_snapshots_for_merged_dataset(
    monkeypatch,
):
    select_calls: list[tuple[str, str | None]] = []

    class _FakeQuery:
        def __init__(self, table_name, rows):
            self._table_name = table_name
            self._rows = rows
            self._select_fields: str | None = None
            self._eq_filters: list[tuple[str, object]] = []
            self._in_filters: list[tuple[str, set[object]]] = []
            self._order_key: str | None = None
            self._order_desc = False

        def select(self, fields):
            self._select_fields = fields
            return self

        def eq(self, key, value):
            self._eq_filters.append((key, value))
            return self

        def in_(self, key, values):
            self._in_filters.append((key, set(values)))
            return self

        def order(self, key, desc=False):
            self._order_key = key
            self._order_desc = desc
            return self

        async def execute(self):
            select_calls.append((self._table_name, self._select_fields))
            rows = list(self._rows)
            for key, value in self._eq_filters:
                rows = [row for row in rows if row.get(key) == value]
            for key, values in self._in_filters:
                rows = [row for row in rows if row.get(key) in values]
            if self._order_key:
                rows.sort(
                    key=lambda row: row.get(self._order_key) or "",
                    reverse=self._order_desc,
                )
            return type("Result", (), {"data": rows})()

    class _FakeClient:
        def __init__(self, rows_by_table):
            self._rows_by_table = rows_by_table

        def table(self, name):
            return _FakeQuery(name, self._rows_by_table.get(name, []))

    client = _FakeClient(
        {
            "training_jobs": [],
            "datasets": [
                {
                    "id": "dataset-merged",
                    "task_detail": None,
                    "status": "active",
                    "dataset_type": "merged",
                    "source_datasets": [
                        {
                            "dataset_id": "dataset-a",
                            "name": "Dataset A",
                            "task_detail": "pick cube",
                        },
                        {
                            "dataset_id": "dataset-b",
                            "name": "Dataset B",
                            "task_detail": "place cube",
                        },
                        {
                            "dataset_id": "dataset-c",
                            "name": "Dataset C",
                            "task_detail": "pick cube",
                        },
                    ],
                },
            ],
        }
    )
    monkeypatch.setattr(
        inference_api, "_load_local_dataset_task_candidates", lambda _dataset_id: []
    )

    candidates = asyncio.run(
        inference_api._load_task_candidates_by_model(
            client,
            [
                {"id": "model-a", "dataset_id": "dataset-merged"},
            ],
        )
    )

    assert candidates["model-a"] == ["pick cube", "place cube"]
    dataset_selects = [
        fields for table_name, fields in select_calls if table_name == "datasets"
    ]
    assert dataset_selects == [
        inference_api._DATASET_TASK_COLUMNS,
        inference_api._DATASET_SOURCE_SNAPSHOT_COLUMNS,
    ]
    assert "source_datasets" not in dataset_selects[0]


def test_get_inference_runner_status_includes_model_sync(monkeypatch):
    class _FakeRuntime:
        def get_status(self):
            return InferenceRunnerStatusResponse(
                runner_status=InferenceRunnerStatus(
                    active=False,
                    session_id=None,
                    task=None,
                    queue_length=0,
                    last_error=None,
                ),
                gpu_host_status=GpuHostStatus(
                    status="idle",
                    session_id=None,
                    pid=None,
                    last_error=None,
                ),
            )

    class _FakeLifecycle:
        def get_model_sync_status(self):
            return InferenceModelSyncStatus(
                active=True,
                status="syncing",
                model_id="model_remote",
                message="syncing",
                progress_percent=42.5,
                total_files=8,
                files_done=3,
                total_bytes=1024,
                transferred_bytes=435,
            )

    monkeypatch.setattr(
        inference_api, "get_inference_runtime_manager", lambda: _FakeRuntime()
    )
    monkeypatch.setattr(
        inference_api, "get_dataset_lifecycle", lambda: _FakeLifecycle()
    )

    response = asyncio.run(inference_api.get_inference_runner_status())
    assert response.model_sync.active is True
    assert response.model_sync.status == "syncing"
    assert response.model_sync.model_id == "model_remote"
    assert response.model_sync.progress_percent == 42.5


def test_get_inference_runner_status_preserves_runtime_pause(monkeypatch):
    class _FakeRuntime:
        def get_status(self):
            return InferenceRunnerStatusResponse(
                runner_status=InferenceRunnerStatus(
                    active=True,
                    session_id="session-1",
                    state="paused",
                    task="pick",
                    paused=True,
                ),
                gpu_host_status=GpuHostStatus(
                    status="running",
                    session_id="session-1",
                    pid=123,
                    last_error=None,
                ),
            )

    class _FakeManager:
        def get_active_recording_status(self):
            return {
                "recording_dataset_id": None,
                "recording_active": False,
                "awaiting_continue_confirmation": False,
            }

    class _FakeLifecycle:
        def get_model_sync_status(self):
            return InferenceModelSyncStatus()

    monkeypatch.setattr(
        inference_api, "get_inference_runtime_manager", lambda: _FakeRuntime()
    )
    monkeypatch.setattr(
        inference_api, "get_inference_session_manager", lambda: _FakeManager()
    )
    monkeypatch.setattr(
        inference_api, "get_dataset_lifecycle", lambda: _FakeLifecycle()
    )

    response = asyncio.run(inference_api.get_inference_runner_status())
    assert response.runner_status.state == "paused"
    assert response.runner_status.paused is True


def test_get_runtime_targets_returns_service_snapshot(monkeypatch):
    class _FakeRuntimeTargetsService:
        def list_targets(self, *, policy_type: str | None):
            assert policy_type == "groot"
            return InferenceRuntimeTargetsResponse(
                policy_type="groot",
                current_sm="sm_120",
                recommended_target_id="cuda:default:groot:build-1",
                targets=[
                    InferenceRuntimeTargetInfo(
                        id="cpu",
                        kind="cpu",
                        label="CPU",
                        description="ホスト CPU で実行",
                        device="cpu",
                    ),
                    InferenceRuntimeTargetInfo(
                        id="cuda:default:groot:build-1",
                        kind="cuda",
                        label="CUDA #1",
                        description="GR00T N1.5 / Blackwell 向け GR00T N1.5 実行環境",
                        device="cuda:0",
                        config_id="default",
                        env_name="groot",
                        build_id="build-1",
                        supported_sms=["sm_120"],
                        current_sm="sm_120",
                        sm_supported=True,
                    ),
                ],
            )

    monkeypatch.setattr(
        inference_api,
        "get_inference_runtime_targets_service",
        lambda: _FakeRuntimeTargetsService(),
    )

    response = asyncio.run(inference_api.get_runtime_targets(policy_type="groot"))

    assert response.current_sm == "sm_120"
    assert response.recommended_target_id == "cuda:default:groot:build-1"
    assert response.targets[1].label == "CUDA #1"


def test_start_inference_runner_returns_operation_id(monkeypatch):
    accepted = StartupOperationAcceptedResponse(
        operation_id="op-infer", message="accepted"
    )

    class _FakeRecordingManager:
        @staticmethod
        def any_active():
            return None

    class _FakeOperations:
        def create(self, *, user_id: str, kind: str):
            assert user_id == "user-1"
            assert kind == "inference_start"
            return accepted

    def _fake_create_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(
        inference_api, "get_startup_operations_service", lambda: _FakeOperations()
    )
    monkeypatch.setattr(
        inference_api, "get_recording_session_manager", lambda: _FakeRecordingManager()
    )
    monkeypatch.setattr(inference_api.asyncio, "create_task", _fake_create_task)

    response = asyncio.run(
        inference_api.start_inference_runner(
            InferenceRunnerStartRequest(
                model_id="model-a",
                runtime_target_id="cuda:default:groot:build-1",
                profile="lab-alpha",
                task="pick",
                num_episodes=12,
            )
        )
    )
    assert response.operation_id == "op-infer"


def test_start_inference_runner_rejects_when_recording_session_active(monkeypatch):
    class _FakeRecordingManager:
        @staticmethod
        def any_active():
            return SimpleNamespace(id="dataset-recording")

    monkeypatch.setattr(inference_api, "require_user_id", lambda: "user-1")
    monkeypatch.setattr(
        inference_api, "get_recording_session_manager", lambda: _FakeRecordingManager()
    )

    try:
        asyncio.run(
            inference_api.start_inference_runner(
                InferenceRunnerStartRequest(
                    model_id="model-a",
                    runtime_target_id="cpu",
                    task="pick",
                    num_episodes=12,
                )
            )
        )
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "Recording session is already prepared or active: dataset-recording" in str(exc.detail)


def test_run_inference_start_operation_passes_policy_options(monkeypatch):
    created_kwargs: dict[str, object] = {}
    completed: dict[str, object] = {}

    class _FakeRecordingManager:
        @staticmethod
        def any_active():
            return None

    class _FakeManager:
        async def create(self, **kwargs):
            created_kwargs.update(kwargs)
            return SimpleNamespace(extras={"worker_session_id": "worker-session-1"})

    class _FakeOperations:
        def build_progress_callback(self, _operation_id: str):
            return lambda *_args, **_kwargs: None

        def complete(self, **kwargs):
            completed.update(kwargs)

        def fail(self, **_kwargs):
            raise AssertionError("fail should not be called")

    monkeypatch.setattr(
        inference_api, "get_inference_session_manager", lambda: _FakeManager()
    )
    monkeypatch.setattr(
        inference_api, "get_startup_operations_service", lambda: _FakeOperations()
    )
    monkeypatch.setattr(
        inference_api, "get_recording_session_manager", lambda: _FakeRecordingManager()
    )

    asyncio.run(
        inference_api._run_inference_start_operation(
            "op-1",
            user_id="user-1",
            model_id="model-a",
            runtime_target_id="cuda:default:groot:build-1",
            profile="lab-alpha",
            task="pick",
            num_episodes=12,
            policy_options={"pi0": {"denoising_steps": 12}},
        )
    )

    assert created_kwargs["model_id"] == "model-a"
    assert created_kwargs["user_id"] == "user-1"
    assert created_kwargs["runtime_target_id"] == "cuda:default:groot:build-1"
    assert created_kwargs["profile"] == "lab-alpha"
    assert created_kwargs["num_episodes"] == 12
    assert created_kwargs["policy_options"] == {"pi0": {"denoising_steps": 12}}
    assert completed["target_session_id"] == "worker-session-1"


def test_run_inference_start_operation_fails_when_recording_session_active(monkeypatch):
    failed: dict[str, object] = {}

    class _FakeRecordingManager:
        @staticmethod
        def any_active():
            return SimpleNamespace(id="dataset-recording")

    class _FakeManager:
        async def create(self, **_kwargs):
            raise AssertionError("manager.create should not be called")

    class _FakeOperations:
        def build_progress_callback(self, _operation_id: str):
            return lambda *_args, **_kwargs: None

        def complete(self, **_kwargs):
            raise AssertionError("complete should not be called")

        def fail(self, **kwargs):
            failed.update(kwargs)

    monkeypatch.setattr(
        inference_api, "get_recording_session_manager", lambda: _FakeRecordingManager()
    )
    monkeypatch.setattr(
        inference_api, "get_inference_session_manager", lambda: _FakeManager()
    )
    monkeypatch.setattr(
        inference_api, "get_startup_operations_service", lambda: _FakeOperations()
    )

    asyncio.run(
        inference_api._run_inference_start_operation(
            "op-1",
            user_id="user-1",
            model_id="model-a",
            runtime_target_id="cpu",
            profile=None,
            task="pick",
            num_episodes=12,
            policy_options=None,
        )
    )

    assert failed["operation_id"] == "op-1"
    assert "Recording session is already prepared or active: dataset-recording" in str(failed["error"])

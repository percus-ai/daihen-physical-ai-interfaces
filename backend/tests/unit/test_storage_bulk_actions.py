import asyncio
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("COMM_EXPORTER_MODE", "noop")


def _load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[2] / "src" / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bulk_actions = _load_module(
    "interfaces_backend_services_storage_bulk_actions_test",
    "interfaces_backend/services/storage_bulk_actions.py",
)


class _FakeTableQuery:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table_name = table_name
        self._op = "select"
        self._payload = None
        self._filters: list[tuple[str, str]] = []

    def select(self, _fields: str):
        self._op = "select"
        return self

    def update(self, payload: dict):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, key: str, value: str):
        self._filters.append((key, value))
        return self

    async def execute(self):
        self._client.calls.append(
            {
                "table": self._table_name,
                "op": self._op,
                "payload": self._payload,
                "filters": list(self._filters),
            }
        )
        if self._table_name == "datasets":
            dataset_id = next((value for key, value in self._filters if key == "id"), "")
            row = self._client.dataset_rows.get(dataset_id)
            if self._op == "update" and row is not None and self._payload is not None and not self._client.skip_dataset_updates:
                row.update(self._payload)
            return SimpleNamespace(data=[row] if row else [])
        if self._table_name == "models":
            model_id = next((value for key, value in self._filters if key == "id"), "")
            row = self._client.model_rows.get(model_id)
            if self._op == "update" and row is not None and self._payload is not None and not self._client.skip_model_updates:
                row.update(self._payload)
            return SimpleNamespace(data=[row] if row else [])
        return SimpleNamespace(data=[])


class _FakeDbClient:
    def __init__(self):
        self.dataset_rows: dict[str, dict] = {}
        self.model_rows: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.skip_dataset_updates = False
        self.skip_model_updates = False

    def table(self, table_name: str):
        return _FakeTableQuery(self, table_name)


class _FakeLifecycle:
    def __init__(self, *, ok: bool = True, error: str = ""):
        self.ok = ok
        self.error = error

    async def reupload(self, _dataset_id: str):
        return self.ok, self.error


class _FakeJobsService:
    def __init__(self, *, conflict: bool = False, with_active_job: bool = False):
        self.conflict = conflict
        self.with_active_job = with_active_job
        self.cancelled_job_ids: list[str] = []
        self.created_model_ids: list[str] = []
        self.ensure_worker_called = False

    def create(self, *, user_id: str, model_id: str):
        _ = user_id
        if self.conflict:
            raise bulk_actions.HTTPException(status_code=409, detail="A model sync job is already in progress")
        self.created_model_ids.append(model_id)
        return SimpleNamespace(job_id=f"job-{model_id}")

    def ensure_worker(self):
        self.ensure_worker_called = True

    def list(self, *, user_id: str, include_terminal: bool = False):
        _ = user_id, include_terminal
        if not self.with_active_job:
            return SimpleNamespace(jobs=[])
        return SimpleNamespace(
            jobs=[SimpleNamespace(job_id="job-model-1", model_id="model-1", state="running")]
        )

    def cancel(self, *, user_id: str, job_id: str):
        _ = user_id
        self.cancelled_job_ids.append(job_id)
        return SimpleNamespace(job_id=job_id, accepted=True, state="cancelled", message="cancelled")


def test_archive_dataset_for_bulk_marks_archived(monkeypatch, tmp_path: Path):
    fake_client = _FakeDbClient()
    fake_client.dataset_rows["dataset-1"] = {"id": "dataset-1", "status": "active"}

    async def _fake_get_supabase():
        return fake_client

    monkeypatch.setattr(bulk_actions, "get_supabase_async_client", _fake_get_supabase)

    result = asyncio.run(bulk_actions.archive_dataset_for_bulk("dataset-1"))

    assert result.status == "succeeded"
    assert fake_client.dataset_rows["dataset-1"]["status"] == "archived"


def test_archive_dataset_for_bulk_fails_when_update_not_persisted(monkeypatch):
    fake_client = _FakeDbClient()
    fake_client.dataset_rows["dataset-1"] = {"id": "dataset-1", "status": "active"}
    fake_client.skip_dataset_updates = True

    async def _fake_get_supabase():
        return fake_client

    monkeypatch.setattr(bulk_actions, "get_supabase_async_client", _fake_get_supabase)

    result = asyncio.run(bulk_actions.archive_dataset_for_bulk("dataset-1"))

    assert result.status == "failed"
    assert result.message == "Dataset archive was not persisted"


def test_reupload_dataset_for_bulk_requires_local_dataset(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(bulk_actions, "get_datasets_dir", lambda: tmp_path)
    monkeypatch.setattr(bulk_actions, "get_dataset_lifecycle", lambda: _FakeLifecycle())

    result = asyncio.run(bulk_actions.reupload_dataset_for_bulk("missing-dataset"))

    assert result.status == "failed"
    assert result.message == "Local dataset not found"


def test_sync_model_for_bulk_returns_job_id(monkeypatch):
    fake_client = _FakeDbClient()
    fake_client.model_rows["model-1"] = {"id": "model-1", "status": "active"}
    fake_jobs = _FakeJobsService()

    async def _fake_get_supabase():
        return fake_client

    monkeypatch.setattr(bulk_actions, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(bulk_actions, "get_model_sync_jobs_service", lambda: fake_jobs)

    result = asyncio.run(bulk_actions.sync_model_for_bulk(user_id="user-1", model_id="model-1"))

    assert result.status == "succeeded"
    assert result.job_id == "job-model-1"
    assert fake_jobs.ensure_worker_called is True


def test_archive_model_for_bulk_cancels_active_job(monkeypatch):
    fake_client = _FakeDbClient()
    fake_client.model_rows["model-1"] = {"id": "model-1", "status": "active"}
    fake_jobs = _FakeJobsService(with_active_job=True)

    async def _fake_get_supabase():
        return fake_client

    monkeypatch.setattr(bulk_actions, "get_supabase_async_client", _fake_get_supabase)
    monkeypatch.setattr(bulk_actions, "get_model_sync_jobs_service", lambda: fake_jobs)

    result = asyncio.run(bulk_actions.archive_model_for_bulk(user_id="user-1", model_id="model-1"))

    assert result.status == "succeeded"
    assert fake_jobs.cancelled_job_ids == ["job-model-1"]
    assert fake_client.model_rows["model-1"]["status"] == "archived"

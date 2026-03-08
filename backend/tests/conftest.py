import os
import sys
import hashlib
import importlib.util
import logging
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient


def _install_test_module_stubs() -> None:
    if importlib.util.find_spec("cv2") is None and "cv2" not in sys.modules:
        class _FakeCapture:
            def isOpened(self) -> bool:
                return False

            def get(self, _prop: int) -> float:
                return 0.0

            def getBackendName(self) -> str:
                return "stub"

            def read(self) -> tuple[bool, None]:
                return False, None

            def release(self) -> None:
                return None

        cv2_stub = ModuleType("cv2")
        cv2_stub.CAP_PROP_FRAME_WIDTH = 3
        cv2_stub.CAP_PROP_FRAME_HEIGHT = 4
        cv2_stub.CAP_PROP_FPS = 5
        cv2_stub.VideoCapture = lambda *_args, **_kwargs: _FakeCapture()
        sys.modules["cv2"] = cv2_stub

    if importlib.util.find_spec("serial") is None and "serial" not in sys.modules:
        serial_stub = ModuleType("serial")
        serial_tools_stub = ModuleType("serial.tools")
        serial_tools_stub.list_ports = ModuleType("serial.tools.list_ports")
        serial_tools_stub.list_ports.comports = lambda: []
        serial_stub.tools = serial_tools_stub
        sys.modules["serial"] = serial_stub
        sys.modules["serial.tools"] = serial_tools_stub
        sys.modules["serial.tools.list_ports"] = serial_tools_stub.list_ports


_install_test_module_stubs()


def _find_repo_root(start: Path) -> Path:
    for parent in [start] + list(start.parents):
        if (parent / "AGENTS.md").exists():
            return parent
    return start


REPO_ROOT = _find_repo_root(Path(__file__).resolve())


def _ensure_sys_path(path: Path) -> None:
    resolved = str(path)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)


_ensure_sys_path(REPO_ROOT / "interfaces" / "backend" / "src")
_ensure_sys_path(REPO_ROOT / "features")

LOGS_DIR = REPO_ROOT / "interfaces" / "backend" / "tests" / "logs"


@pytest.fixture(autouse=True)
def _per_test_log(request):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    raw_name = request.node.nodeid
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw_name)
    if len(safe_name) > 120:
        digest = hashlib.sha1(raw_name.encode("utf-8")).hexdigest()[:8]
        safe_name = f"{safe_name[:80]}_{digest}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"{timestamp}__{safe_name}.log"

    logger = logging.getLogger()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
        rep_call = getattr(request.node, "rep_call", None)
        rep_setup = getattr(request.node, "rep_setup", None)
        rep_teardown = getattr(request.node, "rep_teardown", None)
        failed = any(
            rep is not None and rep.failed for rep in (rep_setup, rep_call, rep_teardown)
        )
        if not failed and log_path.exists():
            log_path.unlink()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(scope="session", autouse=True)
def _isolate_env(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("workspace")
    home_dir = tmp_path_factory.mktemp("home")

    prev_cwd = Path.cwd()
    prev_env = os.environ.copy()

    os.chdir(workspace)
    os.environ["HOME"] = str(home_dir)
    os.environ["PHYSICAL_AI_DATA_DIR"] = str(workspace)
    os.environ["PHYSICAL_AI_PROJECT_ROOT"] = str(REPO_ROOT)
    os.environ["PHI_ENV"] = "e2e"
    os.environ["PHI_DISABLE_TRAINING_PROVISION_RECOVERY"] = "1"

    # Pre-create bind-mount source paths as current user to prevent Docker from
    # auto-creating root-owned directories (e.g. profiles/classes).
    (workspace / "profiles" / "classes").mkdir(parents=True, exist_ok=True)

    yield

    os.chdir(prev_cwd)
    os.environ.clear()
    os.environ.update(prev_env)


def _reset_backend_state() -> None:
    import interfaces_backend.api.calibration as calibration
    import interfaces_backend.api.recording as recording
    import interfaces_backend.services.inference_runtime as inference_runtime
    import interfaces_backend.services.startup_operations as startup_operations
    import interfaces_backend.services.tab_realtime as tab_realtime
    import interfaces_backend.services.training_provision_recovery as training_provision_recovery
    import percus_ai.db as percus_db

    calibration._sessions.clear()
    calibration._motor_buses.clear()

    if hasattr(recording, "_sync_service"):
        recording._sync_service = None

    if inference_runtime._runtime_manager is not None:
        inference_runtime._runtime_manager.shutdown()
        inference_runtime._runtime_manager = None

    startup_operations.reset_startup_operations_service()
    tab_realtime.reset_tab_realtime_registry()
    training_provision_recovery.reset_training_provision_recovery_service()
    percus_db.reset_supabase_async_client_cache()



@pytest.fixture(autouse=True)
def _clean_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import shutil

    # Use an isolated data dir per test to avoid cross-test contamination and
    # host permission collisions from container-created files.
    data_dir = tmp_path / "physical-ai-data"
    (data_dir / "profiles" / "classes").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PHYSICAL_AI_DATA_DIR", str(data_dir))

    calib_dir = Path(os.environ["HOME"]) / ".cache" / "percus_ai" / "calibration"
    if calib_dir.exists():
        shutil.rmtree(calib_dir)

    yield


@pytest.fixture
def client():
    from interfaces_backend.main import app

    _reset_backend_state()

    with TestClient(app) as test_client:
        yield test_client

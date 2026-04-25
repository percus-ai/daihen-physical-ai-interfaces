import asyncio
import time
from pathlib import Path

from interfaces_backend.services.build_jobs import BuildJobsService
from percus_ai.environment.build import BuildStore
from percus_ai.environment.build.build_layout import BuildLayout
from percus_ai.environment.config import EnvironmentConfigLoader


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class _FakeEnvironmentBuildOperation:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    def execute(
        self,
        *,
        config_id: str,
        env_name: str,
        config_group: str | None = None,
        build_id: str | None = None,
        cancel_event=None,
        output_callback=None,
    ):
        self.calls.append((config_id, env_name, config_group, build_id))
        if output_callback is not None:
            output_callback("create_env_venv", "stderr", "creating venv\n")
        for index in range(50):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("cancelled")
            if output_callback is not None and index == 10:
                output_callback("runtime-common", "stdout", "installing runtime\n")
            time.sleep(0.01)
        return None


class _FakeSharedBuildOperation:
    def execute(
        self,
        *,
        package: str,
        variant: str,
        build_id: str | None = None,
        cancel_event=None,
        output_callback=None,
    ):
        del package, variant, build_id, cancel_event
        if output_callback is not None:
            output_callback("create_build_venv", "stderr", "creating shared venv\n")
        time.sleep(0.05)
        return None


class _VerboseSharedBuildOperation:
    def execute(
        self,
        *,
        package: str,
        variant: str,
        build_id: str | None = None,
        cancel_event=None,
        output_callback=None,
    ):
        del package, variant, build_id, cancel_event
        if output_callback is None:
            return None
        for index in range(150):
            output_callback("build_shared", "stdout", f"line-{index}\n")
        return None


async def _wait_for_terminal_state(service: BuildJobsService, job_id: str) -> str:
    for _ in range(100):
        state = service.get_job(job_id=job_id).state
        if state in {"completed", "failed"}:
            return state
        await asyncio.sleep(0.02)
    raise AssertionError("job did not reach terminal state")


def test_build_jobs_service_cancel_and_log_buffer(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/runtime/default.yaml",
        """
id: default
envs:
  pi0:
    python: "3.10"
    installs:
      - id: runtime-common
        source:
          type: index
        packages:
          - python-dotenv>=1.0.1
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        root_dir / "features/percus_ai/environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )

    async def _run():
        service = BuildJobsService(
            config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
            build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
            environment_build_operation=_FakeEnvironmentBuildOperation(),
            shared_build_operation=_FakeSharedBuildOperation(),
        )
        accepted = service.start_env_build(config_group="vla_runtime", config_id="default", env_name="pi0")
        job_id = accepted.job.job_id

        await asyncio.sleep(0.15)
        cursor, events = service.poll_log_events()
        assert cursor is not None
        assert any(item["line"] == "creating venv\n" for item in events)

        cancel_response = service.cancel(job_id=job_id)
        assert cancel_response.accepted is True

        terminal_state = await _wait_for_terminal_state(service, job_id)
        assert terminal_state == "failed"
        final_job = service.get_job(job_id=job_id)
        assert final_job.error == "cancelled"
        assert final_job.message == "環境構築を中止しました。"

        await service.shutdown()

    asyncio.run(_run())


def test_build_jobs_service_keeps_latest_100_log_lines_per_job(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        root_dir / "features/percus_ai/environment/configs/venv/vla/runtime/default.yaml",
        """
id: default
envs:
  pi0:
    python: "3.10"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants:
  default:
    python: "3.10"
    runtime_packages: {}
    build:
      source:
        type: index
      commands:
        - id: build_pytorch
          command:
            - python3
            - -c
            - print("noop")
    checks: []
""".strip()
        + "\n",
    )

    async def _run():
        service = BuildJobsService(
            config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
            build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
            environment_build_operation=_FakeEnvironmentBuildOperation(),
            shared_build_operation=_VerboseSharedBuildOperation(),
        )
        accepted = service.start_shared_build(package="pytorch", variant="default")
        job_id = accepted.job.job_id

        terminal_state = await _wait_for_terminal_state(service, job_id)
        assert terminal_state == "completed"

        _, events = service.poll_log_events()
        job_events = [item for item in events if item["job_id"] == job_id]
        assert len(job_events) == 100
        assert job_events[0]["line"] == "line-50\n"
        assert job_events[-1]["line"] == "line-149\n"

        await service.shutdown()

    asyncio.run(_run())


def test_build_jobs_service_passes_train_config_group(tmp_path: Path):
    root_dir = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_text(
        data_dir / "environment/configs/venv/vla/train/sm_120.yaml",
        """
id: sm_120
envs:
  pi0_train:
    usage: training
    python: "3.10"
    installs: []
    checks: []
""".strip()
        + "\n",
    )
    _write_text(
        data_dir / "environment/configs/venv/shared_packages/pytorch.yaml",
        """
package: pytorch
variants: {}
""".strip()
        + "\n",
    )

    async def _run():
        operation = _FakeEnvironmentBuildOperation()
        service = BuildJobsService(
            config_loader=EnvironmentConfigLoader(root_dir=root_dir, data_dir=data_dir),
            build_store=BuildStore(layout=BuildLayout(data_dir=data_dir)),
            environment_build_operation=operation,
            shared_build_operation=_FakeSharedBuildOperation(),
        )
        accepted = service.start_env_build(config_group="vla_train", config_id="sm_120", env_name="pi0_train")
        terminal_state = await _wait_for_terminal_state(service, accepted.job.job_id)
        assert terminal_state == "completed"
        assert operation.calls[0][:3] == ("sm_120", "pi0_train", "vla_train")
        await service.shutdown()

    asyncio.run(_run())

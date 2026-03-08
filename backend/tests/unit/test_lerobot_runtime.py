from __future__ import annotations

import interfaces_backend.services.lerobot_runtime as lerobot_runtime


def test_start_lerobot_starts_all_compose_services(monkeypatch, tmp_path):
    scripts_dir = tmp_path / "docker" / "lerobot_ros2"
    scripts_dir.mkdir(parents=True)
    script_path = scripts_dir / "up"
    script_path.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    script_path.chmod(0o755)
    called: dict[str, object] = {}

    monkeypatch.setattr(lerobot_runtime, "get_project_root", lambda: tmp_path)

    def _fake_run(cmd, **kwargs):
        called["cmd"] = cmd
        called["cwd"] = kwargs.get("cwd")
        called["capture_output"] = kwargs.get("capture_output")
        called["text"] = kwargs.get("text")
        return lerobot_runtime.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(lerobot_runtime.subprocess, "run", _fake_run)

    result = lerobot_runtime.start_lerobot(strict=True)

    assert result.returncode == 0
    assert called["cmd"] == [str(script_path)]
    assert called["cwd"] == tmp_path
    assert called["capture_output"] is True
    assert called["text"] is True

from __future__ import annotations

import json
from pathlib import Path
import zipfile

from interfaces_backend.services.build_error_reports import BuildErrorReportsService


class _FakeUploader:
    def __init__(self, target_dir: Path) -> None:
        self.target_dir = target_dir
        self.uploads: list[tuple[str, str]] = []

    def upload_file(self, filename: str, bucket_name: str, key: str, *, callback=None) -> None:
        del callback
        destination = self.target_dir / Path(key).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(Path(filename).read_bytes())
        self.uploads.append((bucket_name, key))


def test_build_error_report_service_creates_zip_and_uploads(tmp_path: Path):
    artifact_dir = tmp_path / "artifact"
    logs_dir = artifact_dir / "logs"
    venv_dir = artifact_dir / "venv"
    output_dir = artifact_dir / "output"
    logs_dir.mkdir(parents=True)
    venv_dir.mkdir()
    output_dir.mkdir()
    (artifact_dir / "metadata.json").write_text('{"success": false}\n', encoding="utf-8")
    (artifact_dir / "config.yaml").write_text("id: broken\n", encoding="utf-8")
    (logs_dir / "flash-attn.stderr.log").write_text("nvcc missing\n", encoding="utf-8")
    (venv_dir / "ignore.txt").write_text("ignore me\n", encoding="utf-8")
    (output_dir / "artifact.bin").write_bytes(b"binary")

    upload_dir = tmp_path / "uploaded"
    service = BuildErrorReportsService(
        s3_uploader=_FakeUploader(upload_dir),
        bucket="daihen",
        version="v2",
    )

    result = service.create_report(
        kind="env",
        setting_id="default:groot",
        build_id="build-1",
        artifact_dir=artifact_dir,
        metadata={"success": False, "steps": [{"step": "flash-attn"}]},
    )

    assert result.kind == "env"
    assert result.setting_id == "default:groot"
    assert result.object_path.startswith("s3://daihen/v2/build-reports/env/default-groot/")

    uploaded_zip = next(upload_dir.glob("*.zip"))
    with zipfile.ZipFile(uploaded_zip) as archive:
        names = set(archive.namelist())
        assert "report.json" in names
        assert "directory-summary.json" in names
        assert "metadata.json" in names
        assert "config.yaml" in names
        assert "logs/flash-attn.stderr.log" in names
        assert "venv/ignore.txt" not in names
        assert "output/artifact.bin" not in names
        report = json.loads(archive.read("report.json").decode("utf-8"))
        assert report["report_id"] == result.report_id
        assert report["build_id"] == "build-1"

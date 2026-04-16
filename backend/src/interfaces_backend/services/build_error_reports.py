"""Build error report generation and R2 upload."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any, Protocol
from uuid import uuid4
import zipfile

from fastapi import HTTPException

from interfaces_backend.models.build_management import BuildErrorReportResponse
from percus_ai.storage import S3Manager


class S3Uploader(Protocol):
    def upload_file(self, filename: str, bucket_name: str, key: str, *, callback=None) -> None: ...


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_segment(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    compact = "-".join(part for part in normalized.split("-") if part)
    return compact or "unknown"


class BuildErrorReportsService:
    def __init__(
        self,
        *,
        s3_uploader: S3Uploader | None = None,
        bucket: str | None = None,
        version: str | None = None,
    ) -> None:
        self._s3 = s3_uploader or S3Manager()
        self._bucket = bucket
        self._version = version

    def create_report(
        self,
        *,
        kind: str,
        setting_id: str,
        build_id: str,
        artifact_dir: Path,
        metadata: dict[str, Any],
    ) -> BuildErrorReportResponse:
        report_id = self._build_report_id(kind=kind, build_id=build_id)
        bucket = self._resolve_bucket()
        key = self._build_object_key(kind=kind, setting_id=setting_id, report_id=report_id)
        uploaded_at = _utcnow_iso()

        with tempfile.TemporaryDirectory(prefix="build-error-report-") as temp_dir:
            zip_path = Path(temp_dir) / f"{report_id}.zip"
            self._build_zip(
                zip_path=zip_path,
                kind=kind,
                setting_id=setting_id,
                build_id=build_id,
                artifact_dir=artifact_dir,
                metadata=metadata,
                uploaded_at=uploaded_at,
                report_id=report_id,
            )
            self._s3.upload_file(str(zip_path), bucket, key)

        return BuildErrorReportResponse(
            report_id=report_id,
            kind=kind,  # type: ignore[arg-type]
            setting_id=setting_id,
            build_id=build_id,
            object_path=f"s3://{bucket}/{key}",
            uploaded_at=uploaded_at,
        )

    def _build_report_id(self, *, kind: str, build_id: str) -> str:
        suffix = uuid4().hex[:10]
        return f"{_sanitize_segment(kind)}-{_sanitize_segment(build_id)}-{suffix}"

    def _resolve_bucket(self) -> str:
        bucket = self._bucket or os.environ.get("R2_BUCKET") or os.environ.get("S3_BUCKET")
        if not bucket:
            raise HTTPException(status_code=500, detail="R2 bucket is not configured")
        return bucket

    def _version_prefix(self) -> str:
        version = (self._version or os.environ.get("R2_VERSION") or "v2").strip("/")
        return f"{version}/" if version else ""

    def _build_object_key(self, *, kind: str, setting_id: str, report_id: str) -> str:
        return f"{self._version_prefix()}build-reports/{_sanitize_segment(kind)}/{_sanitize_segment(setting_id)}/{report_id}.zip"

    def _build_zip(
        self,
        *,
        zip_path: Path,
        kind: str,
        setting_id: str,
        build_id: str,
        artifact_dir: Path,
        metadata: dict[str, Any],
        uploaded_at: str,
        report_id: str,
    ) -> None:
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            self._write_json(
                archive,
                "report.json",
                {
                    "report_id": report_id,
                    "kind": kind,
                    "setting_id": setting_id,
                    "build_id": build_id,
                    "artifact_dir": str(artifact_dir),
                    "uploaded_at": uploaded_at,
                    "metadata": metadata,
                },
            )
            self._write_json(
                archive,
                "directory-summary.json",
                self._build_directory_summary(artifact_dir),
            )
            self._add_if_exists(archive, artifact_dir / "metadata.json", "metadata.json")
            self._add_if_exists(archive, artifact_dir / "config.yaml", "config.yaml")
            self._add_directory(archive, artifact_dir / "logs", "logs")

    def _build_directory_summary(self, artifact_dir: Path) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for child in sorted(artifact_dir.iterdir(), key=lambda path: path.name) if artifact_dir.exists() else []:
            if child.is_dir():
                file_count = sum(1 for item in child.rglob("*") if item.is_file())
                entries.append(
                    {
                        "name": child.name,
                        "type": "directory",
                        "file_count": file_count,
                    }
                )
            else:
                entries.append(
                    {
                        "name": child.name,
                        "type": "file",
                        "size_bytes": child.stat().st_size,
                    }
                )
        return {"entries": entries}

    def _write_json(self, archive: zipfile.ZipFile, arcname: str, payload: dict[str, Any]) -> None:
        archive.writestr(arcname, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    def _add_if_exists(self, archive: zipfile.ZipFile, path: Path, arcname: str) -> None:
        if path.exists() and path.is_file():
            archive.write(path, arcname)

    def _add_directory(self, archive: zipfile.ZipFile, directory: Path, arc_root: str) -> None:
        if not directory.exists() or not directory.is_dir():
            return
        for file_path in sorted(path for path in directory.rglob("*") if path.is_file()):
            relative = file_path.relative_to(directory)
            archive.write(file_path, f"{arc_root}/{relative.as_posix()}")


_build_error_reports_service: BuildErrorReportsService | None = None


def get_build_error_reports_service() -> BuildErrorReportsService:
    global _build_error_reports_service
    if _build_error_reports_service is None:
        _build_error_reports_service = BuildErrorReportsService()
    return _build_error_reports_service

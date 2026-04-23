from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

from interfaces_backend.models.training import JobInfo


def _load_patch_script():
    script_path = Path(__file__).resolve().parents[4] / "scripts" / "patch_training_job_timestamps.py"
    spec = importlib.util.spec_from_file_location("patch_training_job_timestamps_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_job_info_serializes_naive_training_timestamps_as_utc():
    job = JobInfo(
        job_id="job-1",
        job_name="job",
        instance_id="",
        status="completed",
        mode="train",
        created_at="2026-04-17T00:00:00",
        updated_at="2026-04-17T00:00:00",
        started_at="2026-04-17T00:05:00",
        completed_at="2026-04-17T01:05:00",
    )

    payload = job.model_dump(mode="json")

    assert job.started_at is not None
    assert job.started_at.tzinfo == timezone.utc
    assert payload["started_at"] == "2026-04-17T00:05:00Z"
    assert payload["completed_at"] == "2026-04-17T01:05:00Z"


def test_patch_script_detects_nine_hour_metric_drift():
    module = _load_patch_script()
    detected = module._detect_metric_drift(
        value=datetime(2026, 4, 17, 18, 0, tzinfo=timezone.utc),
        reference=datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc),
        drift_hours=9,
        tolerance_minutes=30,
    )

    assert detected is not None
    new_value, reason = detected
    assert new_value == datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc)
    assert "subtract 9h" in reason


def test_patch_script_parses_five_digit_fraction_timestamps():
    module = _load_patch_script()

    parsed = module._parse_datetime("2026-04-21T16:34:15.99628+00:00")

    assert parsed == datetime(2026, 4, 21, 16, 34, 15, 996280, tzinfo=timezone.utc)


def test_patch_script_converts_berlin_local_wall_time_to_utc():
    module = _load_patch_script()

    patches = module._build_local_timezone_patches(
        {
            "job_id": "job-1",
            "job_name": "Week23-Oshima",
            "started_at": "2026-04-23T12:00:00+00:00",
        },
        ["started_at"],
        timezone_name="Europe/Berlin",
        owner_label="oshima",
    )

    assert len(patches) == 1
    assert patches[0].new_value == "2026-04-23T10:00:00+00:00"
    assert "Europe/Berlin" in patches[0].reason


def test_patch_script_resolves_oshima_timezone_from_owner_profile():
    module = _load_patch_script()
    job = {
        "job_id": "job-1",
        "job_name": "cardboard",
        "owner_user_id": "user-1",
    }
    profiles = {
        "user-1": module.OwnerProfile(
            user_id="user-1",
            username="oshima",
            first_name="",
            last_name="",
        )
    }

    timezone_name = module._resolve_owner_timezone(
        job,
        profiles,
        rules=[("oshima", "Europe/Berlin")],
        default_timezone="Asia/Tokyo",
    )

    assert timezone_name == "Europe/Berlin"


def test_patch_script_skips_completed_at_patch_that_would_break_runtime():
    module = _load_patch_script()
    skipped = []

    patches = module._build_local_timezone_patches(
        {
            "job_id": "job-1",
            "job_name": "job",
            "started_at": "2026-04-21T02:37:07+00:00",
            "completed_at": "2026-04-21T04:09:46+00:00",
        },
        ["completed_at"],
        timezone_name="Asia/Tokyo",
        owner_label="kinoue",
        skipped=skipped,
    )

    assert patches == []
    assert len(skipped) == 1
    assert "completed_at before started_at" in skipped[0].reason


def test_patch_script_skips_created_at_when_it_is_already_before_started_at():
    module = _load_patch_script()
    skipped = []

    patches = module._build_local_timezone_patches(
        {
            "job_id": "job-1",
            "job_name": "job",
            "created_at": "2026-04-23T03:36:15+00:00",
            "started_at": "2026-04-23T03:39:36+00:00",
        },
        ["created_at"],
        timezone_name="Asia/Tokyo",
        owner_label="kinoue",
        skipped=skipped,
    )

    assert patches == []
    assert len(skipped) == 1
    assert "created_at is not later than started_at" in skipped[0].reason


def test_patch_script_skips_completed_at_when_started_at_is_empty():
    module = _load_patch_script()
    skipped = []

    patches = module._build_local_timezone_patches(
        {
            "job_id": "job-1",
            "job_name": "job",
            "completed_at": "2026-04-21T01:10:57+00:00",
        },
        ["completed_at"],
        timezone_name="Asia/Tokyo",
        owner_label="kinoue",
        skipped=skipped,
    )

    assert patches == []
    assert len(skipped) == 1
    assert "started_at is empty" in skipped[0].reason


def test_patch_script_skips_completed_at_when_created_at_is_already_corrected():
    module = _load_patch_script()
    skipped = []

    patches = module._build_local_timezone_patches(
        {
            "job_id": "job-1",
            "job_name": "job",
            "created_at": "2026-04-22T01:56:41+00:00",
            "started_at": "2026-04-22T02:00:32+00:00",
            "completed_at": "2026-04-22T18:16:34+00:00",
        },
        ["completed_at"],
        timezone_name="Asia/Tokyo",
        owner_label="morikawa",
        skipped=skipped,
    )

    assert patches == []
    assert len(skipped) == 1
    assert "created_at is already not later than started_at" in skipped[0].reason

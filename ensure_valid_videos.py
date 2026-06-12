#!/usr/bin/env python3
from __future__ import annotations

"""
Repair YouTube job manifests and pending queue files in-place.

What this fixes:
- Removes jobs whose video file is missing or shorter than 15 minutes
- Removes jobs missing license evidence
- Preserves jobs with missing thumbnails because thumbnails are optional
- Moves fully invalid pending queue files into needs_fix/
- Rewrites stale manifest files so scheduled jobs stop retrying bad inputs
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path("/home/pi/Desktop/test/create")
PENDING_DIR = Path("/mnt/raspberry_storage/nfs_shared/youtubeuploads_pending")
NEEDS_FIX_DIR = PENDING_DIR / "needs_fix"
REPORT_PATH = ROOT / "youtube_job_repair_report.json"
MIN_DURATION_SECONDS = 900.0
MIN_PLAUSIBLE_VIDEO_BYTES = 1_000_000

MANIFEST_PATHS = [
    ROOT / "youtube_jobs.json",
    ROOT / "youtube_jobs_python10.json",
]

@dataclass
class JobIssue:
    """Auto-generated docstring."""
    code: str
    detail: str

def _load_jobs(path: Path) -> list[dict[str, Any]]:
    """Auto-generated docstring."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise ValueError(f"manifest must be a JSON object or array: {path}")

    jobs: list[dict[str, Any]] = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest contains non-object entry {idx}: {path}")
        jobs.append(item)
    return jobs

def _video_duration_seconds(video_path: Path) -> float:
    """Auto-generated docstring."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def _validate_job(job: dict[str, Any]) -> tuple[bool, list[JobIssue]]:
    """Auto-generated docstring."""
    issues: list[JobIssue] = []

    video_path = Path(str(job.get("video_path", "")).strip())
    if not video_path.exists():
        issues.append(JobIssue("missing_video", str(video_path)))
    else:
        if video_path.stat().st_size < MIN_PLAUSIBLE_VIDEO_BYTES:
            issues.append(
                JobIssue("short_video", f"{video_path} (file too small: {video_path.stat().st_size} bytes)")
            )
        else:
            duration = _video_duration_seconds(video_path)
            if duration < MIN_DURATION_SECONDS:
                issues.append(JobIssue("short_video", f"{video_path} ({duration:.1f}s)"))

    license_path = Path(str(job.get("license_evidence_path", "")).strip())
    if not license_path.exists():
        issues.append(JobIssue("missing_license", str(license_path)))

    thumb_raw = str(job.get("thumbnail_path", "")).strip()
    if thumb_raw:
        thumb_path = Path(thumb_raw)
        if not thumb_path.exists():
            issues.append(JobIssue("missing_optional_thumbnail", str(thumb_path)))

    hard_fail_codes = {"missing_video", "short_video", "missing_license"}
    is_valid = not any(issue.code in hard_fail_codes for issue in issues)
    return is_valid, issues

def _write_jobs(path: Path, jobs: list[dict[str, Any]]) -> None:
    """Auto-generated docstring."""
    path.write_text(json.dumps(jobs, indent=2), encoding="utf-8")

def _repair_manifest(path: Path) -> dict[str, Any]:
    """Auto-generated docstring."""
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "kept_jobs": 0,
            "removed_jobs": 0,
            "status": "missing",
            "issues": [],
        }

    jobs = _load_jobs(path)
    kept_jobs: list[dict[str, Any]] = []
    removed_jobs: list[dict[str, Any]] = []
    issue_rows: list[dict[str, Any]] = []

    for index, job in enumerate(jobs, start=1):
        is_valid, issues = _validate_job(job)
        issue_rows.append(
            {
                "job": index,
                "title": job.get("title", ""),
                "issues": [{"code": issue.code, "detail": issue.detail} for issue in issues],
            }
        )
        if is_valid:
            kept_jobs.append(job)
        else:
            removed_jobs.append(job)

    changed = len(removed_jobs) > 0 or len(kept_jobs) != len(jobs)
    if changed:
        _write_jobs(path, kept_jobs)

    return {
        "path": str(path),
        "exists": True,
        "kept_jobs": len(kept_jobs),
        "removed_jobs": len(removed_jobs),
        "status": "rewritten" if changed else "unchanged",
        "issues": issue_rows,
    }

def _repair_pending_queue() -> list[dict[str, Any]]:
    """Auto-generated docstring."""
    NEEDS_FIX_DIR.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []

    for path in sorted(PENDING_DIR.glob("*.json")):
        jobs = _load_jobs(path)
        kept_jobs: list[dict[str, Any]] = []
        issue_rows: list[dict[str, Any]] = []

        for index, job in enumerate(jobs, start=1):
            is_valid, issues = _validate_job(job)
            issue_rows.append(
                {
                    "job": index,
                    "title": job.get("title", ""),
                    "issues": [{"code": issue.code, "detail": issue.detail} for issue in issues],
                }
            )
            if is_valid:
                kept_jobs.append(job)

        if kept_jobs:
            if len(kept_jobs) != len(jobs):
                _write_jobs(path, kept_jobs)
                status = "trimmed"
            else:
                status = "unchanged"
            target = str(path)
        else:
            target_path = NEEDS_FIX_DIR / path.name
            shutil.move(str(path), str(target_path))
            status = "moved_to_needs_fix"
            target = str(target_path)

        reports.append(
            {
                "path": str(path),
                "target": target,
                "original_jobs": len(jobs),
                "kept_jobs": len(kept_jobs),
                "removed_jobs": len(jobs) - len(kept_jobs),
                "status": status,
                "issues": issue_rows,
            }
        )

    return reports

def main() -> int:
    """Auto-generated docstring."""
    manifest_reports = [_repair_manifest(path) for path in MANIFEST_PATHS]
    pending_reports = _repair_pending_queue()

    report = {
        "manifests": manifest_reports,
        "pending_queue": pending_reports,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    manifest_removed = sum(row["removed_jobs"] for row in manifest_reports)
    pending_removed = sum(row["removed_jobs"] for row in pending_reports)
    pending_moved = sum(1 for row in pending_reports if row["status"] == "moved_to_needs_fix")

    print(
        "[DONE] Repaired YouTube job inputs: "
        f"removed {manifest_removed} stale manifest job(s), "
        f"removed {pending_removed} pending job(s), "
        f"moved {pending_moved} file(s) to needs_fix. "
        f"Report: {REPORT_PATH}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

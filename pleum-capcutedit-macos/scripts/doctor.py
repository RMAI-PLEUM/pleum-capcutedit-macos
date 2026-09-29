#!/usr/bin/env python3
"""Cross-platform read-only readiness doctor."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from capcut_installation_locator import installation_candidates
from platform_packages import package_status
from platform_paths import capcut_project_root_candidates


def build_report(run_tests: bool = False) -> dict:
    load_dotenv(ROOT / ".env")
    packages = package_status()
    roots = capcut_project_root_candidates()
    warnings, errors = [], []
    if not packages["ffmpeg_version"] or not packages["ffprobe_version"]:
        errors.append("FFmpeg and ffprobe are required.")
    missing = [
        name for name, available in packages["python_packages"].items()
        if not available and name not in {"rapidfuzz"}
    ]
    if missing:
        errors.append("Missing Python packages: " + ", ".join(missing))
    if not packages["python_packages"].get("rapidfuzz"):
        warnings.append("RapidFuzz is unavailable; slower standard-library fuzzy matching is used.")
    if not installation_candidates():
        warnings.append("CapCut installation was not found.")
    if not roots:
        warnings.append("No verified CapCut project root was found.")
    if not os.getenv("ELEVENLABS_API_KEY", "").strip():
        warnings.append("ELEVENLABS_API_KEY is absent; cached/local modes remain usable.")
    test_status = "not_run"
    if run_tests:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-q"],
            cwd=ROOT,
        )
        test_status = "passed" if result.returncode == 0 else "failed"
        if result.returncode:
            errors.append("Unit tests failed.")
    readiness = "NOT_READY" if errors else (
        "READY_WITH_WARNINGS" if warnings else "READY"
    )
    return {
        **packages,
        "capcut_installation_candidates": installation_candidates(),
        "capcut_project_root_candidates": roots,
        "parseable_project_count": sum(
            item["parseable_project_count"] for item in roots
        ),
        "writable_project_roots": [
            item["path"] for item in roots if item["writable"]
        ],
        "api_key_present": bool(os.getenv("ELEVENLABS_API_KEY", "").strip()),
        "skill_installation_status": "repository_skill_available"
        if (ROOT / "SKILL.md").is_file() else "missing",
        "schema_compatibility_status": "requires_selected_project",
        "style_preset_status": "local_relearn_recommended",
        "unit_test_status": test_status,
        "warnings": warnings, "errors": errors, "readiness": readiness,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args()
    report = build_report(args.run_tests)
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    (output / "doctor_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"Edit CapCut doctor: {report['readiness']}",
        f"OS: {report['operating_system']}",
        f"Architecture: {report['architecture']}",
        f"Python: {report['python_version']}",
        f"FFmpeg: {report['ffmpeg_version'] or 'missing'}",
        f"ffprobe: {report['ffprobe_version'] or 'missing'}",
        f"Projects: {report['parseable_project_count']}",
        f"API key present: {report['api_key_present']}",
        *[f"WARNING: {item}" for item in report["warnings"]],
        *[f"ERROR: {item}" for item in report["errors"]],
    ]
    (output / "doctor_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if report["readiness"] == "NOT_READY" else 0


if __name__ == "__main__":
    raise SystemExit(main())

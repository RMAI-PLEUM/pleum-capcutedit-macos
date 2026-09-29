#!/usr/bin/env python3
"""Read-only macOS prerequisite check with standard-library dependencies only."""

from __future__ import annotations

import json
import platform
import shutil
import sys
from pathlib import Path


def project_count(root: Path) -> int:
    if not root.is_dir():
        return 0
    count = 0
    for child in root.iterdir():
        metadata = child / "draft_meta_info.json"
        if not metadata.is_file():
            continue
        try:
            value = json.loads(metadata.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("draft_name") and value.get("draft_id"):
            count += 1
    return count


def main() -> int:
    home = Path.home()
    capcut_apps = [
        path for path in (
            Path("/Applications/CapCut.app"),
            home / "Applications/CapCut.app",
        )
        if path.exists()
    ]
    roots = [
        home / "Movies/CapCut/User Data/Projects/com.lveditor.draft",
        home / "Library/Application Support/CapCut/User Data/Projects/com.lveditor.draft",
        home / "Library/Containers/com.lemon.lvoverseas/Data/Library/Application Support/CapCut/User Data/Projects/com.lveditor.draft",
    ]
    verified_roots = [
        {"path": str(path), "parseable_projects": count}
        for path in roots
        if (count := project_count(path)) > 0
    ]
    report = {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "python_supported": sys.version_info >= (3, 10),
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "capcut_app_candidates": [str(path) for path in capcut_apps],
        "verified_project_roots": verified_roots,
    }
    missing = []
    if report["platform"] != "Darwin":
        missing.append("macOS")
    if not report["python_supported"]:
        missing.append("Python 3.10+")
    if not report["ffmpeg"] or not report["ffprobe"]:
        missing.append("FFmpeg/ffprobe")
    if not capcut_apps:
        missing.append("CapCut.app")
    report["status"] = "READY_TO_INSTALL" if not missing else "NEEDS_SETUP"
    report["missing"] = missing
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if "FFmpeg/ffprobe" in missing:
        print("Install FFmpeg with your preferred method; Homebrew users: brew install ffmpeg")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

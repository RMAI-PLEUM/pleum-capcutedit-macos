"""Copy complete CapCut fixture folders and hash the copies."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import platform
import plistlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capcut_project_scanner import ProjectDiscovery
from utils import PROJECT_ROOT, write_json


DESTINATIONS = {
    "Schema 01 - Video Only": "01_video_only",
    "Schema 02 - One Caption": "02_one_caption",
    "Schema 03 - Styled Caption": "03_styled_caption",
    "Schema 04 - Multiple Captions": "04_multiple_captions",
    "Schema 05 - One Cut": "05_one_cut",
}


def detect_capcut_version() -> dict[str, str | None]:
    if platform.system() == "Darwin":
        for application in (
            Path("/Applications/CapCut.app"),
            Path.home() / "Applications/CapCut.app",
        ):
            info = application / "Contents/Info.plist"
            if not info.is_file():
                continue
            try:
                with info.open("rb") as handle:
                    plist = plistlib.load(handle)
            except (OSError, plistlib.InvalidFileException):
                continue
            return {
                "detection_method": "macOS CapCut application Info.plist",
                "executable_path": str(application.resolve()),
                "version_number": str(
                    plist.get("CFBundleShortVersionString")
                    or plist.get("CFBundleVersion") or ""
                ) or None,
                "discovery_timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
            }
    local = os.getenv("LOCALAPPDATA")
    apps = Path(local) / "CapCut" / "Apps" if local else Path()
    version_pattern = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
    executables = []
    if apps.is_dir():
        for child in apps.iterdir():
            executable = child / "CapCut.exe"
            if child.is_dir() and version_pattern.match(child.name) and executable.is_file():
                parts = tuple(int(part) for part in child.name.split("."))
                executables.append((parts, child.name, executable))
    if executables:
        _, version, executable = max(executables)
        method = "highest versioned directory under %LOCALAPPDATA%\\CapCut\\Apps"
        return {
            "detection_method": method,
            "executable_path": str(executable.resolve()),
            "version_number": version,
            "discovery_timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
        }
    launcher = apps / "CapCut.exe"
    return {
        "detection_method": "CapCut launcher path fallback" if launcher.is_file() else "not found",
        "executable_path": str(launcher.resolve()) if launcher.is_file() else None,
        "version_number": None,
        "discovery_timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _version_text(version: dict[str, str | None]) -> str:
    return (
        f"Detection method: {version['detection_method']}\n"
        f"Executable path: {version['executable_path'] or 'not found'}\n"
        f"Version number: {version['version_number'] or 'unknown'}\n"
        f"Discovery timestamp: {version['discovery_timestamp']}\n"
    )


def collect_fixtures(projects: list[ProjectDiscovery]) -> tuple[dict[str, Any], Path]:
    base = (PROJECT_ROOT / "sample_capcut_projects").resolve()
    base.mkdir(parents=True, exist_ok=True)
    expected_names = set(DESTINATIONS)
    if {project.display_name for project in projects} != expected_names:
        raise RuntimeError("Collector requires one confident match for every expected fixture.")
    existing = [base / folder for folder in DESTINATIONS.values() if (base / folder).exists()]
    if existing:
        shown = "\n".join(str(path) for path in existing)
        raise FileExistsError(
            "Fixture destinations already exist; refusing to replace them automatically:\n" + shown
        )

    version = detect_capcut_version()
    manifest: dict[str, Any] = {
        "version": 1,
        "read_only_source_collection": True,
        "capcut": version,
        "fixtures": [],
    }
    created: list[Path] = []
    try:
        for project in projects:
            destination = base / DESTINATIONS[project.display_name]
            shutil.copytree(project.project_path, destination, copy_function=shutil.copy2)
            created.append(destination)
            copied_files = sorted(path for path in destination.rglob("*") if path.is_file())
            file_records = [
                {
                    "relative_path": path.relative_to(destination).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in copied_files
            ]
            manifest["fixtures"].append({
                "fixture_name": DESTINATIONS[project.display_name],
                "original_capcut_project_name": project.display_name,
                "original_project_path": str(project.project_path),
                "copied_destination": str(destination),
                "file_count": len(file_records),
                "files": file_records,
                "folder_total_size": sum(item["size"] for item in file_records),
                "copied_timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
                "detected_duration_seconds": project.duration_seconds,
            })
    except Exception:
        # Roll back only destinations created by this invocation, all inside our workspace.
        for destination in reversed(created):
            if destination.parent == base and destination.exists():
                shutil.rmtree(destination)
        raise
    (base / "CAPCUT_VERSION.txt").write_text(_version_text(version), encoding="utf-8")
    manifest_path = base / "fixture_manifest.json"
    write_json(manifest_path, manifest)
    return manifest, manifest_path

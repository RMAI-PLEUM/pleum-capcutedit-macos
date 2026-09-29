#!/usr/bin/env python3
"""Read-only macOS CapCut storage, mirror, and compatibility audit."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from capcut_fixture_collector import detect_capcut_version
from capcut_live_project_reader import read_live_project
from capcut_project_locator import discover_projects
from platform_paths import capcut_project_root_candidates
from platform_process import capcut_process_ids
from schema_compatibility import compatibility_status


def build_report() -> dict:
    running = capcut_process_ids()
    roots = capcut_project_root_candidates()
    projects = []
    if not running:
        for root in roots:
            for project in discover_projects(Path(root["path"])):
                record = {
                    "name": project.name,
                    "identity": project.identity,
                    "path": str(project.path),
                }
                try:
                    live = read_live_project(project)
                    schema = compatibility_status(live.primary)
                    record.update({
                        "readable": True,
                        "storage_format": live.storage_format,
                        "active_mirror_count": len(live.draft_paths),
                        "active_mirrors_identical": all(
                            draft == live.drafts[0] for draft in live.drafts[1:]
                        ),
                        "schema": schema,
                        "direct_write_ready": bool(
                            len(live.draft_paths) == 2
                            and schema["write_allowed"]
                        ),
                    })
                except Exception as exc:
                    record.update({
                        "readable": False,
                        "direct_write_ready": False,
                        "error": str(exc),
                    })
                projects.append(record)
    direct_ready = bool(projects) and all(
        item.get("direct_write_ready") for item in projects
    )
    return {
        "version": 1,
        "read_only": True,
        "platform": platform.platform(),
        "capcut": detect_capcut_version(),
        "capcut_running_process_ids": running,
        "safe_snapshot": not running,
        "project_roots": roots,
        "projects": projects,
        "direct_write_ready": direct_ready,
        "next_gate": None if direct_ready else (
            "Create controlled Mac fixtures, validate both active mirrors, "
            "forced rollback, CapCut reopen, and second read-back."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_report()
    output = ROOT / "output/macos_validation_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"macOS CapCut audit: {'READY' if report['direct_write_ready'] else 'VALIDATION_REQUIRED'}")
        print(f"CapCut: {report['capcut'].get('version_number') or 'unknown'}")
        print(f"Safe snapshot: {report['safe_snapshot']}")
        print(f"Projects audited: {len(report['projects'])}")
        for item in report["projects"]:
            print(
                f"- {item['name']}: {item.get('storage_format', 'unreadable')}, "
                f"mirrors={item.get('active_mirror_count', 0)}, "
                f"write={'ready' if item.get('direct_write_ready') else 'blocked'}"
            )
        print(f"Report: {output}")
    return 0 if report["safe_snapshot"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

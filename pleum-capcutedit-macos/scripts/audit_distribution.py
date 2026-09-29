#!/usr/bin/env python3
"""Fail closed when a release contains secrets, private paths, drafts, or media."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_NAMES = {".env", "draft_content.json", "draft_meta_info.json"}
FORBIDDEN_DIRS = {
    ".git", ".venv", "__pycache__", "output", "logs", "state", "temp",
    "backups", "input", "sample_capcut_projects", "sandbox_capcut_projects",
}
FORBIDDEN_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".mp4", ".mov", ".avi", ".mkv",
    ".ttf", ".otf", ".woff", ".woff2", ".zip", ".7z", ".rar",
}
PATTERNS = {
    "windows_user_path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.I),
    "mac_user_path": re.compile("/" + r"Users/[^/\s\"']+", re.I),
    "api_key": re.compile(r"(?:xi-|sk_)[A-Za-z0-9_-]{20,}"),
    "real_env_assignment": re.compile(
        r"ELEVENLABS_API_KEY\s*=\s*(?!put_your_api_key_here)(?!\s*$)\S+"
    ),
    "private_project_name": re.compile(r"\bInsure\s+Clip\b", re.I),
    "removed_workflow_code": re.compile(
        r"(?:build|apply|learn|inspect|arrange|validate)[-_]cartoon|cartoon_", re.I
    ),
}


def audit(root: Path) -> dict:
    findings, files = [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in FORBIDDEN_DIRS for part in parts):
            continue
        relative = path.relative_to(root).as_posix()
        files.append(relative)
        if "cartoon" in relative.casefold():
            findings.append({"file": relative, "reason": "removed_workflow_path"})
        if path.name in FORBIDDEN_NAMES:
            findings.append({"file": relative, "reason": "forbidden_name"})
        if path.suffix.casefold() in FORBIDDEN_EXTENSIONS:
            findings.append({"file": relative, "reason": "forbidden_binary_or_archive"})
        if path.stat().st_size > 10 * 1024 * 1024:
            findings.append({"file": relative, "reason": "oversized_file"})
        if path.suffix.casefold() in {
            ".py", ".md", ".json", ".yaml", ".yml", ".txt", ".ps1",
            ".sh", ".toml", ".example", "",
        }:
            text = path.read_text(encoding="utf-8", errors="replace")
            for name, pattern in PATTERNS.items():
                if path.name == "audit_distribution.py" and name in {
                    "private_project_name", "removed_workflow_code"
                }:
                    continue
                if pattern.search(text):
                    findings.append({"file": relative, "reason": name})
    return {"passed": not findings, "root": root.name, "file_count": len(files), "findings": findings}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    report = audit(root)
    output = args.output or (root.parent / "Pleum-CapcutEdit-macOS-audit.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

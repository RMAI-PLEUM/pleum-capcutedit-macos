#!/usr/bin/env python3
"""Install the macOS umbrella skill and both component skills safely."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "pleum-capcutedit-macos": ROOT,
    "edit-capcut": ROOT / "skills/edit-capcut",
    "pattern-1": ROOT / "skills/pattern-1",
}
IGNORE = shutil.ignore_patterns(
    ".git", ".env", ".venv", "output", "logs", "state", "temp",
    "backups", "dist", "__pycache__", "*.pyc", "*.zip",
)


def validate_skill(path: Path, expected_name: str) -> None:
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith(f"---\nname: {expected_name}\n"):
        raise RuntimeError(f"Invalid {expected_name} SKILL.md: {path}")
    if "\ndescription:" not in text:
        raise RuntimeError(f"{expected_name} description is missing")


def destination_base(tool: str, project: Path | None) -> Path:
    if tool == "claude-project":
        if project is None:
            raise RuntimeError("--project-path is required for claude-project")
        return project.resolve() / ".claude/skills"
    if tool == "claude-personal":
        return Path.home() / ".claude/skills"
    if project is None:
        raise RuntimeError(
            "Codex destinations vary by version. Pass --project-path for a "
            "repository-level installation or use Codex skill import."
        )
    return project.resolve() / ".agents/skills"


def install_one(source: Path, target: Path, yes: bool) -> int:
    validate_skill(source, target.name)
    if target.exists():
        existing = target / "SKILL.md"
        if existing.is_file() and existing.read_bytes() == (source / "SKILL.md").read_bytes():
            print(f"Already installed: {target.name}")
            return 0
        if not yes:
            answer = input(f"{target} differs. Replace it? [y/N] ").strip().casefold()
            if answer != "y":
                return 2
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=IGNORE)
    validate_skill(target, target.name)
    print(f"Installed: {target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True,
                        choices=("codex", "claude-project", "claude-personal"))
    parser.add_argument("--project-path", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    base = destination_base(args.tool, args.project_path)
    for name, source in SKILLS.items():
        validate_skill(source, name)
        print(f"{name}: {source} -> {base / name}")
    if args.dry_run:
        return 0
    for name, source in SKILLS.items():
        code = install_one(source, base / name, args.yes)
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

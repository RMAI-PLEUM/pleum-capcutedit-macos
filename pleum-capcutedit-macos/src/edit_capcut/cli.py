"""Friendly command wrapper over the proven internal CLI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _internal(*args: str) -> int:
    return subprocess.call([sys.executable, str(ROOT / "src/main.py"), *args])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="edit-capcut")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("setup", "doctor", "macos-validate"):
        sub.add_parser(name)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--project", required=True)
    for name in ("captions", "karaoke", "duplicate-takes", "silence-cut"):
        item = sub.add_parser(name)
        item.add_argument("--project", required=True)
        item.add_argument("--preset")
        item.add_argument("--dry-run", action="store_true")
    captions = sub.choices["captions"]
    captions.add_argument("--max-words", type=int)
    captions.add_argument("--exclude-phrases")
    captions.add_argument("--karaoke", action="store_true")
    auto = sub.add_parser("auto-edit")
    auto.add_argument("--project", required=True)
    auto.add_argument("--preset", default="shorts-clean")
    pattern = sub.add_parser("pattern1-apply")
    pattern.add_argument("--project", required=True)
    pattern.add_argument("--reference-project", required=True)
    pattern.add_argument("--plan", required=True)
    pattern.add_argument("--dry-run", action="store_true")
    remove_pattern = sub.add_parser("pattern1-remove")
    remove_pattern.add_argument("--project", required=True)
    remove_pattern.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "setup":
        return subprocess.call([sys.executable, str(ROOT / "scripts/bootstrap.py")])
    if args.command == "doctor":
        return subprocess.call([sys.executable, str(ROOT / "scripts/doctor.py")])
    if args.command == "macos-validate":
        return subprocess.call(
            [sys.executable, str(ROOT / "scripts/validate_macos.py")]
        )
    if args.command == "inspect":
        return _internal("--mode", "inspect-project", "--project", args.project)
    if args.command == "captions":
        command = ["--mode", "edit-project", "--project", args.project, "--task", "captions"]
        if args.preset:
            command += ["--caption-style", args.preset]
        if args.max_words:
            command += ["--max-words-per-caption", str(args.max_words)]
        if args.exclude_phrases:
            command += ["--exclude-caption-phrases", args.exclude_phrases]
        if args.dry_run:
            command.append("--dry-run")
        code = _internal(*command)
        if code or not args.karaoke or args.dry_run:
            return code
        return _internal(
            "--mode", "apply-karaoke", "--project", args.project,
            "--preset", "karaoke-yellow",
        )
    if args.command == "karaoke":
        command = [
            "--mode", "apply-karaoke", "--project", args.project,
            "--preset", args.preset or "karaoke-yellow",
        ]
        if args.dry_run:
            command.append("--dry-run")
        return _internal(*command)
    if args.command == "duplicate-takes":
        command = [
            "--mode", "auto-remove-duplicate-takes", "--project", args.project
        ]
        if args.dry_run:
            command.append("--dry-run")
        return _internal(*command)
    if args.command == "silence-cut":
        command = [
            "--mode", "auto-cut-silence", "--project", args.project,
            "--silence-preset", args.preset or "shorts-clean",
        ]
        if args.dry_run:
            command.append("--dry-run")
        return _internal(*command)
    if args.command == "pattern1-apply":
        command = [
            "--mode", "apply-pattern-1", "--project", args.project,
            "--reference-project", args.reference_project, "--plan", args.plan,
        ]
        if args.dry_run:
            command.append("--dry-run")
        return _internal(*command)
    if args.command == "pattern1-remove":
        command = ["--mode", "remove-pattern-1", "--project", args.project]
        if args.dry_run:
            command.append("--dry-run")
        return _internal(*command)
    # Auto-edit deliberately composes proven commands and stops on first failure.
    for command in ("auto-remove-duplicate-takes", "auto-cut-silence"):
        code = _internal(
            "--mode", command, "--project", args.project,
            *(["--silence-preset", args.preset] if command == "auto-cut-silence" else []),
        )
        if code:
            return code
    return _internal(
        "--mode", "apply-karaoke", "--project", args.project,
        "--preset", "karaoke-yellow",
    )


if __name__ == "__main__":
    raise SystemExit(main())

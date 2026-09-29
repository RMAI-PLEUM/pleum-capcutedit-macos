#!/usr/bin/env python3
"""First-run, read-only setup and project-root selection."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from platform_paths import capcut_project_root_candidates, load_machine_config, save_machine_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--install-skill-for", choices=("codex", "claude-project", "claude-personal"))
    parser.add_argument("--project-path", type=Path)
    parser.add_argument("--capcut-project-root", type=Path)
    args = parser.parse_args()
    roots = capcut_project_root_candidates()
    selected = args.capcut_project_root
    if selected:
        selected = selected.expanduser().resolve()
        verified = {item["path"] for item in roots}
        if str(selected) not in verified:
            raise SystemExit(
                "Selected root is not verified by parseable CapCut metadata: " + str(selected)
            )
    elif len(roots) == 1:
        selected = Path(roots[0]["path"])
    elif len(roots) > 1 and not args.non_interactive:
        print("Verified CapCut project roots:")
        for index, item in enumerate(roots, 1):
            print(f"{index}. {item['path']} ({item['parseable_project_count']} projects)")
        selected = Path(roots[int(input("Select root number: ")) - 1]["path"])
    if selected and not (args.check_only or args.dry_run):
        config = load_machine_config()
        config["capcut_project_root"] = str(selected)
        if not args.non_interactive:
            sys.path.insert(0, str(ROOT / "src"))
            from capcut_project_locator import discover_projects
            from capcut_live_project_reader import read_live_project
            from schema_compatibility import compatibility_status
            projects = discover_projects(selected)
            print("Read-only CapCut projects:")
            for index, project in enumerate(projects, 1):
                print(f"{index}. {project.name}")
            if projects:
                answer = input(
                    "Select a safe local reference project number, or Enter to skip: "
                ).strip()
                if answer:
                    reference = projects[int(answer) - 1]
                    status = compatibility_status(read_live_project(reference).primary)
                    config["reference_project_name"] = reference.name
                    config["reference_schema_fingerprint"] = status["schema_fingerprint"]
                    print(json.dumps(status, indent=2))
            orientation = input(
                "Default orientation [auto/landscape/portrait/square] (auto): "
            ).strip().casefold() or "auto"
            if orientation not in {"auto", "landscape", "portrait", "square"}:
                raise SystemExit("Invalid orientation.")
            config["caption_orientation"] = orientation
        save_machine_config(config)
    env_example = ROOT / ".env.example"
    env_file = ROOT / ".env"
    if env_example.is_file() and not env_file.exists() and not (args.check_only or args.dry_run):
        shutil.copyfile(env_example, env_file)
    if args.install_skill_for:
        command = [
            sys.executable, str(ROOT / "scripts/install_skill.py"),
            "--tool", args.install_skill_for,
        ]
        if args.project_path:
            command += ["--project-path", str(args.project_path)]
        if args.dry_run:
            command.append("--dry-run")
        subprocess.check_call(command)
    print(
        "Onboarding never writes CapCut projects. If schema is unknown, create "
        "controlled fixtures. Optionally learn caption and mixed-color karaoke "
        "styles only after read-only inspection, then run synthetic tests."
    )
    return subprocess.call([sys.executable, str(ROOT / "scripts/doctor.py")])


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Migrate small machine configuration and presets; never projects or media."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", type=Path, required=True)
    parser.add_argument("--to", dest="target", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    allowed = ("config", "presets")
    actions = []
    for name in allowed:
        source = args.source / name
        if source.exists():
            actions.append({"source": str(source), "target": str(args.target / name)})
            if not args.dry_run:
                shutil.copytree(source, args.target / name, dirs_exist_ok=True)
    print(json.dumps({"dry_run": args.dry_run, "actions": actions}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

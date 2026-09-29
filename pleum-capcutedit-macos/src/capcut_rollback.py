"""Restore the sandbox caption test from its latest complete backup."""

from __future__ import annotations

import shutil
from pathlib import Path

from capcut_project_cloner import (
    BACKUP_ROOT, SANDBOX, SANDBOX_ROOT, sandbox_path, timestamp,
)


def rollback_caption_test() -> tuple[Path, Path]:
    backups = sorted(path for path in BACKUP_ROOT.iterdir() if path.is_dir())
    if not backups:
        raise FileNotFoundError("No caption injection backup is available.")
    backup = backups[-1]
    archived = SANDBOX_ROOT / f"_rollback_archive_{timestamp()}"
    if SANDBOX.exists():
        shutil.move(str(SANDBOX), str(archived))
    shutil.copytree(backup, SANDBOX, copy_function=shutil.copy2)
    return backup, archived


def rollback_caption_plan(sandbox_name: str) -> tuple[Path, Path]:
    sandbox = sandbox_path(sandbox_name)
    backup_root = SANDBOX.parent.parent / "backups" / sandbox_name
    backups = sorted(path for path in backup_root.iterdir() if path.is_dir())
    if not backups:
        raise FileNotFoundError(f"No backup is available for sandbox {sandbox_name}.")
    backup = backups[-1]
    archived = SANDBOX_ROOT / f"_rollback_archive_{sandbox_name}_{timestamp()}"
    if sandbox.exists():
        shutil.move(str(sandbox), str(archived))
    shutil.copytree(backup, sandbox, copy_function=shutil.copy2)
    return backup, archived

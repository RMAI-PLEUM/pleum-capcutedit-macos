"""Clone fixture projects into a sandbox and create complete backups."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from utils import PROJECT_ROOT


SANDBOX_ROOT = PROJECT_ROOT / "sandbox_capcut_projects"
SANDBOX = SANDBOX_ROOT / "caption_injection_test"
SOURCE = PROJECT_ROOT / "sample_capcut_projects" / "01_video_only"
BACKUP_ROOT = PROJECT_ROOT / "backups" / "caption_injection_test"


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def sandbox_path(name: str) -> Path:
    if not name or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in name):
        raise ValueError("Sandbox name may contain only letters, numbers, underscore, and hyphen.")
    return SANDBOX_ROOT / name


def clone_project(name: str) -> tuple[Path, Path, Path | None]:
    if not SOURCE.is_dir():
        raise FileNotFoundError(f"Source fixture missing: {SOURCE}")
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    sandbox = sandbox_path(name)
    archived: Path | None = None
    if sandbox.exists():
        archived = SANDBOX_ROOT / f"_archived_{name}_{timestamp()}"
        shutil.move(str(sandbox), str(archived))
    shutil.copytree(SOURCE, sandbox, copy_function=shutil.copy2)
    backup_root = PROJECT_ROOT / "backups" / name
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / timestamp()
    shutil.copytree(sandbox, backup, copy_function=shutil.copy2)
    return sandbox, backup, archived


def clone_for_injection() -> tuple[Path, Path, Path | None]:
    return clone_project("caption_injection_test")

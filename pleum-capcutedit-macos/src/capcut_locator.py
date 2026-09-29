"""Locate CapCut Desktop draft payloads without modifying them."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from platform_paths import capcut_project_root_candidates


@dataclass(frozen=True)
class DraftCandidate:
    draft_content: Path
    modified_time: float


def default_project_roots() -> list[Path]:
    """Return metadata-verified roots, with legacy Windows fallbacks."""
    local = os.getenv("LOCALAPPDATA")
    roaming = os.getenv("APPDATA")
    home = Path.home()
    candidates: list[Path] = [
        Path(item["path"]) for item in capcut_project_root_candidates()
    ]
    if local:
        candidates.extend([
            Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            Path(local) / "CapCut" / "User Data" / "Projects",
            Path(local) / "ByteDance" / "CapCut" / "User Data" / "Projects"
            / "com.lveditor.draft",
        ])
    if roaming:
        candidates.extend([
            Path(roaming) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            Path(roaming) / "CapCut" / "User Data" / "Projects",
        ])
    candidates.append(
        home / "AppData" / "Local" / "CapCut" / "User Data"
        / "Projects" / "com.lveditor.draft"
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _draft_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        if root.name.casefold() in {"draft_content.json", "draft_info.json"}:
            yield root
        return
    if not root.is_dir():
        return
    try:
        modern = list(root.rglob("draft_info.json"))
        if modern:
            yield from modern
        else:
            yield from (
                path for path in root.rglob("draft_content.json")
                if "subdraft" not in {part.casefold() for part in path.parts}
            )
    except (OSError, PermissionError):
        return


def find_latest_draft(project_root: Path | None = None) -> DraftCandidate:
    """Find the most recently modified active CapCut draft payload."""
    roots = [project_root.expanduser().resolve()] if project_root else default_project_roots()
    discovered: dict[str, DraftCandidate] = {}
    for root in roots:
        for draft in _draft_files(root):
            try:
                resolved = draft.resolve()
                modified = resolved.stat().st_mtime
            except (OSError, PermissionError):
                continue
            key = os.path.normcase(str(resolved))
            discovered[key] = DraftCandidate(resolved, modified)
    if not discovered:
        searched = "\n".join(f"- {path}" for path in roots)
        raise FileNotFoundError(
            "No readable draft_info.json or draft_content.json was found. Searched:\n"
            f"{searched}\nUse --project-root to specify a CapCut project folder or draft file."
        )
    return max(discovered.values(), key=lambda item: item.modified_time)

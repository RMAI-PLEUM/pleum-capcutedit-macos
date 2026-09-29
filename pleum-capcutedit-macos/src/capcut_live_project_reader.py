"""Read all mirrored draft_content.json copies for a selected live project."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from capcut_project_locator import CapCutProject


@dataclass
class LiveProject:
    project: CapCutProject
    metadata: dict[str, Any]
    draft_paths: list[Path]
    drafts: list[dict[str, Any]]
    storage_format: str = "legacy_draft_content"

    @property
    def primary(self) -> dict[str, Any]:
        return self.drafts[0]


def _active_timeline_id(project_path: Path) -> str | None:
    index = project_path / "Timelines/project.json"
    if not index.is_file():
        return None
    try:
        value = json.loads(index.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    identifier = str(value.get("main_timeline_id") or "").strip()
    return identifier or None


def _modern_draft_paths(project_path: Path) -> list[Path]:
    """Resolve CapCut 9+ draft_info mirrors without touching backups/subdrafts."""
    root_copy = project_path / "draft_info.json"
    timeline_id = _active_timeline_id(project_path)
    timeline_copy = (
        project_path / "Timelines" / timeline_id / "draft_info.json"
        if timeline_id else None
    )
    paths = [path for path in (root_copy, timeline_copy) if path and path.is_file()]
    if root_copy.is_file() and timeline_id and not timeline_copy.is_file():
        raise RuntimeError(
            f"Active timeline {timeline_id} has no draft_info.json mirror."
        )
    return paths


def _legacy_draft_paths(project_path: Path) -> list[Path]:
    """Resolve legacy draft_content copies while excluding CapCut subdrafts."""
    paths = []
    for path in sorted(project_path.rglob("draft_content.json")):
        relative = path.relative_to(project_path)
        if any(part.casefold() == "subdraft" for part in relative.parts):
            continue
        paths.append(path)
    return paths


def active_draft_paths(project_path: Path) -> tuple[list[Path], str]:
    paths = _modern_draft_paths(project_path)
    if paths:
        return paths, "macos_draft_info"
    return _legacy_draft_paths(project_path), "legacy_draft_content"


def read_live_project(project: CapCutProject) -> LiveProject:
    metadata = json.loads(project.metadata_path.read_text(encoding="utf-8-sig"))
    paths, storage_format = active_draft_paths(project.path)
    if not paths:
        raise FileNotFoundError(
            f"No active draft_info.json or draft_content.json found in {project.path}"
        )
    drafts = [
        json.loads(path.read_text(encoding="utf-8-sig"))
        for path in paths
    ]
    if len(paths) > 2:
        raise RuntimeError(
            f"Unsupported active-draft structure: expected 1 or 2 copies, found {len(paths)}."
        )
    if any(draft != drafts[0] for draft in drafts[1:]):
        raise RuntimeError("Mirrored draft_content.json copies are not identical.")
    return LiveProject(
        project, metadata, [path.resolve() for path in paths], drafts,
        storage_format,
    )

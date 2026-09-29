"""Exact metadata-backed discovery of local CapCut projects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from platform_paths import selected_project_root


@dataclass(frozen=True)
class CapCutProject:
    name: str
    path: Path
    identity: str
    modified_time: float
    metadata_path: Path


def project_root() -> Path:
    """Return the metadata-verified project root selected for this machine."""
    return selected_project_root()


def discover_projects(root: Path | None = None) -> list[CapCutProject]:
    base = (root or project_root()).resolve()
    if not base.is_dir():
        raise FileNotFoundError(f"CapCut project root not found: {base}")
    projects: list[CapCutProject] = []
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        metadata_path = folder / "draft_meta_info.json"
        if not metadata_path.is_file():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        name = str(metadata.get("draft_name") or "").strip()
        identity = str(metadata.get("draft_id") or "").strip()
        if not name or not identity:
            continue
        # Folder names are never accepted as identity evidence.
        projects.append(CapCutProject(
            name=name,
            path=folder.resolve(),
            identity=identity,
            modified_time=max(folder.stat().st_mtime, metadata_path.stat().st_mtime),
            metadata_path=metadata_path.resolve(),
        ))
    return sorted(projects, key=lambda project: project.name.casefold())


def locate_project(name: str, root: Path | None = None) -> CapCutProject:
    requested = name.strip()
    if not requested or requested.casefold() == "latest":
        raise ValueError("--project must be an exact user-visible CapCut project name.")
    projects = discover_projects(root)
    matches = [project for project in projects if project.name.casefold() == requested.casefold()]
    if not matches:
        available = "\n".join(f"- {project.name}" for project in projects) or "(none)"
        raise FileNotFoundError(
            f'No CapCut project metadata matches "{requested}". Available projects:\n{available}'
        )
    if len(matches) != 1:
        details = "\n".join(
            f"- {project.path} | modified={project.modified_time:.6f}"
            for project in matches
        )
        raise RuntimeError(
            f'Ambiguous CapCut project name "{requested}". Matches:\n{details}'
        )
    return matches[0]

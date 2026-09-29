"""Read-only discovery and metadata inspection for named CapCut projects."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capcut_locator import default_project_roots
from capcut_live_project_reader import active_draft_paths


EXPECTED_PROJECTS = (
    "Schema 01 - Video Only",
    "Schema 02 - One Caption",
    "Schema 03 - Styled Caption",
    "Schema 04 - Multiple Captions",
    "Schema 05 - One Cut",
)


@dataclass(frozen=True)
class ProjectDiscovery:
    display_name: str
    project_path: Path
    modified_time: str
    duration_seconds: float | None
    draft_content_path: Path
    draft_meta_info_path: Path | None
    total_size: int
    file_count: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key, value in result.items():
            if isinstance(value, Path):
                result[key] = str(value)
        return result


def _read_json(path: Path) -> dict[str, Any] | None:
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            value = json.loads(path.read_text(encoding=encoding))
            return value if isinstance(value, dict) else None
        except (UnicodeError, json.JSONDecodeError, OSError):
            continue
    return None


def _duration(path: Path) -> float | None:
    data = _read_json(path)
    value = data.get("duration") if data else None
    try:
        number = float(value)
        return round(number / 1_000_000, 6) if number > 10000 else round(number, 6)
    except (TypeError, ValueError):
        return None


def _project_candidates(roots: list[Path]) -> dict[str, list[Path]]:
    found = {name: [] for name in EXPECTED_PROJECTS}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except (OSError, PermissionError):
            continue
        for child in children:
            if child.is_dir() and child.name in found:
                found[child.name].append(child.resolve())
    return found


def scan_expected_projects(project_root: Path | None = None) -> list[ProjectDiscovery]:
    roots = [project_root.resolve()] if project_root else default_project_roots()
    candidates = _project_candidates(roots)
    ambiguous = {name: paths for name, paths in candidates.items() if len(paths) != 1}
    if ambiguous:
        details = []
        for name, paths in ambiguous.items():
            shown = ", ".join(str(path) for path in paths) if paths else "(none)"
            details.append(f"{name}: {shown}")
        raise RuntimeError(
            "Could not identify every fixture project uniquely; no files were copied.\n"
            + "\n".join(details)
        )

    projects: list[ProjectDiscovery] = []
    for name in EXPECTED_PROJECTS:
        folder = candidates[name][0]
        files = [path for path in folder.rglob("*") if path.is_file()]
        drafts, _storage_format = active_draft_paths(folder)
        if not drafts:
            raise RuntimeError(f"{name} has no active draft payload; no files were copied.")
        # Prefer the newest readable timeline draft, then the project-root draft.
        readable = [(path, _duration(path)) for path in drafts]
        readable = [(path, duration) for path, duration in readable if duration is not None]
        if not readable:
            raise RuntimeError(f"{name} has no readable active draft; no files were copied.")
        draft, duration = max(readable, key=lambda item: item[0].stat().st_mtime)
        meta = next(
            (path for path in files if path.name.casefold() == "draft_meta_info.json"),
            None,
        )
        projects.append(ProjectDiscovery(
            display_name=name,
            project_path=folder,
            modified_time=datetime.fromtimestamp(
                folder.stat().st_mtime, timezone.utc
            ).astimezone().isoformat(),
            duration_seconds=duration,
            draft_content_path=draft,
            draft_meta_info_path=meta,
            total_size=sum(path.stat().st_size for path in files),
            file_count=len(files),
        ))
    return projects

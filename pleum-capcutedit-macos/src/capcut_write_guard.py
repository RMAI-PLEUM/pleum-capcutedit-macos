"""Central safety gate for writes to live CapCut project roots."""

from __future__ import annotations

from pathlib import Path

from capcut_live_project_reader import LiveProject
from capcut_process_guard import require_capcut_closed
from platform_paths import capcut_project_root_candidates
from schema_compatibility import require_compatible_schema


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def is_live_capcut_project(live: LiveProject) -> bool:
    return any(
        _inside(live.project.path, Path(item["path"]))
        for item in capcut_project_root_candidates()
    )


def require_live_project_write_ready(
    live: LiveProject, feature: str | None = None
) -> None:
    """Block unsafe live writes; copied fixtures remain available for validation."""
    require_capcut_closed()
    if any(draft != live.drafts[0] for draft in live.drafts[1:]):
        raise RuntimeError("Active CapCut draft mirrors are not identical.")
    if not is_live_capcut_project(live):
        # Unit tests and copied controlled fixtures are isolated from CapCut.
        return
    if len(live.draft_paths) != 2:
        raise RuntimeError(
            "Direct write requires exactly two verified active draft mirrors; "
            f"found {len(live.draft_paths)} ({live.storage_format})."
        )
    require_compatible_schema(live.primary, feature)
    unwritable = [str(path) for path in live.draft_paths if not os.access(path, os.W_OK)]
    if unwritable:
        raise PermissionError(
            "CapCut draft mirrors are not writable: " + ", ".join(unwritable)
        )

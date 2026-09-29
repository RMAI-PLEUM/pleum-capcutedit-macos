"""Prevent direct reads/writes while CapCut Desktop may be mutating drafts."""

from __future__ import annotations

from platform_process import capcut_process_ids


MESSAGE = "Close CapCut completely before editing the project."

def require_capcut_closed() -> None:
    process_ids = capcut_process_ids()
    if process_ids:
        raise RuntimeError(f"{MESSAGE} Running process IDs: {process_ids}")

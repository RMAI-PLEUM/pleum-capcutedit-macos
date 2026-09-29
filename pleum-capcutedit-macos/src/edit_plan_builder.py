"""Combine validated, non-destructive planning artifacts."""

from __future__ import annotations

from typing import Any


def build_edit_plan(
    timeline: dict[str, Any],
    caption_plan: dict[str, Any],
    cut_plan: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "project": {
            "name": timeline.get("project_name"),
            "path": timeline.get("project_path"),
            "duration": caption_plan.get("project_duration"),
            "draft_content_path": timeline.get("draft_content_path"),
            "read_only": True,
        },
        "captions": caption_plan.get("captions", []),
        "cuts": cut_plan.get("cuts", []),
        "overlays": [],
        "audio": [],
        "warnings": warnings or [],
    }

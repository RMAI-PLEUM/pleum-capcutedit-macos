"""Helpers for classifying registered caption segments after ripple cuts."""

from __future__ import annotations

from typing import Any


def active_registered_ids(draft: dict[str, Any], track_id: str | None) -> list[str]:
    for track in draft.get("tracks", []):
        if track.get("id") == track_id:
            return [segment["id"] for segment in track.get("segments", [])]
    return []

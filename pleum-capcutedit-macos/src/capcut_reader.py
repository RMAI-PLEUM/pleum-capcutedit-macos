"""Read and normalize CapCut Desktop timeline data without modifying projects."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from capcut_locator import DraftCandidate
from utils import PROJECT_ROOT, write_json


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _time_range(value: Any) -> dict[str, int | float] | None:
    if not isinstance(value, dict):
        return None
    start = _number(value.get("start"))
    duration = _number(value.get("duration"))
    if start is None and duration is None:
        return None
    start = start or 0
    duration = duration or 0
    return {"start": start, "duration": duration, "end": start + duration}


def _seconds(value: int | float | None) -> float | None:
    # CapCut draft timeline units are microseconds.
    return round(float(value) / 1_000_000, 6) if value is not None else None


def _seconds_range(value: dict[str, int | float] | None) -> dict[str, float] | None:
    if value is None:
        return None
    return {key: _seconds(number) for key, number in value.items()}


def _material_collections(materials: Any) -> Iterable[tuple[str, dict[str, Any]]]:
    if not isinstance(materials, dict):
        return
    for collection, items in materials.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                yield str(collection), item


def _media_path(material: dict[str, Any]) -> str | None:
    for key in ("path", "file_path", "local_path", "source_path"):
        value = material.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _material_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for collection, material in _material_collections(data.get("materials")):
        material_id = material.get("id") or material.get("material_id")
        if material_id is not None:
            index[str(material_id)] = {
                "collection": collection,
                "path": _media_path(material),
                "name": material.get("name") or material.get("material_name"),
                "duration": _number(material.get("duration")),
                "raw": material,
            }
    return index


def _explicit_false(value: Any) -> bool:
    return value is False or (isinstance(value, str) and value.casefold() == "false")


def _explicit_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.casefold() == "true")


def backup_draft(candidate: DraftCandidate) -> Path:
    destination = PROJECT_ROOT / "backups" / "read_only"
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    project_name = _project_directory(candidate.draft_content).name or "capcut_project"
    safe_name = "".join(c if c.isalnum() or c in " ._-" else "_" for c in project_name)
    backup = destination / f"{safe_name}.{stamp}.draft_content.json"
    shutil.copy2(candidate.draft_content, backup)
    return backup


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CapCut draft is not valid JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected a JSON object in CapCut draft: {path}")
    return data


def _project_directory(draft_path: Path) -> Path:
    """Resolve ProjectName from newer ProjectName/Timelines/<id>/draft layouts."""
    for parent in draft_path.parents:
        if parent.name.casefold() == "timelines" and parent.parent != parent:
            return parent.parent
    return draft_path.parent


def parse_timeline(
    data: dict[str, Any], project_path: Path, draft_path: Path, backup_path: Path
) -> dict[str, Any]:
    materials = _material_index(data)
    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        tracks = data.get("timeline", {}).get("tracks", []) if isinstance(data.get("timeline"), dict) else []

    normalized_tracks: list[dict[str, Any]] = []
    media_paths: list[str] = []
    for track_index, track in enumerate(tracks if isinstance(tracks, list) else []):
        if not isinstance(track, dict):
            continue
        normalized_segments: list[dict[str, Any]] = []
        for segment_index, segment in enumerate(track.get("segments", []) or []):
            if not isinstance(segment, dict):
                continue
            material_id = segment.get("material_id")
            material = materials.get(str(material_id), {}) if material_id is not None else {}
            source = _time_range(segment.get("source_timerange") or segment.get("source_time_range"))
            target = _time_range(segment.get("target_timerange") or segment.get("target_time_range"))
            path = material.get("path")
            if path and path not in media_paths:
                media_paths.append(path)
            duration_units = target.get("duration") if target else None
            speed = _number(segment.get("speed")) or 1.0
            volume = _number(segment.get("volume"))
            disabled = _explicit_false(segment.get("visible")) or _explicit_false(
                segment.get("enable")
            )
            muted = _explicit_true(segment.get("muted")) or (
                volume is not None and volume <= 0
            )
            normalized_segments.append({
                "segment_index": segment_index,
                "segment_id": segment.get("id"),
                "material_id": material_id,
                "material_collection": material.get("collection"),
                "media_name": material.get("name"),
                "media_path": path,
                "source_time_range": {
                    "capcut_units": source,
                    "seconds": _seconds_range(source),
                },
                "target_timeline_range": {
                    "capcut_units": target,
                    "seconds": _seconds_range(target),
                },
                "clip_duration_on_timeline_seconds": _seconds(duration_units),
                "playback_speed": speed,
                "speed": speed,
                "volume": volume,
                "muted": muted,
                "disabled": disabled,
            })
        normalized_tracks.append({
            "track_index": track_index,
            "track_id": track.get("id"),
            "track_type": track.get("type"),
            "track_flag": track.get("flag"),
            "track_attribute": track.get("attribute"),
            "segment_count": len(normalized_segments),
            "segments": normalized_segments,
        })

    project_name = (
        data.get("draft_name")
        or data.get("name")
        or data.get("project_name")
        or project_path.name
    )
    return {
        "read_only": True,
        "project_name": project_name,
        "project_path": str(project_path),
        "draft_content_path": str(draft_path),
        "backup_path": str(backup_path),
        "duration_seconds": _seconds(_number(data.get("duration"))),
        "media_file_paths": media_paths,
        "track_count": len(normalized_tracks),
        "tracks": normalized_tracks,
    }


def read_project(candidate: DraftCandidate) -> tuple[dict[str, Any], Path]:
    """Back up, read from the backup, normalize, and save the timeline summary."""
    backup = backup_draft(candidate)
    data = _load_json(backup)
    project_path = _project_directory(candidate.draft_content)
    timeline = parse_timeline(
        data=data,
        project_path=project_path,
        draft_path=candidate.draft_content,
        backup_path=backup,
    )
    output = PROJECT_ROOT / "output" / "json" / "capcut_timeline.json"
    write_json(output, timeline)
    return timeline, output

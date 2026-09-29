"""Map media-source time to CapCut timeline time with trim/speed clamping."""

from __future__ import annotations

from typing import Any, Iterable

from utils import PROJECT_ROOT, write_json


def clip_range(clip: dict[str, Any], field: str) -> dict[str, float] | None:
    value = clip.get(field)
    if isinstance(value, dict):
        seconds = value.get("seconds")
        if isinstance(seconds, dict):
            try:
                start = float(seconds["start"])
                duration = float(seconds["duration"])
                return {"start": start, "duration": duration, "end": start + duration}
            except (KeyError, TypeError, ValueError):
                return None
    return None


def iter_timeline_clips(timeline: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for track in timeline.get("tracks", []):
        for segment in track.get("segments", []):
            target = clip_range(segment, "target_timeline_range")
            source = clip_range(segment, "source_time_range")
            if not target or not source or not segment.get("media_path"):
                continue
            yield {
                **segment,
                "track_index": track.get("track_index"),
                "track_id": track.get("track_id"),
                "track_type": track.get("track_type"),
                "source_range": source,
                "timeline_range": target,
            }


def map_source_time(
    source_time: float, clip: dict[str, Any], account_for_speed: bool = True
) -> float:
    source = clip["source_range"]
    target = clip["timeline_range"]
    speed = float(clip.get("playback_speed") or clip.get("speed") or 1.0)
    if speed <= 0:
        speed = 1.0
    mapped = target["start"] + (float(source_time) - source["start"]) / (
        speed if account_for_speed else 1.0
    )
    return min(target["end"], max(target["start"], mapped))


def clip_for_timeline_time(
    timeline_time: float, clips: list[dict[str, Any]], tolerance: float = 0.001
) -> dict[str, Any] | None:
    candidates = [
        clip for clip in clips
        if clip["timeline_range"]["start"] - tolerance
        <= timeline_time
        <= clip["timeline_range"]["end"] + tolerance
        and not clip.get("disabled")
        and not clip.get("muted")
    ]
    if not candidates:
        return None
    # Prefer explicit audio, then the lowest track index for deterministic mapping.
    return sorted(
        candidates,
        key=lambda clip: (clip.get("track_type") != "audio", clip.get("track_index", 0)),
    )[0]


def build_mapping_log(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for clip in iter_timeline_clips(timeline):
        records.append({
            "track_index": clip["track_index"],
            "track_id": clip["track_id"],
            "clip_id": clip.get("segment_id"),
            "media_path": clip.get("media_path"),
            "source_range": clip["source_range"],
            "timeline_range": clip["timeline_range"],
            "playback_speed": clip.get("playback_speed", 1.0),
            "muted": bool(clip.get("muted")),
            "disabled": bool(clip.get("disabled")),
        })
    write_json(PROJECT_ROOT / "logs" / "timeline_mapping.json", records)
    return records

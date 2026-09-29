"""Pure CapCut timeline ripple-cut transformation in microsecond units."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any, Callable


TIME_SCALE = 1_000_000
PRIMARY_TYPES = {"video", "audio"}
KNOWN_AUXILIARY_TYPES = {
    "text", "effect", "sticker", "overlay", "adjustment",
}


def _timerange(segment: dict[str, Any], key: str) -> tuple[int, int]:
    value = segment.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"segment {segment.get('id')} missing {key}")
    start, duration = value.get("start"), value.get("duration")
    if not isinstance(start, int) or not isinstance(duration, int) or duration <= 0:
        raise RuntimeError(f"segment {segment.get('id')} has invalid {key}")
    return start, duration


def _check_render_semantics(segment: dict[str, Any]) -> None:
    render = segment.get("render_timerange")
    if render is None:
        return
    if not isinstance(render, dict) or render.get("start") != 0 or render.get("duration") != 0:
        raise RuntimeError(
            f"segment {segment.get('id')} has unsupported render_timerange: {render}"
        )


def _set_target(segment: dict[str, Any], start: int, duration: int) -> None:
    segment["target_timerange"] = {"start": start, "duration": duration}


def _set_source(
    segment: dict[str, Any], start: int, duration: int
) -> None:
    segment["source_timerange"] = {"start": start, "duration": duration}


def transform_segment(
    segment: dict[str, Any],
    cut_start: int,
    cut_end: int,
    track_type: str,
    new_id: Callable[[], str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target_start, target_duration = _timerange(segment, "target_timerange")
    target_end = target_start + target_duration
    cut_duration = cut_end - cut_start
    if target_end <= cut_start:
        return [deepcopy(segment)], {"action": "unchanged_before"}
    if target_start >= cut_end:
        shifted = deepcopy(segment)
        _set_target(shifted, target_start - cut_duration, target_duration)
        return [shifted], {"action": "shifted_after"}
    _check_render_semantics(segment)
    if track_type not in PRIMARY_TYPES | KNOWN_AUXILIARY_TYPES:
        raise RuntimeError(
            f"unsupported track type {track_type!r} crosses approved cut "
            f"at segment {segment.get('id')}"
        )
    if track_type in PRIMARY_TYPES:
        if segment.get("reverse"):
            raise RuntimeError(f"reverse segment unsupported: {segment.get('id')}")
        source_start, source_duration = _timerange(segment, "source_timerange")
        ratio = source_duration / target_duration
        declared_speed = segment.get("speed", ratio)
        if (
            not isinstance(declared_speed, (int, float))
            or abs(float(declared_speed) - ratio) > 0.01
            or abs(ratio - 1.0) > 0.002
        ):
            raise RuntimeError(
                f"segment {segment.get('id')} has unsupported speed ratio {ratio:.9f}"
            )
    else:
        source_start = source_duration = 0
        ratio = 1.0

    if target_start >= cut_start and target_end <= cut_end:
        return [], {"action": "removed_inside"}
    if target_start < cut_start and target_end <= cut_end:
        left = deepcopy(segment)
        new_duration = cut_start - target_start
        _set_target(left, target_start, new_duration)
        if track_type in PRIMARY_TYPES:
            _set_source(left, source_start, round(new_duration * ratio))
        return [left], {"action": "trimmed_end"}
    if target_start >= cut_start and target_end > cut_end:
        right = deepcopy(segment)
        remaining = target_end - cut_end
        _set_target(right, cut_start, remaining)
        if track_type in PRIMARY_TYPES:
            advance = round((cut_end - target_start) * ratio)
            _set_source(right, source_start + advance, round(remaining * ratio))
        return [right], {"action": "trimmed_start"}

    # Segment spans the complete removed interval.
    left = deepcopy(segment)
    right = deepcopy(segment)
    left_duration = cut_start - target_start
    right_duration = target_end - cut_end
    fresh_id = new_id()
    right["id"] = fresh_id
    _set_target(left, target_start, left_duration)
    _set_target(right, cut_start, right_duration)
    if track_type in PRIMARY_TYPES:
        _set_source(left, source_start, round(left_duration * ratio))
        right_source_start = source_start + round((cut_end - target_start) * ratio)
        _set_source(right, right_source_start, round(right_duration * ratio))
    return [left, right], {
        "action": "split_across_cut",
        "generated_segment_id": fresh_id,
    }


def apply_ripple_cut(
    draft: dict[str, Any],
    cut_start: int,
    cut_end: int,
    id_factory: Callable[[], str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if cut_start < 0 or cut_end <= cut_start:
        raise ValueError("Invalid ripple cut range.")
    old_duration = draft.get("duration")
    if not isinstance(old_duration, int) or cut_end > old_duration:
        raise ValueError("Ripple cut is outside project duration.")
    factory = id_factory or (lambda: str(uuid.uuid4()).upper())
    modified = deepcopy(draft)
    changes: list[dict[str, Any]] = []
    generated_ids: list[str] = []
    for track_index, track in enumerate(modified.get("tracks", [])):
        track_type = str(track.get("type") or "unknown")
        output_segments: list[dict[str, Any]] = []
        for segment_index, segment in enumerate(track.get("segments", [])):
            transformed, detail = transform_segment(
                segment, cut_start, cut_end, track_type, factory
            )
            output_segments.extend(transformed)
            if detail["action"] != "unchanged_before":
                record = {
                    "track_index": track_index,
                    "track_type": track_type,
                    "segment_index": segment_index,
                    "segment_id": segment.get("id"),
                    **detail,
                }
                changes.append(record)
                if detail.get("generated_segment_id"):
                    generated_ids.append(detail["generated_segment_id"])
        track["segments"] = output_segments
    modified["duration"] = old_duration - (cut_end - cut_start)
    return modified, {
        "cut_start": cut_start,
        "cut_end": cut_end,
        "cut_duration": cut_end - cut_start,
        "old_duration": old_duration,
        "new_duration": modified["duration"],
        "segment_changes": changes,
        "generated_segment_ids": generated_ids,
    }


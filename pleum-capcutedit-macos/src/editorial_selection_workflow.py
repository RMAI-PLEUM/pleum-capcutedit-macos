"""Transaction-safe application of an approved semantic story-beat selection."""

from __future__ import annotations

from typing import Any

from ai_caption_registry import stable_hash
from auto_duplicate_cleanup import apply_auto_cleanup_transaction
from capcut_live_project_reader import LiveProject
from capcut_process_guard import require_capcut_closed
from capcut_timeline_media_resolver import analyze_timeline


def timeline_hash(draft: dict[str, Any]) -> str:
    analysis = analyze_timeline(draft)
    return stable_hash({
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    })


def _normalized_keep_ranges(
    ranges: list[dict[str, Any]], duration: float
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    previous_end = 0.0
    for index, item in enumerate(sorted(ranges, key=lambda value: float(value["start"])), 1):
        start, end = float(item["start"]), float(item["end"])
        if start < 0 or end <= start or end > duration + 0.000002:
            raise RuntimeError(f"Invalid editorial keep range {index}: {start} -> {end}")
        if start < previous_end - 0.000002:
            raise RuntimeError("Editorial keep ranges overlap.")
        output.append({
            **item,
            "start": round(start, 6),
            "end": round(end, 6),
            "duration": round(end - start, 6),
        })
        previous_end = end
    if not output:
        raise RuntimeError("Editorial selection must keep at least one range.")
    return output


def build_editorial_selection_plan(
    project_name: str,
    draft: dict[str, Any],
    keep_ranges: list[dict[str, Any]],
    *,
    profile_id: str,
) -> dict[str, Any]:
    duration = float(draft["duration"]) / 1_000_000
    kept = _normalized_keep_ranges(keep_ranges, duration)
    cuts: list[dict[str, Any]] = []
    cursor = 0.0
    for item in kept:
        if item["start"] > cursor + 0.000002:
            cuts.append({
                "start": round(cursor, 6),
                "end": item["start"],
                "group_ids": ["editorial_story_selection"],
                "utterance_ids": [],
                "source_segment_ids": [],
            })
        cursor = item["end"]
    if cursor < duration - 0.000002:
        cuts.append({
            "start": round(cursor, 6),
            "end": round(duration, 6),
            "group_ids": ["editorial_story_selection"],
            "utterance_ids": [],
            "source_segment_ids": [],
        })
    kept_duration = sum(item["duration"] for item in kept)
    removed_duration = sum(item["end"] - item["start"] for item in cuts)
    if abs(duration - kept_duration - removed_duration) > 0.003:
        raise RuntimeError("Editorial keep/cut ranges do not cover the timeline exactly.")
    return {
        "version": 1,
        "mode": "reference_guided_semantic_story_selection",
        "project": project_name,
        "timeline_hash": timeline_hash(draft),
        "profile_id": profile_id,
        "old_duration": round(duration, 6),
        "expected_new_duration": round(kept_duration, 6),
        "keep_ranges": kept,
        "cut_ranges": cuts,
        "reason_codes": [
            "USER_REQUESTED_MANUAL_STYLE",
            "SEMANTIC_BEAT_BEST_TAKE_SELECTION",
            "DEDUPLICATE_BEFORE_SILENCE_CLEANUP",
        ],
    }


def apply_editorial_selection_plan(
    live: LiveProject,
    plan: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    if plan.get("version") != 1:
        raise RuntimeError("Unsupported editorial selection plan version.")
    if str(plan.get("project", "")).casefold() != live.project.name.casefold():
        raise RuntimeError("Editorial plan project does not match selected project.")
    current_hash = timeline_hash(live.primary)
    if plan.get("timeline_hash") != current_hash:
        raise RuntimeError("Timeline changed after editorial selection planning.")
    duration = float(live.primary["duration"]) / 1_000_000
    _normalized_keep_ranges(list(plan.get("keep_ranges") or []), duration)
    internal = apply_auto_cleanup_transaction(
        live, plan, current_hash, dry_run=True
    )
    if dry_run:
        return internal
    require_capcut_closed()
    result = apply_auto_cleanup_transaction(
        live, plan, current_hash, dry_run=False
    )
    expected = float(plan["expected_new_duration"])
    actual = float(result["validation"]["new_duration"])
    if abs(expected - actual) > 0.003:
        raise RuntimeError("Editorial selection duration differs from approved plan.")
    return result


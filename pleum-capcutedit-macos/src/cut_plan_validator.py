"""Strict validation for manual-review cut_plan.json."""

from __future__ import annotations

from typing import Any

from timeline_mapper import iter_timeline_clips


def validate_cut_plan(
    plan: dict[str, Any],
    timeline: dict[str, Any],
    minimum_duration: float = 0.40,
    review_below_confidence: float = 0.85,
) -> dict[str, Any]:
    errors: list[str] = []
    duration = float(plan.get("project_duration") or 0)
    clips = {
        str(clip.get("segment_id")): clip for clip in iter_timeline_clips(timeline)
        if clip.get("segment_id") and not clip.get("disabled") and not clip.get("muted")
    }
    previous_end = 0.0
    for index, cut in enumerate(plan.get("cuts", []), 1):
        prefix = f"cut {index}"
        start = float(cut.get("timeline_start", -1))
        end = float(cut.get("timeline_end", -1))
        if start < 0:
            errors.append(f"{prefix}: start is negative")
        if end <= start:
            errors.append(f"{prefix}: end is not after start")
        if end > duration + 0.0005:
            errors.append(f"{prefix}: ends after project duration")
        if start < previous_end - 0.0005:
            errors.append(f"{prefix}: overlaps previous cut")
        if end - start < minimum_duration - 0.0005:
            errors.append(f"{prefix}: duration is below minimum")
        clip = clips.get(str(cut.get("source_clip_id")))
        if clip is None:
            errors.append(f"{prefix}: editable source clip does not exist")
        else:
            target = clip["timeline_range"]
            if start < target["start"] - 0.0005 or end > target["end"] + 0.0005:
                errors.append(f"{prefix}: cut is outside editable clip")
            if end - start > target["duration"] + 0.0005:
                errors.append(f"{prefix}: cut duration is unreasonable for its clip")
        if (
            float(cut.get("confidence", 0)) < review_below_confidence
            and not cut.get("requires_review")
        ):
            errors.append(f"{prefix}: uncertain cut must require review")
        previous_end = end
    return {"valid": not errors, "cut_count": len(plan.get("cuts", [])), "errors": errors}

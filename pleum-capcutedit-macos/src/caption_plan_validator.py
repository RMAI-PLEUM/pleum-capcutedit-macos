"""Strict validation for caption_plan.json."""

from __future__ import annotations

from typing import Any

from timeline_mapper import iter_timeline_clips
from utils import token_count


def validate_caption_plan(
    plan: dict[str, Any],
    timeline: dict[str, Any] | None = None,
    max_words: int = 16,
    lexical_words: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    media_plan = isinstance(plan.get("source"), dict)
    duration = float(
        (plan.get("source") or {}).get("duration")
        if media_plan else plan.get("project_duration") or 0
    )
    clips = {
        str(clip.get("segment_id")): clip for clip in iter_timeline_clips(timeline)
        if clip.get("segment_id")
    } if timeline is not None else {}
    captions = plan.get("captions")
    if plan.get("version") != 1:
        errors.append("plan version must be 1")
    if not isinstance(captions, list) or not captions:
        errors.append("captions must be a nonempty list")
        captions = []
    ids: list[str] = []
    lexical_counts: list[int] | None = None
    if lexical_words is not None:
        import re
        boundaries: list[int] = []
        total = 0
        for word in lexical_words:
            total += len(re.sub(r"\s+", "", str(word.get("text") or "")))
            boundaries.append(total)
        lexical_counts = []
        cursor = 0
        for caption in captions:
            end_cursor = cursor + len(
                re.sub(r"\s+", "", str(caption.get("text") or ""))
            )
            lexical_counts.append(sum(cursor < boundary <= end_cursor for boundary in boundaries))
            cursor = end_cursor
    previous_end = 0.0
    for index, caption in enumerate(captions, 1):
        prefix = f"caption {index}"
        try:
            start, end = float(caption.get("start", -1)), float(caption.get("end", -1))
        except (TypeError, ValueError):
            errors.append(f"{prefix}: timing is invalid")
            continue
        text = str(caption.get("text", ""))
        caption_id = caption.get("id")
        if not isinstance(caption_id, str) or not caption_id:
            errors.append(f"{prefix}: id is missing")
        else:
            ids.append(caption_id)
        if start < 0:
            errors.append(f"{prefix}: start is negative")
        if end <= start:
            errors.append(f"{prefix}: end is not after start")
        if end > duration + 0.0005:
            errors.append(f"{prefix}: ends after project duration")
        if start < previous_end - 0.0005:
            errors.append(f"{prefix}: overlaps previous caption")
        if not text.strip():
            errors.append(f"{prefix}: text is empty")
        if "\n" in text or "\r" in text:
            errors.append(f"{prefix}: text is not one line")
        word_count = (
            lexical_counts[index - 1]
            if lexical_counts is not None else token_count(text)
        )
        if word_count > max_words:
            errors.append(f"{prefix}: exceeds {max_words} words")
        clip = clips.get(str(caption.get("source_clip_id")))
        if timeline is not None and clip is None:
            errors.append(f"{prefix}: source clip does not exist")
        elif clip is not None:
            target = clip["timeline_range"]
            if start < target["start"] - 0.0005 or end > target["end"] + 0.0005:
                errors.append(f"{prefix}: timing is outside source clip timeline range")
        previous_end = end
    if len(ids) != len(set(ids)):
        errors.append("duplicate caption IDs")
    if captions and float(captions[-1].get("end", duration + 1)) > duration:
        errors.append("final caption ends after media duration")
    return {
        "valid": not errors,
        "caption_count": len(captions),
        "duration": duration,
        "errors": errors,
    }

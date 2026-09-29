"""Structural and semantic validation for silence-cut plans/results."""

from __future__ import annotations

from typing import Any


def validate_silence_plan(plan: dict[str, Any], words: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    previous_end = -1.0
    for cut in sorted(plan.get("cuts") or [], key=lambda item: item["cut_start"]):
        start, end = float(cut["cut_start"]), float(cut["cut_end"])
        if end <= start:
            errors.append(f"{cut.get('cut_id')}: non-positive range")
        if start < previous_end:
            errors.append(f"{cut.get('cut_id')}: overlaps prior cut")
        if any(float(word["start"]) < end and float(word["end"]) > start for word in words):
            errors.append(f"{cut.get('cut_id')}: intersects lexical word")
        previous_end = end
    return {
        "valid": not errors, "errors": errors,
        "cut_count": len(plan.get("cuts") or []),
        "no_lexical_words_removed": not any("lexical" in error for error in errors),
    }

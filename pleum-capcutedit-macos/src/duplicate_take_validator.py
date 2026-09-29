"""Strict validation for read-only duplicate-take analysis."""

from __future__ import annotations

from typing import Any


def validate_duplicate_take_analysis(
    words: list[dict[str, Any]],
    utterances: list[dict[str, Any]],
    plan: dict[str, Any],
    minimum_drop_confidence: float,
) -> dict[str, Any]:
    errors: list[str] = []
    duration = float(plan["project_duration"])
    expected_indices = list(range(len(words)))
    actual_indices: list[int] = []
    previous_end = 0.0
    utterance_ids = {item["utterance_id"] for item in utterances}
    for utterance in utterances:
        if utterance["start"] < previous_end - 0.000001:
            errors.append(f"{utterance['utterance_id']}: not chronological")
        if utterance["end"] <= utterance["start"]:
            errors.append(f"{utterance['utterance_id']}: invalid range")
        if utterance["start"] < 0 or utterance["end"] > duration + 0.000001:
            errors.append(f"{utterance['utterance_id']}: outside project duration")
        if not utterance["source_segment_ids"]:
            errors.append(f"{utterance['utterance_id']}: source segment boundary missing")
        actual_indices.extend(utterance["word_indices"])
        previous_end = utterance["end"]
    if sorted(actual_indices) != expected_indices or len(actual_indices) != len(set(actual_indices)):
        errors.append("lexical words do not belong to exactly one utterance")
    for group in plan["groups"]:
        references = [
            group["recommended_keep_utterance_id"],
            *group["recommended_drop_utterance_ids"],
        ]
        if any(reference not in utterance_ids for reference in references):
            errors.append(f"{group['group_id']}: references missing utterance")
        if (
            group["recommended_drop_utterance_ids"]
            and float(group["confidence"]) < minimum_drop_confidence
        ):
            errors.append(f"{group['group_id']}: drop recommendation below threshold")
        keep = group["keep_range"]
        for drop in group["drop_ranges"]:
            suggested = drop["suggested_cut_range"]
            if suggested["end"] <= suggested["start"]:
                errors.append(f"{group['group_id']}: invalid suggested cut range")
            if suggested["start"] < keep["end"] and suggested["end"] > keep["start"]:
                errors.append(f"{group['group_id']}: suggested cut overlaps kept take")
            if len(drop["source_segment_ids"]) != 1:
                errors.append(f"{group['group_id']}: cut crosses source segment boundary")
        for drop in group.get("provisional_review_ranges", []):
            suggested = drop["suggested_cut_range"]
            if suggested["end"] <= suggested["start"]:
                errors.append(f"{group['group_id']}: invalid provisional range")
            if suggested["start"] < keep["end"] and suggested["end"] > keep["start"]:
                errors.append(f"{group['group_id']}: provisional range overlaps kept take")
            if len(drop["source_segment_ids"]) != 1:
                errors.append(
                    f"{group['group_id']}: provisional range crosses source segment boundary"
                )
        if "DIFFERENT_IMPORTANT_FACTS" in group["reason_codes"] and group[
            "recommended_drop_utterance_ids"
        ]:
            errors.append(f"{group['group_id']}: unmatched important content recommended for drop")
    return {
        "valid": not errors,
        "errors": errors,
        "utterance_count": len(utterances),
        "group_count": len(plan["groups"]),
    }

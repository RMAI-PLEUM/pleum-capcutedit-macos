"""Combine lexical gaps with continuous low-energy regions."""

from __future__ import annotations

from typing import Any


def build_silence_candidates(
    words: list[dict[str, Any]], regions: list[dict[str, float]],
    preset: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if "target_remaining_gap_seconds" in preset:
        return _build_target_gap_candidates(words, regions, preset)
    candidates, skipped = [], []
    for previous, following in zip(words, words[1:]):
        gap_start, gap_end = float(previous["end"]), float(following["start"])
        gap = gap_end - gap_start
        if gap < preset["minimum_word_gap_seconds"]:
            continue
        overlaps = [
            region for region in regions
            if region["end"] > gap_start and region["start"] < gap_end
        ]
        if not overlaps:
            skipped.append({"gap_start": gap_start, "gap_end": gap_end,
                            "reason": "NO_CONTINUOUS_LOW_ENERGY_REGION"})
            continue
        best = max(overlaps, key=lambda region: min(gap_end, region["end"]) - max(gap_start, region["start"]))
        detected_start = max(gap_start, best["start"])
        detected_end = min(gap_end, best["end"])
        detected_duration = detected_end - detected_start
        cut_start = max(gap_start + preset["keep_after_previous_word_seconds"], detected_start)
        cut_end = min(gap_end - preset["keep_before_next_word_seconds"], detected_end)
        cut_duration = cut_end - cut_start
        remaining = gap - cut_duration
        reasons = []
        if detected_duration < preset["minimum_detected_silence_seconds"]:
            reasons.append("LOW_ENERGY_REGION_TOO_SHORT")
        if cut_duration < preset["minimum_cut_duration_seconds"]:
            reasons.append("CUT_TOO_SHORT")
        if remaining + 1e-9 < preset["minimum_remaining_gap_seconds"]:
            reasons.append("INSUFFICIENT_SPEECH_HANDLES")
        record = {
            "gap_start": round(gap_start, 6), "gap_end": round(gap_end, 6),
            "previous_word": previous["text"], "next_word": following["text"],
            "detected_silence_start": round(detected_start, 6),
            "detected_silence_end": round(detected_end, 6),
            "cut_start": round(cut_start, 6), "cut_end": round(cut_end, 6),
            "cut_duration": round(cut_duration, 6),
            "remaining_gap_duration": round(remaining, 6),
            "average_dbfs": round(best["average_dbfs"], 3),
        }
        if reasons:
            skipped.append({**record, "reason_codes": reasons})
        else:
            candidates.append({
                **record,
                "reason_codes": ["NO_LEXICAL_SPEECH", "LOW_AUDIO_ENERGY",
                                 "SAFE_SPEECH_HANDLES"],
            })
    for index, candidate in enumerate(candidates, 1):
        candidate["cut_id"] = f"silence_cut_{index:04d}"
    return candidates, skipped


def _build_target_gap_candidates(
    words: list[dict[str, Any]], regions: list[dict[str, float]],
    preset: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select several safe islands until a no-word gap reaches its target."""
    cuts: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    target = float(preset["target_remaining_gap_seconds"])
    tolerance = float(preset["target_remaining_gap_tolerance_seconds"])
    keep_after = float(preset["preferred_keep_after_previous_word_seconds"])
    keep_before = float(preset["preferred_keep_before_next_word_seconds"])
    minimum_cut = float(preset["minimum_cut_duration_seconds"])
    gap_number = 0
    for previous, following in zip(words, words[1:]):
        gap_start, gap_end = float(previous["end"]), float(following["start"])
        original_gap = gap_end - gap_start
        if original_gap <= target + tolerance + 1e-9:
            if original_gap >= 0:
                reports.append({
                    "gap_start": round(gap_start, 6),
                    "gap_end": round(gap_end, 6),
                    "previous_word": previous["text"], "next_word": following["text"],
                    "original_gap_seconds": round(original_gap, 6),
                    "target_gap_seconds": target,
                    "final_gap_seconds": round(original_gap, 6),
                    "within_target_tolerance": abs(original_gap - target) <= tolerance,
                    "reason_codes": ["ALREADY_WITHIN_TARGET"]
                    if abs(original_gap - target) <= tolerance
                    else ["BELOW_TARGET_NO_CUT"],
                    "proposed_cut_ranges": [],
                })
            continue
        gap_number += 1
        gap_id = f"silence_gap_{gap_number:04d}"
        desired_remove = original_gap - target
        preferred_start = gap_start + keep_after
        preferred_end = gap_end - keep_before
        usable: list[dict[str, float]] = []
        protected: list[dict[str, float | str]] = []
        for region in regions:
            start = max(preferred_start, gap_start, float(region["start"]))
            end = min(preferred_end, gap_end, float(region["end"]))
            duration = end - start
            if duration >= minimum_cut:
                usable.append({
                    "start": start, "end": end,
                    "average_dbfs": float(region["average_dbfs"]),
                })
        # Preserve non-low-energy holes. They represent breath/noise/uncertain audio.
        cursor = preferred_start
        for region in usable:
            if region["start"] > cursor + 1e-6:
                protected.append({
                    "start": round(cursor, 6), "end": round(region["start"], 6),
                    "reason": "PROTECTED_NON_SILENT_OR_UNCERTAIN_AUDIO",
                })
            cursor = max(cursor, region["end"])
        if cursor < preferred_end - 1e-6:
            protected.append({
                "start": round(cursor, 6), "end": round(preferred_end, 6),
                "reason": "PROTECTED_NON_SILENT_OR_UNCERTAIN_AUDIO",
            })
        selected: list[dict[str, Any]] = []
        remaining_to_remove = desired_remove
        # Prefer the middle of the pause, preserving both speech-side handles.
        for region in usable:
            if remaining_to_remove < minimum_cut:
                break
            available = region["end"] - region["start"]
            duration = min(available, remaining_to_remove)
            if duration < minimum_cut:
                continue
            start = region["start"]
            end = start + duration
            selected.append({
                "gap_id": gap_id,
                "gap_start": round(gap_start, 6), "gap_end": round(gap_end, 6),
                "previous_word": previous["text"], "next_word": following["text"],
                "detected_silence_start": round(region["start"], 6),
                "detected_silence_end": round(region["end"], 6),
                "cut_start": round(start, 6), "cut_end": round(end, 6),
                "cut_duration": round(duration, 6),
                "average_dbfs": round(region["average_dbfs"], 3),
                "reason_codes": [
                    "NO_LEXICAL_SPEECH", "LOW_AUDIO_ENERGY",
                    "TARGET_REMAINING_GAP", "SAFE_SPEECH_HANDLES",
                ],
            })
            remaining_to_remove -= duration
        removed = sum(item["cut_duration"] for item in selected)
        final_gap = original_gap - removed
        within = abs(final_gap - target) <= tolerance + 1e-6
        for item in selected:
            item.update({
                "original_gap_seconds": round(original_gap, 6),
                "target_gap_seconds": target,
                "final_gap_seconds": round(final_gap, 6),
                "within_target_tolerance": within,
                "remaining_gap_duration": round(final_gap, 6),
                "low_energy_regions_used": [
                    {"start": round(value["cut_start"], 6),
                     "end": round(value["cut_end"], 6)}
                    for value in selected
                ],
                "protected_breath_noise_regions": protected,
            })
        cuts.extend(selected)
        reason_codes = (
            ["TARGET_REACHED"] if within else
            [
                "TARGET_NOT_REACHED_AUDIO_SAFETY_LIMIT",
                "SPEECH_BOUNDARY_PROTECTION",
                "BREATH_PROTECTION",
                "UNCERTAIN_AUDIO_NEAR_WORD",
            ]
        )
        reports.append({
            "gap_id": gap_id, "gap_start": round(gap_start, 6),
            "gap_end": round(gap_end, 6),
            "previous_word": previous["text"], "next_word": following["text"],
            "original_gap_seconds": round(original_gap, 6),
            "target_gap_seconds": target,
            "safe_removable_duration": round(removed, 6),
            "final_gap_seconds": round(final_gap, 6),
            "within_target_tolerance": within,
            "low_energy_regions_used": [
                {"start": item["cut_start"], "end": item["cut_end"]}
                for item in selected
            ],
            "protected_breath_noise_regions": protected,
            "proposed_cut_ranges": [
                {"start": item["cut_start"], "end": item["cut_end"]}
                for item in selected
            ],
            "reason_codes": reason_codes,
        })
    for index, cut in enumerate(cuts, 1):
        cut["cut_id"] = f"silence_cut_{index:04d}"
    return cuts, reports

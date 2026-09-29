"""Learn a local talking-head edit profile from a user-edited CapCut reference."""

from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


FRAME_RATE_CANDIDATES = (24, 25, 30, 50, 60)


def _media_key(value: str) -> str:
    return str(Path(value)).replace("/", "\\").casefold()


def _dominant_media(analysis: dict[str, Any]) -> str:
    totals: dict[str, float] = defaultdict(float)
    original: dict[str, str] = {}
    for segment in analysis.get("audible_segments", []):
        path = str(segment.get("media_path") or "")
        if not path:
            continue
        key = _media_key(path)
        original[key] = path
        totals[key] += float(segment["source_timerange"]["duration"])
    if not totals:
        raise RuntimeError("No audible source media was found in the project.")
    return original[max(totals, key=totals.get)]


def _merge_ranges(
    ranges: list[tuple[float, float]], tolerance: float = 0.000002
) -> list[list[float]]:
    merged: list[list[float]] = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if not merged or start > merged[-1][1] + tolerance:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def _source_ranges(analysis: dict[str, Any], media_path: str) -> list[list[float]]:
    key = _media_key(media_path)
    return _merge_ranges([
        (
            float(segment["source_timerange"]["start"]),
            float(segment["source_timerange"]["end"]),
        )
        for segment in analysis.get("audible_segments", [])
        if _media_key(str(segment.get("media_path") or "")) == key
    ])


def _duration(ranges: list[list[float]]) -> float:
    return sum(end - start for start, end in ranges)


def _intersection_duration(
    left: list[list[float]], right: list[list[float]]
) -> float:
    total = 0.0
    first = second = 0
    while first < len(left) and second < len(right):
        start = max(left[first][0], right[second][0])
        end = min(left[first][1], right[second][1])
        total += max(0.0, end - start)
        if left[first][1] <= right[second][1]:
            first += 1
        else:
            second += 1
    return total


def _subtract_ranges(
    left: list[list[float]], right: list[list[float]]
) -> list[list[float]]:
    """Return the portions of *left* that are not covered by *right*."""
    output: list[list[float]] = []
    right_index = 0
    for left_start, left_end in left:
        cursor = left_start
        while right_index < len(right) and right[right_index][1] <= cursor:
            right_index += 1
        index = right_index
        while index < len(right) and right[index][0] < left_end:
            right_start, right_end = right[index]
            if right_start > cursor:
                output.append([cursor, min(right_start, left_end)])
            cursor = max(cursor, right_end)
            if cursor >= left_end:
                break
            index += 1
        if cursor < left_end:
            output.append([cursor, left_end])
    return _merge_ranges(output)


def _complement(
    ranges: list[list[float]], start: float, end: float
) -> list[list[float]]:
    output: list[list[float]] = []
    cursor = start
    for range_start, range_end in ranges:
        if range_start > cursor:
            output.append([cursor, range_start])
        cursor = max(cursor, range_end)
    if cursor < end:
        output.append([cursor, end])
    return output


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "minimum": round(min(values), 6) if values else 0.0,
        "median": round(statistics.median(values), 6) if values else 0.0,
        "mean": round(statistics.fmean(values), 6) if values else 0.0,
        "p75": round(_percentile(values, 0.75), 6),
        "p90": round(_percentile(values, 0.90), 6),
        "maximum": round(max(values), 6) if values else 0.0,
    }


def _frame_grid(boundaries: list[float]) -> dict[str, Any]:
    candidates = []
    for rate in FRAME_RATE_CANDIDATES:
        errors = [abs(round(value * rate) - value * rate) / rate for value in boundaries]
        candidates.append({
            "fps": rate,
            "mean_error_seconds": statistics.fmean(errors) if errors else 0.0,
            "within_two_ms_ratio": (
                sum(error <= 0.002 for error in errors) / len(errors)
                if errors else 0.0
            ),
        })
    best = min(candidates, key=lambda item: (item["mean_error_seconds"], item["fps"]))
    return {
        "inferred_fps": best["fps"],
        "mean_boundary_error_seconds": round(best["mean_error_seconds"], 8),
        "boundary_alignment_ratio": round(best["within_two_ms_ratio"], 6),
    }


def _boundary_handles(
    reference_analysis: dict[str, Any],
    raw_transcript: dict[str, Any] | None,
) -> dict[str, Any]:
    if not raw_transcript:
        return {"available": False}
    timed = []
    for record in raw_transcript.get("words", []):
        if record.get("type") != "word":
            continue
        try:
            start, end = float(record["start"]), float(record["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            timed.append((start, end))
    target_ranges = sorted([
        (
            float(segment["target_timerange"]["start"]),
            float(segment["target_timerange"]["end"]),
        )
        for segment in reference_analysis.get("audible_segments", [])
    ])
    leads: list[float] = []
    tails: list[float] = []
    lexically_empty_ranges: list[dict[str, float]] = []
    for range_start, range_end in target_ranges:
        overlapping = [
            item for item in timed
            if item[0] < range_end and item[1] > range_start
        ]
        if not overlapping:
            lexically_empty_ranges.append({
                "start": round(range_start, 6),
                "end": round(range_end, 6),
                "duration": round(range_end - range_start, 6),
            })
            continue
        leads.append(max(0.0, overlapping[0][0] - range_start))
        tails.append(max(0.0, range_end - overlapping[-1][1]))
    join_leads: list[float] = []
    join_tails: list[float] = []
    crossing_boundaries: list[float] = []
    for boundary in [end for _start, end in target_ranges[:-1]]:
        if any(start < boundary < end for start, end in timed):
            crossing_boundaries.append(boundary)
        previous = [item for item in timed if item[1] <= boundary]
        following = [item for item in timed if item[0] >= boundary]
        if previous:
            join_tails.append(max(0.0, boundary - previous[-1][1]))
        if following:
            join_leads.append(max(0.0, following[0][0] - boundary))
    spacing = []
    for record in raw_transcript.get("words", []):
        if record.get("type") != "spacing":
            continue
        try:
            duration = float(record["end"]) - float(record["start"])
        except (KeyError, TypeError, ValueError):
            continue
        if duration > 0:
            spacing.append(duration)
    return {
        "available": bool(leads),
        "sample_count": len(leads),
        "lexically_empty_segment_count": len(lexically_empty_ranges),
        "lexically_empty_segments": lexically_empty_ranges,
        "lead_handle_seconds": _stats(leads),
        "tail_handle_seconds": _stats(tails),
        "join_boundary_count": max(0, len(target_ranges) - 1),
        "word_crossing_boundary_count": len(crossing_boundaries),
        "word_crossing_boundaries_seconds": [
            round(value, 6) for value in crossing_boundaries
        ],
        "join_lead_handle_seconds": _stats(join_leads),
        "join_tail_handle_seconds": _stats(join_tails),
        "transcribed_spacing_seconds": _stats(spacing),
        "transcribed_spacing_over_300ms": sum(value > 0.3 for value in spacing),
        "transcribed_spacing_over_500ms": sum(value > 0.5 for value in spacing),
    }


def _timeline_integrity(analysis: dict[str, Any]) -> dict[str, Any]:
    segments = sorted(
        analysis.get("audible_segments", []),
        key=lambda item: (
            int(item.get("track_index", 0)),
            float(item["target_timerange"]["start"]),
        ),
    )
    overlaps: list[dict[str, Any]] = []
    for previous, current in zip(segments, segments[1:]):
        if previous.get("track_index") != current.get("track_index"):
            continue
        previous_end = float(previous["target_timerange"]["end"])
        current_start = float(current["target_timerange"]["start"])
        if current_start < previous_end - 0.000001:
            overlaps.append({
                "previous_segment_id": previous.get("segment_id"),
                "current_segment_id": current.get("segment_id"),
                "start": round(current_start, 6),
                "end": round(previous_end, 6),
                "duration": round(previous_end - current_start, 6),
            })
    return {
        "safe_for_direct_transcription": bool(
            analysis.get("safe_for_direct_transcription")
        ),
        "overlap_count": len(overlaps),
        "overlap_duration_seconds": round(
            sum(item["duration"] for item in overlaps), 6
        ),
        "overlaps": overlaps,
        "unsupported_structures": list(analysis.get("unsupported_structures", [])),
    }


def learn_manual_edit_style(
    source_analysis: dict[str, Any],
    reference_analysis: dict[str, Any],
    raw_transcript: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_media = _dominant_media(source_analysis)
    reference_media = _dominant_media(reference_analysis)
    if _media_key(source_media) != _media_key(reference_media):
        raise RuntimeError(
            "Source and manual-reference projects do not use the same dominant media."
        )
    source_ranges = _source_ranges(source_analysis, source_media)
    reference_ranges = _source_ranges(reference_analysis, reference_media)
    if not source_ranges or not reference_ranges:
        raise RuntimeError("Source ranges could not be reconstructed.")
    baseline_start = min(source_ranges[0][0], reference_ranges[0][0], 0.0)
    baseline_end = max(source_ranges[-1][1], reference_ranges[-1][1])
    baseline_duration = baseline_end - baseline_start
    reference_duration = _duration(reference_ranges)
    source_kept_duration = _duration(source_ranges)
    shared_duration = _intersection_duration(source_ranges, reference_ranges)
    keep_durations = [end - start for start, end in reference_ranges]
    removed_ranges = _complement(reference_ranges, baseline_start, baseline_end)
    cut_durations = [end - start for start, end in removed_ranges]
    boundaries = [value for item in reference_ranges for value in item]
    recall = shared_duration / reference_duration if reference_duration else 0.0
    precision = shared_duration / source_kept_duration if source_kept_duration else 0.0
    keep_ratio = reference_duration / baseline_duration if baseline_duration else 0.0
    frame = _frame_grid(boundaries)
    micro_threshold = 2 / frame["inferred_fps"]
    return {
        "version": 1,
        "profile_type": "local_manual_talking_head_reference",
        "source_project": source_analysis.get("project_name"),
        "reference_project": reference_analysis.get("project_name"),
        "dominant_media_path": source_media,
        "baseline_source_range": {
            "start": round(baseline_start, 6),
            "end": round(baseline_end, 6),
            "duration": round(baseline_duration, 6),
        },
        "reference_timeline_duration": round(
            float(reference_analysis.get("duration", reference_duration)), 6
        ),
        "reference_kept_source_duration": round(reference_duration, 6),
        "reference_output_to_source_ratio": round(keep_ratio, 6),
        "edit_mode": (
            "selective_story_compaction" if keep_ratio < 0.50
            else "conservative_cleanup"
        ),
        "cadence": {
            "kept_segment_count": len(reference_ranges),
            "removed_span_count": len(removed_ranges),
            "kept_segment_duration_seconds": _stats(keep_durations),
            "removed_span_duration_seconds": _stats(cut_durations),
            "micro_segments_under_two_frames": sum(
                duration < micro_threshold for duration in keep_durations
            ),
            **frame,
        },
        "speech_boundary_handles": _boundary_handles(
            reference_analysis, raw_transcript
        ),
        "timeline_integrity": {
            "current_skill": _timeline_integrity(source_analysis),
            "manual_reference": _timeline_integrity(reference_analysis),
        },
        "current_skill_benchmark": {
            "kept_duration": round(source_kept_duration, 6),
            "manual_reference_recall": round(recall, 6),
            "manual_reference_precision": round(precision, 6),
            "over_retained_duration": round(
                max(0.0, source_kept_duration - shared_duration), 6
            ),
            "manual_content_removed_duration": round(
                max(0.0, reference_duration - shared_duration), 6
            ),
        },
        "reference_kept_source_ranges": [
            {"start": round(start, 6), "end": round(end, 6),
             "duration": round(end - start, 6)}
            for start, end in reference_ranges
        ],
        "comparison_ranges": {
            "current_skill_only": [
                {"start": round(start, 6), "end": round(end, 6),
                 "duration": round(end - start, 6)}
                for start, end in _subtract_ranges(source_ranges, reference_ranges)
            ],
            "manual_reference_only": [
                {"start": round(start, 6), "end": round(end, 6),
                 "duration": round(end - start, 6)}
                for start, end in _subtract_ranges(reference_ranges, source_ranges)
            ],
        },
        "learned_policy": {
            "selection_unit": "semantic_beat_best_take",
            "deduplicate_before_silence_cleanup": True,
            "one_complete_take_per_story_beat": True,
            "split_abandoned_prefix_from_completed_setup": True,
            "remove_partial_repeated_clause": True,
            "restart_marker_requires_content_overlap": True,
            "prefer_complete_fluent_take_over_earliest_take": True,
            "preserve_story_order": True,
            "snap_boundaries_to_inferred_frame_grid": True,
            "require_zero_primary_timeline_overlaps": True,
            "minimum_automatic_residual_frames": 2,
            "forbid_standalone_no_lexical_residual_segments": True,
            "target_output_to_source_ratio": round(keep_ratio, 6),
            "target_kept_segment_median_seconds": _stats(keep_durations)["median"],
            "target_kept_segment_p90_seconds": _stats(keep_durations)["p90"],
        },
        "local_only": True,
    }

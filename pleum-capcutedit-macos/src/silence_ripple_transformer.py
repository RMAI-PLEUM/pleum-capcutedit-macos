"""Multi-range silence ripple transform using the proven CapCut cut primitive."""

from __future__ import annotations

from typing import Any

from auto_duplicate_cleanup import transform_multiple_cuts


PRIMARY_TYPES = {"video", "audio"}


def normalize_micro_fragment_cuts(
    draft: dict[str, Any],
    cuts: list[dict[str, Any]],
    words: list[dict[str, Any]],
    minimum_fragment_seconds: float = 2 / 30,
    *,
    remove_internal_transcript_free_residuals: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Absorb transcript-free tiny shards at clip edges or between cuts.

    CapCut may quantize a sub-frame residual to a full frame when reopened. The
    extra frame can overlap the following clip and create an audible repeat.
    Expansion is allowed only through transcript-free audio. Personal editing
    profiles may also remove a longer speechless island trapped between a
    silence cut and an existing internal clip boundary. Outer project handles
    remain untouched.
    """
    segments = []
    for track in draft.get("tracks", []):
        if track.get("type") not in PRIMARY_TYPES:
            continue
        for segment in track.get("segments", []):
            target = segment.get("target_timerange") or {}
            if not isinstance(target.get("start"), int) or not isinstance(
                target.get("duration"), int
            ):
                continue
            start = target["start"] / 1_000_000
            end = (target["start"] + target["duration"]) / 1_000_000
            segments.append((start, end, segment.get("id")))
    project_end = max((end for _start, end, _id in segments), default=0.0)

    def has_word(start: float, end: float) -> bool:
        return any(
            float(word["start"]) < end - 0.000001
            and float(word["end"]) > start + 0.000001
            for word in words
        )

    normalized: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for original in cuts:
        current = dict(original)
        cut_start = float(current["cut_start"])
        cut_end = float(current["cut_end"])
        for segment_start, segment_end, segment_id in segments:
            left_residual = cut_start - segment_start
            remove_left_island = (
                remove_internal_transcript_free_residuals
                and segment_start > 0.000001
                and 0 < left_residual
                and not has_word(segment_start, cut_start)
            )
            if (
                segment_start < cut_start < segment_end
                and (
                    0 < left_residual < minimum_fragment_seconds
                    or remove_left_island
                )
                and not has_word(segment_start, cut_start)
            ):
                actions.append({
                    "cut_id": current.get("cut_id"),
                    "segment_id": segment_id,
                    "edge": "cut_start",
                    "from": round(cut_start, 6),
                    "to": round(segment_start, 6),
                    "removed_micro_fragment_seconds": round(left_residual, 6),
                    "reason": (
                        "TRANSCRIPT_FREE_INTERNAL_RESIDUAL"
                        if remove_left_island
                        else "MICRO_FRAGMENT"
                    ),
                })
                cut_start = segment_start
            right_residual = segment_end - cut_end
            remove_right_island = (
                remove_internal_transcript_free_residuals
                and segment_end < project_end - 0.000001
                and 0 < right_residual
                and not has_word(cut_end, segment_end)
            )
            if (
                segment_start < cut_end < segment_end
                and (
                    0 < right_residual < minimum_fragment_seconds
                    or remove_right_island
                )
                and not has_word(cut_end, segment_end)
            ):
                actions.append({
                    "cut_id": current.get("cut_id"),
                    "segment_id": segment_id,
                    "edge": "cut_end",
                    "from": round(cut_end, 6),
                    "to": round(segment_end, 6),
                    "removed_micro_fragment_seconds": round(right_residual, 6),
                    "reason": (
                        "TRANSCRIPT_FREE_INTERNAL_RESIDUAL"
                        if remove_right_island
                        else "MICRO_FRAGMENT"
                    ),
                })
                cut_end = segment_end
        current["cut_start"] = round(cut_start, 6)
        current["cut_end"] = round(cut_end, 6)
        current["cut_duration"] = round(cut_end - cut_start, 6)
        normalized.append(current)

    # Multiple low-energy islands inside one lexical gap can leave a protected
    # breath/noise shard shorter than two frames between adjacent cuts. Keeping
    # that shard is unsafe in CapCut even though each cut is valid by itself.
    # Absorb it only when the entire inter-cut range is transcript-free.
    coalesced: list[dict[str, Any]] = []
    for current in sorted(normalized, key=lambda item: float(item["cut_start"])):
        if coalesced:
            previous = coalesced[-1]
            previous_end = float(previous["cut_end"])
            current_start = float(current["cut_start"])
            residual = current_start - previous_end
            cuts_overlap = residual <= 0.000001
            transcript_free_tiny_gap = (
                0 < residual < minimum_fragment_seconds
                and not has_word(previous_end, current_start)
            )
            if cuts_overlap or transcript_free_tiny_gap:
                previous["cut_end"] = round(
                    max(previous_end, float(current["cut_end"])), 6
                )
                previous["cut_duration"] = round(
                    float(previous["cut_end"]) - float(previous["cut_start"]), 6
                )
                previous["merged_cut_ids"] = [
                    *previous.get("merged_cut_ids", [previous.get("cut_id")]),
                    *current.get("merged_cut_ids", [current.get("cut_id")]),
                ]
                previous["reason_codes"] = list(dict.fromkeys([
                    *previous.get("reason_codes", []),
                    *current.get("reason_codes", []),
                    (
                        "OVERLAPPING_NORMALIZED_CUTS_MERGED"
                        if cuts_overlap
                        else "MICRO_FRAGMENT_ABSORBED"
                    ),
                ]))
                actions.append({
                    "cut_id": previous.get("cut_id"),
                    "merged_cut_id": current.get("cut_id"),
                    "edge": (
                        "overlapping_cuts" if cuts_overlap else "inter_cut_gap"
                    ),
                    "from": round(previous_end, 6),
                    "to": round(current_start, 6),
                    "removed_micro_fragment_seconds": round(max(residual, 0.0), 6),
                })
                continue
        coalesced.append(current)
    return coalesced, actions


def transform_silence_cuts(
    draft: dict[str, Any], cuts: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    ranges = [{"start": cut["cut_start"], "end": cut["cut_end"],
               "cut_id": cut["cut_id"]} for cut in cuts]
    return transform_multiple_cuts(draft, ranges)

"""Build read-only keep/drop recommendations and provisional safe ranges."""

from __future__ import annotations

from typing import Any


def build_take_plan(
    groups: list[dict[str, Any]],
    utterances: list[dict[str, Any]],
    duration: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    by_id = {item["utterance_id"]: item for item in utterances}
    output_groups: list[dict[str, Any]] = []
    for group in groups:
        keep = by_id[group["recommended_keep_utterance_id"]]
        drop_ranges = []
        skipped_ranges = []
        potential_ids = (
            [
                take["utterance"]["utterance_id"]
                for take in group["takes"]
                if take["utterance"]["utterance_id"]
                != group["recommended_keep_utterance_id"]
            ]
            if group["confidence_class"] in {"high", "medium"} else []
        )
        provisional_ranges = []
        for drop_id in potential_ids:
            drop = by_id[drop_id]
            spoken = {"start": drop["start"], "end": drop["end"]}
            suggested_start = max(
                0.0, float(drop["start"]) - float(config["start_handle"])
            )
            suggested_end = min(
                duration, float(drop["end"]) + float(config["end_handle"])
            )
            if suggested_end > float(keep["start"]) and drop["end"] <= keep["start"]:
                suggested_end = min(suggested_end, float(keep["start"]))
            range_record = {
                "utterance_id": drop_id,
                "spoken_content_range": spoken,
                "suggested_cut_range": {
                    "start": round(suggested_start, 6),
                    "end": round(suggested_end, 6),
                },
                "source_segment_ids": drop["source_segment_ids"],
            }
            overlaps_keep = (
                range_record["suggested_cut_range"]["start"] < float(keep["end"])
                and range_record["suggested_cut_range"]["end"] > float(keep["start"])
            )
            if overlaps_keep:
                skipped_ranges.append({
                    **range_record,
                    "reason_code": "CUT_RANGE_OVERLAPS_KEPT_TAKE",
                })
                continue
            provisional_ranges.append(range_record)
            if drop_id in group["recommended_drop_utterance_ids"]:
                drop_ranges.append(range_record)
        output_groups.append({
            **group,
            "keep_range": {"start": keep["start"], "end": keep["end"]},
            "drop_ranges": drop_ranges,
            "provisional_review_drop_utterance_ids": potential_ids,
            "provisional_review_ranges": provisional_ranges,
            "skipped_unsafe_ranges": skipped_ranges,
        })
    return {
        "version": 1,
        "read_only": True,
        "project_duration": duration,
        "groups": output_groups,
    }

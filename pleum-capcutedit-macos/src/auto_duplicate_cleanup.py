"""Automatic duplicate-take policy and transaction-safe multi-cut execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from capcut_live_project_reader import LiveProject
from capcut_write_guard import require_live_project_write_ready
from capcut_project_validator import all_object_ids
from capcut_ripple_cut import TIME_SCALE, apply_ripple_cut
from capcut_timeline_media_resolver import analyze_timeline


AUTO_CATEGORIES = {
    "explicit_restart",
    "prefix_restart",
    "complete_duplicate",
    "correction_take",
    "partial_repeated_take",
}


def _quality(group: dict[str, Any], utterance_id: str) -> float:
    for take in group.get("takes", []):
        if take["utterance"]["utterance_id"] == utterance_id:
            return float(take["quality_score"]["total_score"])
    return 0.0


def build_auto_cleanup_plan(
    project_name: str,
    timeline_hash: str,
    groups: list[dict[str, Any]],
    utterances: list[dict[str, Any]],
    lexical_words: list[dict[str, Any]],
    config: dict[str, Any],
    fillers: list[str],
    restart_markers: list[str],
) -> dict[str, Any]:
    by_id = {item["utterance_id"]: item for item in utterances}
    applied_groups: list[dict[str, Any]] = []
    skipped_groups: list[dict[str, Any]] = []
    proposed_ranges: list[dict[str, Any]] = []
    for group in groups:
        reasons: list[str] = []
        automatic_threshold = max(
            float(config.get("high_confidence", 0.90)),
            float(config.get("minimum_drop_confidence", 0.90)),
        )
        if float(group.get("confidence", 0.0)) < automatic_threshold:
            reasons.append("CONFIDENCE_BELOW_AUTO_THRESHOLD")
        if group["category"] not in AUTO_CATEGORIES:
            reasons.append("CATEGORY_NOT_AUTO_CUTTABLE")
        if "DIFFERENT_IMPORTANT_FACTS" in group.get("reason_codes", []):
            reasons.append("IMPORTANT_CONTENT_DIFFERS")
        if "TRANSCRIPT_CONFIDENCE_TOO_LOW" in group.get("reason_codes", []):
            reasons.append("TRANSCRIPT_TOO_UNCERTAIN")
        keep_id = group["recommended_keep_utterance_id"]
        competing = [
            take["utterance"]["utterance_id"]
            for take in group.get("takes", [])
            if take["utterance"]["utterance_id"] != keep_id
        ]
        if not competing:
            reasons.append("NO_COMPETING_TAKE")
        keep = by_id.get(keep_id)
        if keep is None:
            reasons.append("KEEP_UTTERANCE_MISSING")
        for drop_id in competing:
            drop = by_id.get(drop_id)
            if drop is None:
                reasons.append("DROP_UTTERANCE_MISSING")
                continue
            if keep and drop.get("speaker") is not None and keep.get("speaker") is not None:
                if drop["speaker"] != keep["speaker"]:
                    reasons.append("SPEAKER_MISMATCH")
            if len(drop.get("source_segment_ids", [])) != 1:
                reasons.append("DROP_CROSSES_SOURCE_SEGMENTS")
            if _quality(group, keep_id) <= _quality(group, drop_id):
                reasons.append("KEEP_TAKE_NOT_HIGHER_QUALITY")
            if keep:
                start = max(0.0, float(drop["start"]) - float(config["start_handle"]))
                end = float(drop["end"]) + float(config["end_handle"])
                if drop["end"] <= keep["start"]:
                    end = min(end, float(keep["start"]))
                if start < float(keep["end"]) and end > float(keep["start"]):
                    reasons.append("DROP_RANGE_OVERLAPS_KEPT_TAKE")
        metrics = group.get("takes") and group.get("confidence", 0)
        evidence = bool(
            "EARLIER_TAKE_HAS_RESTART_MARKER" in group.get("reason_codes", [])
            or "LATER_TAKE_COMPLETES_PREFIX" in group.get("reason_codes", [])
            or "NEAR_DUPLICATE_COMPLETE_TAKE" in group.get("reason_codes", [])
            or "LATER_TAKE_CORRECTS_INFORMATION" in group.get("reason_codes", [])
            or "HIGH_SHORTER_TEXT_CONTAINMENT" in group.get("reason_codes", [])
        )
        if not evidence:
            reasons.append("INSUFFICIENT_INTERNAL_EVIDENCE")
        if reasons:
            skipped_groups.append({
                "group_id": group["group_id"],
                "category": group["category"],
                "confidence": group["confidence"],
                "reason_codes": group.get("reason_codes", []),
                "skipped_reasons": sorted(set(reasons)),
            })
            continue
        group_ranges = []
        for drop_id in competing:
            drop = by_id[drop_id]
            start = max(0.0, float(drop["start"]) - float(config["start_handle"]))
            end = float(drop["end"]) + float(config["end_handle"])
            if keep and drop["end"] <= keep["start"]:
                end = min(end, float(keep["start"]))
            record = {
                "group_ids": [group["group_id"]],
                "utterance_ids": [drop_id],
                "start": round(start, 6),
                "end": round(end, 6),
                "source_segment_ids": drop["source_segment_ids"],
            }
            proposed_ranges.append(record)
            group_ranges.append(record)
        applied_groups.append({
            "group_id": group["group_id"],
            "category": group["category"],
            "confidence": group["confidence"],
            "kept_utterance_id": keep_id,
            "removed_utterance_ids": competing,
            "keep_quality_score": _quality(group, keep_id),
            "removed_quality_scores": {
                uid: _quality(group, uid) for uid in competing
            },
            "reason_codes": group.get("reason_codes", []),
            "original_ranges": group_ranges,
        })

    normalized_fillers = {item.casefold().replace(" ", "") for item in fillers}
    normalized_markers = {item.casefold().replace(" ", "") for item in restart_markers}
    merged: list[dict[str, Any]] = []
    for current in sorted(proposed_ranges, key=lambda item: item["start"]):
        if not merged:
            merged.append(dict(current))
            continue
        previous = merged[-1]
        gap_words = [
            word for word in lexical_words
            if float(word["start"]) >= previous["end"]
            and float(word["end"]) <= current["start"]
        ]
        removable_gap = all(
            str(word["text"]).casefold().replace(" ", "")
            in normalized_fillers | normalized_markers
            for word in gap_words
        )
        if current["start"] <= previous["end"] or (
            removable_gap and current["start"] - previous["end"] <= 0.55
        ):
            previous["end"] = max(previous["end"], current["end"])
            previous["group_ids"] = sorted(set(previous["group_ids"] + current["group_ids"]))
            previous["utterance_ids"] = sorted(
                set(previous["utterance_ids"] + current["utterance_ids"])
            )
            previous["source_segment_ids"] = sorted(
                set(previous["source_segment_ids"] + current["source_segment_ids"])
            )
        else:
            merged.append(dict(current))
    return {
        "version": 1,
        "mode": "automatic_duplicate_take_cleanup",
        "project": project_name,
        "timeline_hash": timeline_hash,
        "detected_group_count": len(groups),
        "applied_groups": applied_groups,
        "skipped_groups": skipped_groups,
        "cut_ranges": merged,
    }


def transform_multiple_cuts(
    draft: dict[str, Any],
    ranges: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    modified = draft
    all_changes: list[dict[str, Any]] = []
    generated: list[str] = []
    total = 0
    for cut in sorted(ranges, key=lambda item: item["start"], reverse=True):
        start = round(float(cut["start"]) * TIME_SCALE)
        end = round(float(cut["end"]) * TIME_SCALE)
        modified, changes = apply_ripple_cut(modified, start, end)
        all_changes.append({"range": cut, **changes})
        generated.extend(changes["generated_segment_ids"])
        total += end - start
    return modified, {
        "applied_cut_count": len(ranges),
        "total_removed": total,
        "generated_segment_ids": generated,
        "cuts_descending": all_changes,
    }


def validate_auto_modified(
    baseline: dict[str, Any],
    modified: dict[str, Any],
    changes: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    expected = int(baseline["duration"]) - int(changes["total_removed"])
    if modified.get("duration") != expected:
        errors.append("new duration does not equal old duration minus all cuts")
    ids = all_object_ids(modified)
    if len(ids) != len(set(ids)):
        errors.append("object IDs are not unique")
    analysis = analyze_timeline(modified)
    if analysis["offline_media"]:
        errors.append("media references are offline")
    if analysis["unsupported_structures"]:
        errors.extend(analysis["unsupported_structures"])
    for track in modified.get("tracks", []):
        previous_end = 0
        for segment in sorted(
            track.get("segments", []),
            key=lambda item: item.get("target_timerange", {}).get("start", -1),
        ):
            target = segment.get("target_timerange") or {}
            start, duration = target.get("start"), target.get("duration")
            if not isinstance(start, int) or not isinstance(duration, int) or duration <= 0:
                errors.append(f"invalid target range: {segment.get('id')}")
                continue
            if start < previous_end:
                errors.append(f"overlap on track {track.get('id')}")
            previous_end = start + duration
    return {
        "valid": not errors,
        "errors": errors,
        "old_duration": baseline["duration"] / TIME_SCALE,
        "new_duration": modified["duration"] / TIME_SCALE,
        "total_removed": changes["total_removed"] / TIME_SCALE,
        "media_references_resolve": not analysis["offline_media"],
        "video_audio_synchronized": not analysis["unsupported_structures"],
    }


def apply_auto_cleanup_transaction(
    live: LiveProject,
    plan: dict[str, Any],
    current_timeline_hash: str,
    dry_run: bool,
    simulate_failure_after: int | None = None,
) -> dict[str, Any]:
    if plan["timeline_hash"] != current_timeline_hash:
        raise RuntimeError("Timeline changed after automatic duplicate detection.")
    modified, changes = transform_multiple_cuts(live.primary, plan["cut_ranges"])
    validation = validate_auto_modified(live.primary, modified, changes)
    if not validation["valid"]:
        raise RuntimeError("Automatic cut preflight failed: " + "; ".join(validation["errors"]))
    if dry_run or not plan["cut_ranges"]:
        return {
            "valid": True, "dry_run": dry_run, "project_written": False,
            "changes": changes, "validation": validation,
            "rollback_performed": False,
        }
    require_live_project_write_ready(live, "duplicate_take_cleanup")
    originals = {path: path.read_bytes() for path in live.draft_paths}
    originals[live.project.metadata_path] = live.project.metadata_path.read_bytes()
    metadata = json.loads(
        originals[live.project.metadata_path].decode("utf-8-sig")
    )
    metadata["tm_duration"] = modified["duration"]
    temporary: list[tuple[Path, Path]] = []
    try:
        payloads = [(path, modified) for path in live.draft_paths] + [
            (live.project.metadata_path, metadata)
        ]
        for path, payload in payloads:
            temp = path.with_name(path.name + ".auto_duplicate.tmp")
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            if json.loads(temp.read_text(encoding="utf-8")) != payload:
                raise RuntimeError(f"temporary parse-back mismatch: {temp}")
            temporary.append((path, temp))
        for index, (path, temp) in enumerate(temporary, 1):
            temp.replace(path)
            if simulate_failure_after == index:
                raise RuntimeError("simulated multi-file failure")
        reread = [
            json.loads(path.read_text(encoding="utf-8-sig"))
            for path in live.draft_paths
        ]
        if any(item != modified for item in reread):
            raise RuntimeError("mirrored drafts differ after automatic cleanup")
        post = validate_auto_modified(live.primary, reread[0], changes)
        if not post["valid"]:
            raise RuntimeError("automatic post-write validation failed")
        return {
            "valid": True, "dry_run": False, "project_written": True,
            "changes": changes, "validation": post,
            "rollback_performed": False,
        }
    except Exception:
        for path, original in originals.items():
            restore = path.with_name(path.name + ".auto_duplicate.restore.tmp")
            restore.write_bytes(original)
            restore.replace(path)
        raise
    finally:
        for _path, temp in temporary:
            temp.unlink(missing_ok=True)


def retime_lexical_after_known_cut(
    lexical_words: list[dict[str, Any]],
    cut_start: float,
    cut_end: float,
) -> list[dict[str, Any]]:
    amount = cut_end - cut_start
    output = []
    for word in lexical_words:
        start, end = float(word["start"]), float(word["end"])
        if start >= cut_start and end <= cut_end:
            continue
        adjusted = dict(word)
        if start >= cut_end:
            adjusted["start"] = round(start - amount, 6)
            adjusted["end"] = round(end - amount, 6)
        elif start < cut_start < end:
            adjusted["end"] = round(cut_start, 6)
        elif start < cut_end < end:
            adjusted["start"] = round(cut_start, 6)
            adjusted["end"] = round(end - amount, 6)
        if adjusted["end"] > adjusted["start"]:
            output.append(adjusted)
    return output

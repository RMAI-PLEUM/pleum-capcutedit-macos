"""Approval-gated, transaction-safe direct CapCut ripple cutting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_caption_registry import stable_hash
from capcut_live_project_reader import LiveProject
from capcut_write_guard import require_live_project_write_ready
from capcut_project_validator import all_object_ids, video_signature
from capcut_ripple_cut import TIME_SCALE, apply_ripple_cut
from capcut_timeline_media_resolver import analyze_timeline


STALE_MESSAGE = (
    "The Apple timeline changed after duplicate-take analysis. "
    "Run detection again before applying cuts."
)


def essential_timeline_hash(draft: dict[str, Any]) -> str:
    analysis = analyze_timeline(draft)
    return stable_hash({
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    })


def validate_approval(
    approval: dict[str, Any],
    project_name: str,
    current_hash: str,
    take_plan: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    if approval.get("version") != 1:
        errors.append("approval version must be 1")
    if str(approval.get("project", "")).casefold() != project_name.casefold():
        errors.append("approval project does not match selected project")
    if approval.get("timeline_hash") != current_hash:
        raise RuntimeError(STALE_MESSAGE)
    cuts = approval.get("cuts")
    if not isinstance(cuts, list) or len(cuts) != 1:
        errors.append("exactly one approved cut is required")
        cuts = []
    group_ids = {group["group_id"] for group in take_plan.get("groups", [])}
    for cut in cuts:
        if cut.get("approved") is not True:
            errors.append("cut is not explicitly approved")
        if cut.get("source_group_id") not in group_ids:
            errors.append("source_group_id does not exist in take plan")
        try:
            start, end, duration = (
                float(cut["start"]), float(cut["end"]), float(cut["duration"])
            )
        except (KeyError, TypeError, ValueError):
            errors.append("cut timing is invalid")
            continue
        if start < 0 or end <= start or abs((end - start) - duration) > 0.002:
            errors.append("cut duration does not match start/end")
        keep = cut.get("keep_range") or {}
        if float(keep.get("start", -1)) < end:
            errors.append("keep range begins before cut end")
        if "MANUALLY_REVIEWED" not in cut.get("reason_codes", []):
            errors.append("manual review reason code is missing")
    return {"valid": not errors, "errors": errors, "cut_count": len(cuts)}


def validate_modified_draft(
    baseline: dict[str, Any],
    modified: dict[str, Any],
    changes: dict[str, Any],
    cut_start: int,
    cut_end: int,
) -> dict[str, Any]:
    errors: list[str] = []
    cut_duration = cut_end - cut_start
    if modified.get("duration") != baseline.get("duration") - cut_duration:
        errors.append("project duration was not reduced by the approved cut")
    all_ids = all_object_ids(modified)
    if len(all_ids) != len(set(all_ids)):
        errors.append("object IDs are not unique after cut")
    generated = set(changes["generated_segment_ids"])
    if generated & set(all_object_ids(baseline)):
        errors.append("split segment ID collides with baseline")
    for track in modified.get("tracks", []):
        previous_end = 0
        for segment in sorted(
            track.get("segments", []),
            key=lambda item: item.get("target_timerange", {}).get("start", -1),
        ):
            target = segment.get("target_timerange")
            if not isinstance(target, dict):
                errors.append(f"segment {segment.get('id')} lacks target_timerange")
                continue
            start, duration = target.get("start"), target.get("duration")
            if not isinstance(start, int) or not isinstance(duration, int) or duration <= 0:
                errors.append(f"segment {segment.get('id')} has invalid target range")
                continue
            if start < previous_end:
                errors.append(f"track {track.get('id')} has overlapping segments")
            if start + duration > modified["duration"]:
                errors.append(f"segment {segment.get('id')} exceeds new duration")
            previous_end = start + duration
    resolved = analyze_timeline(modified)
    if resolved["offline_media"]:
        errors.append("media references are offline after cut")
    if resolved["unsupported_structures"]:
        errors.extend(
            f"post-cut unsupported: {item}"
            for item in resolved["unsupported_structures"]
        )
    primary_at_boundary = [
        segment
        for segment in resolved["audible_segments"]
        if abs(float(segment["target_timerange"]["start"]) - cut_start / TIME_SCALE)
        <= 0.000001
    ]
    if not primary_at_boundary:
        errors.append("no primary audio/video begins at ripple boundary")
    kept_mapping_valid = any(
        abs(float(segment["source_timerange"]["start"]) - cut_end / TIME_SCALE)
        <= 0.000001
        for segment in primary_at_boundary
    )
    if not kept_mapping_valid:
        errors.append("kept-take source mapping does not begin at approved cut end")
    return {
        "valid": not errors,
        "errors": errors,
        "old_duration": baseline["duration"] / TIME_SCALE,
        "new_duration": modified["duration"] / TIME_SCALE,
        "generated_ids_unique": not any("IDs" in error for error in errors),
        "media_references_resolve": not resolved["offline_media"],
        "no_timeline_gap_at_cut": bool(primary_at_boundary),
        "kept_take_ripple_mapping_valid": kept_mapping_valid,
        "video_audio_synchronized": not resolved["unsupported_structures"],
    }


def apply_approved_cut_transaction(
    live: LiveProject,
    approval: dict[str, Any],
    take_plan: dict[str, Any],
    dry_run: bool,
    simulate_failure_after: int | None = None,
) -> dict[str, Any]:
    current_hash = essential_timeline_hash(live.primary)
    approval_validation = validate_approval(
        approval, live.project.name, current_hash, take_plan
    )
    if not approval_validation["valid"]:
        raise RuntimeError(
            "Approved take cut validation failed: "
            + "; ".join(approval_validation["errors"])
        )
    cut = approval["cuts"][0]
    cut_start, cut_end = round(cut["start"] * TIME_SCALE), round(cut["end"] * TIME_SCALE)
    modified, changes = apply_ripple_cut(live.primary, cut_start, cut_end)
    validation = validate_modified_draft(
        live.primary, modified, changes, cut_start, cut_end
    )
    if not validation["valid"]:
        raise RuntimeError("Ripple cut preflight failed: " + "; ".join(validation["errors"]))
    originals = {path: path.read_bytes() for path in live.draft_paths}
    metadata_path = live.project.metadata_path
    originals[metadata_path] = metadata_path.read_bytes()
    metadata = json.loads(originals[metadata_path].decode("utf-8-sig"))
    metadata["tm_duration"] = modified["duration"]
    temporary: list[tuple[Path, Path]] = []
    rollback_performed = False
    if dry_run:
        return {
            "valid": True,
            "dry_run": True,
            "approval_validation": approval_validation,
            "precommit_validation": validation,
            "changes": changes,
            "rollback_performed": False,
            "project_written": False,
        }
    require_live_project_write_ready(live, "editorial_selection")
    try:
        payloads = [(path, modified) for path in live.draft_paths] + [
            (metadata_path, metadata)
        ]
        for path, payload in payloads:
            temp = path.with_name(path.name + ".approved_take_cut.tmp")
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
                raise RuntimeError("simulated replacement failure")
        reread = [
            json.loads(path.read_text(encoding="utf-8-sig"))
            for path in live.draft_paths
        ]
        if any(item != modified for item in reread):
            raise RuntimeError("post-write mirrored draft mismatch")
        post_validation = validate_modified_draft(
            live.primary, reread[0], changes, cut_start, cut_end
        )
        if not post_validation["valid"]:
            raise RuntimeError(
                "post-write validation failed: "
                + "; ".join(post_validation["errors"])
            )
        return {
            "valid": True,
            "dry_run": False,
            "approval_validation": approval_validation,
            "precommit_validation": validation,
            "post_write_validation": post_validation,
            "changes": changes,
            "rollback_performed": False,
            "project_written": True,
        }
    except Exception:
        rollback_performed = True
        for path, original in originals.items():
            restore = path.with_name(path.name + ".approved_take_cut.restore.tmp")
            restore.write_bytes(original)
            restore.replace(path)
        raise
    finally:
        for _path, temp in temporary:
            temp.unlink(missing_ok=True)

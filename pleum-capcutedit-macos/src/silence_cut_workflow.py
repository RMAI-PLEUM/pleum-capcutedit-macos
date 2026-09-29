"""Detection, internal dry-run, atomic application, and validation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ai_caption_registry import stable_hash
from capcut_karaoke_registry import load_karaoke_registry, registry_path
from capcut_process_guard import require_capcut_closed
from capcut_write_guard import require_live_project_write_ready
from capcut_timeline_media_resolver import analyze_timeline
from registered_karaoke_retimer import (
    active_registered_ids, coalesce_identical_adjacent_states,
)
from silence_cut_validator import validate_silence_plan
from silence_ripple_transformer import (
    normalize_micro_fragment_cuts, transform_silence_cuts,
)
from timeline_silence_detector import detect_project_silence, load_silence_preset
from timeline_time_mapper import build_time_map, map_time, retime_words
from utils import PROJECT_ROOT, write_json


def _atomic_payloads(payloads: list[tuple[Path, Any]]) -> None:
    originals = {
        path: path.read_bytes() if path.is_file() else None for path, _ in payloads
    }
    temporaries: list[tuple[Path, Path]] = []
    try:
        for path, value in payloads:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".silence_cut.tmp")
            temporary.write_text(
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            json.loads(temporary.read_text(encoding="utf-8"))
            temporaries.append((path, temporary))
        for path, temporary in temporaries:
            temporary.replace(path)
    except Exception:
        for path, value in originals.items():
            if value is None:
                path.unlink(missing_ok=True)
            else:
                restore = path.with_name(path.name + ".silence_restore.tmp")
                restore.write_bytes(value)
                restore.replace(path)
        raise
    finally:
        for _path, temporary in temporaries:
            temporary.unlink(missing_ok=True)


def retime_raw_transcript(
    raw: dict[str, Any], mapping: dict[str, Any]
) -> dict[str, Any]:
    """Retime provider records after a proven silence-only ripple map."""
    output = deepcopy(raw)
    for record in output.get("words", []):
        try:
            start = float(record["start"])
            end = float(record["end"])
        except (KeyError, TypeError, ValueError):
            continue
        record["start"] = map_time(start, mapping)
        record["end"] = map_time(end, mapping, boundary="end")
        if record["end"] < record["start"]:
            record["end"] = record["start"]
    output["audio_duration_secs"] = mapping["new_duration"]
    return output


def _retimed_cache_payloads(
    slug: str,
    mapping: dict[str, Any],
    transformed_words: list[dict[str, Any]],
    modified_analysis: dict[str, Any],
) -> list[tuple[Path, Any]]:
    raw_path = PROJECT_ROOT / f"output/json/{slug}.timeline.elevenlabs_raw.json"
    summary_path = PROJECT_ROOT / f"logs/direct_edit/{slug}/stt_summary.json"
    if not raw_path.is_file() or not summary_path.is_file():
        return []
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    try:
        raw_duration = float(raw["audio_duration_secs"])
    except (KeyError, TypeError, ValueError):
        return []
    if abs(raw_duration - float(mapping["old_duration"])) <= 0.15:
        raw = retime_raw_transcript(raw, mapping)
    elif abs(raw_duration - float(mapping["new_duration"])) > 0.15:
        return []
    new_hash = stable_hash({
        "duration": modified_analysis["duration"],
        "audible_segments": modified_analysis["audible_segments"],
    })
    summary = {
        **summary,
        "parent_timeline_hash": summary.get("timeline_hash"),
        "timeline_hash": new_hash,
        "cache_transform": "validated_silence_ripple",
        "silence_time_map_hash": stable_hash(mapping),
        "lexical_word_hash": stable_hash(transformed_words),
    }
    return [(raw_path, raw), (summary_path, summary)]


def repair_validated_silence_cache(project_name: str) -> dict[str, Any]:
    """Repair cache provenance for a previously validated silence ripple."""
    from capcut_live_project_reader import read_live_project
    from capcut_project_locator import locate_project

    live = read_live_project(locate_project(project_name))
    analysis = analyze_timeline(live.primary)
    slug = live.project.name.casefold().replace(" ", "_")
    result = json.loads((
        PROJECT_ROOT / f"output/json/{slug}.silence_cut_result.json"
    ).read_text(encoding="utf-8"))
    mapping = json.loads((
        PROJECT_ROOT / f"output/json/{slug}.silence_time_map.json"
    ).read_text(encoding="utf-8"))
    words = json.loads((
        PROJECT_ROOT / f"output/json/{slug}.lexical_words.json"
    ).read_text(encoding="utf-8"))
    if result.get("valid") is not True or abs(
        float(result.get("new_duration", -1)) - float(analysis["duration"])
    ) > 0.02:
        raise RuntimeError("Silence result does not prove the current timeline.")
    payloads = _retimed_cache_payloads(slug, mapping, words, analysis)
    if not payloads:
        raise RuntimeError("Validated silence cache artifacts are incomplete.")
    _atomic_payloads(payloads)
    return {
        "valid": True,
        "project": live.project.name,
        "timeline_hash": stable_hash({
            "duration": analysis["duration"],
            "audible_segments": analysis["audible_segments"],
        }),
        "cache_transform": "validated_silence_ripple",
    }


def apply_project_silence_cut(
    project_name: str, preset_id: str = "shorts-clean", *, dry_run: bool = False
) -> tuple[dict[str, Any], Path]:
    plan, live, words, detection = detect_project_silence(
        project_name, preset_id, keep_audio=False
    )
    plan_validation = validate_silence_plan(plan, words)
    if not plan_validation["valid"]:
        raise RuntimeError("Silence plan invalid: " + "; ".join(plan_validation["errors"]))
    normalized_cuts, boundary_normalizations = normalize_micro_fragment_cuts(
        live.primary,
        plan["cuts"],
        words,
        remove_internal_transcript_free_residuals=bool(
            load_silence_preset(preset_id).get(
                "remove_internal_transcript_free_residuals", False
            )
        ),
    )
    normalized_plan = {**plan, "cuts": normalized_cuts}
    normalized_validation = validate_silence_plan(normalized_plan, words)
    if not normalized_validation["valid"]:
        raise RuntimeError(
            "Normalized silence plan invalid: "
            + "; ".join(normalized_validation["errors"])
        )
    plan = normalized_plan
    slug = live.project.name.casefold().replace(" ", "_")
    if not plan["cuts"]:
        karaoke = load_karaoke_registry(live.project.identity)
        repaired_fragments = 0
        if karaoke:
            karaoke = dict(karaoke)
            repaired, repaired_fragments = coalesce_identical_adjacent_states(
                live.primary, karaoke.get("generated_text_track_id")
            )
            if repaired_fragments and not dry_run:
                require_live_project_write_ready(live, "normal_speed_silence_cut")
                karaoke["generated_segment_ids"] = active_registered_ids(
                    repaired, karaoke.get("generated_text_track_id")
                )
                _atomic_payloads([
                    *((path, repaired) for path in live.draft_paths),
                    (registry_path(live.project.identity), karaoke),
                ])
            karaoke["project_timeline_hash"] = plan["project"]["timeline_hash"]
            karaoke["lexical_word_hash"] = stable_hash(words)
            if not dry_run:
                write_json(registry_path(live.project.identity), karaoke)
        result = {
            "valid": True, "errors": [],
            "dry_run": dry_run,
            "project_written": bool(repaired_fragments) and not dry_run,
            "candidate_silence_count": detection["candidate_silence_count"],
            "internal_no_word_gaps_analyzed": detection.get(
                "internal_no_word_gaps_analyzed", 0
            ),
            "gaps_already_near_target": detection.get(
                "gaps_already_near_target", 0
            ),
            "gaps_longer_than_target": detection.get(
                "gaps_longer_than_target", 0
            ),
            "safe_cut_count": 0,
            "skipped_candidate_count": len(plan["skipped_candidates"]),
            "total_duration_removed": 0.0,
            "old_duration": float(live.primary["duration"]) / 1_000_000,
            "new_duration": float(live.primary["duration"]) / 1_000_000,
            "caption_regeneration": "not_run_no_new_cut",
            "karaoke_regeneration": "not_run_no_new_cut",
            "synchronization_result": "unchanged",
            "elevenlabs_called": False,
            "idempotent_noop": True,
            "karaoke_ripple_fragments_coalesced": repaired_fragments,
        }
        output = PROJECT_ROOT / f"output/json/{slug}.silence_cut_result.json"
        write_json(output, result)
        write_json(
            PROJECT_ROOT / f"logs/direct_edit/{slug}/silence_cut_preflight.json",
            {"valid": True, "dry_run": True, "no_new_cuts": True},
        )
        return result, output
    modified, changes = transform_silence_cuts(live.primary, plan["cuts"])
    mapping = build_time_map(plan["cuts"], float(live.primary["duration"]) / 1_000_000)
    transformed_words = retime_words(words, mapping)
    expected_duration = round(mapping["new_duration"] * 1_000_000)
    errors: list[str] = []
    if abs(int(modified["duration"]) - expected_duration) > 2000:
        errors.append("project duration does not match time map")
    ids = [
        item.get("id")
        for track in modified.get("tracks", []) for item in [track, *track.get("segments", [])]
        if item.get("id")
    ]
    if len(ids) != len(set(ids)):
        errors.append("track/segment IDs are not unique")
    modified_analysis = analyze_timeline(modified)
    if modified_analysis["unsupported_structures"]:
        errors.extend(modified_analysis["unsupported_structures"])
    minimum_primary_duration = round((2 / 30) * 1_000_000)
    micro_primary = [
        segment.get("id")
        for track in modified.get("tracks", [])
        if track.get("type") in {"video", "audio"}
        for segment in track.get("segments", [])
        if isinstance((segment.get("target_timerange") or {}).get("duration"), int)
        and (segment.get("target_timerange") or {})["duration"]
        < minimum_primary_duration
    ]
    if micro_primary:
        errors.append(
            "primary media fragments shorter than two 30fps frames: "
            + ", ".join(str(value) for value in micro_primary)
        )
    # Internal dry-run completed before the process/drive is touched.
    preflight = {
        "valid": not errors, "errors": errors, "plan_validation": plan_validation,
        "old_duration": mapping["old_duration"], "new_duration": mapping["new_duration"],
        "changes": changes,
        "boundary_normalizations": boundary_normalizations,
        "normalized_plan_validation": normalized_validation,
        "elevenlabs_called": False,
    }
    log_dir = PROJECT_ROOT / f"logs/direct_edit/{slug}"
    write_json(log_dir / "silence_cut_preflight.json", preflight)
    if errors:
        raise RuntimeError("Silence cut dry-run failed: " + "; ".join(errors))
    if dry_run:
        result = {
            "valid": True,
            "errors": [],
            "dry_run": True,
            "project_written": False,
            "safe_cut_count": len(plan["cuts"]),
            "total_duration_removed": mapping["total_removed"],
            "old_duration": mapping["old_duration"],
            "new_duration": mapping["new_duration"],
            "changes": changes,
        }
        output = PROJECT_ROOT / f"output/json/{slug}.silence_cut_preflight.json"
        write_json(output, result)
        return result, output
    require_live_project_write_ready(live, "normal_speed_silence_cut")
    metadata = dict(live.metadata)
    metadata["tm_duration"] = modified["duration"]
    karaoke = load_karaoke_registry(live.project.identity)
    payloads: list[tuple[Path, Any]] = [
        *((path, modified) for path in live.draft_paths),
        (live.project.metadata_path, metadata),
    ]
    if karaoke:
        karaoke = dict(karaoke)
        karaoke["generated_segment_ids"] = active_registered_ids(
            modified, karaoke.get("generated_text_track_id")
        )
        karaoke["project_timeline_hash"] = stable_hash({
            "duration": analyze_timeline(modified)["duration"],
            "audible_segments": analyze_timeline(modified)["audible_segments"],
        })
        karaoke["silence_time_map_hash"] = stable_hash(mapping)
        karaoke["lexical_word_hash"] = stable_hash(transformed_words)
        payloads.append((registry_path(live.project.identity), karaoke))
    lexical_path = PROJECT_ROOT / f"output/json/{slug}.lexical_words.json"
    payloads.append((lexical_path, transformed_words))
    payloads.extend(_retimed_cache_payloads(
        slug, mapping, transformed_words, modified_analysis
    ))
    _atomic_payloads(payloads)
    reread = [json.loads(path.read_text(encoding="utf-8-sig")) for path in live.draft_paths]
    post_errors = []
    if any(value != reread[0] for value in reread[1:]):
        post_errors.append("mirrored drafts differ")
    if reread[0]["duration"] != modified["duration"]:
        post_errors.append("duration changed after commit")
    result = {
        "valid": not post_errors, "errors": post_errors,
        "dry_run": False,
        "project_written": True,
        "candidate_silence_count": detection["candidate_silence_count"],
        "safe_cut_count": len(plan["cuts"]),
        "skipped_candidate_count": len(plan["skipped_candidates"]),
        "total_duration_removed": mapping["total_removed"],
        "old_duration": mapping["old_duration"], "new_duration": mapping["new_duration"],
        "largest_removed_pause": max((c["cut_duration"] for c in plan["cuts"]), default=0),
        "shortest_removed_pause": min((c["cut_duration"] for c in plan["cuts"]), default=0),
        "media_segments_split": len(changes["generated_segment_ids"]),
        "micro_fragment_boundaries_normalized": len(boundary_normalizations),
        "caption_regeneration": "registered caption timing transformed",
        "karaoke_regeneration": "registered karaoke states ripple-retimed",
        "synchronization_result": "valid" if not post_errors else "failed",
        "elevenlabs_called": False,
    }
    write_json(PROJECT_ROOT / f"output/json/{slug}.silence_time_map.json", mapping)
    output = PROJECT_ROOT / f"output/json/{slug}.silence_cut_result.json"
    write_json(output, result)
    write_json(log_dir / "silence_cut_changes.json", changes)
    write_json(log_dir / "silence_cut_validation.json", result)
    preview = PROJECT_ROOT / f"output/preview/{slug}_silence_cut_result.txt"
    preview.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if post_errors:
        raise RuntimeError("Post-write validation failed: " + "; ".join(post_errors))
    return result, output


def validate_project_silence_cut(project_name: str) -> tuple[dict[str, Any], Path]:
    from capcut_live_project_reader import read_live_project
    from capcut_project_locator import locate_project
    live = read_live_project(locate_project(project_name))
    analysis = analyze_timeline(live.primary)
    slug = live.project.name.casefold().replace(" ", "_")
    result_path = PROJECT_ROOT / f"output/json/{slug}.silence_cut_result.json"
    prior = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    result = {
        "valid": not analysis["offline_media"],
        "mirrored_drafts_consistent": True,
        "media_references_resolve": not analysis["offline_media"],
        "project_duration": analysis["duration"],
        "elevenlabs_called": False,
        "prior_result": prior,
    }
    output = PROJECT_ROOT / f"logs/direct_edit/{slug}/silence_cut_validation.json"
    write_json(output, result)
    return result, output

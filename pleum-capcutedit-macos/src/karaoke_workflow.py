"""End-to-end local karaoke plan, dry-run, apply, and validation workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_caption_registry import stable_hash
from caption_word_span_mapper import map_caption_word_spans
from capcut_karaoke_injector import apply_karaoke_transaction
from capcut_karaoke_registry import load_karaoke_registry
from capcut_karaoke_style_preset import load_karaoke_preset
from capcut_caption_style_preset import load_caption_style_preset
from capcut_karaoke_duplicate_detector import detect_karaoke_duplicate_layers
from capcut_live_project_reader import read_live_project
from capcut_project_locator import locate_project
from capcut_timeline_media_resolver import analyze_timeline
from karaoke_state_plan_builder import build_karaoke_state_plan
from karaoke_state_plan_validator import validate_karaoke_state_plan
from karaoke_state_plan_optimizer import optimize_karaoke_state_plan
from utils import PROJECT_ROOT, write_json


def _slug(name: str) -> str:
    return name.casefold().replace(" ", "_")


def _validated_lexical_cache(
    project_name: str,
    analysis: dict[str, Any],
    timeline_hash: str,
) -> tuple[list[dict[str, Any]], str]:
    slug = _slug(project_name)
    lexical_path = PROJECT_ROOT / f"output/json/{slug}.lexical_words.json"
    summary_path = PROJECT_ROOT / f"logs/direct_edit/{slug}/stt_summary.json"
    if not lexical_path.is_file() or not summary_path.is_file():
        raise RuntimeError(
            "No local lexical timestamp cache exists. An STT call would be required."
        )
    lexical = json.loads(lexical_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("timeline_hash") == timeline_hash:
        return lexical, "timeline_hash_matched_cache"
    karaoke_registry = load_karaoke_registry(
        locate_project(project_name).identity
    ) or {}
    silence_result_path = (
        PROJECT_ROOT / f"output/json/{slug}.silence_cut_result.json"
    )
    silence_result = (
        json.loads(silence_result_path.read_text(encoding="utf-8"))
        if silence_result_path.is_file() else {}
    )
    lexical_end = max(float(item["end"]) for item in lexical)
    if (
        karaoke_registry.get("silence_time_map_hash")
        and silence_result.get("valid") is True
        and abs(float(silence_result.get("new_duration", -1))
                - float(analysis["duration"])) <= .02
        and lexical_end <= float(analysis["duration"]) + .000001
    ):
        return lexical, "timeline_hash_matched_locally_retimed_cache"
    applied_path = PROJECT_ROOT / f"output/json/{slug}.applied_take_cut_report.json"
    approval_path = PROJECT_ROOT / f"output/json/{slug}.approved_take_cuts.json"
    if applied_path.is_file() and approval_path.is_file():
        applied = json.loads(applied_path.read_text(encoding="utf-8"))
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        audible_end = max(
            float(item["target_timerange"]["end"])
            for item in analysis["audible_segments"]
        )
        lexical_end = max(float(item["end"]) for item in lexical)
        if (
            applied.get("valid") is True
            and applied.get("project_written") is True
            and summary.get("timeline_hash") == approval.get("timeline_hash")
            and lexical_end <= audible_end + 0.000001
            and len(approval.get("cuts") or []) == 1
            and abs(
                int(applied["changes"]["new_duration"]) / 1_000_000
                - audible_end
            ) <= 0.02
        ):
            return lexical, "locally_retimed_after_validated_cut"
    raise RuntimeError(
        "Local lexical cache does not match the current timeline and cannot be "
        "proven as a validated local retime. STT would be required."
    )


def build_project_karaoke_plan(
    project_name: str,
    preset_id: str,
) -> tuple[dict[str, Any], dict[str, Any], Any, list[dict[str, Any]]]:
    project = locate_project(project_name)
    live = read_live_project(project)
    analysis = analyze_timeline(live.primary)
    timeline_hash = stable_hash({
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    })
    lexical, cache_status = _validated_lexical_cache(
        project.name, analysis, timeline_hash
    )
    slug = _slug(project.name)
    caption_path = (
        PROJECT_ROOT / f"output/json/{slug}.caption_plan.thai_normalized.json"
    )
    if not caption_path.is_file():
        raise FileNotFoundError(
            f"Validated Thai-normalized caption plan not found: {caption_path}"
        )
    caption_plan = json.loads(caption_path.read_text(encoding="utf-8"))
    mapped, mapping_stats = map_caption_word_spans(
        caption_plan["captions"], lexical
    )
    plan = build_karaoke_state_plan(
        project.name, timeline_hash, analysis["duration"], preset_id, mapped
    )
    plan, optimization = optimize_karaoke_state_plan(plan)
    validation = validate_karaoke_state_plan(plan)
    if not validation["valid"]:
        raise RuntimeError(
            "Karaoke state plan failed: " + "; ".join(validation["errors"])
        )
    metadata = {
        **validation,
        "timeline_cache_status": cache_status,
        "elevenlabs_called": False,
        "timeline_hash": timeline_hash,
        "lexical_word_hash": stable_hash(lexical),
        "mapping_stats": mapping_stats,
        "optimization": optimization,
    }
    write_json(PROJECT_ROOT / f"output/json/{slug}.karaoke_plan.json", plan)
    preview_lines: list[str] = []
    for index, cue in enumerate(plan["cues"], 1):
        preview_lines.extend([
            f"CAPTION {index:03d}",
            f"{cue['start']:.3f} --> {cue['end']:.3f}",
            cue["text"], "", "States:",
        ])
        for state in cue["states"]:
            label = (
                f"HIGHLIGHT: {state['active_word_text']}"
                if state["type"] == "highlight" else "NORMAL"
            )
            preview_lines.append(
                f"{state['start']:.3f}-{state['end']:.3f} {label}"
            )
        preview_lines.append("")
    preview = PROJECT_ROOT / f"output/preview/{slug}_karaoke_preview.txt"
    preview.write_text("\n".join(preview_lines), encoding="utf-8")
    return plan, metadata, live, lexical


def apply_project_karaoke(
    project_name: str, preset_id: str,
    *, base_caption_preset: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, Any], Path]:
    plan, metadata, live, lexical = build_project_karaoke_plan(
        project_name, preset_id
    )
    preset = load_karaoke_preset(preset_id)
    preset_fingerprint = preset["source"]["style_fingerprint"]
    log_dir = PROJECT_ROOT / f"logs/direct_edit/{_slug(project_name)}"
    dry = apply_karaoke_transaction(
        live, plan, metadata["lexical_word_hash"], preset_fingerprint,
        dry_run=True, base_caption_preset=base_caption_preset,
    )
    write_json(log_dir / "karaoke_preflight.json", {
        **metadata, "dry_run": dry,
    })
    if dry_run:
        output = (
            PROJECT_ROOT
            / f"output/json/{_slug(project_name)}.karaoke_application_preflight.json"
        )
        write_json(output, {**dry, **metadata})
        return dry, output
    result = apply_karaoke_transaction(
        live, plan, metadata["lexical_word_hash"], preset_fingerprint,
        dry_run=False, base_caption_preset=base_caption_preset,
    )
    write_json(log_dir / "karaoke_changes.json", result["changes"])
    output = PROJECT_ROOT / f"output/json/{_slug(project_name)}.karaoke_application_result.json"
    write_json(output, {**result, **metadata})
    return result, output


def validate_project_karaoke(project_name: str) -> dict[str, Any]:
    project = locate_project(project_name)
    live = read_live_project(project)
    registry = load_karaoke_registry(project.identity)
    errors: list[str] = []
    if registry is None:
        raise FileNotFoundError("No AI karaoke registry exists for project.")
    analysis = analyze_timeline(live.primary)
    current_hash = stable_hash({
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    })
    if registry.get("project_timeline_hash") != current_hash:
        errors.append("karaoke registry timeline hash is stale")
    track_ids = {item.get("id") for item in live.primary.get("tracks", [])}
    if registry.get("generated_text_track_id") not in track_ids:
        errors.append("registered karaoke track is missing")
    all_segments = {
        segment.get("id")
        for track in live.primary.get("tracks", [])
        for segment in track.get("segments", [])
    }
    all_materials = {
        item.get("id")
        for items in (live.primary.get("materials") or {}).values()
        if isinstance(items, list)
        for item in items if isinstance(item, dict)
    }
    if not set(registry.get("generated_segment_ids") or []).issubset(all_segments):
        errors.append("registered karaoke segments are missing")
    if not set(registry.get("generated_material_ids") or []).issubset(all_materials):
        errors.append("registered karaoke materials are missing")
    plan_path = PROJECT_ROOT / f"output/json/{_slug(project_name)}.karaoke_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    state_validation = validate_karaoke_state_plan(plan)
    errors.extend(state_validation["errors"])
    karaoke_preset = load_karaoke_preset(plan["preset"])
    base_preset = load_caption_style_preset(
        registry.get("base_caption_preset")
        or karaoke_preset["base_caption_preset"]
    )
    base_content = json.loads(base_preset["material_template"]["content"])
    base_style = (base_content.get("styles") or [None])[0]
    material_index = {
        item.get("id"): item
        for item in (live.primary.get("materials") or {}).get("texts", [])
    }
    karaoke_track = next(
        (
            track for track in live.primary.get("tracks", [])
            if track.get("id") == registry.get("generated_text_track_id")
        ),
        None,
    )
    flat_states = [
        (cue, state)
        for cue in plan["cues"]
        for state in cue["states"]
    ]
    highlight_color_valid = True
    style_fields_preserved = True
    if karaoke_track is None or len(karaoke_track.get("segments") or []) != len(flat_states):
        errors.append("karaoke track state segment count mismatch")
    else:
        for segment, (cue, state) in zip(karaoke_track["segments"], flat_states):
            material = material_index.get(segment.get("material_id"))
            if material is None:
                errors.append("karaoke state material reference does not resolve")
                continue
            comparable_material = {
                key: value for key, value in material.items()
                if key not in {"id", "content"}
            }
            comparable_base = {
                key: value for key, value in base_preset["material_template"].items()
                if key not in {"id", "content"}
            }
            if comparable_material != comparable_base:
                style_fields_preserved = False
            content = json.loads(material["content"])
            if content.get("text") != cue["text"]:
                errors.append("state text differs from its complete cue text")
            styles = content.get("styles") or []
            if state["type"] == "normal":
                if len(styles) != 1:
                    errors.append("normal state has mixed rich-text styles")
                elif {k: v for k, v in styles[0].items() if k != "range"} != {
                    k: v for k, v in base_style.items() if k != "range"
                }:
                    style_fields_preserved = False
            else:
                yellow = [
                    style for style in styles
                    if style.get("fill", {}).get("content", {})
                    .get("solid", {}).get("color")
                    == karaoke_preset["highlight"]["capcut_color_value"]
                ]
                if len(yellow) != 1:
                    highlight_color_valid = False
                    errors.append("highlight state does not contain exactly one yellow range")
                elif yellow:
                    yellow_comparable = {
                        key: value for key, value in yellow[0].items()
                        if key not in {"range", "fill"}
                    }
                    base_comparable = {
                        key: value for key, value in base_style.items()
                        if key not in {"range", "fill"}
                    }
                    if yellow_comparable != base_comparable:
                        style_fields_preserved = False
                expected_start = state["active_utf16_start"]
                expected_end = expected_start + state["active_utf16_length"]
                actual_range = yellow[0].get("range") if yellow else None
                valid_ends = {expected_end}
                if (
                    karaoke_preset["highlight"].get(
                        "range_includes_trailing_separator"
                    )
                    and actual_range
                ):
                    valid_ends.add(expected_end + 1)
                if (
                    not actual_range or actual_range[0] != expected_start
                    or actual_range[1] not in valid_ends
                ):
                    errors.append("highlight material range differs from active word")
    if not style_fields_preserved:
        errors.append("karaoke changed non-color caption style fields")
    rediscovered = locate_project(project.name)
    report = {
        "valid": not errors, "errors": errors,
        "mirrored_drafts_consistent": len(live.drafts) == 2 and live.drafts[0] == live.drafts[1],
        "project_remains_discoverable": rediscovered.path == project.path,
        "project_duration": analysis["duration"],
        "timeline_hash_current": current_hash,
        "registered_segment_count": len(registry.get("generated_segment_ids") or []),
        "state_plan_validation": state_validation,
        "highlight_color_valid": highlight_color_valid,
        "style_fields_preserved": style_fields_preserved,
        "duration_unchanged": abs(
            float(plan["project"]["duration"]) - float(analysis["duration"])
        ) <= 0.000001,
    }
    write_json(
        PROJECT_ROOT / f"logs/direct_edit/{_slug(project_name)}/karaoke_validation.json",
        report,
    )
    return report


def repair_project_karaoke_duplicates(
    project_name: str,
) -> tuple[dict[str, Any], Path]:
    project = locate_project(project_name)
    current_live = read_live_project(project)
    slug = _slug(project.name)
    existing_plan = json.loads(
        (PROJECT_ROOT / f"output/json/{slug}.karaoke_plan.json").read_text(
            encoding="utf-8"
        )
    )
    before = detect_karaoke_duplicate_layers(current_live, existing_plan)
    duration_before = float(current_live.primary.get("duration") or 0) / 1_000_000
    plan, metadata, live, lexical = build_project_karaoke_plan(
        project.name, existing_plan["preset"]
    )
    preset = load_karaoke_preset(plan["preset"])
    dry = apply_karaoke_transaction(
        live, plan, metadata["lexical_word_hash"],
        preset["source"]["style_fingerprint"], dry_run=True,
    )
    log_dir = PROJECT_ROOT / f"logs/direct_edit/{slug}"
    write_json(log_dir / "karaoke_repair_preflight.json", {
        "valid": dry["valid"],
        "duplicate_detection": before,
        "optimization": metadata["optimization"],
        "dry_run": dry,
        "elevenlabs_called": False,
    })
    applied = apply_karaoke_transaction(
        live, plan, metadata["lexical_word_hash"],
        preset["source"]["style_fingerprint"], dry_run=False,
    )
    after_live = read_live_project(locate_project(project.name))
    after = detect_karaoke_duplicate_layers(after_live, plan)
    independent = validate_project_karaoke(project.name)
    duration_after = float(after_live.primary.get("duration") or 0) / 1_000_000
    result = {
        "valid": (
            applied["valid"] and independent["valid"]
            and after["duplicate_layer_count"] == 0
        ),
        "duplicate_track_count_before": before["duplicate_track_pair_count"],
        "duplicate_overlap_count_before": before["duplicate_layer_count"],
        "duplicate_track_count_after": after["duplicate_track_pair_count"],
        "duplicate_overlap_count_after": after["duplicate_layer_count"],
        "removed_base_segment_count": len(
            applied["changes"]["replaced_base_segment_ids"]
        ),
        "removed_material_count": len(
            applied["changes"]["removed_base_material_ids"]
        ) + applied["changes"]["removed_previous_karaoke_material_count"],
        "removed_track_id": applied["changes"]["removed_base_track_id"],
        "removed_orphan_karaoke_lineage_track_ids": applied["changes"][
            "removed_orphan_karaoke_lineage_track_ids"
        ],
        "preserved_manual_caption_count": sum(
            len(track.get("segments") or [])
            for track in after_live.primary.get("tracks", [])
            if track.get("type") == "text"
            and track.get("id")
            != applied["generated"]["generated_text_track_id"]
        ),
        "karaoke_state_count": len(applied["generated"]["generated_segment_ids"]),
        "micro_states_optimized": metadata["optimization"][
            "micro_normal_states_removed"
        ],
        "project_duration_before": duration_before,
        "project_duration_after": duration_after,
        "elevenlabs_called": False,
        "changes": applied["changes"],
        "validation": independent,
    }
    if not result["valid"]:
        raise RuntimeError("Karaoke duplicate repair post-validation failed.")
    output = PROJECT_ROOT / f"output/json/{slug}.karaoke_repair_result.json"
    write_json(output, result)
    write_json(log_dir / "karaoke_repair_changes.json", applied["changes"])
    write_json(log_dir / "karaoke_repair_validation.json", result)
    preview = [
        "KARAOKE DUPLICATE REPAIR",
        "",
        f"Duplicate track pairs before: {result['duplicate_track_count_before']}",
        f"Duplicate overlaps before: {result['duplicate_overlap_count_before']}",
        f"Duplicate track pairs after: {result['duplicate_track_count_after']}",
        f"Duplicate overlaps after: {result['duplicate_overlap_count_after']}",
        f"Removed base segments: {result['removed_base_segment_count']}",
        f"Removed materials: {result['removed_material_count']}",
        f"Removed base track: {result['removed_track_id']}",
        f"Removed orphan lineage tracks: {result['removed_orphan_karaoke_lineage_track_ids']}",
        f"Preserved manual captions: {result['preserved_manual_caption_count']}",
        f"Karaoke states: {result['karaoke_state_count']}",
        f"Micro states optimized: {result['micro_states_optimized']}",
        f"Duration: {duration_before:.6f} -> {duration_after:.6f}",
        "ElevenLabs called: NO",
        "Validation: PASS",
    ]
    preview_path = PROJECT_ROOT / f"output/preview/{slug}_karaoke_repair.txt"
    preview_path.write_text("\n".join(preview) + "\n", encoding="utf-8")
    return result, output

"""Atomic direct karaoke injection with same-process rollback."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ai_caption_registry import (
    load_registry, registry_path as caption_registry_path, stable_hash,
)
from capcut_caption_style_preset import load_caption_style_preset
from capcut_direct_editor import _remove_registered
from capcut_karaoke_id_factory import CapCutKaraokeIdFactory
from capcut_write_guard import require_live_project_write_ready
from capcut_karaoke_registry import (
    load_karaoke_registry, registry_path, write_karaoke_registry,
)
from capcut_karaoke_style_preset import (
    apply_highlight_range, load_karaoke_preset,
)
from capcut_live_project_reader import LiveProject
from capcut_project_validator import all_object_ids
from karaoke_state_plan_validator import validate_karaoke_state_plan
from caption_state_template_validator import validate_state_template_consistency
from utils import write_json


def _build(
    baseline: dict[str, Any],
    plan: dict[str, Any],
    project_identity: str,
    base_caption_preset: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    old_karaoke = load_karaoke_registry(project_identity) or {}
    old_caption = load_registry(project_identity) or {}
    old_karaoke_segment_ids = set(
        old_karaoke.get("generated_segment_ids") or []
    )
    old_caption_segment_ids = set(
        old_caption.get("generated_segment_ids") or []
    )
    baseline_segments = {
        segment.get("id")
        for track in baseline.get("tracks", [])
        for segment in track.get("segments", [])
    }
    baseline_materials = {
        item.get("id")
        for items in (baseline.get("materials") or {}).values()
        if isinstance(items, list)
        for item in items if isinstance(item, dict)
    }
    lineage_empty_track_ids = {
        track.get("id")
        for track in baseline.get("tracks", [])
        if track.get("type") == "text"
        and track.get("segments")
        and all(
            segment.get("id") in old_karaoke_segment_ids
            for segment in track.get("segments") or []
        )
    }
    cleaned = _remove_registered(baseline, old_karaoke)
    cleaned = _remove_registered(cleaned, old_caption)
    remaining_references = {
        segment.get("material_id")
        for track in cleaned.get("tracks", [])
        for segment in track.get("segments", [])
        if segment.get("material_id")
    }
    for collection, original_items in (baseline.get("materials") or {}).items():
        if not isinstance(original_items, list):
            continue
        current_items = cleaned.setdefault("materials", {}).setdefault(
            collection, []
        )
        current_ids = {
            item.get("id") for item in current_items if isinstance(item, dict)
        }
        for item in original_items:
            if (
                isinstance(item, dict)
                and item.get("id") in remaining_references
                and item.get("id") not in current_ids
            ):
                current_items.append(deepcopy(item))
                current_ids.add(item.get("id"))
    cleaned["tracks"] = [
        track for track in cleaned.get("tracks", [])
        if not (
            track.get("id") in lineage_empty_track_ids
            and not track.get("segments")
        )
    ]
    base_preset = (
        deepcopy(base_caption_preset)
        if base_caption_preset is not None
        else load_caption_style_preset("system-default")
    )
    karaoke_preset = load_karaoke_preset(plan["preset"])
    modified = deepcopy(cleaned)
    factory = CapCutKaraokeIdFactory(set(all_object_ids(baseline)))
    track = deepcopy(base_preset["track_template"])
    track_id = factory.new()
    track["id"] = track_id
    track["segments"] = []
    segment_ids: list[str] = []
    material_ids: list[str] = []
    auxiliary_ids: list[str] = []
    state_material_map: dict[str, str] = {}
    for cue in plan["cues"]:
        for state in cue["states"]:
            material = deepcopy(base_preset["material_template"])
            material_id = factory.new()
            material["id"] = material_id
            content = json.loads(material["content"])
            content["text"] = cue["text"]
            content = apply_highlight_range(
                content,
                state["active_utf16_start"] if state["type"] == "highlight" else None,
                state["active_utf16_length"] if state["type"] == "highlight" else None,
                karaoke_preset,
            )
            material["content"] = json.dumps(
                content, ensure_ascii=False, separators=(",", ":")
            )
            segment = deepcopy(base_preset["segment_style_template"])
            segment_id = factory.new()
            segment["id"] = segment_id
            segment["material_id"] = material_id
            start = round(float(state["start"]) * 1_000_000)
            duration = round((float(state["end"]) - float(state["start"])) * 1_000_000)
            segment["target_timerange"] = {"start": start, "duration": duration}
            if "source_timerange" in segment:
                segment["source_timerange"] = None
            if "render_timerange" in segment:
                segment["render_timerange"] = {"start": start, "duration": duration}
            refs: list[str] = []
            for record in base_preset.get("auxiliary_material_templates") or []:
                auxiliary = deepcopy(record["template"])
                auxiliary_id = factory.new()
                auxiliary["id"] = auxiliary_id
                modified["materials"].setdefault(record["collection"], []).append(
                    auxiliary
                )
                refs.append(auxiliary_id)
                auxiliary_ids.append(auxiliary_id)
            segment["extra_material_refs"] = refs
            track["segments"].append(segment)
            modified["materials"].setdefault("texts", []).append(material)
            segment_ids.append(segment_id)
            material_ids.append(material_id)
            state_material_map[state["state_id"]] = material_id
    modified["tracks"].append(track)
    generated = {
        "generated_text_track_id": track_id,
        "generated_segment_ids": segment_ids,
        "generated_material_ids": material_ids,
        "generated_auxiliary_material_ids": auxiliary_ids,
    }
    changes = {
        "karaoke_track_added": 1,
        "state_segments_added": len(segment_ids),
        "state_materials_added": len(material_ids),
        "state_material_map": state_material_map,
        "replaced_base_segment_ids": sorted(
            old_caption_segment_ids & baseline_segments
        ),
        "removed_base_material_ids": sorted(
            set(old_caption.get("generated_material_ids") or [])
            & baseline_materials
            - remaining_references
        ),
        "removed_base_track_id": (
            old_caption.get("generated_text_track_id")
            if any(
                track.get("id") == old_caption.get("generated_text_track_id")
                for track in baseline.get("tracks", [])
            ) else None
        ),
        "removed_orphan_karaoke_lineage_track_ids": sorted(
            lineage_empty_track_ids
        ),
        "removed_previous_karaoke_segment_count": len(
            old_karaoke_segment_ids & baseline_segments
        ),
        "removed_previous_karaoke_material_count": len(
            set(old_karaoke.get("generated_material_ids") or [])
            & baseline_materials
            - remaining_references
        ),
    }
    return modified, generated, changes


def _validate_modified(
    modified: dict[str, Any],
    baseline: dict[str, Any],
    plan: dict[str, Any],
    generated: dict[str, Any],
    project_identity: str,
    base_caption_preset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    state_validation = validate_karaoke_state_plan(plan)
    errors.extend(state_validation["errors"])
    if modified.get("duration") != baseline.get("duration"):
        errors.append("project duration changed")
    baseline_non_text = [
        track for track in baseline.get("tracks", []) if track.get("type") != "text"
    ]
    modified_non_text = [
        track for track in modified.get("tracks", []) if track.get("type") != "text"
    ]
    if modified_non_text != baseline_non_text:
        errors.append("video/audio/non-text tracks changed")
    old_karaoke_validation = load_karaoke_registry(project_identity) or {}
    old_karaoke_ids_validation = set(
        old_karaoke_validation.get("generated_segment_ids") or []
    )
    lineage_tracks_validation = {
        track.get("id")
        for track in baseline.get("tracks", [])
        if track.get("type") == "text"
        and track.get("segments")
        and all(
            segment.get("id") in old_karaoke_ids_validation
            for segment in track.get("segments") or []
        )
    }
    cleaned = _remove_registered(baseline, old_karaoke_validation)
    cleaned = _remove_registered(cleaned, load_registry(project_identity))
    cleaned["tracks"] = [
        track for track in cleaned.get("tracks", [])
        if not (
            track.get("id") in lineage_tracks_validation
            and not track.get("segments")
        )
    ]
    manual_before = [
        track for track in cleaned.get("tracks", []) if track.get("type") == "text"
    ]
    generated_track_id = generated["generated_text_track_id"]
    manual_after = [
        track for track in modified.get("tracks", [])
        if track.get("type") == "text" and track.get("id") != generated_track_id
    ]
    if manual_before != manual_after:
        errors.append("manual text tracks changed")
    all_ids = set(all_object_ids(modified))
    generated_ids = {
        generated_track_id,
        *generated["generated_segment_ids"],
        *generated["generated_material_ids"],
        *generated["generated_auxiliary_material_ids"],
    }
    if not generated_ids.issubset(all_ids):
        errors.append("generated IDs/material references do not resolve")
    text_materials = {
        item.get("id"): item
        for item in modified.get("materials", {}).get("texts", [])
    }
    karaoke_track = next(
        track for track in modified["tracks"] if track.get("id") == generated_track_id
    )
    for segment in karaoke_track["segments"]:
        if segment.get("material_id") not in text_materials:
            errors.append("segment.material_id does not resolve exactly once")
    if (
        base_caption_preset is not None
        and base_caption_preset.get("runtime_caption_layout")
    ):
        horizontal = validate_state_template_consistency(
            [
                text_materials[material_id]
                for material_id in generated["generated_material_ids"]
                if material_id in text_materials
            ],
            karaoke_track["segments"],
            base_caption_preset,
        )
        errors.extend(horizontal["errors"])
    return {
        "valid": not errors, "errors": errors,
        "state_plan_validation": state_validation,
        "duration_unchanged": modified.get("duration") == baseline.get("duration"),
        "non_text_tracks_unchanged": modified_non_text == baseline_non_text,
        "manual_text_tracks_unchanged": manual_before == manual_after,
        "references_resolve": not any("resolve" in error for error in errors),
    }


def apply_karaoke_transaction(
    live: LiveProject,
    plan: dict[str, Any],
    lexical_hash: str,
    preset_fingerprint: str,
    *,
    dry_run: bool = False,
    base_caption_preset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    originals = {path: path.read_bytes() for path in live.draft_paths}
    registry_file = registry_path(live.project.identity)
    registry_original = (
        registry_file.read_bytes() if registry_file.is_file() else None
    )
    caption_registry_file = caption_registry_path(live.project.identity)
    caption_registry_original = (
        caption_registry_file.read_bytes()
        if caption_registry_file.is_file() else None
    )
    modified, generated, changes = _build(
        live.primary, plan, live.project.identity, base_caption_preset
    )
    validation = _validate_modified(
        modified, live.primary, plan, generated, live.project.identity,
        base_caption_preset,
    )
    if not validation["valid"]:
        raise RuntimeError("Karaoke preflight failed: " + "; ".join(validation["errors"]))
    if dry_run:
        return {
            "valid": True, "dry_run": True, "validation": validation,
            "generated": generated, "changes": changes,
        }
    require_live_project_write_ready(live, "karaoke_direct_write")
    temporary_paths: list[Path] = []
    try:
        for path in live.draft_paths:
            temporary = path.with_name(path.name + ".ai_karaoke.tmp")
            temporary.write_text(
                json.dumps(modified, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            if json.loads(temporary.read_text(encoding="utf-8")) != modified:
                raise RuntimeError("Temporary karaoke JSON parse-back mismatch.")
            temporary_paths.append(temporary)
        for path, temporary in zip(live.draft_paths, temporary_paths):
            temporary.replace(path)
        parsed = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in live.draft_paths
        ]
        if any(value != modified for value in parsed):
            raise RuntimeError("Mirrored karaoke drafts differ after write.")
        post_write_validation = _validate_modified(
            parsed[0], live.primary, plan, generated, live.project.identity,
            base_caption_preset,
        )
        if not post_write_validation["valid"]:
            raise RuntimeError(
                "Karaoke post-write validation failed: "
                + "; ".join(post_write_validation["errors"])
            )
        registry_value = {
            "project_identity": live.project.identity,
            "project_path": str(live.project.path),
            "project_timeline_hash": plan["project"]["timeline_hash"],
            **generated,
            "caption_plan_hash": stable_hash(plan["cues"]),
            "lexical_word_hash": lexical_hash,
            "preset_fingerprint": preset_fingerprint,
            "base_caption_preset": (
                (base_caption_preset or {}).get("preset_id")
                or karaoke_preset["base_caption_preset"]
            ),
            "replaced_base_segment_ids": changes["replaced_base_segment_ids"],
            "removed_base_material_ids": changes["removed_base_material_ids"],
            "removed_base_track_id": changes["removed_base_track_id"],
            "cue_coverage": [
                {
                    "caption_id": cue["caption_id"],
                    "start": cue["start"], "end": cue["end"],
                    "state_count": len(cue["states"]),
                }
                for cue in plan["cues"]
            ],
        }
        registry_written = write_karaoke_registry(
            live.project.identity, registry_value
        )
        caption_registry = load_registry(live.project.identity) or {
            "project_identity": live.project.identity,
            "project_path": str(live.project.path),
        }
        write_json(caption_registry_file, {
            **caption_registry,
            "status": "replaced_by_karaoke",
            "replacement_registry": "ai_karaoke.json",
            "generated_text_track_id": None,
            "generated_segment_ids": [],
            "generated_material_ids": [],
            "generated_auxiliary_material_ids": [],
            "replaced_segment_ids": (
                caption_registry.get("generated_segment_ids") or []
            ),
        })
        return {
            "valid": True, "dry_run": False, "validation": validation,
            "post_write_validation": post_write_validation,
            "generated": generated, "changes": changes,
            "registry_path": str(registry_written),
        }
    except Exception:
        for path, content in originals.items():
            path.write_bytes(content)
        if registry_original is None:
            registry_file.unlink(missing_ok=True)
        else:
            registry_file.write_bytes(registry_original)
        if caption_registry_original is None:
            caption_registry_file.unlink(missing_ok=True)
        else:
            caption_registry_file.write_bytes(caption_registry_original)
        raise
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)

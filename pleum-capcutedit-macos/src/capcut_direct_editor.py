"""Transaction-safe direct caption writes with in-memory rollback."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ai_caption_registry import load_registry, stable_hash, write_registry
from capcut_caption_style_preset import (
    render_learned_templates, resolve_caption_style,
)
from capcut_live_project_reader import LiveProject
from capcut_project_validator import all_object_ids, validate_injected_data, video_signature
from capcut_write_guard import require_live_project_write_ready


def _remove_registered(data: dict[str, Any], registry: dict[str, Any] | None) -> dict[str, Any]:
    modified = deepcopy(data)
    if not registry:
        return modified
    track_id = registry.get("generated_text_track_id")
    segment_ids = set(registry.get("generated_segment_ids") or [])
    material_ids = set(registry.get("generated_material_ids") or [])
    auxiliary_ids = set(registry.get("generated_auxiliary_material_ids") or [])
    modified["tracks"] = [
        track for track in modified.get("tracks", [])
        if track.get("id") != track_id
    ]
    for track in modified.get("tracks", []):
        track["segments"] = [
            segment for segment in track.get("segments", [])
            if segment.get("id") not in segment_ids
        ]
    for collection, items in (modified.get("materials") or {}).items():
        if isinstance(items, list):
            modified["materials"][collection] = [
                item for item in items
                if item.get("id") not in material_ids | auxiliary_ids
            ]
    return modified


def _direct_build(
    baseline: dict[str, Any],
    plan: dict[str, Any],
    registry: dict[str, Any] | None,
    caption_style_preset: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cleaned = _remove_registered(baseline, registry)
    manual_text_tracks = [
        track for track in cleaned.get("tracks", []) if track.get("type") == "text"
    ]
    # The proven builder requires a no-text baseline. Build into a temporary
    # copy, then restore manual tracks/materials untouched.
    build_base = deepcopy(cleaned)
    build_base["tracks"] = [
        track for track in build_base.get("tracks", []) if track.get("type") != "text"
    ]
    existing_texts = deepcopy(build_base.get("materials", {}).get("texts", []))
    build_base.setdefault("materials", {})["texts"] = []
    if caption_style_preset is None:
        _preset_id, caption_style_preset = resolve_caption_style(
            None, plan["captions"]
        )
    modified, generated, changes = render_learned_templates(
        build_base, plan["captions"], caption_style_preset
    )
    new_track = next(track for track in modified["tracks"] if track.get("id") == generated["track_id"])
    modified["tracks"] = [
        track for track in cleaned.get("tracks", []) if track.get("type") != "text"
    ] + manual_text_tracks + [new_track]
    new_text_ids = set(generated["material_ids"])
    generated_texts = [
        item for item in modified["materials"]["texts"]
        if item.get("id") in new_text_ids
    ]
    modified["materials"]["texts"] = existing_texts + generated_texts
    return modified, generated, changes


def edit_captions_direct(
    live: LiveProject,
    plan: dict[str, Any],
    timeline_signature: Any,
    caption_style_preset: dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    registry = load_registry(live.project.identity)
    originals = {path: path.read_bytes() for path in live.draft_paths}
    baseline = live.primary
    cleaned = _remove_registered(baseline, registry)
    modified, generated, changes = _direct_build(
        baseline, plan, registry, caption_style_preset
    )
    generated_id_set = {
        generated["track_id"],
        *generated["segment_ids"],
        *generated["material_ids"],
        *generated["auxiliary_material_ids"],
    }
    if generated_id_set.intersection(all_object_ids(cleaned)):
        raise RuntimeError("Generated ID collision with an existing live-project object.")
    if video_signature(modified) != video_signature(baseline):
        raise RuntimeError("Direct edit preflight changed video structure.")
    temporary_paths: list[Path] = []
    try:
        # Reuse strict schema checks on an isolated view of the generated
        # track/materials while manual text objects stay present and untouched
        # in the actual modified project.
        isolated_baseline = deepcopy(cleaned)
        isolated_baseline["tracks"] = [
            track for track in isolated_baseline.get("tracks", [])
            if track.get("type") != "text"
        ]
        isolated_baseline.setdefault("materials", {})["texts"] = []
        isolated_modified = deepcopy(modified)
        isolated_modified["tracks"] = [
            track for track in isolated_modified.get("tracks", [])
            if track.get("type") != "text" or track.get("id") == generated["track_id"]
        ]
        generated_material_ids = set(generated["material_ids"])
        isolated_modified.setdefault("materials", {})["texts"] = [
            material for material in isolated_modified["materials"].get("texts", [])
            if material.get("id") in generated_material_ids
        ]
        validation = validate_injected_data(
            isolated_modified, isolated_baseline, plan, generated
        )
        manual_tracks_before = [
            track for track in cleaned.get("tracks", []) if track.get("type") == "text"
        ]
        manual_tracks_after = [
            track for track in modified.get("tracks", [])
            if track.get("type") == "text" and track.get("id") != generated["track_id"]
        ]
        if manual_tracks_after != manual_tracks_before:
            validation["errors"].append("manual caption tracks changed")
            validation["valid"] = False
        if not validation["valid"]:
            raise RuntimeError(
                "Direct injection preflight failed: " + "; ".join(validation["errors"])
            )
        if dry_run:
            return {
                "valid": True,
                "dry_run": True,
                "project_written": False,
                "changes": changes,
                "validation": validation,
                "generated_ids": generated,
                "caption_plan_hash": stable_hash(plan),
            }
        require_live_project_write_ready(live, "neutral_caption_injection")
        for path in live.draft_paths:
            temporary = path.with_name(path.name + ".ai_caption.tmp")
            temporary.write_text(
                json.dumps(modified, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            parsed = json.loads(temporary.read_text(encoding="utf-8"))
            if parsed != modified:
                raise RuntimeError(f"Temporary parse-back mismatch: {temporary}")
            temporary_paths.append(temporary)
        for path, temporary in zip(live.draft_paths, temporary_paths):
            temporary.replace(path)
        post = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in live.draft_paths
        ]
        if any(item != modified for item in post):
            raise RuntimeError("Post-write mirrored draft mismatch.")
        registry_path = write_registry(
            live.project.identity, live.project.path, generated, plan,
            timeline_signature,
        )
        return {
            "valid": True,
            "dry_run": False,
            "project_written": True,
            "changes": changes,
            "validation": validation,
            "generated_ids": generated,
            "registry_path": str(registry_path),
            "caption_plan_hash": stable_hash(plan),
        }
    except Exception:
        for path, original in originals.items():
            path.write_bytes(original)
        raise
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)

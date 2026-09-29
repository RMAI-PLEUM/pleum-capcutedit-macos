"""Validated caption injection into the cloned sandbox project only."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from capcut_id_factory import CapCutIdFactory
from capcut_project_cloner import (
    SANDBOX, SOURCE, clone_for_injection, clone_project, sandbox_path,
)
from capcut_project_validator import (
    all_object_ids, draft_paths, load_json, validate_injected_data,
    verify_fixture_hashes,
)
from utils import PROJECT_ROOT, token_count, write_json


TEST_CAPTIONS = [
    {"start": 1.000, "end": 3.000, "text": "ทดสอบระบบอัตโนมัติ"},
    {"start": 4.000, "end": 6.000, "text": "กำลังเพิ่มซับลง CapCut"},
    {"start": 7.000, "end": 10.000, "text": "โดยไม่แก้โปรเจกต์ต้นฉบับ"},
]


def injection_plan() -> dict[str, Any]:
    return {
        "version": 1,
        "sandbox_only": True,
        "source_fixture": str(SOURCE),
        "sandbox_destination": str(SANDBOX),
        "time_scale": 1_000_000,
        "template_fixture": str(
            PROJECT_ROOT / "sample_capcut_projects" / "02_one_caption"
        ),
        "captions": TEST_CAPTIONS,
    }


def _latest_draft(folder: Path) -> dict[str, Any]:
    paths = sorted(draft_paths(folder), key=lambda path: path.stat().st_mtime)
    if not paths:
        raise FileNotFoundError(f"No active CapCut draft payload in {folder}")
    return load_json(paths[-1])


def _update_ranges(value: Any, utf16_length: int) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "range" and isinstance(item, list) and len(item) == 2:
                value[key] = [0, utf16_length]
            else:
                _update_ranges(item, utf16_length)
    elif isinstance(value, list):
        for item in value:
            _update_ranges(item, utf16_length)


def _build_modified(
    baseline: dict[str, Any],
    template: dict[str, Any],
    captions: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    captions = captions or TEST_CAPTIONS
    text_tracks = [track for track in template["tracks"] if track.get("type") == "text"]
    template_materials = template.get("materials", {}).get("texts", [])
    if len(text_tracks) != 1 or len(text_tracks[0].get("segments", [])) != 1:
        raise RuntimeError("Schema 02 must contain exactly one template caption segment.")
    if len(template_materials) != 1:
        raise RuntimeError("Schema 02 must contain exactly one text material.")
    template_segment = text_tracks[0]["segments"][0]
    template_material = template_materials[0]
    content = json.loads(template_material["content"])
    template_text = content.get("text", "")
    template_length = len(template_text.encode("utf-16-le")) // 2
    ranges = [style.get("range") for style in content.get("styles", [])]
    if not ranges or any(value != [0, template_length] for value in ranges):
        raise RuntimeError(
            "Schema 02 rich-text ranges do not match the template Thai UTF-16 length."
        )

    forbidden = set(all_object_ids(baseline)) | set(all_object_ids(template))
    factory = CapCutIdFactory(forbidden)
    track_id = factory.new()
    segment_ids, material_ids, auxiliary_ids = [], [], []
    modified = deepcopy(baseline)
    if any(track.get("type") == "text" for track in modified.get("tracks", [])):
        raise RuntimeError("Cloned Schema 01 unexpectedly already contains a text track.")
    modified.setdefault("materials", {}).setdefault("texts", [])
    new_track = deepcopy(text_tracks[0])
    new_track["id"] = track_id
    new_track["segments"] = []

    template_material_index = {
        item.get("id"): (collection, item)
        for collection, items in template.get("materials", {}).items()
        if isinstance(items, list)
        for item in items
        if isinstance(item, dict) and item.get("id")
    }
    for caption in captions:
        segment_id, material_id = factory.new(), factory.new()
        segment_ids.append(segment_id)
        material_ids.append(material_id)
        material = deepcopy(template_material)
        material["id"] = material_id
        material_content = json.loads(material["content"])
        material_content["text"] = caption["text"]
        length = len(caption["text"].encode("utf-16-le")) // 2
        _update_ranges(material_content.get("styles", []), length)
        material["content"] = json.dumps(
            material_content, ensure_ascii=False, separators=(",", ":")
        )
        segment = deepcopy(template_segment)
        segment["id"] = segment_id
        segment["material_id"] = material_id
        start = round(caption["start"] * 1_000_000)
        duration = round((caption["end"] - caption["start"]) * 1_000_000)
        segment["target_timerange"] = {"start": start, "duration": duration}
        if isinstance(segment.get("source_timerange"), dict):
            segment["source_timerange"] = {"start": start, "duration": duration}
        if isinstance(segment.get("render_timerange"), dict):
            segment["render_timerange"] = {"start": start, "duration": duration}
        new_refs = []
        for old_ref in segment.get("extra_material_refs", []):
            if old_ref not in template_material_index:
                raise RuntimeError(f"Unresolved Schema 02 auxiliary reference: {old_ref}")
            collection, auxiliary_template = template_material_index[old_ref]
            auxiliary_id = factory.new()
            auxiliary_ids.append(auxiliary_id)
            auxiliary = deepcopy(auxiliary_template)
            auxiliary["id"] = auxiliary_id
            modified["materials"].setdefault(collection, []).append(auxiliary)
            new_refs.append(auxiliary_id)
        segment["extra_material_refs"] = new_refs
        modified["materials"]["texts"].append(material)
        new_track["segments"].append(segment)
    modified["tracks"].append(new_track)
    generated = {
        "track_id": track_id,
        "segment_ids": segment_ids,
        "material_ids": material_ids,
        "auxiliary_material_ids": auxiliary_ids,
    }
    changes = {
        "tracks_added": 1,
        "caption_segments_added": len(captions),
        "text_materials_added": len(captions),
        "auxiliary_materials_added": len(auxiliary_ids),
        "video_changed": False,
        "duration_changed": False,
        "changed_fields": [
            "new IDs", "caption text", "target start", "target duration",
            "text-length-dependent rich-text ranges",
        ],
    }
    return modified, generated, changes


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".caption_injection.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    parsed = load_json(temporary)
    if parsed != data:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Atomic write parse-back mismatch: {path}")
    temporary.replace(path)


def _restore_complete_backup(backup: Path, sandbox: Path = SANDBOX) -> None:
    if sandbox.parent != PROJECT_ROOT / "sandbox_capcut_projects":
        raise RuntimeError("Unsafe sandbox restore target.")
    if sandbox.exists():
        shutil.rmtree(sandbox)
    shutil.copytree(backup, sandbox, copy_function=shutil.copy2)


def inject_caption_test() -> dict[str, Any]:
    plan = injection_plan()
    write_json(PROJECT_ROOT / "output/json/caption_injection_test_plan.json", plan)
    fixture_before = verify_fixture_hashes()
    if not fixture_before["valid"]:
        raise RuntimeError("Original fixture hash validation failed before cloning.")
    sandbox, backup, archived = clone_for_injection()
    paths = draft_paths(sandbox)
    if len(paths) != 2:
        raise RuntimeError(f"Expected two sandbox draft mirrors, found {len(paths)}")
    baselines = {str(path): load_json(path) for path in paths}
    if baselines[str(paths[0])] != baselines[str(paths[1])]:
        raise RuntimeError("Sandbox draft JSON copies differ before injection.")
    template = _latest_draft(
        PROJECT_ROOT / "sample_capcut_projects" / "02_one_caption"
    )
    modified, generated, changes = _build_modified(baselines[str(paths[0])], template)
    preflight_results = [
        validate_injected_data(modified, baseline, plan, generated)
        for baseline in baselines.values()
    ]
    preflight = {
        "valid": all(item["valid"] for item in preflight_results),
        "sandbox": str(sandbox),
        "backup": str(backup),
        "archived_previous_sandbox": str(archived) if archived else None,
        "draft_paths": [str(path) for path in paths],
        "template_range_validated_as_utf16": True,
        "results": preflight_results,
    }
    write_json(PROJECT_ROOT / "logs/caption_injection_preflight.json", preflight)
    write_json(PROJECT_ROOT / "logs/caption_injection_generated_ids.json", generated)
    write_json(PROJECT_ROOT / "logs/caption_injection_changes.json", changes)
    if not preflight["valid"]:
        raise RuntimeError("Caption injection preflight failed; sandbox was not written.")
    try:
        for path in paths:
            _atomic_write_json(path, modified)
        post_results = [
            validate_injected_data(load_json(path), baselines[str(path)], plan, generated)
            for path in paths
        ]
        fixture_after = verify_fixture_hashes()
        validation = {
            "valid": all(item["valid"] for item in post_results) and fixture_after["valid"],
            "sandbox_path": str(sandbox),
            "modified_json_paths": [str(path) for path in paths],
            "backup_path": str(backup),
            "generated_ids": generated,
            "captions": plan["captions"],
            "draft_results": post_results,
            "original_fixture_hashes_unchanged": fixture_after,
        }
        write_json(PROJECT_ROOT / "logs/caption_injection_validation.json", validation)
        if not validation["valid"]:
            raise RuntimeError("Post-write validation failed.")
    except Exception:
        _restore_complete_backup(backup)
        raise
    preview = [
        "CAPTION INJECTION TEST - SANDBOX ONLY",
        f"Sandbox: {sandbox}",
        f"Backup: {backup}",
        f"Track ID: {generated['track_id']}",
        "Original fixture hashes unchanged: YES",
        "References resolve: YES",
        "",
    ]
    for index, (caption, segment_id, material_id) in enumerate(zip(
        plan["captions"], generated["segment_ids"], generated["material_ids"]
    ), 1):
        preview.append(
            f"{index}. {caption['start']:.3f}-{caption['end']:.3f} "
            f"{caption['text']} | segment={segment_id} | material={material_id}"
        )
    preview_path = PROJECT_ROOT / "output/preview/caption_injection_test.txt"
    preview_path.write_text("\n".join(preview) + "\n", encoding="utf-8")
    write_json(PROJECT_ROOT / "logs/caption_injection_state.json", {
        "sandbox": str(sandbox), "backup": str(backup), "generated_ids": generated
    })
    return validation


def validate_input_plan(plan: dict[str, Any], project_duration: float) -> dict[str, Any]:
    errors: list[str] = []
    if plan.get("version") != 1:
        errors.append("plan version must be 1")
    captions = plan.get("captions")
    if not isinstance(captions, list) or not captions:
        errors.append("captions must be a nonempty list")
        captions = []
    ids: list[str] = []
    previous_end = 0.0
    for index, caption in enumerate(captions):
        prefix = f"caption {index + 1}"
        if not isinstance(caption, dict):
            errors.append(f"{prefix} is not an object")
            continue
        caption_id = caption.get("id")
        if not isinstance(caption_id, str) or not caption_id:
            errors.append(f"{prefix} has no valid id")
        else:
            ids.append(caption_id)
        try:
            start, end = float(caption["start"]), float(caption["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{prefix} has invalid timing")
            continue
        text = caption.get("text")
        if start < 0:
            errors.append(f"{prefix} starts before zero")
        if end <= start:
            errors.append(f"{prefix} end is not after start")
        if end > project_duration + 0.000001:
            errors.append(f"{prefix} exceeds project duration")
        if start < previous_end - 0.000001:
            errors.append(f"{prefix} overlaps the previous caption")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{prefix} text is empty")
        elif "\n" in text or "\r" in text:
            errors.append(f"{prefix} text is not one line")
        elif token_count(text) > 16:
            errors.append(f"{prefix} exceeds 16 words")
        if caption.get("style_preset") != "fixture_default":
            errors.append(f"{prefix} style_preset must be fixture_default")
        previous_end = end
    if len(ids) != len(set(ids)):
        errors.append("duplicate plan caption IDs")
    texts = [item.get("text") for item in captions if isinstance(item, dict)]
    if len(texts) != len(set(texts)):
        errors.append("duplicate caption texts are not allowed in this exact-once test")
    return {
        "valid": not errors,
        "errors": errors,
        "caption_count": len(captions),
        "project_duration": project_duration,
    }


def inject_caption_plan(plan_path: Path, sandbox_name: str) -> dict[str, Any]:
    plan_path = plan_path.resolve()
    plan = load_json(plan_path)
    source_baseline = _latest_draft(SOURCE)
    duration_seconds = float(source_baseline["duration"]) / 1_000_000
    input_validation = validate_input_plan(plan, duration_seconds)
    if not input_validation["valid"]:
        raise RuntimeError(
            "Caption plan validation failed: " + "; ".join(input_validation["errors"])
        )
    sandbox, backup, archived = clone_project(sandbox_name)
    paths = draft_paths(sandbox)
    if len(paths) != 2:
        raise RuntimeError(f"Expected two sandbox draft copies, found {len(paths)}")
    baselines = {str(path): load_json(path) for path in paths}
    if baselines[str(paths[0])] != baselines[str(paths[1])]:
        raise RuntimeError("Sandbox draft copies differ before injection.")
    template = _latest_draft(
        PROJECT_ROOT / "sample_capcut_projects" / "02_one_caption"
    )
    modified, generated, changes = _build_modified(
        baselines[str(paths[0])], template, plan["captions"]
    )
    results = [
        validate_injected_data(modified, baseline, plan, generated)
        for baseline in baselines.values()
    ]
    prefix = (
        "bulk_caption_injection"
        if sandbox_name == "bulk_caption_test"
        else "elevenlabs_regrouped_injection"
        if sandbox_name == "elevenlabs_regrouped_test"
        else f"{sandbox_name}_caption_injection"
    )
    preflight = {
        **input_validation,
        "valid": input_validation["valid"] and all(item["valid"] for item in results),
        "sandbox": str(sandbox),
        "backup": str(backup),
        "archived_previous_sandbox": str(archived) if archived else None,
        "draft_paths": [str(path) for path in paths],
        "results": results,
    }
    write_json(PROJECT_ROOT / "logs" / f"{prefix}_preflight.json", preflight)
    write_json(PROJECT_ROOT / "logs" / f"{prefix}_generated_ids.json", generated)
    write_json(PROJECT_ROOT / "logs" / f"{prefix}_changes.json", changes)
    if not preflight["valid"]:
        raise RuntimeError("Bulk caption preflight failed; sandbox was not written.")
    try:
        for path in paths:
            _atomic_write_json(path, modified)
        post = [
            validate_injected_data(load_json(path), baselines[str(path)], plan, generated)
            for path in paths
        ]
        fixture = verify_fixture_hashes()
        validation = {
            "valid": all(item["valid"] for item in post) and fixture["valid"],
            "sandbox_path": str(sandbox),
            "modified_json_paths": [str(path) for path in paths],
            "backup_path": str(backup),
            "caption_count": len(plan["captions"]),
            "text_track_count": 1,
            "material_count": len(plan["captions"]),
            "segment_count": len(plan["captions"]),
            "generated_ids": generated,
            "captions": plan["captions"],
            "draft_results": post,
            "original_fixture_hashes_unchanged": fixture,
        }
        write_json(PROJECT_ROOT / "logs" / f"{prefix}_validation.json", validation)
        if not validation["valid"]:
            raise RuntimeError("Post-write bulk validation failed.")
    except Exception:
        _restore_complete_backup(backup, sandbox)
        raise
    preview_lines = [
        "BULK CAPTION INJECTION - SANDBOX ONLY",
        f"Sandbox: {sandbox}",
        f"Backup: {backup}",
        f"Captions: {len(plan['captions'])}",
        f"Track ID: {generated['track_id']}",
        "References: PASS",
        "Video structure: UNCHANGED",
        "",
    ]
    for caption in plan["captions"]:
        preview_lines.append(
            f"{caption['id']} {caption['start']:.3f}-{caption['end']:.3f} {caption['text']}"
        )
    preview_name = (
        "elevenlabs_regrouped_injection.txt"
        if sandbox_name == "elevenlabs_regrouped_test"
        else "bulk_caption_injection_test.txt"
    )
    (PROJECT_ROOT / "output/preview" / preview_name).write_text(
        "\n".join(preview_lines) + "\n", encoding="utf-8"
    )
    write_json(PROJECT_ROOT / "logs" / f"{prefix}_state.json", {
        "sandbox": str(sandbox),
        "backup": str(backup),
        "plan_path": str(plan_path),
        "generated_ids": generated,
    })
    return validation

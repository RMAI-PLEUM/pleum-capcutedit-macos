"""Validation gates for sandbox-only CapCut caption injection."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from capcut_project_cloner import SANDBOX, sandbox_path
from capcut_live_project_reader import active_draft_paths
from utils import PROJECT_ROOT


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def draft_paths(folder: Path = SANDBOX) -> list[Path]:
    paths, _storage_format = active_draft_paths(folder)
    return paths


def video_signature(data: dict[str, Any]) -> list[dict[str, Any]]:
    return deepcopy([
        track for track in data.get("tracks", []) if track.get("type") == "video"
    ])


def all_object_ids(data: dict[str, Any]) -> list[str]:
    values: list[str] = []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("id"), str) and value["id"]:
                values.append(value["id"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(data)
    return values


def verify_fixture_hashes() -> dict[str, Any]:
    manifest = load_json(PROJECT_ROOT / "sample_capcut_projects" / "fixture_manifest.json")
    record = next(item for item in manifest["fixtures"] if item["fixture_name"] == "01_video_only")
    root = PROJECT_ROOT / "sample_capcut_projects" / "01_video_only"
    errors = []
    for file_record in record["files"]:
        path = root / Path(file_record["relative_path"])
        if not path.is_file():
            errors.append(f"missing: {file_record['relative_path']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.stat().st_size != file_record["size"] or digest != file_record["sha256"]:
            errors.append(f"hash mismatch: {file_record['relative_path']}")
    return {"valid": not errors, "errors": errors, "checked_files": len(record["files"])}


def validate_injected_data(
    data: dict[str, Any],
    baseline: dict[str, Any],
    plan: dict[str, Any],
    generated_ids: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    duration = data.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        errors.append("project duration is missing or invalid")
        duration = 0
    if data.get("duration") != baseline.get("duration"):
        errors.append("project duration changed")
    if video_signature(data) != video_signature(baseline):
        errors.append("video track or segments changed")
    text_tracks = [track for track in data.get("tracks", []) if track.get("type") == "text"]
    text_materials = data.get("materials", {}).get("texts", [])
    expected_count = len(plan.get("captions", []))
    if len(text_tracks) != 1:
        errors.append(f"expected one text track, found {len(text_tracks)}")
    segments = text_tracks[0].get("segments", []) if len(text_tracks) == 1 else []
    expected_segment_ids = list(generated_ids.get("segment_ids") or [])
    expected_material_ids = list(generated_ids.get("material_ids") or [])
    actual_segment_ids = [segment.get("id") for segment in segments]
    actual_material_ids = [material.get("id") for material in text_materials]
    segment_material_ids = [segment.get("material_id") for segment in segments]
    if len(text_tracks) == 1 and text_tracks[0].get("id") != generated_ids.get("track_id"):
        errors.append("generated text track ID mismatch")
    if len(segments) != expected_count:
        errors.append(
            f"expected {expected_count} caption segments, found {len(segments)}"
        )
    if len(text_materials) != expected_count:
        errors.append(
            f"expected {expected_count} text materials, found {len(text_materials)}"
        )
    if actual_segment_ids != expected_segment_ids:
        errors.append("generated caption segment IDs or order mismatch")
    if actual_material_ids != expected_material_ids:
        errors.append("generated caption material IDs or order mismatch")
    if segment_material_ids != expected_material_ids:
        errors.append("caption segment-to-material mapping or order mismatch")
    material_by_id: dict[str, list[dict[str, Any]]] = {}
    for material in text_materials:
        material_by_id.setdefault(material.get("id"), []).append(material)
    texts = []
    for index, material in enumerate(text_materials):
        for required in ("id", "content", "type"):
            if required not in material:
                errors.append(f"material {index} missing required field {required}")
        try:
            content = json.loads(material["content"])
            texts.append(content.get("text"))
            utf16_length = len(content.get("text", "").encode("utf-16-le")) // 2
            for style in content.get("styles", []):
                if style.get("range") != [0, utf16_length]:
                    errors.append(f"material {index} rich-text range mismatch")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"material {index} content is invalid: {exc}")
    expected_texts = [item["text"] for item in plan["captions"]]
    if texts != expected_texts:
        errors.append(f"caption texts mismatch: {texts}")
    previous_end = 0
    for index, (segment, requested) in enumerate(zip(segments, plan["captions"])):
        for required in ("id", "material_id", "target_timerange"):
            if required not in segment:
                errors.append(f"segment {index} missing required field {required}")
        if len(material_by_id.get(segment.get("material_id"), [])) != 1:
            errors.append(f"segment {index} material reference does not resolve exactly once")
        timerange = segment.get("target_timerange", {})
        start, length = timerange.get("start"), timerange.get("duration")
        if not isinstance(start, int) or not isinstance(length, int) or length <= 0:
            errors.append(f"segment {index} timing is invalid")
            continue
        if start < previous_end:
            errors.append(f"segment {index} overlaps previous caption")
        if start + length > duration:
            errors.append(f"segment {index} exceeds project duration")
        requested_start = requested["start"]
        requested_duration = requested["end"] - requested["start"]
        if abs(start / 1_000_000 - requested_start) > 0.001:
            errors.append(f"segment {index} start round-trip error exceeds 0.001s")
        if abs(length / 1_000_000 - requested_duration) > 0.001:
            errors.append(f"segment {index} duration round-trip error exceeds 0.001s")
        previous_end = start + length
    new_ids = [
        generated_ids["track_id"],
        *generated_ids["segment_ids"],
        *generated_ids["material_ids"],
        *generated_ids["auxiliary_material_ids"],
    ]
    if len(new_ids) != len(set(new_ids)):
        errors.append("generated IDs are not unique")
    baseline_ids = set(all_object_ids(baseline))
    if baseline_ids.intersection(new_ids):
        errors.append("a generated ID collides with the cloned baseline")
    return {
        "valid": not errors,
        "errors": errors,
        "project_duration_capcut": duration,
        "project_duration_seconds": duration / 1_000_000 if duration else 0,
        "caption_count": len(segments),
        "material_count": len(text_materials),
        "texts": texts,
        "texts_match_exactly_once": (
            texts == expected_texts
            and actual_segment_ids == expected_segment_ids
            and actual_material_ids == expected_material_ids
            and segment_material_ids == expected_material_ids
        ),
        "references_resolve": not any("reference" in error for error in errors),
        "utf16_ranges_valid": not any("rich-text range" in error for error in errors),
        "generated_ids_unique": len(new_ids) == len(set(new_ids)),
        "video_unchanged": video_signature(data) == video_signature(baseline),
        "duration_unchanged": data.get("duration") == baseline.get("duration"),
    }


def validate_caption_test() -> dict[str, Any]:
    state = load_json(PROJECT_ROOT / "logs" / "caption_injection_state.json")
    plan = load_json(
        PROJECT_ROOT / "output/json" / "caption_injection_test_plan.json"
    )
    sandbox = Path(state["sandbox"]).resolve()
    backup = Path(state["backup"]).resolve()
    if sandbox != SANDBOX.resolve():
        raise RuntimeError("Validation state points outside the expected sandbox.")
    results = []
    for path in draft_paths(sandbox):
        relative = path.relative_to(sandbox)
        baseline_path = backup / relative
        if not baseline_path.is_file():
            raise FileNotFoundError(f"Backup draft missing: {baseline_path}")
        results.append(validate_injected_data(
            load_json(path), load_json(baseline_path), plan, state["generated_ids"]
        ))
    fixture = verify_fixture_hashes()
    report = {
        "valid": bool(results) and all(item["valid"] for item in results) and fixture["valid"],
        "sandbox_path": str(sandbox),
        "backup_path": str(backup),
        "draft_results": results,
        "original_fixture_hashes_unchanged": fixture,
        "generated_ids": state["generated_ids"],
        "captions": plan["captions"],
    }
    return report


def validate_caption_plan_sandbox(sandbox_name: str) -> dict[str, Any]:
    prefix = (
        "bulk_caption_injection"
        if sandbox_name == "bulk_caption_test"
        else "elevenlabs_regrouped_injection"
        if sandbox_name == "elevenlabs_regrouped_test"
        else f"{sandbox_name}_caption_injection"
    )
    state = load_json(PROJECT_ROOT / "logs" / f"{prefix}_state.json")
    plan = load_json(Path(state["plan_path"]))
    sandbox = sandbox_path(sandbox_name).resolve()
    backup = Path(state["backup"]).resolve()
    if Path(state["sandbox"]).resolve() != sandbox:
        raise RuntimeError("Validation state does not match requested sandbox.")
    results = []
    for path in draft_paths(sandbox):
        baseline_path = backup / path.relative_to(sandbox)
        if not baseline_path.is_file():
            raise FileNotFoundError(f"Backup draft missing: {baseline_path}")
        results.append(validate_injected_data(
            load_json(path), load_json(baseline_path), plan, state["generated_ids"]
        ))
    fixture = verify_fixture_hashes()
    report = {
        "valid": bool(results) and all(item["valid"] for item in results) and fixture["valid"],
        "sandbox_path": str(sandbox),
        "backup_path": str(backup),
        "plan_path": state["plan_path"],
        "caption_count": len(plan["captions"]),
        "text_track_count": 1 if results else 0,
        "material_count": results[0]["material_count"] if results else 0,
        "segment_count": results[0]["caption_count"] if results else 0,
        "draft_results": results,
        "original_fixture_hashes_unchanged": fixture,
        "generated_ids": state["generated_ids"],
        "captions": plan["captions"],
    }
    return report

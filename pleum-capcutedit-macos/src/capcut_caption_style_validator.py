"""Strict in-memory validation for learned CapCut caption presets."""

from __future__ import annotations

import json
from typing import Any

from capcut_caption_style_fingerprint import fingerprint
from capcut_caption_style_preset import (
    load_caption_style_preset, render_learned_templates, utf16_length,
)
from utils import PROJECT_ROOT, write_json


TEST_CAPTIONS = [
    {"id": "test_1", "start": 1.0, "end": 2.0, "text": "ทดสอบรูปแบบซับมาตรฐาน"},
    {"id": "test_2", "start": 2.2, "end": 3.2, "text": "Apple Caption 2026"},
    {
        "id": "test_3", "start": 3.4, "end": 4.6,
        "text": "ภาษาไทย English และตัวเลข 123",
    },
]


def _all_ranges(value: Any) -> list[list[Any]]:
    ranges: list[list[Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "range" and isinstance(item, list):
                ranges.append(item)
            else:
                ranges.extend(_all_ranges(item))
    elif isinstance(value, list):
        for item in value:
            ranges.extend(_all_ranges(item))
    return ranges


def _contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, dict):
        return any(_contains(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_contains(item, needle) for item in value)
    return False


def validate_caption_style(preset_id: str) -> dict[str, Any]:
    errors: list[str] = []
    preset = load_caption_style_preset(preset_id)
    for key in (
        "version", "preset_id", "source", "material_template",
        "segment_style_template", "track_template", "dynamic_fields",
        "placement", "validation",
    ):
        if key not in preset:
            errors.append(f"preset missing {key}")
    if preset.get("version") != 1:
        errors.append("preset version must be 1")
    if preset.get("preset_id") != preset_id:
        errors.append("preset_id does not match requested preset")
    for template_key in ("material_template", "segment_style_template", "track_template"):
        template = preset.get(template_key)
        if isinstance(template, dict) and "id" in template:
            errors.append(f"{template_key} reuses a source ID")
    if (preset.get("track_template") or {}).get("segments") != []:
        errors.append("track_template must contain an empty segments list")
    source_text = str((preset.get("source") or {}).get("source_caption_text") or "")
    for key in ("material_template", "segment_style_template", "track_template"):
        if source_text and _contains(preset.get(key), source_text):
            errors.append(f"{key} permanently embeds source caption text")
    material_template = preset.get("material_template") or {}
    try:
        template_content = json.loads(material_template["content"])
        if template_content.get("text") != "":
            errors.append("material template text must be empty")
        if any(value != [0, 0] for value in _all_ranges(template_content)):
            errors.append("stored material ranges must use dynamic [0, 0] template values")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"source material content does not parse: {exc}")

    for field in ("font_size", "font_path", "font_resource_id", "fonts"):
        if field not in material_template:
            errors.append(f"required proven font field missing: {field}")

    collections = {
        "texts": [],
        **{
            str(record.get("collection")): []
            for record in preset.get("auxiliary_material_templates") or []
        },
    }
    baseline = {
        "duration": 10_000_000,
        "canvas_config": {
            "width": (preset.get("source") or {}).get("canvas_width"),
            "height": (preset.get("source") or {}).get("canvas_height"),
        },
        "tracks": [],
        "materials": collections,
    }
    generated_data: dict[str, Any] = {}
    generated_ids: dict[str, Any] = {}
    try:
        generated_data, generated_ids, _changes = render_learned_templates(
            baseline, TEST_CAPTIONS, preset
        )
        ids = [
            generated_ids["track_id"],
            *generated_ids["segment_ids"],
            *generated_ids["material_ids"],
            *generated_ids["auxiliary_material_ids"],
        ]
        if len(ids) != len(set(ids)):
            errors.append("dynamic IDs are not unique")
        text_track = next(
            track for track in generated_data["tracks"] if track.get("type") == "text"
        )
        materials = {
            item["id"]: item for item in generated_data["materials"]["texts"]
        }
        for index, (caption, segment) in enumerate(zip(TEST_CAPTIONS, text_track["segments"])):
            material = materials.get(segment.get("material_id"))
            if material is None:
                errors.append(f"test caption {index + 1} material reference does not resolve")
                continue
            content = json.loads(material["content"])
            if content.get("text") != caption["text"]:
                errors.append(f"test caption {index + 1} text mismatch")
            expected = utf16_length(caption["text"])
            ranges = _all_ranges(content)
            if not ranges or any(
                value != [0, expected] or value[0] + value[1] > expected
                for value in ranges
            ):
                errors.append(f"test caption {index + 1} UTF-16 ranges are invalid")
        first_segment = text_track["segments"][0]
        first_material = materials[first_segment["material_id"]]
        generated_auxiliary = []
        auxiliary_index = {
            item.get("id"): {"collection": collection, "template": item}
            for collection, items in generated_data["materials"].items()
            if collection != "texts" and isinstance(items, list)
            for item in items if isinstance(item, dict)
        }
        for reference in first_segment.get("extra_material_refs") or []:
            record = auxiliary_index.get(reference)
            if record is None:
                errors.append(f"generated auxiliary reference does not resolve: {reference}")
            else:
                generated_auxiliary.append(record)
        style_hash, _payload = fingerprint(
            text_track, first_segment, first_material, generated_auxiliary
        )
        expected_hash = (preset.get("source") or {}).get("style_fingerprint")
        if style_hash != expected_hash:
            errors.append("generated style fingerprint differs from learned source")
    except Exception as exc:
        errors.append(f"in-memory generation failed: {exc}")

    report = {
        "valid": not errors,
        "errors": errors,
        "preset_id": preset_id,
        "preset_path": str(PROJECT_ROOT / f"presets/captions/{preset_id}.json"),
        "test_caption_count": len(TEST_CAPTIONS),
        "utf16_ranges_valid": not any("UTF-16" in item for item in errors),
        "style_fingerprint_matches": not any("fingerprint" in item for item in errors),
        "material_references_resolve": not any("reference" in item for item in errors),
        "source_hashes_verified": bool(
            (preset.get("validation") or {}).get("source_hashes_verified")
        ),
    }
    slug = str((preset.get("source") or {}).get("project_name") or preset_id).casefold()
    write_json(
        PROJECT_ROOT / f"logs/direct_edit/{slug}/caption_style_validation.json",
        report,
    )
    return report


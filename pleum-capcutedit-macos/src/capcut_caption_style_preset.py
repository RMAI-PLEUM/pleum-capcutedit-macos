"""Load, select, and render complete learned CapCut caption templates."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from capcut_id_factory import CapCutIdFactory
from capcut_project_validator import all_object_ids
from utils import PROJECT_ROOT


PRESET_ROOT = PROJECT_ROOT / "presets/captions"
DEFAULTS_PATH = PROJECT_ROOT / "config/edit_capcut_defaults.json"


def preset_path(preset_id: str) -> Path:
    value = preset_id.strip()
    if not value or any(char in value for char in "\\/:*?\"<>"):
        raise ValueError(f"Invalid caption-style preset ID: {preset_id!r}")
    return PRESET_ROOT / f"{value}.json"


def load_caption_style_preset(preset_id: str) -> dict[str, Any]:
    path = preset_path(preset_id)
    if not path.is_file():
        raise FileNotFoundError(f"Caption-style preset not found: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Caption-style preset is not an object: {path}")
    return value


def default_caption_style_id() -> str:
    if not DEFAULTS_PATH.is_file():
        raise FileNotFoundError(
            "Caption-style defaults are missing; fixture fallback is not automatic."
        )
    value = json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))
    preset_id = str(value.get("default_caption_style_preset") or "").strip()
    if not preset_id:
        raise ValueError("default_caption_style_preset is missing.")
    return preset_id


def resolve_caption_style(
    explicit: str | None,
    captions: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if explicit:
        preset_id = explicit
    else:
        task_values = {
            str(item.get("style_preset") or "").strip()
            for item in captions
            if str(item.get("style_preset") or "").strip()
            not in {"", "default", "fixture_default"}
        }
        if len(task_values) > 1:
            raise ValueError(f"Caption plan contains multiple style presets: {task_values}")
        preset_id = next(iter(task_values)) if task_values else default_caption_style_id()
    if preset_id == "fixture_default":
        raise ValueError(
            "fixture_default is an emergency test fallback and must be invoked "
            "through the fixture-backed sandbox injector."
        )
    return preset_id, load_caption_style_preset(preset_id)


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def regenerate_utf16_ranges(value: Any, length: int) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "range" and isinstance(item, list) and len(item) == 2:
                value[key] = [0, length]
            else:
                regenerate_utf16_ranges(item, length)
    elif isinstance(value, list):
        for item in value:
            regenerate_utf16_ranges(item, length)


def _decoded_content(material: dict[str, Any]) -> dict[str, Any]:
    content = material.get("content")
    if not isinstance(content, str):
        raise ValueError("Preset material_template.content must remain a JSON string.")
    decoded = json.loads(content)
    if not isinstance(decoded, dict):
        raise ValueError("Preset material content must decode to an object.")
    return decoded


def render_learned_templates(
    baseline: dict[str, Any],
    captions: list[dict[str, Any]],
    preset: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    factory = CapCutIdFactory(set(all_object_ids(baseline)))
    modified = deepcopy(baseline)
    modified.setdefault("materials", {}).setdefault("texts", [])
    track = deepcopy(preset["track_template"])
    track_id = factory.new()
    track["id"] = track_id
    track["segments"] = []
    segment_ids: list[str] = []
    material_ids: list[str] = []
    auxiliary_ids: list[str] = []
    auxiliary_templates = preset.get("auxiliary_material_templates") or []

    for caption in captions:
        text = str(caption["text"])
        material = deepcopy(preset["material_template"])
        material_id = factory.new()
        material["id"] = material_id
        content = _decoded_content(material)
        content["text"] = text
        regenerate_utf16_ranges(content, utf16_length(text))
        material["content"] = json.dumps(
            content, ensure_ascii=False, separators=(",", ":")
        )

        segment = deepcopy(preset["segment_style_template"])
        segment_id = factory.new()
        segment["id"] = segment_id
        segment["material_id"] = material_id
        start = round(float(caption["start"]) * 1_000_000)
        duration = round((float(caption["end"]) - float(caption["start"])) * 1_000_000)
        segment["target_timerange"] = {"start": start, "duration": duration}
        if "source_timerange" in segment:
            segment["source_timerange"] = None
        if "render_timerange" in segment:
            segment["render_timerange"] = {"start": start, "duration": duration}
        refs: list[str] = []
        for record in auxiliary_templates:
            auxiliary = deepcopy(record["template"])
            auxiliary_id = factory.new()
            auxiliary["id"] = auxiliary_id
            auxiliary_ids.append(auxiliary_id)
            modified["materials"].setdefault(record["collection"], []).append(auxiliary)
            refs.append(auxiliary_id)
        segment["extra_material_refs"] = refs
        segment_ids.append(segment_id)
        material_ids.append(material_id)
        modified["materials"]["texts"].append(material)
        track["segments"].append(segment)

    modified.setdefault("tracks", []).append(track)
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
        "caption_style_preset": preset["preset_id"],
        "changed_fields": [
            "new IDs", "caption text", "target start", "target duration",
            "text-length-dependent UTF-16 ranges",
        ],
    }
    return modified, generated, changes

"""Validation for learned karaoke rich-text presets."""

from __future__ import annotations

import json
from typing import Any

from capcut_caption_style_preset import load_caption_style_preset
from capcut_karaoke_style_preset import apply_highlight_range, load_karaoke_preset


def validate_karaoke_preset(preset_id: str) -> dict[str, Any]:
    errors: list[str] = []
    preset = load_karaoke_preset(preset_id)
    base = load_caption_style_preset(preset["base_caption_preset"])
    material = base["material_template"]
    content = json.loads(material["content"])
    content["text"] = "หนึ่ง สอง สาม"
    try:
        rendered = apply_highlight_range(content, 6, 4, preset)
        styles = rendered["styles"]
        if [item["range"] for item in styles] != [[0, 6], [6, 10], [10, 13]]:
            errors.append("mixed-color UTF-16 ranges are incorrect")
        color = styles[1]["fill"]["content"]["solid"]["color"]
        if color != preset["highlight"]["capcut_color_value"]:
            errors.append("highlight color differs from learned CapCut value")
    except Exception as exc:
        errors.append(str(exc))
    return {
        "valid": not errors,
        "errors": errors,
        "preset_id": preset_id,
        "highlight_hex": preset["highlight"]["hex"],
        "range_representation": preset["highlight"]["range_representation"],
    }

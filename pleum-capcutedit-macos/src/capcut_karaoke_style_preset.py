"""Karaoke rich-text preset loading and range-style rendering."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from capcut_caption_style_preset import PRESET_ROOT


def karaoke_preset_path(preset_id: str) -> Path:
    if not preset_id.strip() or any(char in preset_id for char in "\\/:*?\"<>"):
        raise ValueError(f"Invalid karaoke preset ID: {preset_id!r}")
    return PRESET_ROOT / f"{preset_id}.json"


def load_karaoke_preset(preset_id: str) -> dict[str, Any]:
    path = karaoke_preset_path(preset_id)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("preset_id") != preset_id:
        raise ValueError("Karaoke preset ID mismatch.")
    return value


def apply_highlight_range(
    base_content: dict[str, Any],
    range_start: int | None,
    range_length: int | None,
    karaoke_preset: dict[str, Any],
) -> dict[str, Any]:
    content = deepcopy(base_content)
    text = str(content.get("text") or "")
    total = len(text.encode("utf-16-le")) // 2
    base_styles = content.get("styles") or []
    if not base_styles:
        raise ValueError("Base caption content has no rich-text style.")
    base_style = deepcopy(base_styles[0])
    base_style["range"] = [0, total]
    if range_start is None:
        content["styles"] = [base_style]
        return content
    if range_length is None or range_length <= 0:
        raise ValueError("Highlight range length must be positive.")
    range_end = range_start + range_length
    if (
        karaoke_preset["highlight"].get("range_includes_trailing_separator")
        and range_end < total
    ):
        suffix = text.encode("utf-16-le")
        # Convert the UTF-16 end back to a Python character boundary and include
        # only the immediately following ASCII separator proven by the fixture.
        prefix_units = 0
        character_index = 0
        for character_index, character in enumerate(text):
            units = len(character.encode("utf-16-le")) // 2
            if prefix_units + units > range_end:
                break
            prefix_units += units
            if prefix_units == range_end:
                character_index += 1
                break
        if character_index < len(text) and text[character_index] == " ":
            range_end += 1
    if range_start < 0 or range_end > total:
        raise ValueError("Highlight range exceeds caption UTF-16 length.")
    # A highlight is a color-only state. Clone the active base caption style
    # so font, size, weight, stroke, shadow, spacing, and every other visual
    # field remain byte-equivalent to the normal state.
    highlight = deepcopy(base_style)
    highlight["fill"] = deepcopy(
        karaoke_preset["highlight"]["range_style_template"]["fill"]
    )
    highlight["range"] = [range_start, range_end]
    styles: list[dict[str, Any]] = []
    if range_start > 0:
        before = deepcopy(base_style)
        before["range"] = [0, range_start]
        styles.append(before)
    styles.append(highlight)
    if range_end < total:
        after = deepcopy(base_style)
        after["range"] = [range_end, total]
        styles.append(after)
    content["styles"] = styles
    return content

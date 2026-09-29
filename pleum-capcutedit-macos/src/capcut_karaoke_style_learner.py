"""Read-only learning of CapCut's mixed-color rich-text karaoke structure."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capcut_caption_style_preset import load_caption_style_preset
from capcut_karaoke_style_preset import karaoke_preset_path
from capcut_live_project_reader import read_live_project
from capcut_project_locator import locate_project
from utils import PROJECT_ROOT, write_json


def _hashes(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(item for item in folder.rglob("*") if item.is_file())
    }


def _utf16_prefix(text: str, character_count: int) -> int:
    return len(text[:character_count].encode("utf-16-le")) // 2


def learn_karaoke_style(
    project_name: str,
    source_text: str,
    highlight_text: str,
    preset_id: str,
) -> tuple[dict[str, Any], Path]:
    project = locate_project(project_name)
    before = _hashes(project.path)
    live = read_live_project(project)
    materials = {
        str(item.get("id")): item
        for item in (live.primary.get("materials") or {}).get("texts", [])
        if isinstance(item, dict) and item.get("id")
    }
    matches: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for track in live.primary.get("tracks") or []:
        if track.get("type") != "text":
            continue
        for segment in track.get("segments") or []:
            material = materials.get(str(segment.get("material_id")))
            if material is None:
                continue
            try:
                content = json.loads(material["content"])
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if content.get("text") == source_text:
                matches.append((track, segment, material))
    if len(matches) != 1:
        raise RuntimeError(
            f'Expected exactly one fixture caption "{source_text}", found {len(matches)}. '
            "Create the exact manually styled fixture before learning."
        )
    track, segment, material = matches[0]
    content = json.loads(material["content"])
    character_start = source_text.find(highlight_text)
    if character_start < 0 or source_text.find(highlight_text, character_start + 1) >= 0:
        raise RuntimeError("Highlighted text must occur exactly once in fixture text.")
    expected_start = _utf16_prefix(source_text, character_start)
    expected_end = _utf16_prefix(
        source_text, character_start + len(highlight_text)
    )
    matching_styles = []
    learned_range: list[int] | None = None
    for style in content.get("styles") or []:
        value = style.get("range")
        if not (
            isinstance(value, list) and len(value) == 2
            and value[0] == expected_start and value[1] >= expected_end
        ):
            continue
        extra_start = character_start + len(highlight_text)
        extra_utf16 = value[1] - expected_end
        following = source_text[extra_start:]
        consumed = ""
        for character in following:
            if len(consumed.encode("utf-16-le")) // 2 >= extra_utf16:
                break
            consumed += character
        if (
            len(consumed.encode("utf-16-le")) // 2 == extra_utf16
            and (not consumed or consumed.isspace())
        ):
            matching_styles.append(style)
            learned_range = [int(value[0]), int(value[1])]
    if len(matching_styles) != 1:
        raise RuntimeError(
            "Fixture has no unique rich-text style range matching the highlighted "
            f"UTF-16 glyph span [{expected_start}, {expected_end}] "
            "(an immediately trailing whitespace bookkeeping span is allowed)."
        )
    highlight_style = deepcopy(matching_styles[0])
    color_value = (
        highlight_style.get("fill", {}).get("content", {})
        .get("solid", {}).get("color")
    )
    if not (
        isinstance(color_value, list) and len(color_value) == 3
        and all(isinstance(value, (int, float)) for value in color_value)
    ):
        raise RuntimeError("Fixture highlight color schema is not proven.")
    expected_rgb = [244 / 255, 199 / 255, 15 / 255]
    if any(abs(float(a) - b) > 0.000001 for a, b in zip(color_value, expected_rgb)):
        raise RuntimeError(f"Fixture highlight is not #F4C70F: {color_value}")
    base = load_caption_style_preset("system-default")
    base_content = json.loads(base["material_template"]["content"])
    base_style = deepcopy((base_content.get("styles") or [None])[0])
    if not isinstance(base_style, dict):
        raise RuntimeError("system-default base rich-text style is missing.")
    def without_range_fill(style: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(style)
        value.pop("range", None)
        value.pop("fill", None)
        return value
    if without_range_fill(highlight_style) != without_range_fill(base_style):
        raise RuntimeError(
            "Fixture highlight changes fields other than range/fill versus system-default."
        )
    highlight_style["range"] = [0, 0]
    canonical = json.dumps(
        highlight_style, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    after = _hashes(project.path)
    if before != after:
        changed = sorted(
            key for key in set(before) | set(after)
            if before.get(key) != after.get(key)
        )
        raise RuntimeError(f"Apple changed during read-only learning: {changed}")
    preset = {
        "version": 1,
        "preset_id": preset_id,
        "base_caption_preset": "system-default",
        "highlight": {
            "hex": "#F4C70F",
            "capcut_color_value": color_value,
            "range_representation": "utf16_start_end_exclusive",
            "range_includes_trailing_separator": (
                learned_range[1] > expected_end if learned_range else False
            ),
            "range_style_template": highlight_style,
            "preserve_base_stroke": True,
            "preserve_base_shadow": True,
            "preserve_base_transform": True,
        },
        "source": {
            "project": project.name,
            "project_identity": project.identity,
            "fixture_text": source_text,
            "highlighted_text": highlight_text,
            "source_track_id": track["id"],
            "source_segment_id": segment["id"],
            "source_material_id": material["id"],
            "style_fingerprint": fingerprint,
            "learned_at": datetime.now(timezone.utc).isoformat(),
            "source_hashes_verified": True,
        },
    }
    path = karaoke_preset_path(preset_id)
    write_json(path, preset)
    report = {
        "valid": True,
        "fixture_text": source_text,
        "highlighted_text": highlight_text,
        "expected_utf16_glyph_range": [expected_start, expected_end],
        "learned_capcut_range": learned_range,
        "learned_color": color_value,
        "hex": "#F4C70F",
        "style_fingerprint": fingerprint,
        "apple_hashes_unchanged": True,
        "apple_file_hashes_before": before,
        "apple_file_hashes_after": after,
        "preset_path": str(path),
    }
    write_json(
        PROJECT_ROOT / "logs/direct_edit/apple/karaoke_style_learning.json", report
    )
    return report, path

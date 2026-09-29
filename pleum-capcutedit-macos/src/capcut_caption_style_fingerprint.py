"""Stable visual fingerprints for CapCut text captions."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


_DYNAMIC_KEYS = {
    "id", "material_id", "track_id", "segment_id",
    "source_timerange", "target_timerange", "render_timerange",
    "recognize_task_id", "group_id", "raw_segment_id",
}
_TEXT_KEYS = {
    "text", "recognize_text", "base_content", "translate_original_text",
    "ssml_content",
}
_TEXT_LENGTH_COLLECTIONS = {"words", "current_words"}
_TIMESTAMP_PARTS = ("timestamp", "create_time", "created_at", "updated_at")


def _normalized(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value):
            lowered = key.casefold()
            if key in _DYNAMIC_KEYS or key in _TEXT_KEYS:
                continue
            if key in _TEXT_LENGTH_COLLECTIONS:
                continue
            if any(part in lowered for part in _TIMESTAMP_PARTS):
                continue
            item = value[key]
            if key == "range" and isinstance(item, list) and len(item) == 2:
                result[key] = ["$UTF16_START", "$UTF16_LENGTH"]
            elif key == "extra_material_refs":
                # IDs differ per cue; referenced templates are fingerprinted separately.
                result[key] = ["$AUXILIARY_REFS"]
            else:
                result[key] = _normalized(item, parent_key=key)
        return result
    if isinstance(value, list):
        return [_normalized(item, parent_key=parent_key) for item in value]
    return value


def decoded_material(material: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(material)
    content = result.get("content")
    if isinstance(content, str):
        result["content"] = json.loads(content)
    return result


def style_payload(
    track: dict[str, Any],
    segment: dict[str, Any],
    material: dict[str, Any],
    auxiliary_templates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    track_style = deepcopy(track)
    track_style.pop("segments", None)
    return _normalized({
        "track": track_style,
        "segment": segment,
        "material": decoded_material(material),
        "auxiliary": auxiliary_templates or [],
    })


def fingerprint(
    track: dict[str, Any],
    segment: dict[str, Any],
    material: dict[str, Any],
    auxiliary_templates: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    payload = style_payload(track, segment, material, auxiliary_templates)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), payload


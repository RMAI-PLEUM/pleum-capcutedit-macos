"""Resolve adaptive caption length from CapCut canvas orientation."""

from __future__ import annotations

from typing import Any


ORIENTATION_LIMITS = {
    "landscape": 16,
    "portrait": 8,
    "square": 10,
}


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def canvas_dimensions(
    draft: dict[str, Any] | None,
    metadata: dict[str, Any] | None = None,
) -> tuple[int | None, int | None]:
    canvas = (draft or {}).get("canvas_config")
    if isinstance(canvas, dict):
        width, height = _positive_int(canvas.get("width")), _positive_int(canvas.get("height"))
        if width is not None and height is not None:
            return width, height
    for group in (metadata or {}).get("draft_materials", []) or []:
        for item in group.get("value", []) if isinstance(group, dict) else []:
            if isinstance(item, dict):
                width, height = _positive_int(item.get("width")), _positive_int(item.get("height"))
                if width is not None and height is not None:
                    return width, height
    return None, None


def orientation_from_dimensions(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def resolve_caption_layout(
    draft: dict[str, Any] | None,
    explicit_layout: str = "auto",
    explicit_max_words: int | None = None,
    fallback_max_words: int = 16,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    width, height = canvas_dimensions(draft, metadata)
    detected = (
        orientation_from_dimensions(width, height)
        if width is not None and height is not None else None
    )
    if explicit_max_words is not None:
        if explicit_max_words <= 0:
            raise ValueError("--max-words-per-caption must be a positive integer.")
        orientation = (
            explicit_layout if explicit_layout != "auto"
            else detected or "landscape"
        )
        limit = explicit_max_words
        source = "explicit_max_words"
    elif explicit_layout != "auto":
        orientation = explicit_layout
        limit = ORIENTATION_LIMITS[orientation]
        source = "explicit_caption_layout"
    elif detected is not None:
        orientation = detected
        limit = ORIENTATION_LIMITS[orientation]
        source = "automatic_canvas_detection"
    else:
        orientation = "unknown"
        limit = int(fallback_max_words)
        source = "existing_default_fallback"
    return {
        "canvas_width": width,
        "canvas_height": height,
        "orientation": orientation,
        "max_words_per_caption": limit,
        "source": source,
    }

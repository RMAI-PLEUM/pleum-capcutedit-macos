"""Validate that karaoke states preserve the selected base caption style."""

from __future__ import annotations

from typing import Any


def validate_state_template_consistency(
    materials: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    resolved_preset: dict[str, Any],
) -> dict[str, Any]:
    """Report style or transform drift across generated karaoke states."""
    errors: list[str] = []
    material_template = {
        key: value for key, value in resolved_preset["material_template"].items()
        if key not in {"id", "content"}
    }
    segment_template = {
        key: value
        for key, value in resolved_preset["segment_style_template"].items()
        if key not in {
            "id", "material_id", "target_timerange", "source_timerange",
            "render_timerange", "extra_material_refs",
        }
    }
    for material in materials:
        comparable = {
            key: value for key, value in material.items()
            if key not in {"id", "content"}
        }
        if comparable != material_template:
            errors.append("karaoke material style drift")
            break
    for segment in segments:
        comparable = {
            key: value for key, value in segment.items()
            if key not in {
                "id", "material_id", "target_timerange", "source_timerange",
                "render_timerange", "extra_material_refs",
            }
        }
        if comparable != segment_template:
            errors.append("karaoke transform drift")
            break
    return {"valid": not errors, "errors": errors}

"""Validate the combined edit plan and its non-destructive contract."""

from __future__ import annotations

from typing import Any


def validate_edit_plan(
    plan: dict[str, Any],
    caption_validation: dict[str, Any],
    cut_validation: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    if plan.get("version") != 1:
        errors.append("edit plan version must be 1")
    if not isinstance(plan.get("project"), dict):
        errors.append("project must be an object")
    if not isinstance(plan.get("captions"), list):
        errors.append("captions must be a list")
    if not isinstance(plan.get("cuts"), list):
        errors.append("cuts must be a list")
    if plan.get("overlays") != []:
        errors.append("overlays must remain empty in this phase")
    if plan.get("audio") != []:
        errors.append("audio actions must remain empty in this phase")
    if not caption_validation.get("valid"):
        errors.append("caption plan validation failed")
    if not cut_validation.get("valid"):
        errors.append("cut plan validation failed")
    return {"valid": not errors, "errors": errors}

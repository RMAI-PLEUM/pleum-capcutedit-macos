"""Human-readable previews for intermediate plans."""

from __future__ import annotations

from typing import Any


def caption_preview(plan: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = [
        "CAPTION PLAN (READ ONLY)",
        f"Project duration: {plan['project_duration']:.3f}s",
        f"Captions: {len(plan['captions'])}",
        f"Validation: {'PASS' if validation['valid'] else 'FAIL'}",
        "",
    ]
    for caption in plan["captions"]:
        lines.append(
            f"{caption['id']}  {caption['start']:.3f} -> {caption['end']:.3f}  "
            f"clip={caption['source_clip_id']}  {caption['text']}"
        )
    if validation["errors"]:
        lines.extend(["", "ERRORS:", *[f"- {error}" for error in validation["errors"]]])
    return "\n".join(lines) + "\n"


def cut_preview(plan: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = [
        "CUT PLAN - PROPOSALS ONLY, NOTHING APPLIED",
        f"Project duration: {plan['project_duration']:.3f}s",
        f"Proposed cuts: {len(plan['cuts'])}",
        f"Validation: {'PASS' if validation['valid'] else 'FAIL'}",
        "",
    ]
    for cut in plan["cuts"]:
        lines.append(
            f"{cut['id']}  {cut['timeline_start']:.3f} -> {cut['timeline_end']:.3f}  "
            f"clip={cut['source_clip_id']}  confidence={cut['confidence']:.2f}  "
            f"review={cut['requires_review']}"
        )
    if validation["errors"]:
        lines.extend(["", "ERRORS:", *[f"- {error}" for error in validation["errors"]]])
    return "\n".join(lines) + "\n"


def edit_summary(
    plan: dict[str, Any],
    caption_validation: dict[str, Any],
    cut_validation: dict[str, Any],
    edit_validation: dict[str, Any],
) -> str:
    project = plan["project"]
    return (
        "EDIT PLAN SUMMARY (DRY RUN)\n"
        f"Project: {project.get('name')}\n"
        f"Path: {project.get('path')}\n"
        f"Duration: {float(project.get('duration') or 0):.3f}s\n"
        f"Captions that would be added: {len(plan['captions'])}\n"
        f"Silence cuts proposed for manual review: {len(plan['cuts'])}\n"
        "Cuts automatically applied: 0\n"
        f"Caption validation: {'PASS' if caption_validation['valid'] else 'FAIL'}\n"
        f"Cut validation: {'PASS' if cut_validation['valid'] else 'FAIL'}\n"
        f"Edit validation: {'PASS' if edit_validation['valid'] else 'FAIL'}\n"
        "CapCut files modified: 0\n"
    )

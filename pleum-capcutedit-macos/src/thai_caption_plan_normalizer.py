"""Local, non-injecting repair of Mai Yamok caption text and boundaries."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from caption_plan_validator import validate_caption_plan
from thai_caption_text_renderer import (
    MAI_YAMOK, MaiYamokAttachmentError, attach_mai_yamok_tokens,
    normalize_thai_caption_text,
)
from thai_caption_validator import validate_thai_caption_plan
from thai_lexical_regrouper import lexical_segments
from utils import PROJECT_ROOT, write_json


def _pseudo_lexical(plan: dict[str, Any]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    cursor = 0.0
    raw_index = 0
    for caption in plan.get("captions") or []:
        text = str(caption.get("text") or "")
        start = float(caption.get("start") or cursor)
        end = float(caption.get("end") or start + 0.1)
        segments = lexical_segments(text)
        step = max((end - start) / max(len(segments), 1), 0.000001)
        for token, char_start, char_end in segments:
            words.append({
                "text": token,
                "start": round(start + raw_index * 0.000001, 6),
                "end": round(min(end, start + step) + raw_index * 0.000001, 6),
                "source_fragment_indices": [raw_index],
                "char_start": char_start,
                "char_end": char_end,
            })
            raw_index += 1
            start += step
        cursor = end
    return attach_mai_yamok_tokens(words)[0]


def normalize_thai_caption_plan(
    plan_path: Path,
    *,
    max_words: int = 16,
) -> tuple[dict[str, Any], Path, Path, Path]:
    source = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise ValueError("Caption plan must be a JSON object.")
    normalized = deepcopy(source)
    captions = normalized.get("captions")
    if not isinstance(captions, list) or not captions:
        raise ValueError("Caption plan contains no captions.")
    raw_canonical = "".join(str(item.get("text") or "") for item in source["captions"])
    stats = {
        "standalone_mai_yamok_found": 0,
        "mai_yamok_attached": 0,
        "caption_boundaries_repaired": 0,
        "missing_spaces_inserted_after_mai_yamok": 0,
        "multiple_spaces_normalized_after_mai_yamok": 0,
        "leading_spaces_removed_before_mai_yamok": 0,
    }
    before_after: list[dict[str, Any]] = []

    for index in range(1, len(captions)):
        previous = str(captions[index - 1].get("text") or "")
        following = str(captions[index].get("text") or "")
        if following.lstrip().startswith(MAI_YAMOK):
            if not previous.strip():
                raise MaiYamokAttachmentError({
                    "text": MAI_YAMOK,
                    "start": captions[index].get("start"),
                    "source_fragment_indices": [],
                }, index)
            original_previous, original_following = previous, following
            captions[index - 1]["text"] = previous.rstrip() + MAI_YAMOK
            captions[index]["text"] = following.lstrip()[1:].lstrip()
            stats["standalone_mai_yamok_found"] += 1
            stats["mai_yamok_attached"] += 1
            stats["caption_boundaries_repaired"] += 1
            before_after.append({
                "before": [original_previous, original_following],
                "after": [
                    captions[index - 1]["text"], captions[index]["text"]
                ],
                "kind": "caption_boundary",
            })
    if str(captions[0].get("text") or "").lstrip().startswith(MAI_YAMOK):
        raise MaiYamokAttachmentError({
            "text": MAI_YAMOK,
            "start": captions[0].get("start"),
            "source_fragment_indices": [],
        }, 0)

    for caption in captions:
        before = str(caption.get("text") or "")
        after, text_stats = normalize_thai_caption_text(before)
        caption["text"] = after
        for key, value in text_stats.items():
            stats[key] += value
        # Whitespace-before repairs represent an attached standalone token.
        stats["standalone_mai_yamok_found"] += text_stats[
            "leading_spaces_removed_before_mai_yamok"
        ]
        stats["mai_yamok_attached"] += text_stats[
            "leading_spaces_removed_before_mai_yamok"
        ]
        if before != after:
            before_after.append({
                "before": before, "after": after, "kind": "caption_text",
            })

    lexical = _pseudo_lexical(normalized)
    structural = validate_caption_plan(
        normalized, max_words=max_words, lexical_words=lexical
    )
    semantic = validate_thai_caption_plan(
        normalized, raw_canonical, lexical, max_words=max_words
    )
    report = {
        "valid": structural["valid"] and semantic["valid"],
        "source_plan": str(plan_path),
        **stats,
        "before_after": before_after,
        "structural_validation": structural,
        "thai_semantic_validation": semantic,
        "elevenlabs_called": False,
        "capcut_project_modified": False,
    }
    filename = plan_path.name
    base = filename[:-5] if filename.casefold().endswith(".json") else filename
    base = base.replace(".regrouped", "")
    output = PROJECT_ROOT / "output/json" / f"{base}.thai_normalized.json"
    preview_name = base.replace(".", "_") + "_thai_normalized.txt"
    preview = PROJECT_ROOT / "output/preview" / preview_name
    log_stem = base.split(".caption_plan", 1)[0].replace(".", "_")
    log = PROJECT_ROOT / "logs" / f"{log_stem}_thai_caption_normalization.json"
    if not report["valid"]:
        write_json(log, report)
        raise RuntimeError(
            "Normalized caption plan failed validation: "
            + "; ".join(structural["errors"] + semantic["errors"])
        )
    write_json(output, normalized)
    write_json(log, report)
    lines = [
        "THAI CAPTION PLAN NORMALIZATION",
        "",
        f"Source: {plan_path}",
        f"Output: {output}",
        f"Standalone ๆ found: {stats['standalone_mai_yamok_found']}",
        f"Attached: {stats['mai_yamok_attached']}",
        f"Caption boundaries repaired: {stats['caption_boundaries_repaired']}",
        f"Missing following spaces inserted: {stats['missing_spaces_inserted_after_mai_yamok']}",
        f"Multiple following spaces normalized: {stats['multiple_spaces_normalized_after_mai_yamok']}",
        f"Structural validation: {'PASS' if structural['valid'] else 'FAIL'}",
        f"Thai semantic validation: {'PASS' if semantic['valid'] else 'FAIL'}",
        "",
    ]
    for item in before_after:
        lines.append(f"Before: {item['before']}")
        lines.append(f"After:  {item['after']}")
        lines.append("")
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_text("\n".join(lines), encoding="utf-8")
    return report, output, preview, log


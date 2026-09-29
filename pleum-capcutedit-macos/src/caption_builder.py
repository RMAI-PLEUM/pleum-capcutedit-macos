from __future__ import annotations

import re
from typing import Any

from thai_caption_text_renderer import (
    attach_mai_yamok_tokens, normalize_thai_caption_text,
    render_thai_caption_tokens, thai_lexical_word_count,
)


def _groups_from_words(words: list[dict[str, Any]], max_words: int) -> list[list[dict[str, Any]]]:
    words, _mai_yamok_stats = attach_mai_yamok_tokens(words)
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        current.append(word)
        text = render_thai_caption_tokens(current)
        boundary = bool(re.search(r"[.!?。！？ฯ]\s*$", text))
        count = thai_lexical_word_count(current)
        if count >= max_words or (boundary and count >= 3):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def build_auto_cues(words: list[dict[str, Any]], subtitle: dict[str, Any]) -> list[dict[str, Any]]:
    cues = []
    for group in _groups_from_words(words, int(subtitle["max_words_per_cue"])):
        text = render_thai_caption_tokens(group)
        cues.append({
            "start": max(0.0, float(group[0]["start"]) - float(subtitle["lead_in"])),
            "end": float(group[-1]["end"]) + float(subtitle["tail_out"]),
            "text": text,
        })
    return cues


def clamp_cues(
    cues: list[dict[str, Any]], target_duration: float, start_offset: float = 0.0
) -> list[dict[str, Any]]:
    result = []
    for cue in cues:
        start = float(cue["start"]) + start_offset
        end = float(cue["end"]) + start_offset
        if end <= 0 or start >= target_duration:
            continue
        start, end = max(0.0, start), min(target_duration, end)
        if end <= start:
            continue
        if result and start < result[-1]["end"]:
            start = result[-1]["end"]
        if end > start:
            result.append({
                **cue, "start": start, "end": end,
                "text": normalize_thai_caption_text(cue["text"])[0],
            })
    return result

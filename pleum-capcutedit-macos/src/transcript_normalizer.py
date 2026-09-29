from __future__ import annotations

from typing import Any

import re

from utils import normalize_space


_AUDIO_EVENT = re.compile(r"^\s*[\[(<][^)\]>\n]+[\])>]\s*$")


def normalize_word_records(
    response: dict[str, Any],
    media_duration: float | None = None,
    include_audio_events: bool = False,
) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for item in response.get("words", []) or []:
        item_type = str(item.get("type", "word")).casefold()
        if item_type != "word":
            continue
        text = normalize_space(str(item.get("text") or ""))
        if not include_audio_events and _AUDIO_EVENT.match(text):
            continue
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        start = max(0.0, start)
        if media_duration is not None:
            end = min(float(media_duration), end)
        if text and end > start and (media_duration is None or start < media_duration):
            confidence = item.get("confidence")
            if not isinstance(confidence, (int, float)):
                confidence = None
            record = {
                "text": text,
                "start": round(start, 6),
                "end": round(end, 6),
                "confidence": confidence,
                "type": "word",
            }
            words.append(record)
    return sorted(words, key=lambda word: (word["start"], word["end"]))


def transcript_text(response: dict[str, Any]) -> str:
    return normalize_space(str(response.get("text") or ""))

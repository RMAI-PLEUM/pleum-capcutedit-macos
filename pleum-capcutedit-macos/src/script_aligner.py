from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


def _match_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold()
    return re.sub(r"[^\w\u0E00-\u0E7F]+", "", text)


def align_script(
    chunks: list[str],
    words: list[dict[str, Any]],
    subtitle: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not chunks:
        return [], []
    if not words:
        raise RuntimeError("ElevenLabs returned no usable word timestamps.")

    cues: list[dict[str, Any]] = []
    debug: list[dict[str, Any]] = []
    cursor = 0
    total_script_chars = max(1, sum(len(_match_text(c)) for c in chunks))
    audio_start, audio_end = float(words[0]["start"]), float(words[-1]["end"])
    cumulative_chars = 0

    for index, chunk in enumerate(chunks):
        normalized = _match_text(chunk)
        expected_words = max(1, round(len(normalized) / max(1, total_script_chars) * len(words)))
        search_end = min(len(words), cursor + max(12, expected_words * 4))
        best: tuple[float, int, int] | None = None
        for start in range(cursor, search_end):
            max_window = min(len(words), start + max(4, expected_words * 2 + 4))
            for end in range(start + 1, max_window + 1):
                candidate = _match_text(" ".join(str(w["text"]) for w in words[start:end]))
                score = SequenceMatcher(None, normalized, candidate).ratio()
                length_penalty = abs(len(candidate) - len(normalized)) / max(len(normalized), 1)
                adjusted = score - min(0.25, length_penalty * 0.12)
                if best is None or adjusted > best[0]:
                    best = (adjusted, start, end)

        confidence = best[0] if best else 0.0
        use_match = bool(best and confidence >= 0.48)
        if use_match:
            _, start_i, end_i = best
            start = float(words[start_i]["start"]) - float(subtitle["lead_in"])
            end = float(words[end_i - 1]["end"]) + float(subtitle["tail_out"])
            cursor = end_i
            method = "fuzzy"
        else:
            start_ratio = cumulative_chars / total_script_chars
            end_ratio = (cumulative_chars + len(normalized)) / total_script_chars
            start = audio_start + (audio_end - audio_start) * start_ratio
            end = audio_start + (audio_end - audio_start) * end_ratio
            method = "proportional"

        minimum = float(subtitle["min_duration"])
        preferred_max = float(subtitle["max_duration"])
        end = max(end, start + minimum)
        if end - start > preferred_max:
            end = start + preferred_max
        if cues and start < cues[-1]["end"]:
            start = cues[-1]["end"]
            end = max(end, start + minimum)
        cues.append({"start": start, "end": end, "text": chunk, "script_chunk_index": index})
        debug.append({
            "chunk_index": index,
            "chunk": chunk,
            "method": method,
            "confidence": round(confidence, 4),
            "word_cursor_after": cursor,
            "start": start,
            "end": end,
        })
        cumulative_chars += len(normalized)
    return cues, debug

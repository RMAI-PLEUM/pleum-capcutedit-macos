"""Map timed lexical token identity to exact rendered UTF-16 caption spans."""

from __future__ import annotations

import re
from typing import Any

from thai_caption_text_renderer import (
    attach_mai_yamok_tokens, render_thai_caption_tokens_with_spans,
)


PUNCTUATION_ONLY = re.compile(r"^[^\w\u0E00-\u0E7F]+$", re.UNICODE)
AUDIO_EVENT = re.compile(r"^\s*[\[\(<].+[\]\)>]\s*$")


def _utf16_index(text: str, character_index: int) -> int:
    return len(text[:character_index].encode("utf-16-le")) // 2


def is_highlightable(text: str) -> bool:
    value = text.strip()
    return bool(value) and not PUNCTUATION_ONLY.fullmatch(value) and not AUDIO_EVENT.fullmatch(value)


def map_caption_word_spans(
    captions: list[dict[str, Any]],
    lexical_words: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    lexical, stats = attach_mai_yamok_tokens(lexical_words)
    output: list[dict[str, Any]] = []
    word_number = 1
    mapped = 0
    for caption in captions:
        cue_start, cue_end = float(caption["start"]), float(caption["end"])
        cue_words = [
            word for word in lexical
            if cue_start
            <= (float(word["start"]) + float(word["end"])) / 2
            < cue_end
        ]
        rendered, spans, attached = render_thai_caption_tokens_with_spans(cue_words)
        expected = str(caption["text"])
        if rendered != expected:
            raise RuntimeError(
                f"Lexical renderer mismatch for {caption['id']}: "
                f"expected={expected!r}, rendered={rendered!r}"
            )
        mapped_words: list[dict[str, Any]] = []
        for token, span in zip(attached, spans):
            text = str(token["text"])
            utf16_start = _utf16_index(rendered, span["character_start"])
            utf16_end = _utf16_index(rendered, span["character_end"])
            mapped_words.append({
                "word_id": f"word_{word_number:06d}",
                "text": text,
                "start": round(float(token["start"]), 6),
                "end": round(float(token["end"]), 6),
                "utf16_start": utf16_start,
                "utf16_length": utf16_end - utf16_start,
                "highlightable": is_highlightable(text),
                "source_fragment_indices": list(
                    token.get("source_fragment_indices") or []
                ),
            })
            word_number += 1
            mapped += 1
        output.append({**caption, "words": mapped_words})
    return output, {
        **stats,
        "mapped_lexical_word_count": mapped,
    }

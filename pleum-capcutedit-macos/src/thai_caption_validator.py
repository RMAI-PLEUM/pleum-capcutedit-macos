"""Semantic validation for Thai caption plans and display-spacing rules."""

from __future__ import annotations

import re
from typing import Any

from thai_caption_text_renderer import (
    CLOSING_PUNCTUATION, MAI_YAMOK, display_normalized_thai,
)
from thai_lexical_regrouper import is_thai_mark, nfc


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", nfc(text))


def _add(
    errors: list[str], reason_codes: list[str], code: str, detail: str
) -> None:
    reason_codes.append(code)
    errors.append(f"{code}: {detail}")


def validate_thai_caption_plan(
    plan: dict[str, Any],
    canonical_transcript: str,
    lexical_words: list[dict[str, Any]],
    max_words: int = 16,
) -> dict[str, Any]:
    errors: list[str] = []
    reason_codes: list[str] = []
    captions = plan.get("captions") or []
    raw_canonical = nfc(canonical_transcript)
    display_canonical = display_normalized_thai(raw_canonical)
    raw_caption_text = "".join(str(item.get("text") or "") for item in captions)
    display_caption_text = display_normalized_thai(raw_caption_text)
    canonical_compact = _compact(display_canonical)
    caption_compact = _compact(display_caption_text)
    if caption_compact != canonical_compact:
        errors.append(
            "concatenated caption text does not match the display-normalized "
            "canonical transcript"
        )

    standalone_token_indices = [
        index for index, token in enumerate(lexical_words)
        if str(token.get("text") or "").strip() == MAI_YAMOK
    ]
    for index in standalone_token_indices:
        token = lexical_words[index]
        _add(
            errors, reason_codes, "THAI_MAI_YAMOK_COUNTED_AS_SEPARATE_WORD",
            f"lexical token {index} at {token.get('start')} is standalone",
        )

    lexical_boundaries: set[int] = set()
    position = 0
    for token in lexical_words:
        if str(token.get("text") or "").strip() == MAI_YAMOK:
            continue
        position += len(_compact(str(token.get("text") or "")))
        lexical_boundaries.add(position)

    caption_position = 0
    split_boundaries: list[int] = []
    previous_caption_position = 0
    closing = re.escape("".join(sorted(CLOSING_PUNCTUATION)))
    for index, caption in enumerate(captions, 1):
        text = nfc(str(caption.get("text") or ""))
        stripped = text.lstrip()
        if stripped.startswith(MAI_YAMOK):
            _add(
                errors, reason_codes, "THAI_MAI_YAMOK_STARTS_CAPTION",
                f"caption {index} starts with ๆ",
            )
        for line_number, line in enumerate(text.splitlines() or [text], 1):
            if line.lstrip().startswith(MAI_YAMOK) and not stripped.startswith(MAI_YAMOK):
                _add(
                    errors, reason_codes, "THAI_MAI_YAMOK_STARTS_CAPTION",
                    f"caption {index} line {line_number} starts with ๆ",
                )
        if re.search(r"\s+ๆ", text):
            _add(
                errors, reason_codes, "THAI_MAI_YAMOK_HAS_LEADING_SPACE",
                f"caption {index} contains whitespace before ๆ",
            )
        if re.search(rf"(^|\s)ๆ(?=$|\s|[{closing}])", text):
            _add(
                errors, reason_codes, "THAI_MAI_YAMOK_STANDALONE",
                f"caption {index} contains standalone ๆ",
            )
        if re.search(rf"ๆ(?=[^\s{closing}])", text):
            _add(
                errors, reason_codes, "THAI_MAI_YAMOK_MISSING_FOLLOWING_SPACE",
                f"caption {index} lacks one space after ๆ before a lexical word",
            )
        if re.search(r"ๆ[ \t]{2,}(?=\S)", text):
            _add(
                errors, reason_codes,
                "THAI_MAI_YAMOK_MULTIPLE_FOLLOWING_SPACES",
                f"caption {index} has multiple spaces after ๆ",
            )
        if text and is_thai_mark(text[0]):
            errors.append(f"caption {index}: begins with a Thai combining mark")
        if text and text[-1] in "เแโใไ":
            errors.append(f"caption {index}: ends with an incomplete Thai cluster")
        thai_cluster_has_base = False
        for character in text:
            if "\u0E00" <= character <= "\u0E7F":
                if is_thai_mark(character):
                    if not thai_cluster_has_base:
                        errors.append(
                            f"caption {index}: contains a standalone Thai mark "
                            f"{character!r}"
                        )
                else:
                    thai_cluster_has_base = True
            else:
                thai_cluster_has_base = False

        next_caption_position = caption_position + len(_compact(text))
        count = sum(
            1 for boundary in lexical_boundaries
            if previous_caption_position < boundary <= next_caption_position
        )
        if count > max_words:
            errors.append(
                f"caption {index}: contains {count} lexical words "
                f"(maximum {max_words})"
            )
        caption_position = next_caption_position
        if index < len(captions) and caption_position not in lexical_boundaries:
            split_boundaries.append(caption_position)
        previous_caption_position = caption_position

    for index in range(1, len(captions)):
        previous = str(captions[index - 1].get("text") or "")
        following = str(captions[index].get("text") or "")
        if following.lstrip().startswith(MAI_YAMOK) and previous.strip():
            _add(
                errors, reason_codes, "THAI_MAI_YAMOK_SPLIT_ACROSS_CAPTIONS",
                f"boundary between captions {index} and {index + 1} separates ๆ",
            )
    if split_boundaries:
        errors.append(
            "known lexical tokens are split across adjacent captions at compact "
            "offsets " + ", ".join(map(str, split_boundaries))
        )
    return {
        "valid": not errors,
        "errors": errors,
        "reason_codes": sorted(set(reason_codes)),
        "caption_count": len(captions),
        "lexical_token_count": len(lexical_words) - len(standalone_token_indices),
        "raw_canonical_transcript": raw_canonical,
        "display_normalized_canonical_transcript": display_canonical,
        "display_normalized_caption_text": display_caption_text,
        "canonical_text_matches": caption_compact == canonical_compact,
        "split_boundary_offsets": split_boundaries,
    }

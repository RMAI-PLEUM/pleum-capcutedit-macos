"""Central Thai caption rendering and Mai Yamok normalization."""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from typing import Any


MAI_YAMOK = "ๆ"
ATTACHED_REASON = "THAI_MAI_YAMOK_ATTACHED_TO_PREVIOUS_TOKEN"
CANONICAL_REASON = "THAI_MAI_YAMOK_FROM_CANONICAL_TEXT_NO_SEPARATE_TIMESTAMP"
CLOSING_PUNCTUATION = set(",.?!;:)]}»”’、。，！？ฯ")
TECHNICAL_RE = re.compile(
    r"https?://[^\s]+|www\.[^\s]+|(?:[A-Za-z]:[\\/]|[/\\])[^\s]+|"
    r"[A-Za-z0-9]+(?:[._/@:+#&'-][A-Za-z0-9]+)+"
)


class MaiYamokAttachmentError(ValueError):
    def __init__(self, token: dict[str, Any], index: int) -> None:
        self.token = token
        self.index = index
        super().__init__(
            "THAI_MAI_YAMOK_STANDALONE: no preceding lexical token "
            f"(timestamp={token.get('start')}, fragment_indices="
            f"{token.get('source_fragment_indices')}, token_index={index})"
        )


def _is_closing_punctuation(token: str) -> bool:
    return bool(token) and all(character in CLOSING_PUNCTUATION for character in token)


def _is_thai(token: str) -> bool:
    return bool(re.search(r"[\u0E00-\u0E7F]", token))


def attach_mai_yamok_tokens(
    tokens: list[dict[str, Any]],
    *,
    canonical_without_timestamp: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    output: list[dict[str, Any]] = []
    attached = standalone = 0
    for index, source in enumerate(tokens):
        token = deepcopy(source)
        text = unicodedata.normalize("NFC", str(token.get("text") or ""))
        token["text"] = text
        if text.startswith(MAI_YAMOK) and text != MAI_YAMOK:
            if text.startswith(MAI_YAMOK * 2):
                raise MaiYamokAttachmentError(token, index)
            if not output or not str(output[-1].get("text") or "").strip():
                raise MaiYamokAttachmentError(token, index)
            previous = output[-1]
            previous["text"] = str(previous["text"]).rstrip() + MAI_YAMOK
            previous_indices = list(previous.get("source_fragment_indices") or [])
            for fragment_index in token.get("source_fragment_indices") or []:
                if fragment_index not in previous_indices:
                    previous_indices.append(fragment_index)
            previous["source_fragment_indices"] = previous_indices
            previous["merge_reason"] = CANONICAL_REASON
            # The recognizer supplied no independent timestamp for the leading
            # Mai Yamok. Keep the following lexical text and its timing intact.
            token["text"] = text[1:]
            output.append(token)
            standalone += 1
            attached += 1
            continue
        if text != MAI_YAMOK:
            output.append(token)
            continue
        standalone += 1
        if not output or not str(output[-1].get("text") or "").strip():
            raise MaiYamokAttachmentError(token, index)
        previous = output[-1]
        previous["text"] = str(previous["text"]).rstrip() + MAI_YAMOK
        if token.get("start") is not None and token.get("end") is not None:
            previous["end"] = round(
                max(float(previous["end"]), float(token["end"])), 6
            )
            reason = ATTACHED_REASON
        else:
            reason = CANONICAL_REASON
        previous_indices = list(previous.get("source_fragment_indices") or [])
        for fragment_index in token.get("source_fragment_indices") or []:
            if fragment_index not in previous_indices:
                previous_indices.append(fragment_index)
        previous["source_fragment_indices"] = previous_indices
        if "char_end" in token:
            previous["char_end"] = token["char_end"]
        previous["merge_reason"] = (
            CANONICAL_REASON if canonical_without_timestamp else reason
        )
        attached += 1
    return output, {
        "standalone_mai_yamok_found": standalone,
        "mai_yamok_attached": attached,
    }


def render_thai_caption_tokens(tokens: list[dict[str, Any] | str]) -> str:
    text, _spans, _tokens = render_thai_caption_tokens_with_spans(tokens)
    return text


def render_thai_caption_tokens_with_spans(
    tokens: list[dict[str, Any] | str],
) -> tuple[str, list[dict[str, int]], list[dict[str, Any]]]:
    normalized: list[dict[str, Any]] = [
        item if isinstance(item, dict) else {"text": str(item)}
        for item in tokens
    ]
    attached, _stats = attach_mai_yamok_tokens(normalized)
    rendered = ""
    previous = ""
    spans: list[dict[str, int]] = []
    for item in attached:
        token = str(item.get("text") or "").strip()
        if not token:
            continue
        separator = ""
        if not rendered:
            pass
        elif _is_closing_punctuation(token):
            pass
        elif previous.endswith(MAI_YAMOK):
            separator = " "
        elif _is_thai(previous) and _is_thai(token):
            pass
        else:
            separator = " "
        rendered += separator
        start = len(rendered)
        rendered += token
        spans.append({"character_start": start, "character_end": len(rendered)})
        previous = token
    return rendered.strip(), spans, attached


def normalize_thai_caption_text(text: str) -> tuple[str, dict[str, int]]:
    """Normalize display spacing without touching protected technical strings."""
    original = unicodedata.normalize("NFC", str(text))
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group())
        return f"\uFFF0{len(protected) - 1}\uFFF1"

    value = TECHNICAL_RE.sub(protect, original)
    leading_matches = len(re.findall(r"\s+ๆ", value))
    multiple_matches = len(re.findall(r"ๆ[ \t]{2,}(?=\S)", value))
    missing_matches = len(
        re.findall(r"ๆ(?=[^\s,\.\?\!;:\)\]\}»”’、。，！？ฯ])", value)
    )
    value = re.sub(r"[ \t]+ๆ", "ๆ", value)
    value = re.sub(r"ๆ[ \t]+(?=[,\.\?\!;:\)\]\}»”’、。，！？ฯ])", "ๆ", value)
    value = re.sub(
        r"ๆ[ \t]*(?=[^\s,\.\?\!;:\)\]\}»”’、。，！？ฯ])", "ๆ ", value
    )
    value = re.sub(r"ๆ[ \t]{2,}", "ๆ ", value)
    value = re.sub(r"[ \t]{2,}", " ", value).strip()
    for index, protected_value in enumerate(protected):
        value = value.replace(f"\uFFF0{index}\uFFF1", protected_value)
    return value, {
        "leading_spaces_removed_before_mai_yamok": leading_matches,
        "missing_spaces_inserted_after_mai_yamok": missing_matches,
        "multiple_spaces_normalized_after_mai_yamok": multiple_matches,
    }


def display_normalized_thai(text: str) -> str:
    return normalize_thai_caption_text(text)[0]


def thai_lexical_word_count(tokens_or_text: list[Any] | str) -> int:
    if isinstance(tokens_or_text, list):
        tokens = [
            item if isinstance(item, dict) else {"text": str(item)}
            for item in tokens_or_text
            if str(item.get("text") if isinstance(item, dict) else item).strip()
        ]
        attached, _stats = attach_mai_yamok_tokens(tokens)
        return len(attached)
    normalized = display_normalized_thai(tokens_or_text)
    if not normalized:
        return 0
    # Used only when timed lexical tokens are unavailable. Thai runs remain
    # established caption words; Mai Yamok is never counted independently.
    parts = [part for part in re.split(r"\s+", normalized) if part]
    return sum(1 for part in parts if part != MAI_YAMOK)

"""Exact lexical phrase filtering for display-only caption cleanup."""

from __future__ import annotations

from typing import Any

from thai_lexical_regrouper import lexical_segments, nfc


def parse_excluded_caption_phrases(value: str | None) -> list[tuple[str, ...]]:
    phrases: list[tuple[str, ...]] = []
    for raw_phrase in str(value or "").split(","):
        phrase = nfc(raw_phrase.strip())
        if not phrase:
            continue
        tokens = tuple(
            token for token, _start, _end in lexical_segments(phrase) if token.strip()
        )
        if tokens and tokens not in phrases:
            phrases.append(tokens)
    return sorted(phrases, key=lambda item: (-len(item), item))


def filter_caption_lexical_words(
    lexical_words: list[dict[str, Any]],
    excluded_phrases: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Remove exact token sequences without changing source audio or timestamps."""
    phrases = parse_excluded_caption_phrases(excluded_phrases)
    texts = [nfc(str(item.get("text") or "").strip()) for item in lexical_words]
    removed = [False] * len(lexical_words)
    match_counts = {" ".join(phrase): 0 for phrase in phrases}
    index = 0
    while index < len(texts):
        matched: tuple[str, ...] | None = None
        for phrase in phrases:
            end = index + len(phrase)
            if end <= len(texts) and tuple(texts[index:end]) == phrase:
                matched = phrase
                break
        if matched is None:
            index += 1
            continue
        for remove_index in range(index, index + len(matched)):
            removed[remove_index] = True
        match_counts[" ".join(matched)] += 1
        index += len(matched)
    filtered = [item for item, is_removed in zip(lexical_words, removed) if not is_removed]
    report = {
        "mode": "exact_lexical_phrase_filter",
        "requested_phrases": [" ".join(phrase) for phrase in phrases],
        "phrase_match_counts": match_counts,
        "removed_token_count": sum(removed),
        "original_token_count": len(lexical_words),
        "remaining_token_count": len(filtered),
        "audio_modified": False,
    }
    return filtered, report

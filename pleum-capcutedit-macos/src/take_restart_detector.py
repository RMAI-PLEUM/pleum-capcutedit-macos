"""Configurable Thai restart-marker and disfluency detection."""

from __future__ import annotations

from typing import Any


def phrase_tokens(phrase: str) -> list[str]:
    from pythainlp.tokenize import word_tokenize
    return [token for token in word_tokenize(phrase, engine="newmm") if token.strip()]


def find_phrases(tokens: list[str], phrases: list[str]) -> list[str]:
    # Match complete lexical-token sequences.  Compact substring matching made
    # the generic marker "ผิด" fire inside ordinary phrases such as
    # "เข้าใจผิด", which then mislabeled unrelated following speech as a
    # restarted take.
    normalized = [token.casefold() for token in tokens if token.strip()]
    matches: list[str] = []
    for phrase in phrases:
        expected = [token.casefold() for token in phrase_tokens(phrase)]
        if not expected or len(expected) > len(normalized):
            continue
        if any(
            normalized[index:index + len(expected)] == expected
            for index in range(len(normalized) - len(expected) + 1)
        ):
            matches.append(phrase)
    return matches


def repeated_fragment(tokens: list[str]) -> dict[str, Any] | None:
    # Two immediately repeated 1-3 token fragments are treated as an internal
    # disfluency. Three repetitions are protected as possible emphasis.
    for width in range(3, 0, -1):
        for start in range(0, len(tokens) - width * 2 + 1):
            fragment = tokens[start:start + width]
            if fragment == tokens[start + width:start + width * 2]:
                third = tokens[start + width * 2:start + width * 3]
                if third == fragment:
                    return {
                        "tokens": fragment,
                        "start_index": start,
                        "deliberate_emphasis_possible": True,
                    }
                return {
                    "tokens": fragment,
                    "start_index": start,
                    "deliberate_emphasis_possible": False,
                }
    return None

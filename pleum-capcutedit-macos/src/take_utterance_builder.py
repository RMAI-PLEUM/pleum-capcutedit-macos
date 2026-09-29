"""Build bounded utterances from already-regrouped lexical timeline words."""

from __future__ import annotations

import math
import re
from typing import Any

from take_restart_detector import find_phrases


def normalize_token(text: str) -> str:
    import unicodedata
    value = unicodedata.normalize("NFC", text).casefold()
    return re.sub(r"[^\w\u0E00-\u0E7F]+", "", value)


def _join(tokens: list[str]) -> str:
    text = ""
    for token in tokens:
        if not text:
            text = token
        elif re.match(r"^[,.;:!?。！？ฯๆ)\]}]", token):
            text += token
        elif (
            re.search(r"[\u0E00-\u0E7F]$", text)
            and re.match(r"^[\u0E00-\u0E7F]", token)
        ):
            text += token
        else:
            text += " " + token
    return re.sub(r"\s+", " ", text).strip()


def _source_ids(word: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    midpoint = (float(word["start"]) + float(word["end"])) / 2
    return [
        str(segment["segment_id"])
        for segment in manifest.get("audible_segments", [])
        if float(segment["target_timerange"]["start"]) <= midpoint
        < float(segment["target_timerange"]["end"])
    ]


def _split_internal_restart(
    group: list[tuple[int, dict[str, Any]]],
) -> list[list[tuple[int, dict[str, Any]]]]:
    tokens = [normalize_token(str(word["text"])) for _, word in group]
    best: tuple[int, int, int] | None = None
    for first in range(len(tokens)):
        for second in range(first + 5, len(tokens)):
            length = 0
            while (
                first + length < second
                and second + length < len(tokens)
                and tokens[first + length]
                and tokens[first + length] == tokens[second + length]
            ):
                length += 1
            if length >= 5 and (best is None or length > best[2]):
                best = (first, second, length)
    if best is None:
        return [group]
    first, second, _length = best
    # Include a repeated lead token despite a one-token hesitation inserted
    # before the second common span (e.g. "นี่คือ..." / "นี่มันคือ...").
    first_start, second_start = first, second
    if first > 0 and second > 1 and tokens[first - 1] == tokens[second - 2]:
        first_start, second_start = first - 1, second - 2
    elif first > 0 and second > 0 and tokens[first - 1] == tokens[second - 1]:
        first_start, second_start = first - 1, second - 1
    pieces = [
        group[:first_start],
        group[first_start:second_start],
        group[second_start:],
    ]
    # Every lexical word must remain assigned to exactly one utterance. A
    # repeated span can legitimately begin after a single lead token; dropping
    # that singleton here makes read-only validation fail and hides content.
    return [piece for piece in pieces if piece]


def build_utterances(
    words: list[dict[str, Any]],
    manifest: dict[str, Any],
    fillers: list[str],
    restart_markers: list[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    if not words:
        return []
    groups: list[list[tuple[int, dict[str, Any]]]] = []
    current: list[tuple[int, dict[str, Any]]] = []
    for index, word in enumerate(words):
        sources = _source_ids(word, manifest)
        previous_sources = _source_ids(current[-1][1], manifest) if current else sources
        gap = (
            float(word["start"]) - float(current[-1][1]["end"])
            if current else 0.0
        )
        boundary = bool(current) and (
            gap > float(config["utterance_silence_gap"])
            or sources != previous_sources
            or float(word["end"]) - float(current[0][1]["start"])
            > float(config["maximum_utterance_duration"])
            or len(current) >= int(config["maximum_utterance_tokens"])
        )
        if boundary:
            groups.append(current)
            current = []
        current.append((index, word))
        current_texts = [str(item["text"]) for _, item in current]
        markers = find_phrases(current_texts, restart_markers)
        if (
            re.search(r"[.!?。！？ฯ]$", str(word["text"]))
            or markers
        ):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    groups = [
        piece
        for group in groups
        for piece in _split_internal_restart(group)
    ]

    utterances: list[dict[str, Any]] = []
    filler_compact = {"".join(normalize_token(x) for x in [filler]) for filler in fillers}
    for number, group in enumerate(groups, 1):
        indices = [index for index, _ in group]
        records = [word for _, word in group]
        texts = [str(word["text"]) for word in records]
        normalized = [normalize_token(text) for text in texts]
        normalized = [token for token in normalized if token]
        markers = find_phrases(texts, restart_markers)
        filler_count = sum(token in filler_compact for token in normalized)
        confidence_values = [
            float(word["confidence"]) for word in records
            if isinstance(word.get("confidence"), (int, float))
        ]
        internal_silence = sum(
            max(0.0, float(right["start"]) - float(left["end"]))
            for left, right in zip(records, records[1:])
        )
        source_ids = sorted({
            source for word in records for source in _source_ids(word, manifest)
        })
        meaningful = [
            token for token in normalized
            if token not in filler_compact
            and not find_phrases([token], restart_markers)
        ]
        text = _join(texts)
        utterances.append({
            "utterance_id": f"utt_{number:04d}",
            "start": round(float(records[0]["start"]), 6),
            "end": round(float(records[-1]["end"]), 6),
            "duration": round(float(records[-1]["end"]) - float(records[0]["start"]), 6),
            "text": text,
            "normalized_tokens": normalized,
            "meaningful_tokens": meaningful,
            "source_segment_ids": source_ids,
            "average_word_confidence": (
                round(sum(confidence_values) / len(confidence_values), 6)
                if confidence_values else None
            ),
            "internal_silence_seconds": round(internal_silence, 6),
            "restart_markers": markers,
            "filler_count": filler_count,
            "is_cut_off_start": bool(text and re.match(r"^[,.;:!?ฯๆ]", text)),
            "is_cut_off_end": bool(
                text and not re.search(r"[.!?。！？ฯ]$", text)
                and (
                    len(records) >= int(config["maximum_utterance_tokens"])
                    or float(records[-1]["end"]) - float(records[0]["start"])
                    >= float(config["maximum_utterance_duration"]) - 0.01
                )
            ),
            "word_indices": indices,
            "speaker": records[0].get("speaker_id"),
        })
    incomplete_endings = ("คือ", "การ", "ที่", "เป็น", "แล้วก็", "เพราะ")
    for index, utterance in enumerate(utterances[:-1]):
        following = utterances[index + 1]
        if (
            float(following["start"]) - float(utterance["end"])
            > float(config["utterance_silence_gap"])
            and any(utterance["text"].endswith(value) for value in incomplete_endings)
        ):
            utterance["is_cut_off_end"] = True
    return utterances

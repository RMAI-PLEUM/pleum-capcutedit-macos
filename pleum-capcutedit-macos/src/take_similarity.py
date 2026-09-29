"""Lexical-token similarity metrics for duplicate-take candidates."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any


def lcs_length(left: list[str], right: list[str]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = [0] * (len(right) + 1)
    for token in left:
        current = [0]
        for index, other in enumerate(right, 1):
            current.append(
                previous[index - 1] + 1
                if token == other else max(previous[index], current[-1])
            )
        previous = current
    return previous[-1]


def similarity_metrics(left: list[str], right: list[str]) -> dict[str, float]:
    if not left or not right:
        return {
            "sequence_similarity": 0.0,
            "lcs_ratio": 0.0,
            "prefix_overlap_ratio": 0.0,
            "shorter_containment_ratio": 0.0,
            "content_jaccard": 0.0,
        }
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    prefix = 0
    for first, second in zip(shorter, longer):
        if first != second:
            break
        prefix += 1
    common_lcs = lcs_length(left, right)
    left_set, right_set = set(left), set(right)
    try:
        from rapidfuzz.fuzz import ratio
        sequence_similarity = ratio("\u241f".join(left), "\u241f".join(right)) / 100
    except ImportError:
        sequence_similarity = SequenceMatcher(
            None, left, right, autojunk=False
        ).ratio()
    return {
        "sequence_similarity": round(sequence_similarity, 6),
        "lcs_ratio": round(common_lcs / max(len(left), len(right)), 6),
        "prefix_overlap_ratio": round(prefix / len(shorter), 6),
        "shorter_containment_ratio": round(
            sum(token in longer for token in shorter) / len(shorter), 6
        ),
        "content_jaccard": round(
            len(left_set & right_set) / max(1, len(left_set | right_set)), 6
        ),
    }


def pair_metrics(
    earlier: dict[str, Any], later: dict[str, Any]
) -> dict[str, float]:
    metrics = similarity_metrics(
        earlier["meaningful_tokens"], later["meaningful_tokens"]
    )
    durations = (float(earlier["duration"]), float(later["duration"]))
    metrics["duration_ratio"] = round(
        min(durations) / max(durations), 6
    ) if max(durations) else 0.0
    metrics["temporal_distance"] = round(
        float(later["start"]) - float(earlier["end"]), 6
    )
    return metrics

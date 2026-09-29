"""Explainable 0-100 quality scoring for competing spoken takes."""

from __future__ import annotations

from typing import Any

from take_restart_detector import repeated_fragment


def score_take(utterance: dict[str, Any], later_tie_break: bool = False) -> dict[str, Any]:
    tokens = utterance["meaningful_tokens"]
    complete = not utterance["is_cut_off_start"] and not utterance["is_cut_off_end"]
    confidence = utterance.get("average_word_confidence")
    components = {
        "completeness": 25.0 if complete else 8.0,
        "fluency": max(0.0, 20.0 - utterance["filler_count"] * 3.0),
        "word_confidence": (
            max(0.0, min(20.0, float(confidence) * 20.0))
            if confidence is not None else 12.0
        ),
        "clean_boundaries": (
            15.0
            if not utterance["is_cut_off_start"] and not utterance["is_cut_off_end"]
            else 5.0
        ),
        "internal_pause": max(
            0.0, 15.0 - float(utterance["internal_silence_seconds"]) * 8.0
        ),
        "content_completeness": min(4.0, len(tokens) * 0.25),
        "later_tie_break": 1.0 if later_tie_break else 0.0,
    }
    repeated = repeated_fragment(utterance["normalized_tokens"])
    penalties = {
        "filler_words": -min(12.0, utterance["filler_count"] * 2.0),
        "restart_marker": -30.0 if utterance["restart_markers"] else 0.0,
        "accidental_repetition": (
            -6.0 if repeated and not repeated["deliberate_emphasis_possible"] else 0.0
        ),
        "low_confidence": (
            -15.0
            if confidence is not None and float(confidence) < 0.45 else 0.0
        ),
    }
    total = max(0.0, min(100.0, sum(components.values()) + sum(penalties.values())))
    return {
        "total_score": round(total, 2),
        "components": {key: round(value, 2) for key, value in components.items()},
        "penalties": {key: round(value, 2) for key, value in penalties.items()},
    }


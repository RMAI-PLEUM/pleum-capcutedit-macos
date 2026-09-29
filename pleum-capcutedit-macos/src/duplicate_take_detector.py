"""Detect duplicate/restarted Thai takes from lexical utterances."""

from __future__ import annotations

import re
from typing import Any

from take_quality_scorer import score_take
from take_restart_detector import repeated_fragment
from take_similarity import pair_metrics


def _numbers(tokens: list[str]) -> set[str]:
    return {token for token in tokens if re.search(r"\d", token)}


def _shared_sources(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return bool(set(left["source_segment_ids"]) & set(right["source_segment_ids"]))


def detect_duplicate_takes(
    utterances: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    for index, utterance in enumerate(utterances):
        if utterance["is_cut_off_end"]:
            candidates.append({
                "earlier_utterance_id": utterance["utterance_id"],
                "later_utterance_id": None,
                "category": "abandoned_phrase",
                "confidence": 0.70,
                "metrics": {},
                "informational_only": True,
            })
        repetition = repeated_fragment(utterance["normalized_tokens"])
        if repetition and not repetition["deliberate_emphasis_possible"]:
            candidates.append({
                "earlier_utterance_id": utterance["utterance_id"],
                "later_utterance_id": utterance["utterance_id"],
                "category": "accidental_repeated_fragment",
                "confidence": 0.82,
                "metrics": {},
                "informational_only": True,
            })
        for later_index in range(index + 1, len(utterances)):
            later = utterances[later_index]
            distance = float(later["start"]) - float(utterance["end"])
            if distance > float(config["maximum_temporal_distance"]):
                break
            if (
                utterance.get("speaker") is not None
                and later.get("speaker") is not None
                and utterance["speaker"] != later["speaker"]
            ):
                continue
            metrics = pair_metrics(utterance, later)
            shared = _shared_sources(utterance, later)
            metrics["shared_source_segment_context"] = 1.0 if shared else 0.0
            shorter_count = min(
                len(utterance["meaningful_tokens"]), len(later["meaningful_tokens"])
            )
            matching_estimate = round(
                metrics["shorter_containment_ratio"] * shorter_count
            )
            category: str | None = None
            confidence = 0.0
            reasons: list[str] = []
            earlier = utterance
            keep = later
            drops = [utterance]
            earlier_numbers = _numbers(utterance["meaningful_tokens"])
            later_numbers = _numbers(later["meaningful_tokens"])
            different_facts = bool(
                earlier_numbers and later_numbers and earlier_numbers != later_numbers
            )
            correction = bool(
                set(later["restart_markers"]) & {"ไม่ใช่", "ผิด", "พูดผิด"}
            )
            shared_non_numeric = (
                set(utterance["meaningful_tokens"]) - earlier_numbers
            ) & (set(later["meaningful_tokens"]) - later_numbers)

            if different_facts and len(shared_non_numeric) >= int(
                config["minimum_meaningful_matching_tokens"]
            ):
                category = "correction_take" if correction else "similar_different_facts"
                confidence = 0.92 if correction else 0.70
                reasons = [
                    "LATER_TAKE_CORRECTS_INFORMATION"
                    if correction else "DIFFERENT_IMPORTANT_FACTS"
                ]

            explicit_restart_has_content_evidence = (
                (
                    matching_estimate
                    >= int(config["minimum_meaningful_matching_tokens"])
                    and metrics["shorter_containment_ratio"] >= float(
                        config.get("explicit_restart_minimum_containment", 0.60)
                    )
                )
                or metrics["prefix_overlap_ratio"] >= float(
                    config["explicit_restart_minimum_prefix_overlap"]
                )
                or metrics["sequence_similarity"] >= float(
                    config["explicit_restart_minimum_sequence_similarity"]
                )
            )
            if (
                category is None
                and utterance["restart_markers"]
                and distance <= float(config["explicit_restart_followup_window"])
                and explicit_restart_has_content_evidence
            ):
                category = "explicit_restart"
                confidence = max(0.90, metrics["shorter_containment_ratio"])
                reasons = [
                    "EARLIER_TAKE_HAS_RESTART_MARKER",
                    "RESTART_HAS_CONTENT_OVERLAP",
                ]
                if metrics["prefix_overlap_ratio"] >= 0.3:
                    reasons.append("LATER_TAKE_COMPLETES_PREFIX")
            elif category is None and (
                matching_estimate >= int(config["minimum_meaningful_matching_tokens"])
                and metrics["prefix_overlap_ratio"] >= float(config["partial_prefix_overlap"])
                and len(later["meaningful_tokens"]) > len(utterance["meaningful_tokens"])
            ):
                category = "prefix_restart"
                confidence = min(
                    0.98,
                    0.55 + metrics["prefix_overlap_ratio"] * 0.25
                    + metrics["shorter_containment_ratio"] * 0.20,
                )
                reasons = ["EARLIER_TAKE_INCOMPLETE", "LATER_TAKE_COMPLETES_PREFIX"]
            elif category is None and (
                metrics["sequence_similarity"] >= float(
                    config["complete_sequence_similarity"]
                )
                and metrics["content_jaccard"] >= float(
                    config["complete_meaningful_overlap"]
                )
                and float(config["minimum_duration_ratio"])
                <= metrics["duration_ratio"]
                <= 1.0
            ):
                category = "complete_duplicate"
                confidence = min(
                    0.97,
                    metrics["sequence_similarity"] * 0.55
                    + metrics["content_jaccard"] * 0.45,
                )
                reasons = ["NEAR_DUPLICATE_COMPLETE_TAKE"]
            elif category is None and (
                metrics["temporal_distance"] <= float(
                    config["internal_restart_max_gap"]
                )
                and metrics["lcs_ratio"] >= float(
                    config["internal_restart_lcs_ratio"]
                )
                and metrics["shorter_containment_ratio"] >= float(
                    config["internal_restart_containment_ratio"]
                )
                and metrics["content_jaccard"] >= float(
                    config["internal_restart_jaccard"]
                )
            ):
                category = "partial_repeated_take"
                confidence = min(
                    0.89,
                    0.35
                    + metrics["lcs_ratio"] * 0.25
                    + metrics["shorter_containment_ratio"] * 0.25
                    + metrics["content_jaccard"] * 0.15,
                )
                reasons = [
                    "NEARBY_REPEATED_THOUGHT",
                    "HIGH_SHORTER_TEXT_CONTAINMENT",
                    "LATER_TAKE_REPHRASES_EARLIER_TAKE",
                ]
            if category is None:
                continue

            # Important numeric differences are protected unless the later
            # utterance explicitly signals a correction.
            if different_facts and not correction:
                confidence = min(confidence, 0.70)
                if "DIFFERENT_IMPORTANT_FACTS" not in reasons:
                    reasons.append("DIFFERENT_IMPORTANT_FACTS")
            elif different_facts and correction:
                category = "correction_take"
                confidence = max(confidence, 0.92)
                if "LATER_TAKE_CORRECTS_INFORMATION" not in reasons:
                    reasons.append("LATER_TAKE_CORRECTS_INFORMATION")
            confidences = (
                utterance.get("average_word_confidence"),
                later.get("average_word_confidence"),
            )
            if any(
                value is not None
                and float(value) < float(config["low_confidence_threshold"])
                for value in confidences
            ):
                confidence = min(confidence, 0.70)
                reasons.append("TRANSCRIPT_CONFIDENCE_TOO_LOW")

            earlier_score = score_take(earlier)
            later_score = score_take(keep, later_tie_break=True)
            if earlier_score["total_score"] > later_score["total_score"] + 3:
                keep, drops = earlier, [later]
                reasons.append("EARLIER_TAKE_HIGHER_QUALITY")
            else:
                reasons.append("LATER_TAKE_HIGHER_QUALITY")
            candidate = {
                "earlier_utterance_id": utterance["utterance_id"],
                "later_utterance_id": later["utterance_id"],
                "category": category,
                "confidence": round(confidence, 4),
                "metrics": metrics,
                "reason_codes": reasons,
            }
            candidates.append(candidate)
            minimum = float(config["minimum_drop_confidence"])
            high = confidence >= float(config["high_confidence"])
            medium = confidence >= float(config["medium_confidence"])
            recommend = confidence >= minimum
            groups.append({
                "group_id": f"take_group_{len(groups) + 1:04d}",
                "category": category,
                "confidence": round(confidence, 4),
                "recommended_keep_utterance_id": keep["utterance_id"],
                "recommended_drop_utterance_ids": (
                    [item["utterance_id"] for item in drops] if recommend else []
                ),
                "reason_codes": reasons,
                "review_required": medium and not high,
                "confidence_class": (
                    "high" if high else "medium" if medium else "low"
                ),
                "takes": [
                    {
                        "utterance": utterance,
                        "quality_score": earlier_score,
                    },
                    {
                        "utterance": later,
                        "quality_score": later_score,
                    },
                ],
            })
    return candidates, groups

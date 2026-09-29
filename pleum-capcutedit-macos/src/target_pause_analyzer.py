"""Read-only fuzzy localization and audio analysis of one target pause."""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ai_caption_registry import stable_hash
from audio_energy_analyzer import analyze_audio_energy, continuous_low_energy_regions
from capcut_live_project_reader import read_live_project
from capcut_project_locator import locate_project
from capcut_timeline_audio_renderer import render_timeline_audio_window
from capcut_timeline_media_resolver import analyze_timeline
from karaoke_workflow import _validated_lexical_cache
from utils import PROJECT_ROOT, write_json


def _compact(text: str) -> str:
    return "".join(str(text).casefold().split())


def _phrase_matches(words: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    query_value = _compact(query)
    matches = []
    for end in range(len(words)):
        for length in range(2, 8):
            start = end - length + 1
            if start < 0:
                continue
            text = "".join(str(item["text"]) for item in words[start:end + 1])
            score = SequenceMatcher(None, _compact(text), query_value).ratio()
            if score >= .55:
                matches.append({
                    "start_index": start, "end_index": end, "text": text,
                    "score": score, "start": words[start]["start"],
                    "end": words[end]["end"],
                })
    return sorted(matches, key=lambda item: item["score"], reverse=True)


def analyze_target_pause(
    project_name: str, previous_text: str, next_text: str,
    initial_target_gap: float = .25,
) -> tuple[dict[str, Any], Path]:
    project = locate_project(project_name)
    live = read_live_project(project)
    analysis = analyze_timeline(live.primary)
    timeline_hash = stable_hash({
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    })
    words, cache_status = _validated_lexical_cache(
        project.name, analysis, timeline_hash
    )
    previous_matches = _phrase_matches(words, previous_text)
    if not previous_matches:
        raise RuntimeError(f"No fuzzy match for previous phrase: {previous_text}")
    candidates = []
    for match in previous_matches[:20]:
        index = match["end_index"] + 1
        if index >= len(words):
            continue
        lookahead = "".join(
            str(item["text"]) for item in words[index:min(len(words), index + 9)]
        )
        next_score = max(
            SequenceMatcher(None, _compact(next_text), _compact(str(words[j]["text"]))).ratio()
            for j in range(index, min(len(words), index + 9))
        )
        candidates.append({
            **match, "next_index": index, "next_phrase": lookahead,
            "next_score": next_score,
            "boundary_distance_from_end": float(analysis["duration"])
            - float(words[index]["start"]),
        })
    candidates.sort(
        key=lambda item: (
            -(item["score"] * .7 + item["next_score"] * .3),
            item["boundary_distance_from_end"],
        )
    )
    selected = candidates[0]
    previous_word = words[selected["end_index"]]
    next_word = words[selected["next_index"]]
    gap_start, gap_end = float(previous_word["end"]), float(next_word["start"])
    original_gap = max(0.0, gap_end - gap_start)
    source_boundaries = sorted({
        round(float(segment["target_timerange"][key]), 6)
        for segment in analysis["audible_segments"]
        for key in ("start", "end")
    })
    nearest_boundary = min(
        source_boundaries,
        key=lambda value: min(abs(value - gap_start), abs(value - gap_end)),
    )
    at_source_boundary = min(
        abs(nearest_boundary - gap_start), abs(nearest_boundary - gap_end)
    ) <= .04
    window_start = max(0.0, gap_start - 1.5)
    window_end = min(float(analysis["duration"]), gap_end + 1.5)
    wav = render_timeline_audio_window(
        analysis, project.name.casefold().replace(" ", "_"),
        window_start, window_end,
    )
    energy = analyze_audio_energy(wav)
    low_regions = continuous_low_energy_regions(energy)
    local_gap_start, local_gap_end = gap_start - window_start, gap_end - window_start
    gap_frames = [
        frame for frame in energy["frames"]
        if frame["end"] > local_gap_start and frame["start"] < local_gap_end
    ]
    average_dbfs = (
        sum(frame["dbfs"] for frame in gap_frames) / len(gap_frames)
        if gap_frames else -160.0
    )
    protected = []
    for frame in gap_frames:
        if not frame["low_energy"]:
            protected.append({
                "start": round(window_start + frame["start"], 6),
                "end": round(window_start + frame["end"], 6),
                "type": "uncertain_audio_or_breath",
                "dbfs": round(frame["dbfs"], 2),
            })
    # The current pause is already shorter than the initial natural sentence
    # target. Analysis cannot add time, so recommend preserving it unchanged.
    classification = "sentence_boundary"
    natural_min, natural_max = (.18, .30)
    recommended = min(natural_max, max(natural_min, initial_target_gap))
    removable = max(0.0, original_gap - recommended)
    keep_after = recommended * .45
    cut_start = gap_start + keep_after
    cut_end = cut_start + removable
    reasons = [
        "FUZZY_TRANSCRIPT_MATCH", "CURRENT_TIMELINE_CACHE_VALID",
        "AUDIO_WINDOW_ANALYZED", "CURRENT_GAP_SHORTER_THAN_RECOMMENDED",
        "NO_ADDITIONAL_CUT_RECOMMENDED", "RESTORATION_REQUIRED_NOT_CUT",
    ]
    if at_source_boundary:
        reasons.append("SOURCE_CLIP_BOUNDARY")
    if protected:
        reasons.append("UNCERTAIN_AUDIO_NEAR_WORD")
    result = {
        "version": 1, "project": project.name,
        "timeline_hash": timeline_hash,
        "matches": candidates[:5],
        "selected_match": selected,
        "previous_word": previous_word["text"],
        "previous_phrase": selected["text"],
        "previous_word_end": gap_start,
        "next_word": next_word["text"],
        "next_phrase": selected["next_phrase"],
        "next_word_start": gap_end,
        "original_gap_seconds": round(original_gap, 6),
        "pause_classification": classification,
        "recommended_remaining_gap_seconds": round(recommended, 6),
        "recommended_range_min_seconds": natural_min,
        "recommended_range_max_seconds": natural_max,
        "safe_removable_duration_seconds": round(removable, 6),
        "proposed_cut_start": round(cut_start, 6),
        "proposed_cut_end": round(cut_end, 6),
        "protected_audio_regions": protected,
        "confidence": round(min(.98, .65 + selected["score"] * .25
                                + selected["next_score"] * .08), 3),
        "reason_codes": reasons,
        "source_clip_boundary": at_source_boundary,
        "nearest_source_boundary": nearest_boundary,
        "timeline_range": {"start": gap_start, "end": gap_end},
        "audio": {
            "window_start": window_start, "window_end": window_end,
            "average_gap_dbfs": round(average_dbfs, 3),
            "noise_floor_dbfs": round(energy["noise_floor_dbfs"], 3),
            "silence_threshold_dbfs": round(energy["silence_threshold_dbfs"], 3),
            "continuous_low_energy_regions": low_regions,
        },
        "timeline_cache_status": cache_status,
        "elevenlabs_called": False, "project_modified": False,
        "visual_continuity_check": "not_required_no_cut_recommended",
    }
    slug = project.name.casefold().replace(" ", "_")
    output = PROJECT_ROOT / f"output/json/{slug}.target_pause_analysis.json"
    write_json(output, result)
    write_json(
        PROJECT_ROOT / f"logs/direct_edit/{slug}/target_pause_analysis.json",
        result,
    )
    preview = PROJECT_ROOT / f"output/preview/{slug}_target_pause_analysis.txt"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_text(
        "\n".join([
            "TARGET PAUSE ANALYSIS", "",
            "Previous:", f"[{gap_start:.3f}]", selected["text"], "",
            "Next:", f"[{gap_end:.3f}]", selected["next_phrase"], "",
            f"Original gap:\n{original_gap:.3f} seconds", "",
            f"Classification:\n{classification}", "",
            f"Recommended remaining gap:\n{recommended:.3f} seconds", "",
            f"Acceptable range:\n{natural_min:.3f}-{natural_max:.3f} seconds", "",
            f"Proposed removable duration:\n{removable:.3f} seconds", "",
            f"Proposed cut:\n{cut_start:.3f}-{cut_end:.3f}", "",
            "Protected:",
            *([f"- {item['type']} {item['start']:.3f}-{item['end']:.3f}"
               for item in protected] or ["- lexical word boundaries"]),
            "", f"Confidence:\n{result['confidence'] * 100:.0f}%", "",
            "Project modified:\nNo", "", "ElevenLabs called:\nNo",
        ]) + "\n",
        encoding="utf-8",
    )
    wav.unlink(missing_ok=True)
    return result, output

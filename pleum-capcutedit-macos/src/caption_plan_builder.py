"""Build timeline-coordinate caption plans from timeline-aligned STT words."""

from __future__ import annotations

import math
import re
from typing import Any

from script_aligner import align_script
from script_chunker import chunk_script
from timeline_mapper import clip_for_timeline_time, iter_timeline_clips
from thai_caption_text_renderer import (
    attach_mai_yamok_tokens, normalize_thai_caption_text,
    render_thai_caption_tokens, thai_lexical_word_count,
)


DEFAULT_MEDIA_CAPTION_CONFIG = {
    "max_words_per_cue": 16,
    "min_duration": 0.60,
    "max_duration": 3.50,
    "silence_boundary": 0.45,
}


def _join_words(words: list[dict[str, Any]]) -> str:
    """Render lexical tokens with the global Thai display-spacing rules."""
    return render_thai_caption_tokens(words)


def _confidence(words: list[dict[str, Any]]) -> float:
    values = [
        max(0.0, min(1.0, math.exp(float(word["logprob"]))))
        for word in words if isinstance(word.get("logprob"), (int, float))
    ]
    return round(sum(values) / len(values), 4) if values else 0.75


def _auto_cues(
    words: list[dict[str, Any]], clips: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    words, _mai_yamok_stats = attach_mai_yamok_tokens(words)
    max_words = int(config["max_words_per_cue"])
    max_duration = float(config["max_duration"])
    silence_boundary = float(config.get("silence_boundary", 0.65))
    grouped: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    current: list[dict[str, Any]] = []
    current_clip: dict[str, Any] | None = None
    for word in words:
        midpoint = (float(word["start"]) + float(word["end"])) / 2
        clip = clip_for_timeline_time(midpoint, clips)
        if clip is None:
            continue
        boundary = (
            current_clip is not None
            and (
                clip.get("segment_id") != current_clip.get("segment_id")
                or float(word["start"]) - float(current[-1]["end"]) >= silence_boundary
                or float(word["end"]) - float(current[0]["start"]) > max_duration
                or thai_lexical_word_count(current + [word]) > max_words
            )
        )
        if boundary:
            grouped.append((current_clip, current))
            current = []
        current_clip = clip
        current.append(word)
        if re.search(r"[.!?。！？ฯ]$", str(word["text"])) and thai_lexical_word_count(current) >= 3:
            grouped.append((current_clip, current))
            current, current_clip = [], None
    if current and current_clip:
        grouped.append((current_clip, current))

    cues = []
    for clip, group in grouped:
        target = clip["timeline_range"]
        start = max(target["start"], float(group[0]["start"]) - 0.03)
        end = min(target["end"], float(group[-1]["end"]) + 0.10)
        minimum = float(config["min_duration"])
        end = min(target["end"], max(end, start + minimum))
        if end > start:
            cues.append({
                "start": start,
                "end": end,
                "text": _join_words(group),
                "track_index": clip["track_index"],
                "source_clip_id": clip.get("segment_id"),
                "confidence": _confidence(group),
            })
    return cues


def _script_cues(
    script: str,
    words: list[dict[str, Any]],
    clips: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    script = normalize_thai_caption_text(script)[0]
    chunks = chunk_script(script, int(config["max_words_per_cue"]))
    aligned, debug = align_script(chunks, words, {
        "lead_in": 0.03,
        "tail_out": 0.10,
        "min_duration": config["min_duration"],
        "max_duration": config["max_duration"],
    })
    cues = []
    for cue, detail in zip(aligned, debug):
        midpoint = (float(cue["start"]) + float(cue["end"])) / 2
        clip = clip_for_timeline_time(midpoint, clips)
        if clip is None:
            continue
        target = clip["timeline_range"]
        start = max(target["start"], float(cue["start"]))
        end = min(target["end"], float(cue["end"]))
        if end > start:
            cues.append({
                "start": start,
                "end": end,
                "text": cue["text"],
                "track_index": clip["track_index"],
                "source_clip_id": clip.get("segment_id"),
                "confidence": float(detail.get("confidence", 0.0)),
            })
    return cues


def build_caption_plan(
    timeline: dict[str, Any],
    words: list[dict[str, Any]],
    project_duration: float,
    caption_config: dict[str, Any],
    script: str | None = None,
) -> dict[str, Any]:
    clips = list(iter_timeline_clips(timeline))
    cues = (
        _script_cues(script, words, clips, caption_config)
        if script else _auto_cues(words, clips, caption_config)
    )
    captions = []
    previous_end = 0.0
    for index, cue in enumerate(sorted(cues, key=lambda item: item["start"]), 1):
        start = max(previous_end, float(cue["start"]))
        end = min(project_duration, float(cue["end"]))
        if end <= start:
            continue
        captions.append({
            "id": f"caption_{index:04d}",
            "start": round(start, 6),
            "end": round(end, 6),
            "text": normalize_thai_caption_text(cue["text"])[0],
            "track_index": cue["track_index"],
            "source_clip_id": cue["source_clip_id"],
            "confidence": round(float(cue["confidence"]), 4),
            "style_preset": "default",
        })
        previous_end = end
    return {"version": 1, "project_duration": project_duration, "captions": captions}


def _group_media_words(
    words: list[dict[str, Any]], config: dict[str, Any]
) -> list[list[dict[str, Any]]]:
    words, _mai_yamok_stats = attach_mai_yamok_tokens(words)
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        boundary = bool(current) and (
            float(word["start"]) - float(current[-1]["end"])
            > float(config["silence_boundary"])
            or float(word["end"]) - float(current[0]["start"])
            > float(config["max_duration"])
            or thai_lexical_word_count(current + [word])
            > int(config["max_words_per_cue"])
        )
        if boundary:
            groups.append(current)
            current = []
        current.append(word)
        if (
            re.search(r"[.!?。！？ฯ]$", str(word["text"]))
            and thai_lexical_word_count(current) >= 2
        ):
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    # Avoid one-word micro-captions where merging remains within all limits.
    merged: list[list[dict[str, Any]]] = []
    for group in groups:
        if (
            len(group) == 1
            and merged
            and float(group[-1]["end"]) - float(merged[-1][0]["start"])
            <= float(config["max_duration"])
            and thai_lexical_word_count(merged[-1] + group)
            <= int(config["max_words_per_cue"])
            and float(group[0]["start"]) - float(merged[-1][-1]["end"])
            <= float(config["silence_boundary"])
        ):
            merged[-1].extend(group)
        else:
            merged.append(group)
    return merged


def build_media_caption_plan(
    media_path: str,
    duration: float,
    words: list[dict[str, Any]],
    script: str | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    settings = {**DEFAULT_MEDIA_CAPTION_CONFIG, **(config or {})}
    alignment_log: list[dict[str, Any]] = []
    if script is None:
        raw_cues = [
            {
                "start": float(group[0]["start"]),
                "end": float(group[-1]["end"]),
                "text": _join_words(group),
            }
            for group in _group_media_words(words, settings)
        ]
    else:
        script = normalize_thai_caption_text(script)[0]
        chunks = chunk_script(script, int(settings["max_words_per_cue"]))
        raw_cues, alignment_log = align_script(chunks, words, {
            "lead_in": 0.0,
            "tail_out": 0.0,
            "min_duration": settings["min_duration"],
            "max_duration": settings["max_duration"],
        })

    captions: list[dict[str, Any]] = []
    previous_end = 0.0
    for cue in raw_cues:
        start = max(previous_end, 0.0, float(cue["start"]))
        if start >= duration:
            continue
        natural_end = min(duration, float(cue["end"]))
        end = min(
            duration,
            max(natural_end, start + float(settings["min_duration"])),
        )
        text = normalize_thai_caption_text(str(cue["text"]))[0]
        if not text or end <= start:
            continue
        captions.append({
            "id": f"caption_{len(captions) + 1:04d}",
            "start": round(start, 6),
            "end": round(end, 6),
            "text": text,
            "style_preset": "fixture_default",
        })
        previous_end = end
    return {
        "version": 1,
        "source": {
            "media_path": str(media_path),
            "duration": round(float(duration), 6),
            "provider": "elevenlabs",
            "model": "scribe_v2",
        },
        "captions": captions,
    }, alignment_log


def build_regrouped_caption_plan(
    media_path: str,
    duration: float,
    canonical_transcript: str,
    lexical_words: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build cues only at already validated lexical-token boundaries."""
    lexical_words, _mai_yamok_stats = attach_mai_yamok_tokens(lexical_words)
    settings = {**DEFAULT_MEDIA_CAPTION_CONFIG, **(config or {})}
    # A fixed display minimum is incompatible with true one-word captions:
    # rapid speech can contain more than one lexical token inside that minimum,
    # causing the timing cursor to run past later words. Use each token's proven
    # STT interval unless the caller explicitly requests another minimum.
    if int(settings["max_words_per_cue"]) == 1 and not (
        config and "min_duration" in config
    ):
        settings["min_duration"] = 0.0
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for token in lexical_words:
        gap = (
            float(token["start"]) - float(current[-1]["end"])
            if current else 0.0
        )
        would_exceed_words = len(current) >= int(settings["max_words_per_cue"])
        would_exceed_duration = bool(current) and (
            float(token["end"]) - float(current[0]["start"])
            > float(settings["max_duration"])
        )
        if current and (
            gap > float(settings["silence_boundary"])
            or would_exceed_words
            or would_exceed_duration
        ):
            groups.append(current)
            current = []
        current.append(token)
        if re.search(r"[.!?。！？ฯ]$", str(token["text"])) and len(current) >= 2:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    # Rebalance avoidable one-token groups without crossing real silence,
    # lexical boundaries, the word limit, or preferred cue duration.
    index = 0
    while index < len(groups):
        group = groups[index]
        if len(group) != 1:
            index += 1
            continue
        merged = False
        if index + 1 < len(groups):
            following = groups[index + 1]
            gap = float(following[0]["start"]) - float(group[-1]["end"])
            combined = group + following
            if (
                gap <= float(settings["silence_boundary"])
                and len(combined) <= int(settings["max_words_per_cue"])
                and float(combined[-1]["end"]) - float(combined[0]["start"])
                <= float(settings["max_duration"])
            ):
                groups[index:index + 2] = [combined]
                merged = True
        if not merged and index > 0:
            previous = groups[index - 1]
            gap = float(group[0]["start"]) - float(previous[-1]["end"])
            combined = previous + group
            if (
                gap <= float(settings["silence_boundary"])
                and len(combined) <= int(settings["max_words_per_cue"])
                and float(combined[-1]["end"]) - float(combined[0]["start"])
                <= float(settings["max_duration"])
            ):
                groups[index - 1:index + 1] = [combined]
                index -= 1
                merged = True
        if not merged:
            index += 1

    captions: list[dict[str, Any]] = []
    previous_end = 0.0
    canonical = str(canonical_transcript)
    for group in groups:
        start = max(previous_end, float(group[0]["start"]))
        if start >= duration:
            continue
        end = min(duration, float(group[-1]["end"]))
        end = min(duration, max(end, start + float(settings["min_duration"])))
        if end <= start:
            continue
        text = render_thai_caption_tokens(group)
        if not text:
            continue
        captions.append({
            "id": f"caption_{len(captions) + 1:04d}",
            "start": round(start, 6),
            "end": round(end, 6),
            "text": text,
            "style_preset": "fixture_default",
        })
        previous_end = end
    return {
        "version": 1,
        "source": {
            "media_path": str(media_path),
            "duration": round(float(duration), 6),
            "provider": "elevenlabs",
            "model": "scribe_v2",
        },
        "captions": captions,
    }

"""Create manual-review silence cut candidates in timeline coordinates."""

from __future__ import annotations

from typing import Any

from timeline_mapper import clip_for_timeline_time, iter_timeline_clips


def build_cut_plan(
    timeline: dict[str, Any],
    words: list[dict[str, Any]],
    project_duration: float,
    cut_config: dict[str, Any],
) -> dict[str, Any]:
    clips = list(iter_timeline_clips(timeline))
    words_by_clip: dict[str, list[dict[str, Any]]] = {}
    for word in words:
        midpoint = (float(word["start"]) + float(word["end"])) / 2
        clip = clip_for_timeline_time(midpoint, clips)
        if clip and clip.get("segment_id"):
            words_by_clip.setdefault(str(clip["segment_id"]), []).append(word)

    threshold = float(cut_config["silence_threshold"])
    padding = float(cut_config["speech_padding"])
    minimum = float(cut_config["minimum_cut_duration"])
    review_below = float(cut_config["require_review_below_confidence"])
    candidates: list[dict[str, Any]] = []
    for clip in clips:
        clip_id = str(clip.get("segment_id") or "")
        speech = sorted(words_by_clip.get(clip_id, []), key=lambda word: word["start"])
        # No speech means music/ambience/unknown: never propose automatic removal.
        if len(speech) < 2:
            continue
        target = clip["timeline_range"]
        for left, right in zip(speech, speech[1:]):
            raw_gap = float(right["start"]) - float(left["end"])
            if raw_gap < threshold:
                continue
            start = max(target["start"], float(left["end"]) + padding)
            end = min(target["end"], float(right["start"]) - padding)
            duration = end - start
            if duration < minimum:
                continue
            confidence = round(min(0.99, 0.72 + min(raw_gap, 3.0) / 15.0), 4)
            candidates.append({
                "action": "remove",
                "timeline_start": round(start, 6),
                "timeline_end": round(end, 6),
                "reason": "silence",
                "confidence": confidence,
                "source_clip_id": clip_id,
                "requires_review": confidence < review_below,
            })
    cuts = []
    for index, cut in enumerate(sorted(candidates, key=lambda item: item["timeline_start"]), 1):
        if cuts and cut["timeline_start"] < cuts[-1]["timeline_end"]:
            continue
        cuts.append({"id": f"cut_{index:04d}", **cut})
    return {"version": 1, "project_duration": project_duration, "cuts": cuts}

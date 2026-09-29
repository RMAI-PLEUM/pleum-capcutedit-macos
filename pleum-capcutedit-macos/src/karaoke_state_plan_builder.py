"""Build sequential normal/highlight state segments for caption cues."""

from __future__ import annotations

from typing import Any


def _resolve_word_overlaps(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [dict(word) for word in words]
    for left, right in zip(result, result[1:]):
        overlap = float(left["end"]) - float(right["start"])
        if overlap <= 0:
            continue
        if overlap > 0.0200001:
            raise RuntimeError(
                f"Word timestamp overlap exceeds 0.020s: "
                f"{left['word_id']} -> {right['word_id']} ({overlap:.6f}s)"
            )
        midpoint = (float(left["end"]) + float(right["start"])) / 2
        left["end"] = round(midpoint, 6)
        right["start"] = round(midpoint, 6)
    return result


def build_karaoke_state_plan(
    project_name: str,
    timeline_hash: str,
    duration: float,
    preset_id: str,
    captions: list[dict[str, Any]],
) -> dict[str, Any]:
    cues: list[dict[str, Any]] = []
    state_number = 1
    for caption in captions:
        cue_start, cue_end = float(caption["start"]), float(caption["end"])
        words = [
            {
                **word,
                "start": max(cue_start, float(word["start"])),
                "end": min(cue_end, float(word["end"])),
            }
            for word in caption.get("words") or []
            if word.get("highlightable")
        ]
        words = [word for word in words if word["end"] > word["start"]]
        words = _resolve_word_overlaps(words)
        states: list[dict[str, Any]] = []
        cursor = cue_start
        for word in words:
            start, end = float(word["start"]), float(word["end"])
            if start > cursor + 0.000001:
                states.append({
                    "state_id": f"karaoke_state_{state_number:06d}",
                    "type": "normal", "start": round(cursor, 6),
                    "end": round(start, 6), "active_word_id": None,
                    "active_utf16_start": None, "active_utf16_length": None,
                })
                state_number += 1
            states.append({
                "state_id": f"karaoke_state_{state_number:06d}",
                "type": "highlight", "start": round(start, 6),
                "end": round(end, 6), "active_word_id": word["word_id"],
                "active_word_text": word["text"],
                "active_utf16_start": word["utf16_start"],
                "active_utf16_length": word["utf16_length"],
            })
            state_number += 1
            cursor = end
        if cursor < cue_end - 0.000001:
            states.append({
                "state_id": f"karaoke_state_{state_number:06d}",
                "type": "normal", "start": round(cursor, 6),
                "end": round(cue_end, 6), "active_word_id": None,
                "active_utf16_start": None, "active_utf16_length": None,
            })
            state_number += 1
        if not states:
            states.append({
                "state_id": f"karaoke_state_{state_number:06d}",
                "type": "normal", "start": round(cue_start, 6),
                "end": round(cue_end, 6), "active_word_id": None,
                "active_utf16_start": None, "active_utf16_length": None,
            })
            state_number += 1
        cues.append({
            "caption_id": caption["id"], "text": caption["text"],
            "start": cue_start, "end": cue_end,
            "words": caption.get("words") or [], "states": states,
        })
    return {
        "version": 1,
        "project": {
            "name": project_name, "timeline_hash": timeline_hash,
            "duration": duration,
        },
        "preset": preset_id,
        "cues": cues,
    }

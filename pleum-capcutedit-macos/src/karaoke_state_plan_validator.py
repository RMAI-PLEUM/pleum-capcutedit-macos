"""Strict validation of continuous single-word karaoke state plans."""

from __future__ import annotations

from typing import Any
from karaoke_state_plan_optimizer import MIN_NORMAL_STATE_SECONDS


def validate_karaoke_state_plan(plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    normal = highlight = words = 0
    for cue_index, cue in enumerate(plan.get("cues") or [], 1):
        states = cue.get("states") or []
        cursor = float(cue["start"])
        total_utf16 = len(str(cue["text"]).encode("utf-16-le")) // 2
        word_index = {
            word["word_id"]: word for word in cue.get("words") or []
        }
        words += len(word_index)
        for state_index, state in enumerate(states, 1):
            start, end = float(state["start"]), float(state["end"])
            if end <= start:
                errors.append(f"cue {cue_index} state {state_index}: non-positive duration")
            if abs(start - cursor) > 0.000001:
                errors.append(f"cue {cue_index}: state coverage gap/overlap at {start}")
            if state["type"] == "highlight":
                highlight += 1
                word = word_index.get(state.get("active_word_id"))
                if word is None or not word.get("highlightable"):
                    errors.append(f"cue {cue_index}: invalid active lexical word")
                range_start = state.get("active_utf16_start")
                range_length = state.get("active_utf16_length")
                if (
                    not isinstance(range_start, int)
                    or not isinstance(range_length, int)
                    or range_length <= 0
                    or range_start < 0
                    or range_start + range_length > total_utf16
                ):
                    errors.append(f"cue {cue_index}: invalid UTF-16 highlight range")
            else:
                normal += 1
                if end - start < MIN_NORMAL_STATE_SECONDS - 0.000001:
                    errors.append(
                        f"cue {cue_index}: normal state is shorter than "
                        f"{MIN_NORMAL_STATE_SECONDS:.3f}s"
                    )
                if state.get("active_word_id") is not None:
                    errors.append(f"cue {cue_index}: normal state has active word")
            cursor = end
        if abs(cursor - float(cue["end"])) > 0.000001:
            errors.append(f"cue {cue_index}: states do not cover cue end")
    return {
        "valid": not errors, "errors": errors,
        "caption_count": len(plan.get("cues") or []),
        "lexical_word_count": words,
        "normal_state_count": normal,
        "highlight_state_count": highlight,
        "generated_segment_count": normal + highlight,
        "utf16_ranges_valid": not any("UTF-16" in error for error in errors),
    }

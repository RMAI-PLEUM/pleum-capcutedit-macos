"""Optimize sub-frame karaoke normal states before CapCut injection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


MIN_NORMAL_STATE_SECONDS = 0.040


def optimize_karaoke_state_plan(
    plan: dict[str, Any],
    minimum_normal_state: float = MIN_NORMAL_STATE_SECONDS,
) -> tuple[dict[str, Any], dict[str, int]]:
    optimized = deepcopy(plan)
    removed = zero_removed = boundaries_adjusted = 0
    for cue in optimized.get("cues") or []:
        states = cue.get("states") or []
        output: list[dict[str, Any]] = []
        index = 0
        while index < len(states):
            state = deepcopy(states[index])
            duration = float(state["end"]) - float(state["start"])
            if duration <= 0:
                zero_removed += 1
                index += 1
                continue
            if (
                state["type"] == "normal"
                and duration < minimum_normal_state
            ):
                if (
                    output and index + 1 < len(states)
                    and output[-1]["type"] == "highlight"
                    and states[index + 1]["type"] == "highlight"
                ):
                    following = deepcopy(states[index + 1])
                    midpoint = round(
                        (float(state["start"]) + float(state["end"])) / 2, 6
                    )
                    output[-1]["end"] = midpoint
                    following["start"] = midpoint
                    output.append(following)
                    index += 2
                elif output and output[-1]["type"] == "highlight":
                    output[-1]["end"] = state["end"]
                    index += 1
                elif index + 1 < len(states) and states[index + 1]["type"] == "highlight":
                    following = deepcopy(states[index + 1])
                    following["start"] = state["start"]
                    output.append(following)
                    index += 2
                else:
                    output.append(state)
                    index += 1
                    continue
                removed += 1
                boundaries_adjusted += 1
                continue
            output.append(state)
            index += 1
        for left, right in zip(output, output[1:]):
            boundary = round(
                (float(left["end"]) + float(right["start"])) / 2, 6
            )
            left["end"] = boundary
            right["start"] = boundary
        cue["states"] = [
            state for state in output
            if float(state["end"]) - float(state["start"]) > 0
        ]
    return optimized, {
        "micro_normal_states_removed": removed,
        "zero_duration_states_removed": zero_removed,
        "boundaries_adjusted": boundaries_adjusted,
    }

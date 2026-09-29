"""Reusable old-to-new time mapping for non-overlapping ripple cuts."""

from __future__ import annotations

from typing import Any


def build_time_map(cuts: list[dict[str, Any]], old_duration: float) -> dict[str, Any]:
    ranges = sorted(
        [{"start": float(c["cut_start"]), "end": float(c["cut_end"])} for c in cuts],
        key=lambda value: value["start"],
    )
    removed = sum(value["end"] - value["start"] for value in ranges)
    return {
        "version": 1, "old_duration": old_duration,
        "new_duration": round(old_duration - removed, 6),
        "removed_ranges": ranges, "total_removed": round(removed, 6),
    }


def map_time(value: float, mapping: dict[str, Any], *, boundary: str = "start") -> float:
    shift = 0.0
    for cut in mapping["removed_ranges"]:
        if value >= cut["end"]:
            shift += cut["end"] - cut["start"]
        elif cut["start"] < value < cut["end"]:
            return cut["start"] - shift
        elif value == cut["end"] and boundary == "end":
            shift += cut["end"] - cut["start"]
    return round(value - shift, 6)


def retime_words(words: list[dict[str, Any]], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for original in words:
        for cut in mapping["removed_ranges"]:
            if float(original["start"]) < cut["end"] and float(original["end"]) > cut["start"]:
                raise RuntimeError(f"Lexical word intersects silence cut: {original.get('text')}")
        word = dict(original)
        word["start"] = map_time(float(original["start"]), mapping)
        word["end"] = map_time(float(original["end"]), mapping, boundary="end")
        output.append(word)
    return output

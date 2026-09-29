"""Conservative frame-based PCM energy analysis for timeline silence cuts."""

from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path
from typing import Any


def analyze_audio_energy(
    wav_path: Path, frame_ms: int = 20, hop_ms: int = 10
) -> dict[str, Any]:
    with wave.open(str(wav_path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise RuntimeError("Silence analysis requires mono PCM16 WAV.")
        rate = handle.getframerate()
        samples = array("h", handle.readframes(handle.getnframes()))
    frame = max(1, round(rate * frame_ms / 1000))
    hop = max(1, round(rate * hop_ms / 1000))
    values: list[dict[str, float]] = []
    for offset in range(0, max(1, len(samples) - frame + 1), hop):
        window = samples[offset:offset + frame]
        rms = math.sqrt(sum(value * value for value in window) / max(1, len(window)))
        dbfs = 20 * math.log10(max(rms / 32768.0, 1e-8))
        values.append({
            "start": offset / rate,
            "end": min(len(samples), offset + frame) / rate,
            "dbfs": dbfs,
        })
    ordered = sorted(item["dbfs"] for item in values)
    noise_floor = ordered[max(0, round(len(ordered) * 0.2) - 1)] if ordered else -160.0
    # Follow the local floor so steady room noise can still be classified as
    # silence. Lexical no-word gaps and protected handles remain the primary
    # safeguards against quiet speech removal.
    threshold = max(-48.0, min(-25.0, noise_floor + 6.0))
    for item in values:
        item["low_energy"] = item["dbfs"] <= threshold
    return {
        "sample_rate": rate, "frame_ms": frame_ms, "hop_ms": hop_ms,
        "noise_floor_dbfs": noise_floor, "silence_threshold_dbfs": threshold,
        "frames": values,
    }


def continuous_low_energy_regions(analysis: dict[str, Any]) -> list[dict[str, float]]:
    regions: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    readings: list[float] = []
    for frame in analysis["frames"]:
        if frame["low_energy"]:
            if current is None:
                current = {"start": frame["start"], "end": frame["end"]}
                readings = []
            current["end"] = frame["end"]
            readings.append(frame["dbfs"])
        elif current is not None:
            current["average_dbfs"] = sum(readings) / len(readings)
            regions.append(current)
            current, readings = None, []
    if current is not None:
        current["average_dbfs"] = sum(readings) / len(readings)
        regions.append(current)
    return regions

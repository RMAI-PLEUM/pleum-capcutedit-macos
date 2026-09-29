"""Render resolved timeline audio directly into exact timeline coordinates."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from utils import PROJECT_ROOT


def _tempo_filters(speed: float) -> list[str]:
    if speed <= 0:
        raise RuntimeError(f"Unsupported non-positive speed: {speed}")
    factors: list[float] = []
    while speed > 2.0:
        factors.append(2.0)
        speed /= 2.0
    while speed < 0.5:
        factors.append(0.5)
        speed /= 0.5
    if abs(speed - 1.0) > 0.000001:
        factors.append(speed)
    return [f"atempo={factor:.9f}" for factor in factors]


def render_timeline_audio(analysis: dict[str, Any], project_slug: str) -> Path:
    if not analysis.get("safe_for_direct_transcription"):
        reasons = (
            analysis.get("offline_media", [])
            + analysis.get("unsupported_structures", [])
        )
        raise RuntimeError("Timeline is not safe to render: " + "; ".join(reasons))
    output_dir = PROJECT_ROOT / "temp/timeline_audio" / project_slug
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "timeline.wav"
    segments = analysis["audible_segments"]
    command = ["ffmpeg", "-y", "-v", "error"]
    for segment in segments:
        command.extend(["-i", segment["media_path"]])
    filters: list[str] = []
    labels: list[str] = []
    for index, segment in enumerate(segments):
        source = segment["source_timerange"]
        delay = round(float(segment["target_timerange"]["start"]) * 1000)
        chain = [
            f"[{index}:a]atrim=start={source['start']:.6f}:end={source['end']:.6f}",
            "asetpts=PTS-STARTPTS",
            *_tempo_filters(float(segment["speed"])),
            f"volume={float(segment['volume']):.9f}",
            f"adelay={delay}:all=1",
        ]
        label = f"a{index}"
        filters.append(",".join(chain) + f"[{label}]")
        labels.append(f"[{label}]")
    duration = float(analysis["duration"])
    filters.append(
        f"anullsrc=r=16000:cl=mono,atrim=duration={duration:.6f}[silence]"
    )
    mix_inputs = "".join(labels) + "[silence]"
    filters.append(
        f"{mix_inputs}amix=inputs={len(labels) + 1}:normalize=0:"
        f"duration=longest,atrim=duration={duration:.6f}[out]"
    )
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[out]", "-ar", "16000", "-ac", "1",
        "-c:a", "pcm_s16le", str(output),
    ])
    try:
        subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", check=True
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg was not found.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Timeline audio rendering failed: {exc.stderr.strip()}") from exc
    return output


def render_timeline_audio_window(
    analysis: dict[str, Any], project_slug: str, start: float, end: float,
    filename: str = "target_pause_window.wav",
) -> Path:
    """Render only a bounded timeline window, never the complete project."""
    if end <= start:
        raise ValueError("Audio window end must be after start.")
    selected = []
    for original in analysis["audible_segments"]:
        target = original["target_timerange"]
        overlap_start = max(start, float(target["start"]))
        overlap_end = min(end, float(target["end"]))
        if overlap_end <= overlap_start:
            continue
        segment = dict(original)
        segment["source_timerange"] = dict(original["source_timerange"])
        segment["source_timerange"]["start"] += (
            overlap_start - float(target["start"])
        ) * float(original["speed"])
        segment["source_timerange"]["end"] = (
            segment["source_timerange"]["start"]
            + (overlap_end - overlap_start) * float(original["speed"])
        )
        segment["target_timerange"] = {
            "start": overlap_start - start,
            "end": overlap_end - start,
            "duration": overlap_end - overlap_start,
        }
        selected.append(segment)
    output_dir = PROJECT_ROOT / "temp/timeline_audio" / project_slug
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / filename
    command = ["ffmpeg", "-y", "-v", "error"]
    for segment in selected:
        command.extend(["-i", segment["media_path"]])
    filters, labels = [], []
    for index, segment in enumerate(selected):
        source = segment["source_timerange"]
        delay = round(float(segment["target_timerange"]["start"]) * 1000)
        label = f"w{index}"
        filters.append(
            f"[{index}:a]atrim=start={source['start']:.6f}:"
            f"end={source['end']:.6f},asetpts=PTS-STARTPTS,"
            + ",".join(_tempo_filters(float(segment["speed"])))
            + ("," if _tempo_filters(float(segment["speed"])) else "")
            + f"volume={float(segment['volume']):.9f},"
            f"adelay={delay}:all=1[{label}]"
        )
        labels.append(f"[{label}]")
    duration = end - start
    filters.append(
        f"anullsrc=r=16000:cl=mono,atrim=duration={duration:.6f}[silence]"
    )
    filters.append(
        f"{''.join(labels)}[silence]amix=inputs={len(labels)+1}:normalize=0:"
        f"duration=longest,atrim=duration={duration:.6f}[out]"
    )
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(output),
    ])
    try:
        subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", check=True
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Timeline window render failed: {exc.stderr.strip()}") from exc
    return output

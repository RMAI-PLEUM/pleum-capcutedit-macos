"""Render only audible CapCut timeline portions into a timeline-aligned WAV."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from timeline_mapper import iter_timeline_clips
from utils import PROJECT_ROOT, write_json


def project_duration(timeline: dict[str, Any]) -> float:
    explicit = timeline.get("duration_seconds") or timeline.get("project_duration")
    if explicit is not None and float(explicit) > 0:
        return float(explicit)
    ends = [
        clip["timeline_range"]["end"] for clip in iter_timeline_clips(timeline)
    ]
    if not ends:
        raise RuntimeError("CapCut timeline contains no usable media clips.")
    return max(ends)


def _atempo_filters(speed: float) -> list[str]:
    speed = max(0.01, speed)
    filters: list[str] = []
    while speed > 2.0:
        filters.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        filters.append("atempo=0.5")
        speed /= 0.5
    filters.append(f"atempo={speed:.8f}")
    return filters


def _has_audio(path: Path, cache: dict[str, bool]) -> bool:
    key = str(path).casefold()
    if key in cache:
        return cache[key]
    command = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", check=True
        )
        cache[key] = bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError):
        cache[key] = False
    return cache[key]


def build_timeline_audio(timeline: dict[str, Any]) -> tuple[Path, list[dict[str, Any]]]:
    duration = project_duration(timeline)
    audio_probe_cache: dict[str, bool] = {}
    clips = [
        clip for clip in iter_timeline_clips(timeline)
        if not clip.get("muted")
        and not clip.get("disabled")
        and Path(str(clip["media_path"])).is_file()
        and _has_audio(Path(str(clip["media_path"])), audio_probe_cache)
    ]
    # Remove exact duplicate media sections sometimes represented by linked tracks.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for clip in sorted(clips, key=lambda item: item["timeline_range"]["start"]):
        key = (
            str(clip["media_path"]).casefold(),
            round(clip["source_range"]["start"], 4),
            round(clip["source_range"]["duration"], 4),
            round(clip["timeline_range"]["start"], 4),
        )
        if key not in seen:
            seen.add(key)
            unique.append(clip)
    if not unique:
        raise RuntimeError("No enabled, audible timeline media files are available locally.")

    command = ["ffmpeg", "-y", "-v", "error"]
    for clip in unique:
        command.extend(["-i", str(clip["media_path"])])

    filters = [
        f"anullsrc=r=16000:cl=mono,atrim=duration={duration:.6f}[base]"
    ]
    labels = ["[base]"]
    audio_map: list[dict[str, Any]] = []
    for index, clip in enumerate(unique):
        source = clip["source_range"]
        target = clip["timeline_range"]
        speed = float(clip.get("playback_speed") or 1.0)
        chain = [
            f"[{index}:a]atrim=start={source['start']:.6f}:duration={source['duration']:.6f}",
            "asetpts=PTS-STARTPTS",
            *_atempo_filters(speed),
            f"atrim=duration={target['duration']:.6f}",
            f"adelay={round(target['start'] * 1000)}:all=1",
            f"aresample=16000[a{index}]",
        ]
        filters.append(",".join(chain))
        labels.append(f"[a{index}]")
        audio_map.append({
            "section_index": index,
            "clip_id": clip.get("segment_id"),
            "track_id": clip.get("track_id"),
            "track_index": clip.get("track_index"),
            "source_media": clip.get("media_path"),
            "source_start": source["start"],
            "source_end": source["end"],
            "source_duration": source["duration"],
            "timeline_start": target["start"],
            "timeline_end": target["end"],
            "timeline_duration": target["duration"],
            "playback_speed": speed,
        })
    filters.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
        + f"atrim=duration={duration:.6f},alimiter=limit=0.95[out]"
    )
    output = PROJECT_ROOT / "temp" / "capcut_timeline_audio.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(output),
    ])
    try:
        subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is required in PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Timeline audio render failed: {exc.stderr.strip()}") from exc
    write_json(PROJECT_ROOT / "logs" / "timeline_audio_map.json", audio_map)
    return output, audio_map

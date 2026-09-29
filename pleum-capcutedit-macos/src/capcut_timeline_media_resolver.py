"""Resolve audible CapCut timeline segments without guessing schema semantics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

TIME_SCALE = 1_000_000


def _range(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Missing {label}.")
    try:
        start = int(value["start"])
        duration = int(value["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid {label}.") from exc
    if start < 0 or duration <= 0:
        raise RuntimeError(f"Invalid {label}: start={start}, duration={duration}.")
    return {
        "start": start / TIME_SCALE,
        "duration": duration / TIME_SCALE,
        "end": (start + duration) / TIME_SCALE,
        "capcut_start": start,
        "capcut_duration": duration,
    }


def analyze_timeline(data: dict[str, Any]) -> dict[str, Any]:
    materials = data.get("materials") or {}
    material_index = {
        str(item.get("id")): (kind, item)
        for kind in ("videos", "audios")
        for item in materials.get(kind, []) or []
        if isinstance(item, dict) and item.get("id")
    }
    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        raise RuntimeError("Unsupported timeline: tracks is not a list.")
    unsupported: list[str] = []
    offline: list[str] = []
    audible: list[dict[str, Any]] = []
    video_count = audio_count = video_segments = audio_segments = 0
    for track_index, track in enumerate(tracks):
        kind = track.get("type")
        if kind not in {"video", "audio"}:
            continue
        if kind == "video":
            video_count += 1
        else:
            audio_count += 1
        # Normal tracks in the proven schema use flag=0 and attribute=0.
        if track.get("flag", 0) != 0 or track.get("attribute", 0) != 0:
            unsupported.append(
                f"track {track_index}: unknown mute/attribute semantics "
                f"(flag={track.get('flag')}, attribute={track.get('attribute')})"
            )
            continue
        for segment_index, segment in enumerate(track.get("segments") or []):
            if kind == "video":
                video_segments += 1
            else:
                audio_segments += 1
            prefix = f"{kind} track {track_index} segment {segment_index}"
            if segment.get("reverse"):
                unsupported.append(f"{prefix}: reverse playback")
            if segment.get("is_loop"):
                unsupported.append(f"{prefix}: loop/compound behavior")
            if segment.get("source") not in (None, "", "segmentsourcenormal"):
                unsupported.append(f"{prefix}: unsupported source type {segment.get('source')!r}")
            material_id = str(segment.get("material_id") or "")
            resolved = material_index.get(material_id)
            if resolved is None:
                unsupported.append(f"{prefix}: material_id does not resolve: {material_id}")
                continue
            material_kind, material = resolved
            if material_kind == "videos" and material.get("freeze") is not None:
                unsupported.append(f"{prefix}: freeze frame")
            has_audio = (
                bool(material.get("has_audio", True))
                if material_kind == "videos" else True
            )
            volume = segment.get("volume", 1.0)
            if not isinstance(volume, (int, float)):
                unsupported.append(f"{prefix}: unknown volume semantics")
                continue
            if not has_audio or float(volume) <= 0:
                continue
            source = _range(segment.get("source_timerange"), f"{prefix} source_timerange")
            target = _range(segment.get("target_timerange"), f"{prefix} target_timerange")
            speed = source["duration"] / target["duration"]
            declared_speed = segment.get("speed", speed)
            if not isinstance(declared_speed, (int, float)):
                unsupported.append(f"{prefix}: unsupported speed curve")
                continue
            if abs(float(declared_speed) - speed) > 0.01:
                unsupported.append(
                    f"{prefix}: inconsistent constant speed "
                    f"(ranges={speed:.6f}, segment={float(declared_speed):.6f})"
                )
            path_text = str(material.get("path") or material.get("media_path") or "")
            media_path = Path(path_text)
            if not path_text or not media_path.is_file():
                offline.append(str(media_path))
            audible.append({
                "track_index": track_index,
                "segment_index": segment_index,
                "track_type": kind,
                "segment_id": segment.get("id"),
                "material_id": material_id,
                "media_path": str(media_path),
                "source_timerange": source,
                "target_timerange": target,
                "volume": float(volume),
                "speed": round(speed, 9),
                "speed_changed": abs(speed - 1.0) > 0.000001,
            })
    audible.sort(key=lambda item: item["target_timerange"]["start"])
    gaps: list[dict[str, float]] = []
    cursor = 0.0
    for segment in audible:
        target = segment["target_timerange"]
        if target["start"] < cursor - 0.000001:
            unsupported.append(
                "overlapping spoken audio from multiple tracks or segments: "
                f"{segment['segment_id']}"
            )
        elif target["start"] > cursor + 0.000001:
            gaps.append({
                "start": round(cursor, 6),
                "end": round(target["start"], 6),
                "duration": round(target["start"] - cursor, 6),
            })
        cursor = max(cursor, target["end"])
    duration = float(data.get("duration") or 0) / TIME_SCALE
    if cursor < duration - 0.000001:
        gaps.append({
            "start": round(cursor, 6),
            "end": round(duration, 6),
            "duration": round(duration - cursor, 6),
        })
    return {
        "duration": duration,
        "video_track_count": video_count,
        "audio_track_count": audio_count,
        "video_segment_count": video_segments,
        "audio_segment_count": audio_segments,
        "audible_segments": audible,
        "timeline_gaps": gaps,
        "speed_changes": [
            {
                "segment_id": item["segment_id"],
                "speed": item["speed"],
            }
            for item in audible if item["speed_changed"]
        ],
        "offline_media": sorted(set(offline)),
        "unsupported_structures": sorted(set(unsupported)),
        "safe_for_direct_transcription": bool(audible) and not offline and not unsupported,
    }


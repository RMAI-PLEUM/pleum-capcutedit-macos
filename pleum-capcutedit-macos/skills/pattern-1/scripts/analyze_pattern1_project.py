#!/usr/bin/env python3
"""Read-only structural analyzer for a CapCut project using Pattern 1."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

US = 1_000_000


def seconds(value: int | float | None) -> float:
    return round(float(value or 0) / US, 6)


def timerange(segment: dict[str, Any]) -> tuple[float, float, float]:
    value = segment.get("target_timerange") or {}
    start = seconds(value.get("start"))
    duration = seconds(value.get("duration"))
    return start, round(start + duration, 6), duration


def load_project(project_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    files = sorted(project_dir.rglob("draft_content.json"))
    if not files:
        raise FileNotFoundError(f"No draft_content.json below {project_dir}")
    mirrors: list[dict[str, Any]] = []
    payloads: list[bytes] = []
    for path in files:
        raw = path.read_bytes()
        payloads.append(raw)
        mirrors.append({
            "relative_path": str(path.relative_to(project_dir)),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        })
    parsed = [json.loads(raw.decode("utf-8")) for raw in payloads]
    canonical = json.dumps(parsed[0], sort_keys=True, ensure_ascii=False)
    identical = all(json.dumps(item, sort_keys=True, ensure_ascii=False) == canonical for item in parsed[1:])
    for item in mirrors:
        item["semantically_identical"] = identical
    if not identical:
        raise ValueError("draft_content.json mirrors differ; inspect before editing")
    return parsed[0], mirrors


def decode_text(material: dict[str, Any]) -> str:
    try:
        value = str(json.loads(material.get("content") or "{}").get("text") or "")
    except (json.JSONDecodeError, TypeError):
        value = str(material.get("recognize_text") or "")
    # Some CapCut drafts contain UTF-8 Thai bytes stored as Latin-1 codepoints.
    # Repair that representation only when the round-trip is valid.
    try:
        repaired = value.encode("latin-1").decode("utf-8")
        if repaired:
            value = repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return value


def style(material: dict[str, Any], segment: dict[str, Any]) -> dict[str, Any]:
    clip = segment.get("clip") or {}
    transform = clip.get("transform") or {}
    animations = []
    return {
        "font": Path(material.get("font_path") or "").stem or material.get("font_title") or "",
        "font_size": material.get("font_size") or material.get("text_size"),
        "color": material.get("text_color"),
        "bold": bool(material.get("bold_width", 0)),
        "position": {"x": transform.get("x"), "y": transform.get("y")},
        "animations": animations,
    }


def analyze(data: dict[str, Any], mirrors: list[dict[str, Any]]) -> dict[str, Any]:
    tracks = data.get("tracks") or []
    materials = data.get("materials") or {}
    by_kind = {
        kind: {item.get("id"): item for item in materials.get(kind, [])}
        for kind in ("texts", "audios", "transitions", "material_animations")
    }
    text_tracks = [t for t in tracks if t.get("type") == "text"]
    ordinary_track = max(text_tracks, key=lambda t: len(t.get("segments") or []), default={})
    callout_tracks = [t for t in text_tracks if t is not ordinary_track]
    video_tracks = [t for t in tracks if t.get("type") == "video"]
    audio_tracks = [t for t in tracks if t.get("type") == "audio"]
    video_segments = (video_tracks[0].get("segments") or []) if video_tracks else []
    ordinary_segments = ordinary_track.get("segments") or []

    animation_map = by_kind["material_animations"]
    caption_rows = []
    for seg in ordinary_segments:
        material = by_kind["texts"].get(seg.get("material_id"), {})
        start, end, duration = timerange(seg)
        caption_rows.append({
            "id": seg.get("id"), "text": decode_text(material),
            "start": start, "end": end, "duration": duration,
            "style": style(material, seg),
        })

    callouts = []
    for track in callout_tracks:
        for seg in track.get("segments") or []:
            material = by_kind["texts"].get(seg.get("material_id"), {})
            start, end, duration = timerange(seg)
            row_style = style(material, seg)
            anims = []
            for ref in seg.get("extra_material_refs") or []:
                for anim in animation_map.get(ref, {}).get("animations") or []:
                    anims.append({"name": anim.get("name"), "type": anim.get("type"), "duration": seconds(anim.get("duration"))})
            row_style["animations"] = anims
            callouts.append({"text": decode_text(material), "start": start, "end": end, "duration": duration, "style": row_style})

    audio_events = []
    for track_index, track in enumerate(audio_tracks, 1):
        for seg in track.get("segments") or []:
            material = by_kind["audios"].get(seg.get("material_id"), {})
            start, end, duration = timerange(seg)
            audio_events.append({
                "track": track_index, "name": material.get("name") or "",
                "start": start, "end": end, "duration": duration,
                "volume": seg.get("volume"),
            })
    audio_events.sort(key=lambda item: (item["start"], item["track"]))

    transitions = []
    zooms = []
    warnings = []
    sections = []
    transition_map = by_kind["transitions"]
    for index, seg in enumerate(video_segments, 1):
        start, end, duration = timerange(seg)
        seg_transitions = []
        for ref in seg.get("extra_material_refs") or []:
            trans = transition_map.get(ref)
            if trans:
                item = {
                    "after_section": index, "boundary": end, "name": trans.get("name"),
                    "duration": seconds(trans.get("duration")), "overlap": bool(trans.get("is_overlap")),
                }
                transitions.append(item)
                seg_transitions.append(item["name"])
        seg_zooms = []
        for keyframes in seg.get("common_keyframes") or []:
            if keyframes.get("property_type") != "KFTypeScaleX":
                continue
            points = keyframes.get("keyframe_list") or []
            if len(points) >= 2:
                first = (points[0].get("values") or [None])[0]
                last = (points[-1].get("values") or [None])[0]
                change = round((last / first - 1) * 100, 3) if first else None
                item = {"section": index, "start": start, "end": end, "from": first, "to": last, "relative_change_percent": change}
                zooms.append(item)
                seg_zooms.append(item)
        words = [c["text"] for c in caption_rows if c["start"] < end and c["end"] > start]
        sounds = [a["name"] for a in audio_events if a["start"] < end and a["end"] > start]
        sections.append({"section": index, "start": start, "end": end, "duration": duration, "captions": words, "sounds": sounds, "transitions_after": seg_transitions, "zooms": seg_zooms})
        if duration <= 0.05:
            warnings.append({"type": "one_frame_or_micro_segment", "section": index, "start": start, "duration": duration})

    project_duration = seconds(data.get("duration"))
    if not project_duration:
        project_duration = max((timerange(s)[1] for t in tracks for s in t.get("segments") or []), default=0)
    caption_durations = [row["duration"] for row in caption_rows]
    video_durations = [timerange(seg)[2] for seg in video_segments]
    style_keys = {
        json.dumps(row["style"], sort_keys=True, ensure_ascii=False)
        for row in caption_rows
    }
    metrics = {
        "duration_seconds": project_duration,
        "video_segments": len(video_segments),
        "ordinary_captions": len(caption_rows),
        "callouts": len(callouts),
        "audio_events": len(audio_events),
        "transitions": len(transitions),
        "slow_zooms": len(zooms),
        "ordinary_caption_style_variants": len(style_keys),
        "caption_average_seconds": round(statistics.mean(caption_durations), 6) if caption_durations else 0,
        "caption_under_0_1_seconds": sum(d < 0.1 for d in caption_durations),
        "video_median_seconds": round(statistics.median(video_durations), 6) if video_durations else 0,
        "sfx_per_minute": round(len(audio_events) / (project_duration / 60), 3) if project_duration else 0,
        "transition_boundary_fraction": round(len(transitions) / max(len(video_segments) - 1, 1), 4),
        "zoom_segment_fraction": round(len(zooms) / max(len(video_segments), 1), 4),
    }
    return {
        "schema": "pattern-1-analysis-v1",
        "read_only": True,
        "mirrors": mirrors,
        "metrics": metrics,
        "ordinary_captions": caption_rows,
        "ordinary_caption_sample": caption_rows[:12],
        "callouts": callouts,
        "audio_events": audio_events,
        "transitions": transitions,
        "slow_zooms": zooms,
        "sections": sections,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data, mirrors = load_project(args.project_dir.resolve())
    report = analyze(data, mirrors)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(args.output.resolve())
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

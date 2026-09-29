"""Detect registry-backed duplicate active caption layers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_caption_registry import load_registry
from capcut_karaoke_registry import load_karaoke_registry
from capcut_live_project_reader import LiveProject
from utils import PROJECT_ROOT, write_json


def detect_karaoke_duplicate_layers(
    live: LiveProject,
    plan: dict[str, Any],
) -> dict[str, Any]:
    caption_registry = load_registry(live.project.identity) or {}
    karaoke_registry = load_karaoke_registry(live.project.identity) or {}
    caption_ids = set(caption_registry.get("generated_segment_ids") or [])
    karaoke_ids = set(karaoke_registry.get("generated_segment_ids") or [])
    materials = {
        item.get("id"): item
        for item in (live.primary.get("materials") or {}).get("texts", [])
    }
    state_order = [
        state for cue in plan.get("cues") or [] for state in cue.get("states") or []
    ]
    state_by_segment = {
        segment_id: state
        for segment_id, state in zip(
            karaoke_registry.get("generated_segment_ids") or [], state_order
        )
    }
    rows: list[dict[str, Any]] = []
    for track in live.primary.get("tracks") or []:
        if track.get("type") != "text":
            continue
        for segment in track.get("segments") or []:
            segment_id = segment.get("id")
            if segment_id not in caption_ids | karaoke_ids:
                continue
            timerange = segment.get("target_timerange") or {}
            start = int(timerange.get("start") or 0)
            end = start + int(timerange.get("duration") or 0)
            material = materials.get(segment.get("material_id")) or {}
            try:
                text = json.loads(material.get("content") or "{}").get("text", "")
            except json.JSONDecodeError:
                text = ""
            rows.append({
                "track_id": track.get("id"),
                "segment_id": segment_id,
                "material_id": segment.get("material_id"),
                "start": start, "end": end, "text": text,
                "clip": segment.get("clip"),
                "lineage": (
                    "base_ai_caption" if segment_id in caption_ids
                    else "ai_karaoke"
                ),
                "state": state_by_segment.get(segment_id),
            })
    duplicates: list[dict[str, Any]] = []
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            if left["track_id"] == right["track_id"]:
                continue
            overlap_start = max(left["start"], right["start"])
            overlap_end = min(left["end"], right["end"])
            if (
                overlap_end <= overlap_start
                or left["text"] != right["text"]
                or left["clip"] != right["clip"]
                or {left["lineage"], right["lineage"]}.isdisjoint({"ai_karaoke"})
            ):
                continue
            deletion = None
            preservation = None
            for candidate, other in ((left, right), (right, left)):
                state = candidate.get("state") or {}
                if (
                    candidate["lineage"] == "base_ai_caption"
                    or (
                        candidate["lineage"] == "ai_karaoke"
                        and state.get("type") == "normal"
                        and candidate["end"] - candidate["start"] < 40_000
                    )
                ):
                    deletion, preservation = candidate, other
                    break
            duplicates.append({
                "base_caption_track": (
                    left["track_id"] if left["lineage"] == "base_ai_caption"
                    else right["track_id"] if right["lineage"] == "base_ai_caption"
                    else None
                ),
                "karaoke_tracks": sorted({left["track_id"], right["track_id"]}),
                "overlap_start": overlap_start / 1_000_000,
                "overlap_end": overlap_end / 1_000_000,
                "duplicate_active_duration": (
                    overlap_end - overlap_start
                ) / 1_000_000,
                "text": left["text"],
                "segment_ids": [left["segment_id"], right["segment_id"]],
                "material_ids": [left["material_id"], right["material_id"]],
                "deletion_candidate": (
                    {
                        "segment_id": deletion["segment_id"],
                        "material_id": deletion["material_id"],
                        "track_id": deletion["track_id"],
                        "reason": (
                            "registered_base_ai_caption"
                            if deletion["lineage"] == "base_ai_caption"
                            else "sub_40ms_registered_karaoke_normal_state"
                        ),
                    } if deletion else None
                ),
                "preservation_candidate": (
                    {
                        "segment_id": preservation["segment_id"],
                        "material_id": preservation["material_id"],
                        "track_id": preservation["track_id"],
                    } if preservation else None
                ),
            })
    report = {
        "project": live.project.name,
        "base_ai_caption_track_id": caption_registry.get("generated_text_track_id"),
        "base_ai_caption_track_present": any(
            track.get("id") == caption_registry.get("generated_text_track_id")
            for track in live.primary.get("tracks") or []
        ),
        "karaoke_registry_track_id": karaoke_registry.get("generated_text_track_id"),
        "karaoke_lineage_track_ids": sorted({
            row["track_id"] for row in rows if row["lineage"] == "ai_karaoke"
        }),
        "duplicate_layer_count": len(duplicates),
        "duplicate_track_pair_count": len({
            tuple(item["karaoke_tracks"]) for item in duplicates
        }),
        "duplicate_active_duration": round(sum(
            item["duplicate_active_duration"] for item in duplicates
        ), 6),
        "duplicates": duplicates,
    }
    slug = live.project.name.casefold()
    write_json(
        PROJECT_ROOT / f"output/json/{slug}.karaoke_duplicate_layers.json",
        report,
    )
    write_json(
        PROJECT_ROOT / f"logs/direct_edit/{slug}/karaoke_duplicate_detection.json",
        report,
    )
    preview = [
        "KARAOKE DUPLICATE LAYERS",
        "",
        f"Project: {live.project.name}",
        f"Duplicate overlaps: {len(duplicates)}",
        f"Track pairs: {report['duplicate_track_pair_count']}",
        f"Duplicate active duration: {report['duplicate_active_duration']:.6f}s",
        "",
    ]
    for item in duplicates:
        preview.append(
            f"{item['overlap_start']:.6f}-{item['overlap_end']:.6f} "
            f"{item['text']} | delete={item['deletion_candidate']} "
            f"| preserve={item['preservation_candidate']}"
        )
    path = PROJECT_ROOT / f"output/preview/{slug}_karaoke_duplicate_layers.txt"
    path.write_text("\n".join(preview) + "\n", encoding="utf-8")
    return report

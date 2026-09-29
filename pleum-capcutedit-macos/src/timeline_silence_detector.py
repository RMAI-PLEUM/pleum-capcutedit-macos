"""Read-only hybrid silence detection for a selected live CapCut project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_caption_registry import stable_hash
from audio_energy_analyzer import analyze_audio_energy, continuous_low_energy_regions
from capcut_live_project_reader import read_live_project
from capcut_project_locator import locate_project
from capcut_timeline_audio_renderer import render_timeline_audio
from capcut_timeline_media_resolver import analyze_timeline
from karaoke_workflow import _validated_lexical_cache
from silence_candidate_builder import build_silence_candidates
from capcut_ripple_cut import apply_ripple_cut
from capcut_karaoke_registry import load_karaoke_registry
from ai_caption_registry import load_registry
from utils import PROJECT_ROOT, write_json


def load_silence_preset(preset_id: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "presets/silence_cut/default.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    try:
        return document["presets"][preset_id]
    except KeyError as exc:
        raise RuntimeError(f"Unknown silence preset: {preset_id}") from exc


def detect_project_silence(
    project_name: str, preset_id: str = "shorts-clean",
    *, keep_audio: bool = False,
) -> tuple[dict[str, Any], Any, list[dict[str, Any]], dict[str, Any]]:
    project = locate_project(project_name)
    live = read_live_project(project)
    analysis = analyze_timeline(live.primary)
    media_hash = stable_hash({
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    })
    words, cache_status = _validated_lexical_cache(project.name, analysis, media_hash)
    preset = load_silence_preset(preset_id)
    # Rendering uses only already resolved audible timeline segments. Unsupported
    # non-audio structures are handled per-cut by the ripple dry-run.
    render_analysis = {**analysis, "safe_for_direct_transcription": True}
    wav = render_timeline_audio(render_analysis, project.name.casefold().replace(" ", "_"))
    silence_wav = wav.with_name("silence_detection.wav")
    wav.replace(silence_wav)
    energy = analyze_audio_energy(silence_wav)
    regions = continuous_low_energy_regions(energy)
    candidates, gap_reports = build_silence_candidates(words, regions, preset)
    skipped: list[dict[str, Any]] = []
    generated_ids = set()
    for registry in (
        load_karaoke_registry(project.identity) or {},
        load_registry(project.identity) or {},
    ):
        generated_ids.update(registry.get("generated_segment_ids") or [])
    safe_candidates = []
    for candidate in candidates:
        start = round(candidate["cut_start"] * 1_000_000)
        end = round(candidate["cut_end"] * 1_000_000)
        manual_crossing = [
            segment.get("id")
            for track in live.primary.get("tracks", [])
            if track.get("type") == "text"
            for segment in track.get("segments", [])
            if segment.get("id") not in generated_ids
            and (segment.get("target_timerange") or {}).get("start", 0) < end
            and (
                (segment.get("target_timerange") or {}).get("start", 0)
                + (segment.get("target_timerange") or {}).get("duration", 0)
            ) > start
        ]
        try:
            if manual_crossing:
                raise RuntimeError("manual text crosses cut")
            apply_ripple_cut(live.primary, start, end)
            safe_candidates.append(candidate)
        except RuntimeError as exc:
            skipped.append({
                **candidate, "reason_codes": ["UNSUPPORTED_TIMELINE_STRUCTURE"],
                "detail": str(exc), "manual_segment_ids": manual_crossing,
            })
    candidates = safe_candidates
    for index, candidate in enumerate(candidates, 1):
        candidate["cut_id"] = f"silence_cut_{index:04d}"
    duration = float(analysis["duration"])
    plan = {
        "version": 1,
        "project": {
            "name": project.name, "timeline_hash": media_hash,
            "duration": duration,
        },
        "preset": preset_id, "cuts": candidates,
        "gap_reports": gap_reports,
        "skipped_candidates": skipped,
    }
    slug = project.name.casefold().replace(" ", "_")
    json_dir = PROJECT_ROOT / "output/json"
    log_dir = PROJECT_ROOT / f"logs/direct_edit/{slug}"
    write_json(json_dir / f"{slug}.silence_candidates.json", {
        "version": 1, "candidates": candidates, "gap_reports": gap_reports,
        "skipped_candidates": skipped,
        "energy": {key: value for key, value in energy.items() if key != "frames"},
    })
    write_json(json_dir / f"{slug}.silence_cut_plan.json", plan)
    metadata = {
        "internal_no_word_gaps_analyzed": max(0, len(words) - 1),
        "gaps_already_near_target": sum(
            abs(
                float(following["start"]) - float(previous["end"])
                - float(preset.get("target_remaining_gap_seconds", 1.0))
            ) <= float(preset.get("target_remaining_gap_tolerance_seconds", .05))
            for previous, following in zip(words, words[1:])
        ),
        "gaps_longer_than_target": sum(
            float(following["start"]) - float(previous["end"]) >
            float(preset.get("target_remaining_gap_seconds", 1.0))
            + float(preset.get("target_remaining_gap_tolerance_seconds", .05))
            for previous, following in zip(words, words[1:])
        ),
        "candidate_silence_count": len(candidates) + len(skipped),
        "safe_cut_count": len(candidates), "skipped_candidate_count": len(skipped),
        "total_silence_duration_detected": round(sum(
            item["detected_silence_end"] - item["detected_silence_start"]
            for item in candidates
        ), 6),
        "total_duration_proposed": round(sum(item["cut_duration"] for item in candidates), 6),
        "timeline_cache_status": cache_status, "elevenlabs_called": False,
        "audio_energy": {key: value for key, value in energy.items() if key != "frames"},
        "temporary_wav": str(silence_wav),
    }
    write_json(log_dir / "silence_detection.json", {**metadata, "plan": plan})
    preview = PROJECT_ROOT / f"output/preview/{slug}_silence_cut_preview.txt"
    lines = [
        f"Project: {project.name}", f"Preset: {preset_id}",
        f"Cache: {cache_status}", f"Safe cuts: {len(candidates)}", "",
    ]
    lines.extend(
        f"{item['cut_id']} {item['cut_start']:.3f} --> {item['cut_end']:.3f} "
        f"({item['cut_duration']:.3f}s) {item['previous_word']} | {item['next_word']}"
        for item in candidates
    )
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not keep_audio:
        silence_wav.unlink(missing_ok=True)
    return plan, live, words, metadata

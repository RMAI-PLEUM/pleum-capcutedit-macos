from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import re
import hashlib
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import srt
from rich.console import Console
from rich.table import Table

from audio_extract import extract_audio
from capcut_locator import find_latest_draft
from capcut_process_guard import require_capcut_closed
from schema_compatibility import compatibility_status
from capcut_project_locator import discover_projects, locate_project
from capcut_live_project_reader import read_live_project
from capcut_timeline_media_resolver import analyze_timeline
from capcut_timeline_audio_renderer import render_timeline_audio
from capcut_direct_editor import edit_captions_direct
from capcut_caption_style_learner import learn_caption_style
from capcut_caption_style_preset import resolve_caption_style
from capcut_caption_style_validator import validate_caption_style
from capcut_karaoke_style_learner import learn_karaoke_style
from capcut_karaoke_style_validator import validate_karaoke_preset
from karaoke_workflow import (
    apply_project_karaoke, build_project_karaoke_plan,
    validate_project_karaoke,
    repair_project_karaoke_duplicates,
)
from timeline_silence_detector import detect_project_silence
from manual_edit_style_learner import learn_manual_edit_style
from editorial_selection_workflow import apply_editorial_selection_plan
from silence_cut_workflow import (
    apply_project_silence_cut, validate_project_silence_cut,
)
from target_pause_analyzer import analyze_target_pause
from pattern1_injector import apply_pattern1, remove_pattern1_registered
from ai_caption_registry import load_registry, stable_hash
from capcut_reader import read_project
from capcut_project_scanner import scan_expected_projects
from capcut_fixture_collector import collect_fixtures, detect_capcut_version, DESTINATIONS
from capcut_fixture_validator import validate_fixtures
from capcut_schema_diff import learn_capcut_schema
from capcut_caption_injector import inject_caption_plan, inject_caption_test
from capcut_project_validator import (
    validate_caption_plan_sandbox, validate_caption_test,
)
from capcut_rollback import rollback_caption_plan, rollback_caption_test
from caption_builder import build_auto_cues, clamp_cues
from caption_plan_builder import (
    build_caption_plan, build_media_caption_plan, build_regrouped_caption_plan,
)
from caption_plan_validator import validate_caption_plan
from caption_layout import resolve_caption_layout
from caption_lexical_filter import filter_caption_lexical_words
from config import load_config
from elevenlabs_stt import load_default_keyterms, transcribe
from edit_plan_builder import build_edit_plan
from edit_plan_validator import validate_edit_plan
from media_info import probe_media
from cut_plan_builder import build_cut_plan
from cut_plan_validator import validate_cut_plan
from plan_preview import caption_preview, cut_preview, edit_summary
from script_aligner import align_script
from script_chunker import chunk_script
from timeline_audio_builder import build_timeline_audio, project_duration
from timeline_mapper import build_mapping_log, iter_timeline_clips
from transcript_normalizer import transcript_text
from thai_caption_validator import validate_thai_caption_plan
from thai_caption_plan_normalizer import normalize_thai_caption_plan
from thai_lexical_regrouper import regroup_raw_response
from take_utterance_builder import build_utterances
from duplicate_take_detector import detect_duplicate_takes
from duplicate_take_validator import validate_duplicate_take_analysis
from take_plan_builder import build_take_plan
from approved_take_cut_editor import (
    apply_approved_cut_transaction, essential_timeline_hash,
)
from capcut_ripple_cut import TIME_SCALE
from auto_duplicate_cleanup import (
    apply_auto_cleanup_transaction, build_auto_cleanup_plan,
    retime_lexical_after_known_cut,
)
from utils import (
    PROJECT_ROOT, atomic_write_text, ensure_directories, read_text_file,
    safe_basename, setup_logging, write_json,
)
from validator import validate_cues, validation_report


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Editor Capcut: Thai subtitle workflow")
    parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "transcribe", "script-align", "capcut-read",
            "build-caption-plan", "build-cut-plan", "build-edit-plan", "dry-run",
            "collect-capcut-fixtures", "validate-capcut-fixtures",
            "learn-capcut-schema",
            "inject-caption-test", "validate-caption-test", "rollback-caption-test",
            "inject-caption-plan", "validate-caption-plan", "rollback-caption-plan",
            "elevenlabs-test", "build-caption-plan-from-stt",
            "build-caption-plan-from-script", "inject-stt-caption-plan",
            "regroup-thai-caption-plan",
            "inspect-project", "transcribe-project", "edit-project",
            "validate-project-edit",
            "detect-duplicate-takes",
            "learn-manual-edit-style",
            "apply-editorial-selection-plan",
            "list-capcut-projects",
            "apply-approved-take-cuts",
            "auto-remove-duplicate-takes",
            "learn-caption-style", "validate-caption-style",
            "normalize-thai-caption-plan",
            "learn-karaoke-style", "build-karaoke-plan",
            "apply-karaoke", "validate-karaoke",
            "repair-karaoke-duplicates",
            "detect-silence", "auto-cut-silence", "validate-silence-cut",
            "analyze-target-pause",
            "apply-pattern-1", "remove-pattern-1",
        ),
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--plan", type=Path, help="Caption-plan JSON for sandbox injection")
    parser.add_argument("--sandbox-name", help="Named sandbox project folder")
    parser.add_argument("--task", choices=("captions",))
    parser.add_argument(
        "--project-root",
        type=Path,
        help="Optional CapCut projects folder, project folder, or draft_content.json",
    )
    parser.add_argument(
        "--project",
        default="latest",
        help="CapCut project selector. Currently supports 'latest' or a project path.",
    )
    parser.add_argument(
        "--reference-project",
        help="User-edited CapCut project used as a local editing-style reference.",
    )
    parser.add_argument("--max-duration", type=float)
    parser.add_argument("--start-offset", type=float, default=0.0)
    parser.add_argument("--keyterms", help="Comma-separated ElevenLabs keyterms")
    parser.add_argument(
        "--timestamp-granularity",
        choices=("word", "character"),
        help="Override ElevenLabs timestamp granularity; character output is saved separately.",
    )
    parser.add_argument(
        "--caption-layout",
        choices=("auto", "landscape", "portrait", "square"),
        default="auto",
    )
    parser.add_argument("--max-words-per-caption", type=int)
    parser.add_argument("--caption-style")
    parser.add_argument(
        "--exclude-caption-phrases",
        help=(
            "Comma-separated exact lexical words or phrases to omit from "
            "generated caption text without changing audio."
        ),
    )
    parser.add_argument("--preset")
    parser.add_argument("--replace-existing-preset", action="store_true")
    parser.add_argument("--source-text")
    parser.add_argument("--highlight-text")
    parser.add_argument(
        "--replace-base-ai-captions", action="store_true", default=True
    )
    parser.add_argument("--reuse-transcript", action="store_true")
    parser.add_argument("--take-detection-preset", default="default")
    parser.add_argument("--silence-preset", default="shorts-clean")
    parser.add_argument("--cut-leading-silence", action="store_true")
    parser.add_argument("--cut-trailing-silence", action="store_true")
    parser.add_argument("--previous-text")
    parser.add_argument("--next-text")
    parser.add_argument("--initial-target-gap", type=float, default=0.25)
    parser.add_argument("--minimum-drop-confidence", type=float)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.yaml")
    return parser.parse_args()


def cues_to_srt(cues: list[dict[str, Any]]) -> str:
    subtitles = [
        srt.Subtitle(
            index=index,
            start=timedelta(seconds=float(cue["start"])),
            end=timedelta(seconds=float(cue["end"])),
            content=str(cue["text"]),
        )
        for index, cue in enumerate(cues, 1)
    ]
    return srt.compose(subtitles, reindex=True)


def _format_range(value: dict[str, Any] | None) -> str:
    if not value:
        return "unknown"
    seconds = value.get("seconds")
    if not seconds:
        return "unknown"
    return f"{seconds['start']:.3f}s → {seconds['end']:.3f}s"


def print_capcut_timeline(timeline: dict[str, Any]) -> None:
    console.print(f"[bold]Project:[/bold] {timeline['project_name']}")
    console.print(f"[bold]Path:[/bold] {timeline['project_path']}")
    console.print(f"[bold]Draft:[/bold] {timeline['draft_content_path']}")
    console.print(f"[bold]Read-only backup:[/bold] {timeline['backup_path']}")
    table = Table(title="CapCut timeline media")
    table.add_column("Track")
    table.add_column("Media path")
    table.add_column("Source range")
    table.add_column("Target timeline range")
    table.add_column("Clip duration")
    rows = 0
    for track in timeline["tracks"]:
        for segment in track["segments"]:
            if not segment.get("media_path"):
                continue
            rows += 1
            table.add_row(
                f"{track.get('track_type') or 'unknown'} #{track['track_index']}",
                segment["media_path"],
                _format_range(segment.get("source_time_range")),
                _format_range(segment.get("target_timeline_range")),
                (
                    f"{segment['clip_duration_on_timeline_seconds']:.3f}s"
                    if segment.get("clip_duration_on_timeline_seconds") is not None
                    else "unknown"
                ),
            )
    if rows:
        console.print(table)
    else:
        console.print("[yellow]No timeline segments with resolved local media paths were found.[/yellow]")


def run_capcut_read(project_root: Path | None) -> Path:
    ensure_directories()
    candidate = find_latest_draft(project_root)
    timeline, output = read_project(candidate)
    print_capcut_timeline(timeline)
    return output


def _print_fixture_discovery(projects: list[Any]) -> None:
    table = Table(title="CapCut schema fixture discovery (source is read-only)")
    table.add_column("Project")
    table.add_column("Source folder")
    table.add_column("Modified")
    table.add_column("Duration")
    table.add_column("draft_content.json")
    table.add_column("draft_meta_info.json")
    table.add_column("Size")
    for project in projects:
        table.add_row(
            project.display_name,
            str(project.project_path),
            project.modified_time,
            (
                f"{project.duration_seconds:.3f}s"
                if project.duration_seconds is not None else "unknown"
            ),
            str(project.draft_content_path),
            str(project.draft_meta_info_path or "not found"),
            f"{project.total_size:,} bytes",
        )
    console.print(table)


def _print_fixture_validation(report: dict[str, Any]) -> None:
    table = Table(title="Copied fixture validation")
    table.add_column("Fixture")
    table.add_column("Files")
    table.add_column("Caption texts found")
    table.add_column("Result")
    for fixture in report.get("fixtures", []):
        table.add_row(
            fixture["fixture_name"],
            str(fixture.get("file_count", 0)),
            ", ".join(
                fixture.get("caption_texts")
                or fixture.get("caption_texts_found", [])
            ) or "(none)",
            "PASS" if fixture.get("valid") else "FAIL",
        )
    console.print(table)
    if report.get("warnings"):
        console.print("[yellow]Warnings:[/yellow]")
        for warning in report["warnings"]:
            console.print(f"- {warning}")
    if report.get("errors"):
        console.print("[red]Errors:[/red]")
        for error in report["errors"]:
            console.print(f"- {error}")


def run_collect_capcut_fixtures(project_root: Path | None) -> Path:
    projects = scan_expected_projects(project_root)
    _print_fixture_discovery(projects)
    console.print(
        "[bold]Copy preview:[/bold] complete source folders will be copied to:"
    )
    for project in projects:
        destination = PROJECT_ROOT / "sample_capcut_projects" / DESTINATIONS[project.display_name]
        console.print(f"- {project.project_path} -> {destination}")
    manifest, manifest_path = collect_fixtures(projects)
    report = validate_fixtures()
    write_json(PROJECT_ROOT / "logs/capcut_fixture_validation.json", report)
    version = manifest["capcut"]
    console.print(
        f"[bold]Detected CapCut version:[/bold] {version.get('version_number') or 'unknown'}"
    )
    _print_fixture_validation(report)
    if not report["valid"]:
        raise RuntimeError(
            "Fixture collection completed but validation failed. "
            "No source CapCut project was modified."
        )
    return manifest_path


def run_validate_capcut_fixtures() -> Path:
    report = validate_fixtures()
    output = PROJECT_ROOT / "logs/capcut_fixture_validation.json"
    write_json(output, report)
    _print_fixture_validation(report)
    if not report["valid"]:
        raise RuntimeError("Fixture validation failed.")
    return output


def run_learn_capcut_schema() -> Path:
    learned, output = learn_capcut_schema()
    caption = learned["caption"]
    time_report = learned["time"]
    cut = learned["cut"]
    console.print("[bold]CapCut schema learning completed (read-only fixtures).[/bold]")
    console.print(f"Caption track path: {caption['caption_track_path']}")
    console.print(f"Caption segment path: {caption['caption_segment_path']}")
    console.print(f"Caption material path: {caption['caption_material_path']}")
    console.print(f"Caption text path: {caption['caption_text_path']}")
    console.print(
        f"Time unit: {time_report['capcut_time_unit']} "
        f"({time_report['units_per_second']} units/second)"
    )
    console.print(f"ID relationship: {caption['reference_rule']}")
    console.print(f"Style differences found: {len(learned['style']['differences'])}")
    console.print(
        "Cut structure: "
        f"{cut['schema_01_video_segment_count']} -> "
        f"{cut['schema_05_video_segment_count']} video segments; "
        f"source gaps={cut['source_gaps_seconds']}; "
        f"timeline gaps={cut['timeline_gaps_seconds']}"
    )
    console.print(
        f"Unresolved fields: {len(learned['summary']['unresolved_fields'])}"
    )
    console.print(
        f"Schema confidence: {learned['summary']['schema_confidence']:.2%}"
    )
    if not learned["summary"]["validation_passed"]:
        raise RuntimeError("Schema learning validation failed.")
    return output


def run_inject_caption_test() -> Path:
    validation = inject_caption_test()
    console.print(f"[bold]Sandbox:[/bold] {validation['sandbox_path']}")
    console.print(f"[bold]Backup:[/bold] {validation['backup_path']}")
    console.print(
        f"[bold]Caption track ID:[/bold] {validation['generated_ids']['track_id']}"
    )
    console.print("[green]Sandbox caption injection validation: PASS[/green]")
    return PROJECT_ROOT / "logs/caption_injection_validation.json"


def run_validate_caption_test() -> Path:
    validation = validate_caption_test()
    output = PROJECT_ROOT / "logs/caption_injection_validation.json"
    write_json(output, validation)
    if not validation["valid"]:
        raise RuntimeError("Sandbox caption validation failed.")
    console.print("[green]Independent sandbox caption validation: PASS[/green]")
    return output


def run_rollback_caption_test() -> Path:
    backup, archived = rollback_caption_test()
    console.print(f"[green]Sandbox restored from:[/green] {backup}")
    console.print(f"Pre-rollback sandbox archived at: {archived}")
    return PROJECT_ROOT / "sandbox_capcut_projects/caption_injection_test"


def run_inject_caption_plan(args: argparse.Namespace) -> Path:
    if args.plan is None or not args.sandbox_name:
        raise ValueError("--plan and --sandbox-name are required.")
    validation = inject_caption_plan(args.plan, args.sandbox_name)
    console.print(f"[bold]Sandbox:[/bold] {validation['sandbox_path']}")
    console.print(f"[bold]Captions injected:[/bold] {validation['caption_count']}")
    console.print("[green]Caption-plan sandbox injection: PASS[/green]")
    prefix = (
        "bulk_caption_injection"
        if args.sandbox_name == "bulk_caption_test"
        else "elevenlabs_regrouped_injection"
        if args.sandbox_name == "elevenlabs_regrouped_test"
        else f"{args.sandbox_name}_caption_injection"
    )
    return PROJECT_ROOT / "logs" / f"{prefix}_validation.json"


def run_validate_caption_plan(args: argparse.Namespace) -> Path:
    if not args.sandbox_name:
        raise ValueError("--sandbox-name is required.")
    validation = validate_caption_plan_sandbox(args.sandbox_name)
    prefix = (
        "bulk_caption_injection"
        if args.sandbox_name == "bulk_caption_test"
        else "elevenlabs_regrouped_injection"
        if args.sandbox_name == "elevenlabs_regrouped_test"
        else f"{args.sandbox_name}_caption_injection"
    )
    output = PROJECT_ROOT / "logs" / f"{prefix}_validation.json"
    write_json(output, validation)
    if not validation["valid"]:
        raise RuntimeError("Independent caption-plan validation failed.")
    console.print(
        f"[green]Independent caption-plan validation: PASS "
        f"({validation['caption_count']} captions)[/green]"
    )
    return output


def run_rollback_caption_plan(args: argparse.Namespace) -> Path:
    if not args.sandbox_name:
        raise ValueError("--sandbox-name is required.")
    backup, archived = rollback_caption_plan(args.sandbox_name)
    console.print(f"[green]Sandbox restored from:[/green] {backup}")
    console.print(f"Injected sandbox archived at: {archived}")
    return PROJECT_ROOT / "sandbox_capcut_projects" / args.sandbox_name


def _stt_preflight(config: dict[str, Any]) -> dict[str, Any]:
    env_path = PROJECT_ROOT / ".env"
    report = {
        "env_exists": env_path.is_file(),
        "api_key_detected": bool(os.getenv("ELEVENLABS_API_KEY", "").strip()),
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "ffprobe_available": shutil.which("ffprobe") is not None,
        "elevenlabs_sdk_importable": importlib.util.find_spec("elevenlabs") is not None,
        "model_id": config["model_id"],
        "language_code": config["language_code"],
        "timestamps_granularity": config["timestamps_granularity"],
        "diarize": config["diarize"],
    }
    report["valid"] = all((
        report["env_exists"], report["api_key_detected"],
        report["ffmpeg_available"], report["ffprobe_available"],
        report["elevenlabs_sdk_importable"],
    ))
    write_json(PROJECT_ROOT / "logs/elevenlabs_test_preflight.json", report)
    if not report["valid"]:
        failed = [key for key, value in report.items() if key.endswith(
            ("exists", "detected", "available", "importable")
        ) and not value]
        raise RuntimeError("ElevenLabs preflight failed: " + ", ".join(failed))
    return report


def _run_short_stt(args: argparse.Namespace) -> tuple[Path, float, float, dict[str, Any], list[dict[str, Any]]]:
    if args.input is None:
        raise ValueError("--input is required.")
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input media not found: {input_path}")
    basename = safe_basename(input_path)
    config = load_config(args.config)
    if args.timestamp_granularity:
        config["timestamps_granularity"] = args.timestamp_granularity
    _stt_preflight(config)
    media = probe_media(input_path, basename)
    duration = float(media["target_duration"])
    submitted_duration = min(duration, 20.0)
    audio_path = extract_audio(input_path, basename, max_duration=submitted_duration)
    terms = (
        [term.strip() for term in args.keyterms.split(",") if term.strip()]
        if args.keyterms is not None else None
    )
    output_basename = (
        f"{basename}.character"
        if config["timestamps_granularity"] == "character" else basename
    )
    raw, words = transcribe(
        audio_path, output_basename, config, terms, media_duration=submitted_duration
    )
    write_json(PROJECT_ROOT / "logs/elevenlabs_test_words.json", words)
    console.print("[green]API connection status: connected[/green]")
    console.print(f"Media duration: {duration:.3f}s")
    console.print(f"Submitted sample duration: {submitted_duration:.3f}s")
    console.print(
        f"Detected language: {raw.get('language_code') or raw.get('language') or 'unknown'}"
    )
    console.print(f"Transcript: {transcript_text(raw)}")
    console.print(f"Word timestamp count: {len(words)}")
    console.print("First 20 normalized words:")
    console.print_json(json.dumps(words[:20], ensure_ascii=False))
    console.print(f"Raw response: output/json/{output_basename}.elevenlabs_raw.json")
    console.print(f"Normalized words: output/json/{output_basename}.words.json")
    return input_path, duration, submitted_duration, raw, words


def run_elevenlabs_test(args: argparse.Namespace) -> Path:
    input_path, _duration, _submitted, _raw, _words = _run_short_stt(args)
    suffix = ".character" if args.timestamp_granularity == "character" else ""
    return PROJECT_ROOT / "output/json" / f"{safe_basename(input_path)}{suffix}.words.json"


def run_local_thai_regrouping(args: argparse.Namespace) -> Path:
    if args.input is None:
        raise ValueError("--input is required.")
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input media not found: {input_path}")
    basename = safe_basename(input_path)
    raw_path = PROJECT_ROOT / "output/json" / f"{basename}.elevenlabs_raw.json"
    if not raw_path.is_file():
        raise FileNotFoundError(f"Saved ElevenLabs response not found: {raw_path}")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    media = probe_media(input_path, basename)
    duration = min(float(media["target_duration"]), 20.0)
    terms = (
        [term.strip() for term in args.keyterms.split(",") if term.strip()]
        if args.keyterms is not None else load_default_keyterms()
    )
    lexical_words, analysis = regroup_raw_response(raw, terms)
    lexical_output = PROJECT_ROOT / "output/json" / f"{basename}.lexical_words.json"
    public_lexical_words = [
        {
            "text": word["text"],
            "start": word["start"],
            "end": word["end"],
            "source_fragment_indices": word["source_fragment_indices"],
            "merge_reason": word["merge_reason"],
        }
        for word in lexical_words
    ]
    write_json(lexical_output, public_lexical_words)
    write_json(PROJECT_ROOT / "logs" / f"{basename}_thai_token_analysis.json", analysis)
    layout = resolve_caption_layout(
        None, args.caption_layout, args.max_words_per_caption
    )
    max_words = int(layout["max_words_per_caption"])
    plan = build_regrouped_caption_plan(
        str(input_path), duration, str(raw.get("text") or ""), lexical_words,
        config={"max_words_per_cue": max_words},
    )
    structural = validate_caption_plan(
        plan, max_words=max_words, lexical_words=lexical_words
    )
    semantic = validate_thai_caption_plan(
        plan, str(raw.get("text") or ""), lexical_words, max_words=max_words
    )
    combined = {
        "valid": structural["valid"] and semantic["valid"],
        "structural": structural,
        "semantic": semantic,
        "character_timestamp_rerun_necessary": False,
        "caption_layout": layout,
    }
    write_json(
        PROJECT_ROOT / "logs" / f"{basename}_thai_lexical_validation.json",
        combined,
    )
    output = PROJECT_ROOT / "output/json" / f"{basename}.caption_plan.regrouped.json"
    if not combined["valid"]:
        failed = output.with_name(f"{basename}.caption_plan.regrouped.failed.json")
        write_json(failed, plan)
        raise RuntimeError(
            "Regrouped caption validation failed: "
            + "; ".join(structural["errors"] + semantic["errors"])
        )
    write_json(output, plan)
    preview = [
        f"{caption['id']} {caption['start']:.3f}-{caption['end']:.3f} {caption['text']}"
        for caption in plan["captions"]
    ]
    (PROJECT_ROOT / "output/preview" / f"{basename}_caption_plan_regrouped.txt").write_text(
        "\n".join(preview) + "\n", encoding="utf-8"
    )
    console.print(f"Raw fragment count: {analysis['raw_record_count']}")
    console.print(f"Regrouped lexical token count: {len(lexical_words)}")
    console.print(f"Caption count: {len(plan['captions'])}")
    console.print(
        f"Semantic validation: {'PASS' if semantic['valid'] else 'FAIL'}"
    )
    console.print("Character-timestamp API rerun necessary: NO")
    return output


def _project_slug(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9\u0E00-\u0E7F]+", "_", name).strip("_")
    return value.casefold() or "project"


def _timeline_preview(project: Any, analysis: dict[str, Any]) -> str:
    lines = [
        f"Project: {project.name}",
        f"Path: {project.path}",
        f"Duration: {analysis['duration']:.6f}s",
        f"Video tracks: {analysis['video_track_count']}",
        f"Audio tracks: {analysis['audio_track_count']}",
        f"Video segments: {analysis['video_segment_count']}",
        f"Audio segments: {analysis['audio_segment_count']}",
        "",
        "AUDIBLE TIMELINE SEGMENTS",
    ]
    for item in analysis["audible_segments"]:
        source, target = item["source_timerange"], item["target_timerange"]
        lines.append(
            f"- {item['track_type']} {item['segment_id']} | {item['media_path']} | "
            f"source={source['start']:.6f}-{source['end']:.6f} | "
            f"target={target['start']:.6f}-{target['end']:.6f} | "
            f"speed={item['speed']:.6f}"
        )
    lines.extend(["", "TIMELINE GAPS"])
    lines.extend(
        f"- {gap['start']:.6f}-{gap['end']:.6f} ({gap['duration']:.6f}s)"
        for gap in analysis["timeline_gaps"]
    )
    if not analysis["timeline_gaps"]:
        lines.append("- none")
    lines.extend(["", "UNSUPPORTED STRUCTURES"])
    lines.extend(f"- {item}" for item in analysis["unsupported_structures"])
    if not analysis["unsupported_structures"]:
        lines.append("- none")
    lines.append(
        f"\nSafe for direct transcription: "
        f"{'YES' if analysis['safe_for_direct_transcription'] else 'NO'}"
    )
    return "\n".join(lines) + "\n"


def _inspect_direct_project(args: argparse.Namespace) -> tuple[Any, Any, dict[str, Any], str]:
    require_capcut_closed()
    project = locate_project(str(args.project))
    live = read_live_project(project)
    schema_status = compatibility_status(live.primary)
    analysis = analyze_timeline(live.primary)
    layout = resolve_caption_layout(
        live.primary, args.caption_layout, args.max_words_per_caption,
        metadata=live.metadata,
    )
    slug = _project_slug(project.name)
    analysis = {
        "project_identity": project.identity,
        "project_name": project.name,
        "project_path": str(project.path),
        "draft_paths": [str(path) for path in live.draft_paths],
        "draft_storage_format": live.storage_format,
        "schema_compatibility": schema_status,
        "caption_layout": layout,
        **layout,
        **analysis,
    }
    output = PROJECT_ROOT / "output/json" / f"{slug}.timeline_analysis.json"
    preview = PROJECT_ROOT / "output/preview" / f"{slug}_timeline_analysis.txt"
    log_dir = PROJECT_ROOT / "logs/direct_edit" / slug
    write_json(output, analysis)
    write_json(log_dir / "timeline_analysis.json", analysis)
    write_json(log_dir / "preflight.json", {
        "valid": analysis["safe_for_direct_transcription"],
        "capcut_closed": True,
        "project_match_count": 1,
        "project_identity": project.identity,
        "project_path": str(project.path),
        "mirrored_draft_count": len(live.draft_paths),
        "draft_storage_format": live.storage_format,
        "schema_compatibility": schema_status,
        "offline_media": analysis["offline_media"],
        "unsupported_structures": analysis["unsupported_structures"],
        "caption_layout": layout,
        **layout,
    })
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_text(_timeline_preview(project, analysis), encoding="utf-8")
    return project, live, analysis, slug


def run_inspect_project(args: argparse.Namespace) -> Path:
    project, _live, analysis, slug = _inspect_direct_project(args)
    console.print(f"Matched project path: {project.path}")
    console.print(f"User-visible project name: {project.name}")
    console.print(f"Project duration: {analysis['duration']:.6f}s")
    console.print(f"Video tracks: {analysis['video_track_count']}")
    console.print(f"Audio tracks: {analysis['audio_track_count']}")
    console.print(f"Video segments: {analysis['video_segment_count']}")
    console.print(
        f"Draft storage: {analysis['draft_storage_format']}; "
        f"direct write: "
        f"{'ALLOWED' if analysis['schema_compatibility']['write_allowed'] else 'BLOCKED'}"
    )
    layout = analysis["caption_layout"]
    console.print(
        f"Canvas: {layout['canvas_width']}x{layout['canvas_height']} "
        f"({layout['orientation']}); max lexical words: "
        f"{layout['max_words_per_caption']}"
    )
    console.print(
        "Direct timeline transcription safe: "
        + ("YES" if analysis["safe_for_direct_transcription"] else "NO")
    )
    return PROJECT_ROOT / "output/json" / f"{slug}.timeline_analysis.json"


def run_list_capcut_projects() -> Path:
    require_capcut_closed()
    projects = discover_projects()
    output = PROJECT_ROOT / "output/json/capcut_projects.json"
    records = [
        {
            "name": project.name,
            "path": str(project.path),
            "identity": project.identity,
            "modified_time": project.modified_time,
        }
        for project in projects
    ]
    write_json(output, records)
    if not records:
        console.print("[yellow]No metadata-backed CapCut projects found.[/yellow]")
    else:
        table = Table(title="CapCut projects")
        table.add_column("Name")
        table.add_column("Path")
        table.add_column("Modified")
        for record in records:
            table.add_row(
                record["name"], record["path"], f"{record['modified_time']:.6f}"
            )
        console.print(table)
    return output


def _transcribe_direct_timeline(
    args: argparse.Namespace,
) -> tuple[Any, Any, dict[str, Any], str, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    project, live, analysis, slug = _inspect_direct_project(args)
    if not analysis["safe_for_direct_transcription"]:
        raise RuntimeError(
            "Direct timeline transcription is unsafe: "
            + "; ".join(analysis["offline_media"] + analysis["unsupported_structures"])
        )
    wav = render_timeline_audio(analysis, slug)
    config = load_config(args.config)
    terms = (
        [term.strip() for term in args.keyterms.split(",") if term.strip()]
        if args.keyterms is not None else load_default_keyterms()
    )
    timeline_hash = stable_hash({
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    })
    try:
        raw_path = (
            PROJECT_ROOT / "output/json"
            / f"{slug}.timeline.elevenlabs_raw.json"
        )
        cached_raw: dict[str, Any] | None = None
        cache_summary_path = (
            PROJECT_ROOT / "logs/direct_edit" / slug / "stt_summary.json"
        )
        if raw_path.is_file() and cache_summary_path.is_file():
            candidate = json.loads(raw_path.read_text(encoding="utf-8"))
            cache_summary = json.loads(
                cache_summary_path.read_text(encoding="utf-8")
            )
            if cache_summary.get("timeline_hash") == timeline_hash:
                cached_raw = candidate
        elif raw_path.is_file() and not cache_summary_path.is_file():
            # A provider response may already have been saved before a later
            # local regrouping/validation failure. Reuse it only when it is
            # newer than every current draft and its rendered-audio duration
            # proves that it belongs to this exact, unchanged timeline.
            candidate = json.loads(raw_path.read_text(encoding="utf-8"))
            draft_mtime = max(
                Path(path).stat().st_mtime_ns for path in analysis["draft_paths"]
            )
            try:
                cached_duration = float(candidate["audio_duration_secs"])
            except (KeyError, TypeError, ValueError):
                cached_duration = -1.0
            if (
                raw_path.stat().st_mtime_ns >= draft_mtime
                and abs(cached_duration - float(analysis["duration"])) <= 0.15
            ):
                cached_raw = candidate
            elif (
                not cache_summary.get("timeline_hash")
                and cache_summary.get("transcript") == candidate.get("text")
                and raw_path.stat().st_mtime_ns
                >= max(Path(path).stat().st_mtime_ns for path in analysis["draft_paths"])
            ):
                # Migrate cache summaries written by older builds that omitted
                # timeline_hash. A raw response created after the current,
                # closed-project drafts and matching the saved transcript is
                # evidence that it belongs to this exact inspected timeline.
                cached_raw = candidate
        if cached_raw is not None:
            raw = cached_raw
            console.print("[cyan]Reusing saved timeline transcription; no API call.[/cyan]")
        else:
            raw, _fragments = transcribe(
                wav, f"{slug}.timeline", config, terms,
                media_duration=float(analysis["duration"]),
            )
        lexical, token_analysis = regroup_raw_response(raw, terms)
        public_lexical = [
            {
                "text": word["text"],
                "start": word["start"],
                "end": word["end"],
                "confidence": word.get("confidence"),
                "source_fragment_indices": word["source_fragment_indices"],
            }
            for word in lexical
        ]
        write_json(
            PROJECT_ROOT / "output/json" / f"{slug}.lexical_words.json",
            public_lexical,
        )
        caption_lexical = lexical
        # The display transcript is the exact lexical stream. Provider-level
        # audio-event annotations are intentionally excluded from captions and
        # from silence/take semantics.
        caption_transcript = "".join(
            str(word.get("text") or "") for word in lexical
        )
        caption_filter = None
        if args.exclude_caption_phrases:
            caption_lexical, caption_filter = filter_caption_lexical_words(
                lexical, args.exclude_caption_phrases
            )
            if not caption_lexical:
                raise RuntimeError(
                    "Caption phrase filtering removed every lexical token."
                )
            # Semantic validation compares compact text, so joining the exact
            # retained lexical tokens is authoritative and spacing-agnostic.
            caption_transcript = "".join(
                str(word.get("text") or "") for word in caption_lexical
            )
            write_json(
                PROJECT_ROOT / "output/json"
                / f"{slug}.caption_lexical_words.filtered.json",
                [
                    {
                        "text": word["text"],
                        "start": word["start"],
                        "end": word["end"],
                        "confidence": word.get("confidence"),
                        "source_fragment_indices": word["source_fragment_indices"],
                    }
                    for word in caption_lexical
                ],
            )
        layout = analysis["caption_layout"]
        max_words = int(layout["max_words_per_caption"])
        plan = build_regrouped_caption_plan(
            str(project.path), float(analysis["duration"]),
            caption_transcript, caption_lexical,
            config={"max_words_per_cue": max_words},
        )
        if caption_filter is not None:
            plan["caption_filter"] = caption_filter
        plan_path = PROJECT_ROOT / "output/json" / f"{slug}.caption_plan.json"
        structural = validate_caption_plan(
            plan, max_words=max_words, lexical_words=caption_lexical
        )
        semantic = validate_thai_caption_plan(
            plan, caption_transcript, caption_lexical, max_words=max_words
        )
        # Caption grouping must never strand Thai Mai Yamok at a cue boundary.
        # Repair this locally from the generated plan before final validation;
        # this does not alter timings, call transcription, or touch CapCut.
        if not (structural["valid"] and semantic["valid"]) and any(
            "THAI_MAI_YAMOK_" in error
            for error in structural["errors"] + semantic["errors"]
        ):
            repair_input = plan_path.with_name(
                f"{slug}.caption_plan.pre_normalization.json"
            )
            write_json(repair_input, plan)
            _repair, repaired_path, _preview, _log = normalize_thai_caption_plan(
                repair_input, max_words=max_words
            )
            plan = json.loads(repaired_path.read_text(encoding="utf-8"))
            structural = validate_caption_plan(
                plan, max_words=max_words, lexical_words=caption_lexical
            )
            semantic = validate_thai_caption_plan(
                plan, caption_transcript, caption_lexical, max_words=max_words
            )
        validation = {
            "valid": structural["valid"] and semantic["valid"],
            "structural": structural,
            "semantic": semantic,
            "caption_layout": layout,
            "timeline_hash": timeline_hash,
            "caption_filter": caption_filter,
        }
        log_dir = PROJECT_ROOT / "logs/direct_edit" / slug
        write_json(log_dir / "stt_summary.json", {
            "provider": "elevenlabs",
            "model": "scribe_v2",
            "detected_language": raw.get("language_code"),
            "transcript": raw.get("text"),
            "lexical_token_count": len(lexical),
            "caption_lexical_token_count": len(caption_lexical),
            "caption_filter": caption_filter,
            "token_analysis": token_analysis,
            "caption_layout": layout,
            "timeline_hash": timeline_hash,
        })
        write_json(log_dir / "caption_plan_validation.json", validation)
        if not validation["valid"]:
            write_json(
                plan_path.with_name(f"{slug}.caption_plan.failed.json"), plan
            )
            raise RuntimeError(
                "Direct caption plan validation failed: "
                + "; ".join(structural["errors"] + semantic["errors"])
            )
        write_json(plan_path, plan)
        # Karaoke consumes the validated display-normalized plan by this
        # stable name. Always publish it, including when no repair was needed.
        write_json(
            plan_path.with_name(f"{slug}.caption_plan.thai_normalized.json"),
            plan,
        )
        return project, live, analysis, slug, plan, lexical, validation
    finally:
        wav.unlink(missing_ok=True)


def run_transcribe_project(args: argparse.Namespace) -> Path:
    _project, _live, _analysis, slug, _plan, _lexical, _validation = (
        _transcribe_direct_timeline(args)
    )
    return PROJECT_ROOT / "output/json" / f"{slug}.caption_plan.json"


def run_edit_project(args: argparse.Namespace) -> Path:
    if args.task != "captions":
        raise ValueError("--task captions is required for edit-project.")
    project, live, analysis, slug, plan, _lexical, validation = (
        _transcribe_direct_timeline(args)
    )
    if not validation["valid"]:
        raise RuntimeError("Caption validation did not pass; direct write aborted.")
    preset_id, caption_style = resolve_caption_style(
        args.caption_style, plan["captions"]
    )
    source_orientation = str(
        (caption_style.get("source") or {}).get("orientation") or "unknown"
    )
    target_orientation = str(
        (analysis.get("caption_layout") or {}).get("orientation") or "unknown"
    )
    style_warning = (
        f"Caption style {preset_id} was learned for {source_orientation} but "
        f"target canvas is {target_orientation}; exact values were preserved without scaling."
        if source_orientation not in {"", "unknown", target_orientation}
        else None
    )
    result = edit_captions_direct(
        live, plan, {
            "duration": analysis["duration"],
            "audible_segments": analysis["audible_segments"],
        },
        caption_style,
        dry_run=bool(args.dry_run),
    )
    log_dir = PROJECT_ROOT / "logs/direct_edit" / slug
    write_json(log_dir / "injection_changes.json", result["changes"])
    write_json(log_dir / "post_write_validation.json", {
        **result,
        "caption_style_preset": preset_id,
        "caption_style_warning": style_warning,
    })
    if args.dry_run:
        return PROJECT_ROOT / "output/json" / f"{slug}.caption_plan.json"
    return Path(result["registry_path"])


def run_learn_caption_style(args: argparse.Namespace) -> Path:
    if not args.preset:
        raise ValueError("--preset is required for learn-caption-style.")
    learning, path = learn_caption_style(
        str(args.project), args.preset,
        replace_existing=args.replace_existing_preset,
    )
    console.print(
        f"[green]Learned {learning['selected_style_usage_count']}/"
        f"{learning['caption_count']} captions into {args.preset} without "
        "modifying Apple.[/green]"
    )
    return path


def run_validate_caption_style(args: argparse.Namespace) -> Path:
    if not args.preset:
        raise ValueError("--preset is required for validate-caption-style.")
    report = validate_caption_style(args.preset)
    if not report["valid"]:
        raise RuntimeError(
            "Caption-style validation failed: " + "; ".join(report["errors"])
        )
    source_name = args.preset
    try:
        preset = json.loads(
            (PROJECT_ROOT / f"presets/captions/{args.preset}.json").read_text(
                encoding="utf-8"
            )
        )
        source_name = str((preset.get("source") or {}).get("project_name") or source_name)
    except (OSError, json.JSONDecodeError):
        pass
    return (
        PROJECT_ROOT / "logs/direct_edit" / source_name.casefold()
        / "caption_style_validation.json"
    )


def run_normalize_thai_caption_plan(args: argparse.Namespace) -> Path:
    if args.plan is None:
        raise ValueError("--plan is required for normalize-thai-caption-plan.")
    plan_path = args.plan.resolve()
    if not plan_path.is_file():
        raise FileNotFoundError(f"Caption plan not found: {plan_path}")
    report, output, _preview, _log = normalize_thai_caption_plan(plan_path)
    console.print(
        f"[green]Thai caption normalization PASS: "
        f"attached={report['mai_yamok_attached']}, "
        f"boundaries={report['caption_boundaries_repaired']}[/green]"
    )
    return output


def run_learn_karaoke_style(args: argparse.Namespace) -> Path:
    if not args.preset or not args.source_text or not args.highlight_text:
        raise ValueError(
            "--preset, --source-text, and --highlight-text are required."
        )
    report, path = learn_karaoke_style(
        str(args.project), args.source_text, args.highlight_text, args.preset
    )
    validation = validate_karaoke_preset(args.preset)
    if not validation["valid"]:
        raise RuntimeError(
            "Karaoke preset validation failed: " + "; ".join(validation["errors"])
        )
    console.print(
        f"[green]Learned karaoke glyph range {report['expected_utf16_glyph_range']} "
        f"with {report['hex']} without modifying Apple.[/green]"
    )
    return path


def run_build_karaoke_plan(args: argparse.Namespace) -> Path:
    if not args.preset:
        raise ValueError("--preset is required for build-karaoke-plan.")
    plan, metadata, _live, _lexical = build_project_karaoke_plan(
        str(args.project), args.preset
    )
    console.print(
        f"[green]Karaoke plan PASS: captions={metadata['caption_count']}, "
        f"states={metadata['generated_segment_count']}, "
        f"cache={metadata['timeline_cache_status']}[/green]"
    )
    return PROJECT_ROOT / f"output/json/{str(args.project).casefold()}.karaoke_plan.json"


def run_apply_karaoke(args: argparse.Namespace) -> Path:
    if not args.preset:
        raise ValueError("--preset is required for apply-karaoke.")
    require_capcut_closed()
    _result, output = apply_project_karaoke(
        str(args.project), args.preset, dry_run=bool(args.dry_run)
    )
    if args.dry_run:
        return output
    report = validate_project_karaoke(str(args.project))
    if not report["valid"]:
        raise RuntimeError(
            "Independent karaoke validation failed: " + "; ".join(report["errors"])
        )
    return output


def run_validate_karaoke(args: argparse.Namespace) -> Path:
    report = validate_project_karaoke(str(args.project))
    if not report["valid"]:
        raise RuntimeError("Karaoke validation failed: " + "; ".join(report["errors"]))
    return (
        PROJECT_ROOT / f"logs/direct_edit/{str(args.project).casefold()}"
        / "karaoke_validation.json"
    )


def run_repair_karaoke_duplicates(args: argparse.Namespace) -> Path:
    require_capcut_closed()
    result, output = repair_project_karaoke_duplicates(str(args.project))
    console.print(
        f"[green]Karaoke duplicate repair PASS: "
        f"{result['duplicate_overlap_count_before']} -> "
        f"{result['duplicate_overlap_count_after']} overlaps[/green]"
    )
    return output


def run_detect_silence(args: argparse.Namespace) -> Path:
    plan, _live, _words, metadata = detect_project_silence(
        str(args.project), args.silence_preset
    )
    console.print(
        f"[green]Silence detection PASS: safe={len(plan['cuts'])}, "
        f"skipped={len(plan['skipped_candidates'])}, "
        f"proposed={metadata['total_duration_proposed']:.3f}s, "
        f"cache={metadata['timeline_cache_status']}, ElevenLabs=false[/green]"
    )
    return (
        PROJECT_ROOT / "output/json"
        / f"{str(args.project).casefold().replace(' ', '_')}.silence_cut_plan.json"
    )


def run_auto_cut_silence(args: argparse.Namespace) -> Path:
    _result, output = apply_project_silence_cut(
        str(args.project), args.silence_preset, dry_run=bool(args.dry_run)
    )
    return output


def run_validate_silence_cut(args: argparse.Namespace) -> Path:
    report, output = validate_project_silence_cut(str(args.project))
    if not report["valid"]:
        raise RuntimeError("Silence-cut validation failed.")
    return output


def run_analyze_target_pause(args: argparse.Namespace) -> Path:
    if not args.previous_text or not args.next_text:
        raise ValueError(
            "--previous-text and --next-text are required for analyze-target-pause."
        )
    result, output = analyze_target_pause(
        str(args.project), args.previous_text, args.next_text,
        args.initial_target_gap,
    )
    console.print(
        f"[green]Target pause analysis PASS: gap="
        f"{result['original_gap_seconds']:.3f}s, recommended="
        f"{result['recommended_remaining_gap_seconds']:.3f}s, "
        f"project_modified=false, ElevenLabs=false[/green]"
    )
    return output


def run_apply_pattern1(args: argparse.Namespace) -> Path:
    if args.plan is None:
        raise ValueError("--plan is required for apply-pattern-1.")
    if not args.reference_project:
        raise ValueError("--reference-project is required for apply-pattern-1.")
    _result, output = apply_pattern1(
        str(args.project), str(args.reference_project), args.plan,
        dry_run=bool(args.dry_run),
    )
    return output


def run_remove_pattern1(args: argparse.Namespace) -> Path:
    _result, output = remove_pattern1_registered(
        str(args.project), dry_run=bool(args.dry_run),
    )
    return output


def run_validate_project_edit(args: argparse.Namespace) -> Path:
    project, live, analysis, slug = _inspect_direct_project(args)
    registry = load_registry(project.identity)
    if registry is None:
        raise FileNotFoundError("No AI caption registry exists for this project.")
    data = live.primary
    track_ids = {track.get("id") for track in data.get("tracks", [])}
    all_segments = {
        segment.get("id")
        for track in data.get("tracks", [])
        for segment in track.get("segments", [])
    }
    all_materials = {
        item.get("id")
        for items in (data.get("materials") or {}).values()
        if isinstance(items, list)
        for item in items if isinstance(item, dict)
    }
    errors = []
    if registry["generated_text_track_id"] not in track_ids:
        errors.append("registered AI text track is missing")
    if not set(registry["generated_segment_ids"]).issubset(all_segments):
        errors.append("registered AI caption segments are missing")
    if not set(registry["generated_material_ids"]).issubset(all_materials):
        errors.append("registered AI text materials are missing")
    timeline_hash = stable_hash({
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    })
    if timeline_hash != registry["timeline_hash"]:
        errors.append("timeline hash differs from the registered edit")
    report = {"valid": not errors, "errors": errors, "registry": registry}
    output = PROJECT_ROOT / "logs/direct_edit" / slug / "post_write_validation.json"
    write_json(output, report)
    if errors:
        raise RuntimeError("Current AI caption validation failed: " + "; ".join(errors))
    return output


def _read_config_lines(path: Path) -> list[str]:
    return [
        line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _project_file_hashes(path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = file_path.relative_to(path).as_posix()
        hashes[relative] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return hashes


def _take_preview(plan: dict[str, Any], utterances: list[dict[str, Any]]) -> str:
    by_id = {item["utterance_id"]: item for item in utterances}
    lines = ["DUPLICATE TAKE ANALYSIS - READ ONLY", ""]
    for number, group in enumerate(plan["groups"], 1):
        keep = by_id[group["recommended_keep_utterance_id"]]
        lines.extend([
            f"DUPLICATE TAKE GROUP {number:03d}",
            f"Category: {group['category'].replace('_', ' ').title()}",
            f"Confidence: {group['confidence']:.0%}",
            "",
        ])
        for drop_id in group["recommended_drop_utterance_ids"]:
            drop = by_id[drop_id]
            lines.extend([
                "DROP CANDIDATE",
                f"{drop['start']:.3f} --> {drop['end']:.3f}",
                f"“{drop['text']}”",
                "",
            ])
        lines.extend([
            "KEEP CANDIDATE",
            f"{keep['start']:.3f} --> {keep['end']:.3f}",
            f"“{keep['text']}”",
            "",
            "Reasons:",
            *[f"- {reason}" for reason in group["reason_codes"]],
            "",
            "Decision:",
            (
                "HIGH-CONFIDENCE DROP RECOMMENDATION"
                if group["recommended_drop_utterance_ids"]
                and group["confidence_class"] == "high"
                else "REVIEW REQUIRED"
                if group["confidence_class"] == "medium"
                else "INFORMATIONAL ONLY"
            ),
            "",
        ])
    if not plan["groups"]:
        lines.append("No duplicate-take groups detected.")
    return "\n".join(lines) + "\n"


def run_detect_duplicate_takes(args: argparse.Namespace) -> Path:
    project, _live, analysis, slug = _inspect_direct_project(args)
    if not analysis["safe_for_direct_transcription"]:
        raise RuntimeError(
            "Timeline is unsafe for duplicate-take analysis: "
            + "; ".join(analysis["offline_media"] + analysis["unsupported_structures"])
        )
    before_hashes = _project_file_hashes(project.path)
    preset_path = (
        PROJECT_ROOT / "presets/take_detection"
        / f"{args.take_detection_preset}.json"
    )
    if not preset_path.is_file():
        raise FileNotFoundError(f"Take-detection preset not found: {preset_path}")
    preset = json.loads(preset_path.read_text(encoding="utf-8"))
    if args.minimum_drop_confidence is not None:
        if not 0 <= args.minimum_drop_confidence <= 1:
            raise ValueError("--minimum-drop-confidence must be between 0 and 1.")
        preset["minimum_drop_confidence"] = args.minimum_drop_confidence
    fillers = _read_config_lines(
        PROJECT_ROOT / "presets/take_detection/thai_fillers.txt"
    )
    markers = _read_config_lines(
        PROJECT_ROOT / "presets/take_detection/thai_restart_markers.txt"
    )
    timeline_signature = {
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    }
    timeline_hash = stable_hash(timeline_signature)
    log_dir = PROJECT_ROOT / "logs/direct_edit" / slug
    summary_path = log_dir / "stt_summary.json"
    lexical_path = PROJECT_ROOT / "output/json" / f"{slug}.lexical_words.json"
    raw_path = (
        PROJECT_ROOT / "output/json" / f"{slug}.timeline.elevenlabs_raw.json"
    )
    cached = False
    raw: dict[str, Any]
    lexical: list[dict[str, Any]]
    if summary_path.is_file() and lexical_path.is_file() and raw_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("timeline_hash") == timeline_hash:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            lexical = json.loads(lexical_path.read_text(encoding="utf-8"))
            cached = True
    if not cached:
        if args.reuse_transcript:
            raise RuntimeError(
                "--reuse-transcript was requested, but no timeline-hash-matched cache exists."
            )
        wav = render_timeline_audio(analysis, slug)
        try:
            config = load_config(args.config)
            terms = (
                [term.strip() for term in args.keyterms.split(",") if term.strip()]
                if args.keyterms is not None else load_default_keyterms()
            )
            raw, _fragments = transcribe(
                wav, f"{slug}.timeline", config, terms,
                media_duration=float(analysis["duration"]),
            )
            regrouped, token_analysis = regroup_raw_response(raw, terms)
            lexical = [
                {
                    "text": word["text"],
                    "start": word["start"],
                    "end": word["end"],
                    "confidence": word.get("confidence"),
                    "source_fragment_indices": word["source_fragment_indices"],
                }
                for word in regrouped
            ]
            write_json(lexical_path, lexical)
            write_json(summary_path, {
                "provider": "elevenlabs",
                "model": "scribe_v2",
                "detected_language": raw.get("language_code"),
                "transcript": raw.get("text"),
                "lexical_token_count": len(lexical),
                "timeline_hash": timeline_hash,
                "token_analysis": token_analysis,
            })
        finally:
            wav.unlink(missing_ok=True)
    utterances = build_utterances(lexical, analysis, fillers, markers, preset)
    candidates, groups = detect_duplicate_takes(utterances, preset)
    plan = build_take_plan(
        groups, utterances, float(analysis["duration"]), preset
    )
    validation = validate_duplicate_take_analysis(
        lexical, utterances, plan, float(preset["minimum_drop_confidence"])
    )
    after_hashes = _project_file_hashes(project.path)
    hashes_unchanged = before_hashes == after_hashes
    if not hashes_unchanged:
        validation["errors"].append("CapCut project files changed during read-only analysis")
        validation["valid"] = False
    validation["project_hashes_unchanged"] = hashes_unchanged
    write_json(
        PROJECT_ROOT / "output/json" / f"{slug}.utterances.json", utterances
    )
    write_json(
        PROJECT_ROOT / "output/json" / f"{slug}.duplicate_take_candidates.json",
        candidates,
    )
    output = PROJECT_ROOT / "output/json" / f"{slug}.take_plan.json"
    write_json(output, plan)
    preview_path = (
        PROJECT_ROOT / "output/preview" / f"{slug}_duplicate_takes.txt"
    )
    preview_path.write_text(_take_preview(plan, utterances), encoding="utf-8")
    detection_log = {
        "project_name": project.name,
        "project_path": str(project.path),
        "project_duration": analysis["duration"],
        "transcript_source": (
            "timeline_hash_matched_cache" if cached else "elevenlabs_scribe_v2"
        ),
        "timeline_hash": timeline_hash,
        "utterance_count": len(utterances),
        "candidate_count": len(candidates),
        "group_count": len(groups),
        "confidence_classes": {
            level: sum(group["confidence_class"] == level for group in groups)
            for level in ("high", "medium", "low")
        },
        "preset": preset,
        "read_only": True,
    }
    write_json(log_dir / "duplicate_take_detection.json", detection_log)
    write_json(log_dir / "duplicate_take_validation.json", validation)
    if not validation["valid"]:
        raise RuntimeError(
            "Duplicate-take validation failed: " + "; ".join(validation["errors"])
        )
    return output


def run_learn_manual_edit_style(args: argparse.Namespace) -> Path:
    if not args.reference_project:
        raise ValueError("--reference-project is required.")
    source_project = locate_project(str(args.project))
    reference_project = locate_project(str(args.reference_project))
    source_live = read_live_project(source_project)
    reference_live = read_live_project(reference_project)
    source_analysis = analyze_timeline(source_live.primary)
    reference_analysis = analyze_timeline(reference_live.primary)
    slug = _project_slug(source_project.name)
    reference_slug = _project_slug(reference_project.name)
    raw_path = (
        PROJECT_ROOT / "output/json"
        / f"{reference_slug}.timeline.elevenlabs_raw.json"
    )
    raw = (
        json.loads(raw_path.read_text(encoding="utf-8"))
        if raw_path.is_file() else None
    )
    profile = learn_manual_edit_style(
        {**source_analysis, "project_name": source_project.name},
        {**reference_analysis, "project_name": reference_project.name},
        raw,
    )
    preset_dir = PROJECT_ROOT / "presets/editing"
    preset_dir.mkdir(parents=True, exist_ok=True)
    preset_path = preset_dir / f"{reference_slug}.json"
    write_json(preset_path, profile)
    output = (
        PROJECT_ROOT / "output/json"
        / f"{slug}.manual_edit_style_learning.json"
    )
    write_json(output, profile)
    benchmark = profile["current_skill_benchmark"]
    cadence = profile["cadence"]
    integrity = profile["timeline_integrity"]
    spacing = profile["speech_boundary_handles"].get(
        "transcribed_spacing_seconds", {}
    )
    preview = PROJECT_ROOT / "output/preview" / f"{slug}_manual_style_learning.txt"
    preview.write_text("\n".join([
        "MANUAL EDIT STYLE LEARNING",
        "",
        f"Source project: {source_project.name}",
        f"Reference project: {reference_project.name}",
        f"Edit mode: {profile['edit_mode']}",
        f"Output/source ratio: {profile['reference_output_to_source_ratio']:.1%}",
        f"Kept segments: {cadence['kept_segment_count']}",
        "Median kept segment: "
        f"{cadence['kept_segment_duration_seconds']['median']:.3f}s",
        f"Inferred frame grid: {cadence['inferred_fps']} fps",
        f"Current skill recall: {benchmark['manual_reference_recall']:.1%}",
        f"Current skill precision: {benchmark['manual_reference_precision']:.1%}",
        f"Over-retained: {benchmark['over_retained_duration']:.3f}s",
        "Current primary overlaps: "
        f"{integrity['current_skill']['overlap_count']}",
        "Manual primary overlaps: "
        f"{integrity['manual_reference']['overlap_count']}",
        "Manual spacing p90/max: "
        f"{spacing.get('p90', 0):.3f}s / {spacing.get('maximum', 0):.3f}s",
        "",
        "Policy: choose one complete, fluent take per semantic story beat; ",
        "remove alternate/rehearsal takes before silence cleanup.",
    ]) + "\n", encoding="utf-8")
    console.print(
        f"[green]Manual style learned: mode={profile['edit_mode']}, "
        f"ratio={profile['reference_output_to_source_ratio']:.1%}, "
        f"precision={benchmark['manual_reference_precision']:.1%}[/green]"
    )
    return output


def run_apply_editorial_selection_plan(args: argparse.Namespace) -> Path:
    if args.plan is None:
        raise ValueError("--plan is required.")
    project = locate_project(str(args.project))
    live = read_live_project(project)
    plan_path = args.plan.resolve()
    if not plan_path.is_file():
        raise FileNotFoundError(f"Editorial selection plan not found: {plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    before_hashes = _project_file_hashes(project.path)
    result = apply_editorial_selection_plan(live, plan, dry_run=args.dry_run)
    after_hashes = _project_file_hashes(project.path)
    if args.dry_run and before_hashes != after_hashes:
        raise RuntimeError("Editorial selection dry-run modified project files.")
    slug = _project_slug(project.name)
    post_live = read_live_project(locate_project(project.name))
    post_analysis = analyze_timeline(post_live.primary)
    report = {
        **result,
        "project": project.name,
        "profile_id": plan.get("profile_id"),
        "keep_range_count": len(plan.get("keep_ranges") or []),
        "cut_range_count": len(plan.get("cut_ranges") or []),
        "expected_new_duration": plan.get("expected_new_duration"),
        "project_duration": post_analysis["duration"],
        "mirrored_drafts_consistent": all(
            draft == post_live.drafts[0] for draft in post_live.drafts[1:]
        ),
        "media_references_resolve": not post_analysis["offline_media"],
        "project_remains_discoverable": True,
        "dry_run_project_hashes_unchanged": (
            before_hashes == after_hashes if args.dry_run else None
        ),
    }
    output = PROJECT_ROOT / "output/json" / f"{slug}.editorial_selection_result.json"
    write_json(output, report)
    write_json(
        PROJECT_ROOT / "logs/direct_edit" / slug / "editorial_selection_validation.json",
        report,
    )
    preview = PROJECT_ROOT / "output/preview" / f"{slug}_editorial_selection.txt"
    preview.write_text("\n".join([
        "REFERENCE-GUIDED EDITORIAL SELECTION",
        "",
        f"Project: {project.name}",
        f"Profile: {plan.get('profile_id')}",
        f"Kept story-beat ranges: {len(plan.get('keep_ranges') or [])}",
        f"Removed ranges: {len(plan.get('cut_ranges') or [])}",
        f"Old duration: {plan.get('old_duration'):.3f}s",
        f"New duration: {post_analysis['duration']:.3f}s",
        f"Dry run: {'YES' if args.dry_run else 'NO'}",
        "Validation: PASS",
    ]) + "\n", encoding="utf-8")
    return output


def _intersecting_track_report(
    draft: dict[str, Any], start: float, end: float
) -> dict[str, Any]:
    categories = {
        "video": [], "audio": [], "text": [], "effect": [], "sticker": [],
        "overlay": [], "adjustment": [], "unknown": [],
    }
    for track_index, track in enumerate(draft.get("tracks", [])):
        track_type = str(track.get("type") or "unknown")
        category = track_type if track_type in categories else "unknown"
        for segment_index, segment in enumerate(track.get("segments", [])):
            target = segment.get("target_timerange") or {}
            target_start = float(target.get("start", 0)) / TIME_SCALE
            target_end = (
                float(target.get("start", 0)) + float(target.get("duration", 0))
            ) / TIME_SCALE
            if target_start < end and target_end > start:
                categories[category].append({
                    "track_index": track_index,
                    "track_type": track_type,
                    "segment_index": segment_index,
                    "segment_id": segment.get("id"),
                    "material_id": segment.get("material_id"),
                    "target_start": target_start,
                    "target_end": target_end,
                    "source_timerange": segment.get("source_timerange"),
                    "render_timerange": segment.get("render_timerange"),
                    "speed": segment.get("speed"),
                    "reverse": segment.get("reverse"),
                })
    return categories


def run_apply_approved_take_cuts(args: argparse.Namespace) -> Path:
    if args.approval is None:
        raise ValueError("--approval is required.")
    require_capcut_closed()
    project = locate_project(str(args.project))
    live = read_live_project(project)
    project_hashes_before = _project_file_hashes(project.path)
    approval_path = args.approval.resolve()
    if not approval_path.is_file():
        raise FileNotFoundError(f"Approval file not found: {approval_path}")
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    slug = _project_slug(project.name)
    take_plan_path = PROJECT_ROOT / "output/json" / f"{slug}.take_plan.json"
    if not take_plan_path.is_file():
        raise FileNotFoundError(f"Take plan not found: {take_plan_path}")
    take_plan = json.loads(take_plan_path.read_text(encoding="utf-8"))
    current_hash = essential_timeline_hash(live.primary)
    cut = approval["cuts"][0]
    start, end = float(cut["start"]), float(cut["end"])
    intersections = _intersecting_track_report(live.primary, start, end)
    old_duration = float(live.primary["duration"]) / TIME_SCALE
    preflight = {
        "valid": True,
        "dry_run": args.dry_run,
        "project_name": project.name,
        "project_path": str(project.path),
        "project_identity": project.identity,
        "draft_paths": [str(path) for path in live.draft_paths],
        "old_duration": old_duration,
        "expected_new_duration": old_duration - (end - start),
        "current_timeline_hash": current_hash,
        "approval_timeline_hash": approval.get("timeline_hash"),
        "approved_cut": cut,
        "intersecting_tracks": intersections,
    }
    log_dir = PROJECT_ROOT / "logs/direct_edit" / slug
    write_json(log_dir / "take_cut_preflight.json", preflight)
    result = apply_approved_cut_transaction(
        live, approval, take_plan, dry_run=args.dry_run
    )
    project_hashes_after = _project_file_hashes(project.path)
    if args.dry_run and project_hashes_before != project_hashes_after:
        raise RuntimeError("Dry-run modified CapCut project files.")
    write_json(log_dir / "take_cut_changes.json", result["changes"])
    write_json(log_dir / "take_cut_generated_ids.json", {
        "generated_segment_ids": result["changes"]["generated_segment_ids"]
    })
    post = {
        **result,
        "project_name_unchanged": project.name == approval["project"],
        "mirrored_draft_count": len(live.draft_paths),
        "approved_cut_only": len(approval["cuts"]) == 1,
        "unapproved_candidates_removed": False,
        "dry_run_project_hashes_unchanged": (
            project_hashes_before == project_hashes_after
            if args.dry_run else None
        ),
        "changed_project_files": (
            sorted(
                path for path in set(project_hashes_before) | set(project_hashes_after)
                if project_hashes_before.get(path) != project_hashes_after.get(path)
            )
            if not args.dry_run else []
        ),
        "kept_take_before": cut["keep_range"],
        "kept_take_after": {
            "start": round(float(cut["keep_range"]["start"]) - (end - start), 6),
            "end": round(float(cut["keep_range"]["end"]) - (end - start), 6),
        },
    }
    write_json(log_dir / "take_cut_post_write_validation.json", post)
    report_path = PROJECT_ROOT / "output/json" / f"{slug}.applied_take_cut_report.json"
    write_json(report_path, post)
    preview = [
        "APPROVED DUPLICATE TAKE CUT",
        "",
        f"Project: {project.name}",
        "",
        f"Removed: {start:09.3f} --> {end:09.3f}",
        f"Duration removed: {end - start:.3f} seconds",
        "",
        f"Kept take before ripple: {cut['keep_range']['start']:.3f} --> "
        f"{cut['keep_range']['end']:.3f}",
        f"Kept take after ripple: {post['kept_take_after']['start']:.3f} --> "
        f"{post['kept_take_after']['end']:.3f}",
        "",
        f"Old duration: {old_duration:.6f} seconds",
        f"Expected new duration: {old_duration - (end - start):.6f} seconds",
        "",
        f"Dry run: {'YES' if args.dry_run else 'NO'}",
        "Validation: PASS",
    ]
    preview_path = (
        PROJECT_ROOT / "output/preview" / f"{slug}_applied_take_cut.txt"
    )
    preview_path.write_text("\n".join(preview) + "\n", encoding="utf-8")
    return report_path


def run_auto_remove_duplicate_takes(args: argparse.Namespace) -> Path:
    project, live, analysis, slug = _inspect_direct_project(args)
    if not analysis["safe_for_direct_transcription"]:
        raise RuntimeError(
            "Timeline is unsafe for automatic duplicate cleanup: "
            + "; ".join(analysis["offline_media"] + analysis["unsupported_structures"])
        )
    current_hash = stable_hash({
        "duration": analysis["duration"],
        "audible_segments": analysis["audible_segments"],
    })
    log_dir = PROJECT_ROOT / "logs/direct_edit" / slug
    summary_path = log_dir / "stt_summary.json"
    lexical_path = PROJECT_ROOT / "output/json" / f"{slug}.lexical_words.json"
    transcript_source = "none"
    elevenlabs_called = False
    lexical: list[dict[str, Any]] = []
    if summary_path.is_file() and lexical_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("timeline_hash") == current_hash:
            lexical = json.loads(lexical_path.read_text(encoding="utf-8"))
            transcript_source = "timeline_hash_matched_cache"
    if not lexical and summary_path.is_file() and lexical_path.is_file():
        # A previously validated local cut can retime the cached lexical words
        # without retranscribing audio.
        applied_path = (
            PROJECT_ROOT / "output/json" / f"{slug}.applied_take_cut_report.json"
        )
        approval_path = (
            PROJECT_ROOT / "output/json" / f"{slug}.approved_take_cuts.json"
        )
        if applied_path.is_file() and approval_path.is_file():
            applied = json.loads(applied_path.read_text(encoding="utf-8"))
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            changes = applied.get("changes") or {}
            if (
                applied.get("project_written") is True
                and summary.get("timeline_hash") == approval.get("timeline_hash")
                and int(changes.get("new_duration", -1)) == int(live.primary["duration"])
                and len(approval.get("cuts", [])) == 1
            ):
                old_lexical = json.loads(lexical_path.read_text(encoding="utf-8"))
                cut = approval["cuts"][0]
                lexical = retime_lexical_after_known_cut(
                    old_lexical, float(cut["start"]), float(cut["end"])
                )
                write_json(lexical_path, lexical)
                summary["timeline_hash"] = current_hash
                summary["transcript_source"] = "locally_retimed_after_validated_cut"
                summary["lexical_token_count"] = len(lexical)
                write_json(summary_path, summary)
                transcript_source = "locally_retimed_timeline_cache"
    if not lexical:
        run_detect_duplicate_takes(args)
        elevenlabs_called = True
        lexical = json.loads(lexical_path.read_text(encoding="utf-8"))
        transcript_source = "elevenlabs_scribe_v2"
        # Detection writes its own timeline-hash-matched summary.
    preset_path = (
        PROJECT_ROOT / "presets/take_detection"
        / f"{args.take_detection_preset}.json"
    )
    preset = json.loads(preset_path.read_text(encoding="utf-8"))
    fillers = _read_config_lines(
        PROJECT_ROOT / "presets/take_detection/thai_fillers.txt"
    )
    markers = _read_config_lines(
        PROJECT_ROOT / "presets/take_detection/thai_restart_markers.txt"
    )
    utterances = build_utterances(lexical, analysis, fillers, markers, preset)
    candidates, groups = detect_duplicate_takes(utterances, preset)
    auto_plan = build_auto_cleanup_plan(
        project.name, current_hash, groups, utterances, lexical, preset,
        fillers, markers,
    )
    plan_path = (
        PROJECT_ROOT / "output/json" / f"{slug}.auto_duplicate_take_plan.json"
    )
    write_json(plan_path, auto_plan)
    hashes_before = _project_file_hashes(project.path)
    dry_result = apply_auto_cleanup_transaction(
        live, auto_plan, current_hash, dry_run=True
    )
    hashes_after_dry = _project_file_hashes(project.path)
    if hashes_before != hashes_after_dry:
        raise RuntimeError("Automatic cleanup internal dry-run modified project files.")
    preflight = {
        "valid": dry_result["valid"],
        "timeline_hash": current_hash,
        "transcript_source": transcript_source,
        "elevenlabs_called": elevenlabs_called,
        "detected_groups": len(groups),
        "safe_groups": len(auto_plan["applied_groups"]),
        "skipped_groups": len(auto_plan["skipped_groups"]),
        "cut_ranges": auto_plan["cut_ranges"],
        "dry_run_project_hashes_unchanged": True,
        "dry_run_validation": dry_result["validation"],
    }
    write_json(log_dir / "auto_duplicate_detection.json", {
        "utterance_count": len(utterances),
        "candidate_count": len(candidates),
        "groups": groups,
        "transcript_source": transcript_source,
        "elevenlabs_called": elevenlabs_called,
    })
    write_json(log_dir / "auto_duplicate_cut_preflight.json", preflight)
    if args.dry_run:
        output = (
            PROJECT_ROOT / "output/json"
            / f"{slug}.auto_duplicate_take_preflight.json"
        )
        write_json(output, {
            **dry_result,
            "preflight": preflight,
            "project": project.name,
        })
        return output
    result = apply_auto_cleanup_transaction(
        live, auto_plan, current_hash, dry_run=False
    )
    write_json(log_dir / "auto_duplicate_cut_changes.json", result["changes"])
    after_hashes = _project_file_hashes(project.path)
    rediscovered = locate_project(project.name)
    post = {
        **result,
        "project_name_unchanged": rediscovered.name == project.name,
        "project_remains_discoverable": rediscovered.path == project.path,
        "mirrored_drafts_consistent": (
            read_live_project(rediscovered).drafts[0]
            == read_live_project(rediscovered).drafts[1]
        ),
        "applied_group_count": len(auto_plan["applied_groups"]),
        "skipped_group_count": len(auto_plan["skipped_groups"]),
        "applied_groups": auto_plan["applied_groups"],
        "skipped_groups": auto_plan["skipped_groups"],
        "elevenlabs_called": elevenlabs_called,
        "transcript_source": transcript_source,
        "changed_project_files": sorted(
            path for path in set(hashes_before) | set(after_hashes)
            if hashes_before.get(path) != after_hashes.get(path)
        ),
    }
    output = (
        PROJECT_ROOT / "output/json" / f"{slug}.auto_duplicate_take_result.json"
    )
    write_json(output, post)
    write_json(log_dir / "auto_duplicate_cut_validation.json", post)
    preview_lines = [
        "AUTOMATIC DUPLICATE TAKE CLEANUP",
        "",
        f"Project: {project.name}",
        f"Detected groups: {len(groups)}",
        f"Applied groups: {len(auto_plan['applied_groups'])}",
        f"Skipped groups: {len(auto_plan['skipped_groups'])}",
        f"Applied cuts: {result['changes']['applied_cut_count']}",
        f"Total removed: {result['changes']['total_removed'] / TIME_SCALE:.3f}s",
        f"Old duration: {result['validation']['old_duration']:.6f}s",
        f"New duration: {result['validation']['new_duration']:.6f}s",
        f"ElevenLabs called: {'YES' if elevenlabs_called else 'NO'}",
        "Validation: PASS",
        "",
    ]
    for group in auto_plan["applied_groups"]:
        preview_lines.append(
            f"APPLIED {group['group_id']} {group['category']} "
            f"keep={group['kept_utterance_id']} "
            f"remove={','.join(group['removed_utterance_ids'])}"
        )
    for group in auto_plan["skipped_groups"]:
        preview_lines.append(
            f"SKIPPED {group['group_id']}: "
            f"{', '.join(group['skipped_reasons'])}"
        )
    (
        PROJECT_ROOT / "output/preview"
        / f"{slug}_auto_duplicate_take_cleanup.txt"
    ).write_text("\n".join(preview_lines) + "\n", encoding="utf-8")
    return output


def _build_stt_plan(args: argparse.Namespace, inject: bool = False) -> Path:
    input_path, duration, submitted, raw, words = _run_short_stt(args)
    basename = safe_basename(input_path)
    script: str | None = None
    if args.mode == "build-caption-plan-from-script":
        if args.script is None or not args.script.resolve().is_file():
            raise FileNotFoundError("--script must name an existing UTF-8 text file.")
        script = read_text_file(args.script.resolve())
    # Phase 7A proof is deliberately limited to the submitted 20-second sample.
    plan_duration = submitted
    plan, alignment = build_media_caption_plan(
        str(input_path), plan_duration, words, script=script
    )
    validation = validate_caption_plan(plan, max_words=16)
    build_log = {
        "input": str(input_path),
        "media_duration": duration,
        "submitted_sample_duration": submitted,
        "detected_language": raw.get("language_code") or raw.get("language"),
        "word_count": len(words),
        "caption_count": len(plan["captions"]),
        "script_mode": script is not None,
        "alignment": alignment,
    }
    write_json(PROJECT_ROOT / "logs/caption_plan_build.json", build_log)
    write_json(PROJECT_ROOT / "logs/caption_plan_validation.json", validation)
    output = PROJECT_ROOT / "output/json" / f"{basename}.caption_plan.json"
    if not validation["valid"]:
        failed = output.with_name(f"{basename}.caption_plan.failed.json")
        write_json(failed, plan)
        raise RuntimeError(
            "Caption plan validation failed: " + "; ".join(validation["errors"])
            + f". Failed plan: {failed}"
        )
    write_json(output, plan)
    preview = [
        f"{caption['id']} {caption['start']:.3f}-{caption['end']:.3f} {caption['text']}"
        for caption in plan["captions"]
    ]
    (PROJECT_ROOT / "output/preview" / f"{basename}_caption_plan.txt").write_text(
        "\n".join(preview) + "\n", encoding="utf-8"
    )
    if inject:
        if not args.sandbox_name:
            raise ValueError("--sandbox-name is required.")
        result = inject_caption_plan(output, args.sandbox_name)
        console.print(f"[green]Sandbox injection PASS:[/green] {result['sandbox_path']}")
    return output


def _load_script_for_project(
    explicit: Path | None, timeline: dict[str, Any]
) -> str | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    else:
        project_name = str(timeline.get("project_name") or "").strip()
        if project_name:
            candidates.append(PROJECT_ROOT / "input/scripts" / f"{project_name}.txt")
    for candidate in candidates:
        if candidate.is_file():
            return read_text_file(candidate)
    return None


def _print_plan_sample(title: str, entries: list[dict[str, Any]]) -> None:
    console.print(f"\n[bold]{title} (first 10)[/bold]")
    if not entries:
        console.print("(none)")
        return
    console.print_json(json.dumps(entries[:10], ensure_ascii=False))


def run_plan_mode(args: argparse.Namespace) -> Path:
    ensure_directories()
    selector = str(args.project)
    root = args.project_root
    if selector.casefold() != "latest":
        root = Path(selector)
    candidate = find_latest_draft(root)
    timeline, _ = read_project(candidate)
    duration = project_duration(timeline)
    mapping = build_mapping_log(timeline)
    audio_path, _audio_map = build_timeline_audio(timeline)
    config = load_config(args.config)
    terms = (
        [term.strip() for term in args.keyterms.split(",") if term.strip()]
        if args.keyterms is not None else None
    )
    _raw, words = transcribe(audio_path, "capcut_timeline", config, terms)
    script = _load_script_for_project(args.script, timeline)
    caption_config = config["caption"]
    caption_config = {
        **caption_config,
        "silence_boundary": config["cut"]["silence_threshold"],
    }
    caption_plan = build_caption_plan(timeline, words, duration, caption_config, script)
    cut_plan = build_cut_plan(timeline, words, duration, config["cut"])
    caption_validation = validate_caption_plan(
        caption_plan, timeline, int(caption_config["max_words_per_cue"])
    )
    cut_validation = validate_cut_plan(
        cut_plan, timeline, float(config["cut"]["minimum_cut_duration"]),
        float(config["cut"]["require_review_below_confidence"]),
    )
    warnings: list[str] = []
    missing_media = [item for item in mapping if not Path(str(item["media_path"])).is_file()]
    if missing_media:
        warnings.append(f"{len(missing_media)} timeline clips reference unavailable media.")
    if script:
        warnings.append("Paired script alignment was used; script text is final caption text.")
    edit_plan = build_edit_plan(timeline, caption_plan, cut_plan, warnings)
    edit_validation = validate_edit_plan(edit_plan, caption_validation, cut_validation)

    json_dir = PROJECT_ROOT / "output/json"
    preview_dir = PROJECT_ROOT / "output/preview"
    write_json(json_dir / "caption_plan.json", caption_plan)
    write_json(json_dir / "cut_plan.json", cut_plan)
    write_json(json_dir / "edit_plan.json", edit_plan)
    write_json(PROJECT_ROOT / "logs/caption_plan_validation.json", caption_validation)
    write_json(PROJECT_ROOT / "logs/cut_plan_validation.json", cut_validation)
    write_json(PROJECT_ROOT / "logs/edit_plan_validation.json", edit_validation)
    preview_dir.mkdir(parents=True, exist_ok=True)
    (preview_dir / "caption_plan.txt").write_text(
        caption_preview(caption_plan, caption_validation), encoding="utf-8"
    )
    (preview_dir / "cut_plan.txt").write_text(
        cut_preview(cut_plan, cut_validation), encoding="utf-8"
    )
    (preview_dir / "edit_plan_summary.txt").write_text(
        edit_summary(edit_plan, caption_validation, cut_validation, edit_validation),
        encoding="utf-8",
    )

    clip_count = sum(
        len(track.get("segments", [])) for track in timeline.get("tracks", [])
    )
    console.print(f"[bold]Detected project duration:[/bold] {duration:.3f}s")
    console.print(f"[bold]Timeline clips:[/bold] {clip_count}")
    console.print(f"[bold]Captions:[/bold] {len(caption_plan['captions'])}")
    console.print(f"[bold]Proposed silence cuts:[/bold] {len(cut_plan['cuts'])}")
    console.print(
        "[bold]Validation:[/bold] "
        f"captions={'PASS' if caption_validation['valid'] else 'FAIL'}, "
        f"cuts={'PASS' if cut_validation['valid'] else 'FAIL'}, "
        f"edit={'PASS' if edit_validation['valid'] else 'FAIL'}"
    )
    if args.mode == "dry-run":
        console.print("[green]Dry-run only: no CapCut project files were modified.[/green]")
        _print_plan_sample("Caption plan", caption_plan["captions"])
        _print_plan_sample("Cut plan", cut_plan["cuts"])
    if not all((
        caption_validation["valid"],
        cut_validation["valid"],
        edit_validation["valid"],
    )):
        raise RuntimeError("Plan validation failed. Inspect logs/*_plan_validation.json.")
    outputs = {
        "build-caption-plan": json_dir / "caption_plan.json",
        "build-cut-plan": json_dir / "cut_plan.json",
        "build-edit-plan": json_dir / "edit_plan.json",
        "dry-run": json_dir / "edit_plan.json",
    }
    return outputs[args.mode]


def run(args: argparse.Namespace) -> Path:
    ensure_directories()
    if args.mode == "list-capcut-projects":
        return run_list_capcut_projects()
    if args.mode == "learn-caption-style":
        return run_learn_caption_style(args)
    if args.mode == "validate-caption-style":
        return run_validate_caption_style(args)
    if args.mode == "normalize-thai-caption-plan":
        return run_normalize_thai_caption_plan(args)
    if args.mode == "learn-karaoke-style":
        return run_learn_karaoke_style(args)
    if args.mode == "build-karaoke-plan":
        return run_build_karaoke_plan(args)
    if args.mode == "apply-karaoke":
        return run_apply_karaoke(args)
    if args.mode == "validate-karaoke":
        return run_validate_karaoke(args)
    if args.mode == "repair-karaoke-duplicates":
        return run_repair_karaoke_duplicates(args)
    if args.mode == "detect-silence":
        return run_detect_silence(args)
    if args.mode == "auto-cut-silence":
        return run_auto_cut_silence(args)
    if args.mode == "validate-silence-cut":
        return run_validate_silence_cut(args)
    if args.mode == "analyze-target-pause":
        return run_analyze_target_pause(args)
    if args.mode == "apply-pattern-1":
        return run_apply_pattern1(args)
    if args.mode == "remove-pattern-1":
        return run_remove_pattern1(args)
    if args.mode == "apply-approved-take-cuts":
        return run_apply_approved_take_cuts(args)
    if args.mode == "auto-remove-duplicate-takes":
        return run_auto_remove_duplicate_takes(args)
    if args.mode == "inspect-project":
        return run_inspect_project(args)
    if args.mode == "transcribe-project":
        return run_transcribe_project(args)
    if args.mode == "edit-project":
        return run_edit_project(args)
    if args.mode == "validate-project-edit":
        return run_validate_project_edit(args)
    if args.mode == "learn-manual-edit-style":
        return run_learn_manual_edit_style(args)
    if args.mode == "apply-editorial-selection-plan":
        return run_apply_editorial_selection_plan(args)
    if args.mode == "detect-duplicate-takes":
        return run_detect_duplicate_takes(args)
    if args.mode == "elevenlabs-test":
        return run_elevenlabs_test(args)
    if args.mode in {"regroup-thai-caption-plan", "build-caption-plan-from-stt"}:
        cached = (
            PROJECT_ROOT / "output/json"
            / f"{safe_basename(args.input) if args.input else 'missing'}.elevenlabs_raw.json"
        )
        if args.mode == "regroup-thai-caption-plan" or cached.is_file():
            return run_local_thai_regrouping(args)
        return _build_stt_plan(args)
    if args.mode == "build-caption-plan-from-script":
        return _build_stt_plan(args)
    if args.mode == "inject-stt-caption-plan":
        return _build_stt_plan(args, inject=True)
    if args.mode == "capcut-read":
        return run_capcut_read(args.project_root)
    if args.mode == "collect-capcut-fixtures":
        return run_collect_capcut_fixtures(args.project_root)
    if args.mode == "validate-capcut-fixtures":
        return run_validate_capcut_fixtures()
    if args.mode == "learn-capcut-schema":
        return run_learn_capcut_schema()
    if args.mode == "inject-caption-test":
        return run_inject_caption_test()
    if args.mode == "validate-caption-test":
        return run_validate_caption_test()
    if args.mode == "rollback-caption-test":
        return run_rollback_caption_test()
    if args.mode == "inject-caption-plan":
        return run_inject_caption_plan(args)
    if args.mode == "validate-caption-plan":
        return run_validate_caption_plan(args)
    if args.mode == "rollback-caption-plan":
        return run_rollback_caption_plan(args)
    if args.mode in {"build-caption-plan", "build-cut-plan", "build-edit-plan", "dry-run"}:
        return run_plan_mode(args)
    if args.input is None:
        raise ValueError("--input is required in transcribe and script-align modes.")
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input media not found: {input_path}")
    if args.mode == "script-align" and not args.script:
        raise ValueError("--script is required in script-align mode.")
    if args.max_duration is not None and args.max_duration <= 0:
        raise ValueError("--max-duration must be positive.")

    basename = safe_basename(input_path)
    logger = setup_logging(basename)
    config = load_config(args.config)
    logger.info("Starting %s for %s", args.mode, input_path)
    media = probe_media(input_path, basename)
    media_duration = float(media["target_duration"])
    target_duration = min(media_duration, args.max_duration) if args.max_duration else media_duration
    audio_path = extract_audio(input_path, basename)
    terms = ([term.strip() for term in args.keyterms.split(",") if term.strip()]
             if args.keyterms is not None else None)
    raw, words = transcribe(audio_path, basename, config, terms)
    logger.info("Received %d timestamped words", len(words))

    subtitle = config["subtitle"]
    script_chunks: list[str] | None = None
    if args.mode == "script-align":
        script_path = args.script.resolve()
        if not script_path.is_file():
            raise FileNotFoundError(f"Script not found: {script_path}")
        script_chunks = chunk_script(read_text_file(script_path), int(subtitle["max_words_per_cue"]))
        write_json(PROJECT_ROOT / "logs" / f"{basename}.script_chunks.json", script_chunks)
        cues, alignment_debug = align_script(script_chunks, words, subtitle)
        write_json(PROJECT_ROOT / "logs" / f"{basename}.alignment_debug.json", alignment_debug)
        output_path = PROJECT_ROOT / "output/srt" / f"{basename}.script.th.srt"
    else:
        cues = build_auto_cues(words, subtitle)
        output_path = PROJECT_ROOT / "output/srt" / f"{basename}.auto.th.srt"

    write_json(PROJECT_ROOT / "logs" / f"{basename}.cues_before_clamp.json", cues)
    cues = clamp_cues(cues, target_duration, args.start_offset)
    write_json(PROJECT_ROOT / "logs" / f"{basename}.cues_after_clamp.json", cues)
    valid, errors = validate_cues(
        cues, target_duration, int(subtitle["max_words_per_cue"]), script_chunks
    )
    report = validation_report(valid, errors, len(cues), target_duration)
    (PROJECT_ROOT / "logs" / f"{basename}.validation_report.txt").write_text(report, encoding="utf-8")
    rendered = cues_to_srt(cues)
    if not valid:
        failed_path = PROJECT_ROOT / "output/srt" / f"{basename}.failed.srt"
        atomic_write_text(failed_path, rendered)
        raise RuntimeError(
            f"Validation failed; previous good SRT was preserved. Inspect {failed_path} "
            f"and logs/{basename}.validation_report.txt"
        )
    atomic_write_text(output_path, rendered)
    logger.info("Wrote validated SRT: %s", output_path)
    return output_path


def main() -> int:
    try:
        output = run(parse_args())
        console.print(f"[green]Success:[/green] {output}")
        return 0
    except Exception as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

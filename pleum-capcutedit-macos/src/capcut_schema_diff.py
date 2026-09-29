"""Learn CapCut's read-only caption/cut schema from validated fixture copies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from capcut_fixture_validator import validate_fixtures
from capcut_live_project_reader import active_draft_paths
from utils import PROJECT_ROOT, write_json


FIXTURES = {
    "01": "01_video_only",
    "02": "02_one_caption",
    "03": "03_styled_caption",
    "04": "04_multiple_captions",
    "05": "05_one_cut",
}


def _load_fixture(name: str) -> tuple[Path, dict[str, Any]]:
    folder = PROJECT_ROOT / "sample_capcut_projects" / FIXTURES[name]
    drafts, _storage_format = active_draft_paths(folder)
    drafts = sorted(drafts, key=lambda path: path.stat().st_mtime)
    if not drafts:
        raise FileNotFoundError(f"No active CapCut draft payload in {folder}")
    path = drafts[-1]
    return path, json.loads(path.read_text(encoding="utf-8-sig"))


def _tracks(data: dict[str, Any], track_type: str) -> list[dict[str, Any]]:
    return [track for track in data.get("tracks", []) if track.get("type") == track_type]


def _segments(data: dict[str, Any], track_type: str) -> list[dict[str, Any]]:
    return [
        segment
        for track in _tracks(data, track_type)
        for segment in track.get("segments", [])
    ]


def _caption_text(material: dict[str, Any]) -> str | None:
    content = material.get("content")
    if not isinstance(content, str):
        return None
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError:
        return None
    value = decoded.get("text") if isinstance(decoded, dict) else None
    return value if isinstance(value, str) else None


def _flatten(value: Any, prefix: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _flatten(value[key], f"{prefix}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


def _style_value_map(material: dict[str, Any]) -> dict[str, Any]:
    ignored = {
        "id", "name", "recognize_task_id", "base_content", "words",
        "current_words", "fonts", "content",
    }
    style = {key: value for key, value in material.items() if key not in ignored}
    content = material.get("content")
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
            style["content.styles"] = decoded.get("styles")
        except json.JSONDecodeError:
            pass
    return dict(_flatten(style, "$.materials.texts[*]"))


def _style_differences(
    plain: dict[str, Any], styled: dict[str, Any]
) -> list[dict[str, Any]]:
    left, right = _style_value_map(plain), _style_value_map(styled)
    differences = []
    for path in sorted(set(left) | set(right)):
        if left.get(path) != right.get(path):
            differences.append({
                "path": path,
                "schema_02_value": left.get(path),
                "schema_03_value": right.get(path),
            })
    return differences


def _range_seconds(value: dict[str, Any], scale: float) -> dict[str, float]:
    start = float(value.get("start") or 0)
    duration = float(value.get("duration") or 0)
    return {
        "start": start / scale,
        "duration": duration / scale,
        "end": (start + duration) / scale,
    }


def _comparison_text(
    left_name: str, left: dict[str, Any], right_name: str, right: dict[str, Any]
) -> str:
    lines = [f"READ-ONLY SCHEMA COMPARISON: {left_name} vs {right_name}", ""]
    for label, data in ((left_name, left), (right_name, right)):
        video = _segments(data, "video")
        text = _segments(data, "text")
        materials = data.get("materials", {}).get("texts", [])
        lines.extend([
            label,
            f"  tracks: {[(track.get('type'), len(track.get('segments', []))) for track in data.get('tracks', [])]}",
            f"  video segments: {len(video)}",
            f"  text segments: {len(text)}",
            f"  text materials: {len(materials)}",
            f"  caption texts: {[ _caption_text(item) for item in materials ]}",
            "",
        ])
    return "\n".join(lines) + "\n"


def learn_capcut_schema() -> tuple[dict[str, Any], Path]:
    fixture_validation = validate_fixtures()
    if not fixture_validation.get("valid"):
        raise RuntimeError("Fixture validation must pass before schema learning.")
    loaded = {name: _load_fixture(name) for name in FIXTURES}
    data = {name: item[1] for name, item in loaded.items()}
    output = PROJECT_ROOT / "output" / "json"
    preview = PROJECT_ROOT / "output" / "preview"
    output.mkdir(parents=True, exist_ok=True)
    preview.mkdir(parents=True, exist_ok=True)

    caption_materials = {
        name: value.get("materials", {}).get("texts", []) for name, value in data.items()
    }
    caption_segments = {name: _segments(value, "text") for name, value in data.items()}
    expected_counts = {"01": 0, "02": 1, "03": 1, "04": 3, "05": 0}
    validation_checks: list[dict[str, Any]] = []
    reference_edges: list[dict[str, Any]] = []
    for name in FIXTURES:
        materials = caption_materials[name]
        segments = caption_segments[name]
        material_by_id = {item.get("id"): item for item in materials}
        refs_valid = all(segment.get("material_id") in material_by_id for segment in segments)
        check = {
            "fixture": FIXTURES[name],
            "materials_texts_path_exists": isinstance(
                data[name].get("materials", {}).get("texts"), list
            ),
            "tracks_path_exists": isinstance(data[name].get("tracks"), list),
            "caption_count_matches_fixture": (
                len(materials) == len(segments) == expected_counts[name]
            ),
            "segment_material_references_valid": refs_valid,
            "caption_content_json_decodes": all(
                _caption_text(material) is not None for material in materials
            ),
        }
        check["valid"] = all(value for key, value in check.items() if key != "fixture")
        validation_checks.append(check)
        for index, segment in enumerate(segments):
            reference_edges.append({
                "fixture": FIXTURES[name],
                "from": f"$.tracks[?(@.type=='text')].segments[{index}].material_id",
                "from_id": segment.get("material_id"),
                "relationship": "equals",
                "to": "$.materials.texts[?(@.id == segment.material_id)].id",
                "resolved": segment.get("material_id") in material_by_id,
                "segment_id": segment.get("id"),
                "track_id": next(
                    (track.get("id") for track in _tracks(data[name], "text")
                     if segment in track.get("segments", [])),
                    None,
                ),
            })

    scales = []
    for name, value in data.items():
        metric = next(
            item for item in fixture_validation["fixtures"]
            if item["fixture_name"] == FIXTURES[name]
        )
        duration_seconds = float(metric["duration_seconds"])
        if duration_seconds > 0:
            scales.append(round(float(value["duration"]) / duration_seconds))
    time_scale = 1_000_000 if scales and all(scale == 1_000_000 for scale in scales) else None

    style_diffs = _style_differences(caption_materials["02"][0], caption_materials["03"][0])
    style_profile = {
        "version": 1,
        "comparison": "02_one_caption vs 03_styled_caption",
        "style_container_path": "$.materials.texts[*]",
        "rich_style_path": "$.materials.texts[*].content (JSON string) -> $.styles[*]",
        "differences": style_diffs,
        "validated_style_difference": bool(style_diffs),
    }

    cut_video = _segments(data["05"], "video")
    base_video = _segments(data["01"], "video")
    cut_ranges = []
    for segment in cut_video:
        cut_ranges.append({
            "segment_id": segment.get("id"),
            "material_id": segment.get("material_id"),
            "source": _range_seconds(segment["source_timerange"], time_scale or 1),
            "timeline": _range_seconds(segment["target_timerange"], time_scale or 1),
        })
    timeline_gaps = [
        max(0.0, right["timeline"]["start"] - left["timeline"]["end"])
        for left, right in zip(cut_ranges, cut_ranges[1:])
    ]
    source_gaps = [
        max(0.0, right["source"]["start"] - left["source"]["end"])
        for left, right in zip(cut_ranges, cut_ranges[1:])
    ]
    cut_profile = {
        "version": 1,
        "video_track_path": "$.tracks[?(@.type=='video')]",
        "video_segment_path": "$.tracks[?(@.type=='video')].segments[*]",
        "source_range_path": "$.tracks[?(@.type=='video')].segments[*].source_timerange",
        "target_range_path": "$.tracks[?(@.type=='video')].segments[*].target_timerange",
        "schema_01_video_segment_count": len(base_video),
        "schema_05_video_segment_count": len(cut_video),
        "schema_05_ranges_seconds": cut_ranges,
        "source_gaps_seconds": source_gaps,
        "timeline_gaps_seconds": timeline_gaps,
        "middle_source_removed": any(gap > 0 for gap in source_gaps),
        "timeline_is_contiguous": all(gap <= 0.000001 for gap in timeline_gaps),
        "structure_differs_from_schema_01": len(base_video) != len(cut_video),
    }

    caption_profile = {
        "version": 1,
        "caption_track_path": "$.tracks[?(@.type=='text')]",
        "caption_segment_path": "$.tracks[?(@.type=='text')].segments[*]",
        "caption_material_path": "$.materials.texts[*]",
        "caption_text_path": "$.materials.texts[*].content (JSON string) -> $.text",
        "caption_start_path": (
            "$.tracks[?(@.type=='text')].segments[*].target_timerange.start"
        ),
        "caption_duration_path": (
            "$.tracks[?(@.type=='text')].segments[*].target_timerange.duration"
        ),
        "segment_id_path": "$.tracks[?(@.type=='text')].segments[*].id",
        "segment_material_reference_path": (
            "$.tracks[?(@.type=='text')].segments[*].material_id"
        ),
        "material_id_path": "$.materials.texts[*].id",
        "reference_rule": "caption_segment.material_id == text_material.id",
        "fixture_validation": validation_checks,
    }
    reference_graph = {
        "version": 1,
        "nodes": [
            {"kind": "track", "id_path": "$.tracks[*].id"},
            {"kind": "segment", "id_path": "$.tracks[*].segments[*].id"},
            {"kind": "text_material", "id_path": "$.materials.texts[*].id"},
            {"kind": "video_material", "id_path": "$.materials.videos[*].id"},
        ],
        "edges": reference_edges,
    }
    time_report = {
        "version": 1,
        "capcut_time_unit": "microseconds" if time_scale == 1_000_000 else "unresolved",
        "units_per_second": time_scale,
        "seconds_formula": "capcut_value / 1_000_000",
        "capcut_formula": "seconds * 1_000_000",
        "observed_scales_by_fixture": scales,
        "caption_mapping": {
            "start_seconds": "segment.target_timerange.start / 1_000_000",
            "duration_seconds": "segment.target_timerange.duration / 1_000_000",
            "end_seconds": (
                "(segment.target_timerange.start + "
                "segment.target_timerange.duration) / 1_000_000"
            ),
        },
    }
    unresolved = [
        {
            "path": "$.tracks[*].segments[*].render_timerange",
            "reason": "fixtures do not isolate render-range semantics",
        },
        {
            "path": "$.tracks[*].segments[*].extra_material_refs[*]",
            "reason": "fixtures do not isolate every auxiliary material relationship",
        },
        {
            "path": "$.materials.texts[*].content.styles[*].range",
            "reason": "appears to be character range but Unicode indexing semantics are unproven",
        },
        {
            "path": "$.tracks[*].flag / $.tracks[*].attribute",
            "reason": "track flag bit meanings are not isolated by these fixtures",
        },
    ]
    all_checks = [check["valid"] for check in validation_checks]
    all_edges = [edge["resolved"] for edge in reference_edges]
    scored = all_checks + all_edges + [
        time_scale == 1_000_000,
        bool(style_diffs),
        cut_profile["middle_source_removed"],
        cut_profile["timeline_is_contiguous"],
        cut_profile["structure_differs_from_schema_01"],
    ]
    # Unresolved semantics reduce overall confidence even when every proven path passes.
    confidence = round(
        sum(bool(item) for item in scored) / (len(scored) + len(unresolved)),
        4,
    )
    summary = {
        "version": 1,
        "read_only": True,
        "fixtures": {name: str(path) for name, (path, _) in loaded.items()},
        "caption_schema_profile": "capcut_caption_schema_profile.json",
        "caption_style_schema_profile": "capcut_caption_style_schema_profile.json",
        "cut_schema_profile": "capcut_cut_schema_profile.json",
        "reference_graph": "capcut_reference_graph.json",
        "time_conversion_report": "capcut_time_conversion_report.json",
        "unresolved_fields": unresolved,
        "schema_confidence": confidence,
        "validation_passed": all(scored),
    }
    artifacts = {
        "capcut_caption_schema_profile.json": caption_profile,
        "capcut_caption_style_schema_profile.json": style_profile,
        "capcut_cut_schema_profile.json": cut_profile,
        "capcut_reference_graph.json": reference_graph,
        "capcut_time_conversion_report.json": time_report,
        "capcut_schema_learning_summary.json": summary,
    }
    for filename, value in artifacts.items():
        write_json(output / filename, value)
    comparisons = (("01", "02"), ("02", "03"), ("01", "04"), ("01", "05"))
    for left, right in comparisons:
        name = f"capcut_diff_{left}_vs_{right}.txt"
        (preview / name).write_text(
            _comparison_text(FIXTURES[left], data[left], FIXTURES[right], data[right]),
            encoding="utf-8",
        )
    write_json(PROJECT_ROOT / "logs" / "capcut_schema_learning_validation.json", {
        "valid": all(scored),
        "confidence": confidence,
        "fixture_path_checks": validation_checks,
        "reference_checks": reference_edges,
        "unresolved_fields": unresolved,
    })
    return {
        "summary": summary,
        "caption": caption_profile,
        "style": style_profile,
        "cut": cut_profile,
        "references": reference_graph,
        "time": time_report,
    }, output / "capcut_schema_learning_summary.json"

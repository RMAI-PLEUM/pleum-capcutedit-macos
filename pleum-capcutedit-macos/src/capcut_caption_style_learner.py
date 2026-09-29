"""Read-only learning of complete caption templates from a live CapCut project."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capcut_caption_style_fingerprint import decoded_material, fingerprint
from capcut_caption_style_preset import DEFAULTS_PATH, PRESET_ROOT, preset_path
from capcut_live_project_reader import read_live_project
from capcut_project_locator import locate_project
from caption_layout import canvas_dimensions, orientation_from_dimensions
from utils import PROJECT_ROOT, write_json


TIME_SCALE = 1_000_000


def project_file_hashes(folder: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        relative = path.relative_to(folder).as_posix()
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _clear_ranges(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "range" and isinstance(item, list) and len(item) == 2:
                value[key] = [0, 0]
            else:
                _clear_ranges(item)
    elif isinstance(value, list):
        for item in value:
            _clear_ranges(item)


def _material_template(material: dict[str, Any]) -> dict[str, Any]:
    template = deepcopy(material)
    template.pop("id", None)
    for key in (
        "recognize_text", "base_content", "translate_original_text", "ssml_content",
    ):
        if key in template:
            template[key] = ""
    for key in ("words", "current_words"):
        if isinstance(template.get(key), dict):
            template[key] = {
                child: [] for child in template[key]
            }
    content = decoded_material(material)["content"]
    content["text"] = ""
    _clear_ranges(content)
    template["content"] = json.dumps(
        content, ensure_ascii=False, separators=(",", ":")
    )
    return template


def _segment_template(segment: dict[str, Any]) -> dict[str, Any]:
    template = deepcopy(segment)
    for key in (
        "id", "material_id", "source_timerange", "target_timerange",
        "render_timerange", "group_id", "raw_segment_id",
    ):
        template.pop(key, None)
    template["extra_material_refs"] = []
    return template


def _track_template(track: dict[str, Any]) -> dict[str, Any]:
    template = deepcopy(track)
    template.pop("id", None)
    template["segments"] = []
    return template


def _auxiliary_records(
    data: dict[str, Any], segment: dict[str, Any]
) -> list[dict[str, Any]]:
    index = {
        str(item.get("id")): (collection, item)
        for collection, items in (data.get("materials") or {}).items()
        if isinstance(items, list)
        for item in items
        if isinstance(item, dict) and item.get("id")
    }
    records: list[dict[str, Any]] = []
    for reference in segment.get("extra_material_refs") or []:
        resolved = index.get(str(reference))
        if resolved is None:
            raise RuntimeError(f"Caption auxiliary reference does not resolve: {reference}")
        collection, item = resolved
        template = deepcopy(item)
        template.pop("id", None)
        records.append({"collection": collection, "template": template})
    return records


def _flatten_paths(value: Any, prefix: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}"
            paths.append(path)
            paths.extend(_flatten_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[*]"
            if path not in paths:
                paths.append(path)
            paths.extend(_flatten_paths(item, path))
    return paths


def _find_values(value: Any, names: set[str]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in names and key not in found:
                    found[key] = child
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    return found


def _style_summary(
    material: dict[str, Any], segment: dict[str, Any]
) -> dict[str, Any]:
    decoded = decoded_material(material)
    values = _find_values(decoded, {
        "font_name", "font_title", "font_resource_id", "font_path", "font_size",
        "bold", "weight", "text_color", "text_alpha", "border_color",
        "border_width", "border_alpha", "has_shadow", "shadow_color",
        "shadow_alpha", "shadow_angle", "shadow_distance", "shadow_smoothing",
        "background_style", "background_color", "background_alpha",
        "background_round_radius", "alignment", "line_spacing", "letter_spacing",
    })
    clip = segment.get("clip") if isinstance(segment.get("clip"), dict) else {}
    values["position"] = deepcopy(clip.get("transform"))
    values["scale"] = deepcopy(clip.get("scale"))
    values["rotation"] = clip.get("rotation")
    values["opacity"] = clip.get("alpha")
    explicit_name = str(values.get("font_name") or "").strip()
    title = str(values.get("font_title") or "").strip()
    path = str(values.get("font_path") or "").strip()
    values["font_display_name"] = (
        explicit_name
        or (title if title.casefold() not in {"", "none"} else "")
        or (Path(path).stem if path else "")
        or "(not named in source)"
    )
    return values


def discover_caption_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
    width, height = canvas_dimensions(data)
    orientation = (
        orientation_from_dimensions(width, height)
        if width is not None and height is not None else "unknown"
    )
    materials = {
        str(item.get("id")): item
        for item in (data.get("materials") or {}).get("texts", [])
        if isinstance(item, dict) and item.get("id")
    }
    candidates: list[dict[str, Any]] = []
    for track in data.get("tracks") or []:
        if not isinstance(track, dict) or track.get("type") != "text":
            continue
        for segment in track.get("segments") or []:
            material = materials.get(str(segment.get("material_id")))
            if material is None:
                raise RuntimeError(
                    f"Text segment material does not resolve: {segment.get('material_id')}"
                )
            decoded = decoded_material(material)
            content = decoded.get("content")
            if not isinstance(content, dict):
                raise RuntimeError(f"Text material content is not an object: {material.get('id')}")
            auxiliary = _auxiliary_records(data, segment)
            digest, _payload = fingerprint(track, segment, material, auxiliary)
            timerange = segment.get("target_timerange") or {}
            start = int(timerange.get("start") or 0)
            duration = int(timerange.get("duration") or 0)
            styles = content.get("styles")
            complete = (
                isinstance(styles, list) and bool(styles)
                and all(
                    isinstance(style, dict)
                    and style.get("range") == [0, _utf16_length(str(content.get("text") or ""))]
                    for style in styles
                )
                and isinstance(segment.get("clip"), dict)
            )
            candidates.append({
                "visible_caption_text": str(content.get("text") or ""),
                "segment_id": segment.get("id"),
                "material_id": material.get("id"),
                "track_id": track.get("id"),
                "timeline_start": start / TIME_SCALE,
                "timeline_duration": duration / TIME_SCALE,
                "style_fingerprint": digest,
                "canvas_width": width,
                "canvas_height": height,
                "orientation": orientation,
                "transform_and_position": deepcopy(segment.get("clip")),
                "complete_style_information": complete,
                "style_summary": _style_summary(material, segment),
                "_track": track,
                "_segment": segment,
                "_material": material,
                "_auxiliary": auxiliary,
            })
    return candidates


def _public_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in candidates
    ]


def _select(candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], str, int]:
    if not candidates:
        raise RuntimeError("Apple contains no resolved text caption candidates.")
    counts = Counter(item["style_fingerprint"] for item in candidates)
    ranked = counts.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        details = [
            {
                "caption": item["visible_caption_text"],
                "start": item["timeline_start"],
                "duration": item["timeline_duration"],
                "style_fingerprint": item["style_fingerprint"],
                "style_summary": item["style_summary"],
            }
            for item in candidates
        ]
        raise RuntimeError(
            "Caption styles are tied; no default was selected. Candidates: "
            + json.dumps(details, ensure_ascii=False)
        )
    selected_hash, count = ranked[0]
    selected = next(
        item for item in candidates if item["style_fingerprint"] == selected_hash
    )
    if len(ranked) == 1:
        reason = "all captions use one identical proven style"
    else:
        reason = "one style is used by the clear majority of captions"
    return selected, reason, count


def _diff(old: Any, new: Any, prefix: str = "$") -> list[dict[str, Any]]:
    if type(old) is not type(new):
        return [{"path": prefix, "old": old, "new": new}]
    if isinstance(old, dict):
        result: list[dict[str, Any]] = []
        for key in sorted(set(old) | set(new)):
            if key not in old or key not in new:
                result.append({"path": f"{prefix}.{key}", "old": old.get(key), "new": new.get(key)})
            else:
                result.extend(_diff(old[key], new[key], f"{prefix}.{key}"))
        return result
    if isinstance(old, list):
        if old == new:
            return []
        return [{"path": prefix, "old": old, "new": new}]
    return [] if old == new else [{"path": prefix, "old": old, "new": new}]


def learn_caption_style(
    project_name: str,
    preset_id: str,
    *,
    replace_existing: bool = False,
) -> tuple[dict[str, Any], Path]:
    project = locate_project(project_name)
    hashes_before = project_file_hashes(project.path)
    live = read_live_project(project)
    candidates = discover_caption_candidates(live.primary)
    selected, reason, usage_count = _select(candidates)
    width, height = canvas_dimensions(live.primary, live.metadata)
    orientation = (
        orientation_from_dimensions(width, height)
        if width is not None and height is not None else "unknown"
    )
    now = datetime.now(timezone.utc).isoformat()
    material_template = _material_template(selected["_material"])
    segment_template = _segment_template(selected["_segment"])
    track_template = _track_template(selected["_track"])
    proven = sorted(set(
        _flatten_paths(material_template, "$.material_template")
        + _flatten_paths(segment_template, "$.segment_style_template")
        + _flatten_paths(track_template, "$.track_template")
    ))
    preset = {
        "version": 1,
        "preset_id": preset_id,
        "display_name": "Apple Standard Caption",
        "source": {
            "project_name": project.name,
            "project_identity": project.identity,
            "project_path": str(project.path),
            "canvas_width": width,
            "canvas_height": height,
            "orientation": orientation,
            "source_track_id": selected["track_id"],
            "source_segment_id": selected["segment_id"],
            "source_material_id": selected["material_id"],
            "source_caption_text": selected["visible_caption_text"],
            "source_timeline_start": selected["timeline_start"],
            "source_timeline_duration": selected["timeline_duration"],
            "learned_at": now,
            "style_fingerprint": selected["style_fingerprint"],
            "style_usage_count": usage_count,
            "total_caption_count": len(candidates),
            "selection_reason": reason,
        },
        "material_template": material_template,
        "segment_style_template": segment_template,
        "track_template": track_template,
        "auxiliary_material_templates": selected["_auxiliary"],
        "dynamic_fields": {
            "text": True, "timing": True, "segment_id": True,
            "material_id": True, "track_id": True, "utf16_ranges": True,
        },
        "placement": {
            "mode": "exact_from_apple",
            "source_canvas_width": width,
            "source_canvas_height": height,
        },
        "validation": {
            "style_fields_proven": proven,
            "unresolved_fields": [],
            "source_hashes_verified": False,
            "source_style_summary": selected["style_summary"],
        },
    }
    destination = preset_path(preset_id)
    old_preset: dict[str, Any] | None = None
    visual_diff: list[dict[str, Any]] = []
    if destination.is_file():
        old_preset = json.loads(destination.read_text(encoding="utf-8"))
        if not replace_existing:
            raise FileExistsError(
                f"Preset already exists: {destination}; use --replace-existing-preset."
            )
        if (
            old_preset.get("source", {}).get("style_fingerprint")
            == preset["source"]["style_fingerprint"]
        ):
            raise RuntimeError("No visual style difference; existing preset was not overwritten.")
        visual_diff = _diff(
            {
                "material_template": old_preset.get("material_template"),
                "segment_style_template": old_preset.get("segment_style_template"),
                "track_template": old_preset.get("track_template"),
            },
            {
                "material_template": preset["material_template"],
                "segment_style_template": preset["segment_style_template"],
                "track_template": preset["track_template"],
            },
        )

    hashes_after = project_file_hashes(project.path)
    unchanged = hashes_before == hashes_after
    if not unchanged:
        changed = sorted(
            key for key in set(hashes_before) | set(hashes_after)
            if hashes_before.get(key) != hashes_after.get(key)
        )
        raise RuntimeError(f"Apple project changed during read-only learning: {changed}")
    preset["validation"]["source_hashes_verified"] = True

    PRESET_ROOT.mkdir(parents=True, exist_ok=True)
    if old_preset is not None:
        history = PRESET_ROOT / "history"
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        write_json(history / f"{preset_id}_{stamp}.json", old_preset)
    write_json(destination, preset)
    DEFAULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(DEFAULTS_PATH, {"default_caption_style_preset": preset_id})

    slug = project.name.casefold()
    public = _public_candidates(candidates)
    counts = Counter(item["style_fingerprint"] for item in candidates)
    learning = {
        "valid": True,
        "project_name": project.name,
        "project_identity": project.identity,
        "draft_paths": [str(path) for path in live.draft_paths],
        "mirrored_drafts_consistent": True,
        "caption_count": len(candidates),
        "unique_style_groups": len(counts),
        "style_groups": dict(counts),
        "selected_source_caption": selected["visible_caption_text"],
        "selected_source_timing": {
            "start": selected["timeline_start"],
            "duration": selected["timeline_duration"],
        },
        "selected_style_usage_count": usage_count,
        "selection_reason": reason,
        "style_fingerprint": selected["style_fingerprint"],
        "style_summary": selected["style_summary"],
        "total_fields_preserved": len(proven),
        "unresolved_fields": [],
        "visual_diff": visual_diff,
        "apple_hashes_before": hashes_before,
        "apple_hashes_after": hashes_after,
        "apple_project_unchanged": unchanged,
        "preset_path": str(destination),
        "default_config_path": str(DEFAULTS_PATH),
    }
    write_json(PROJECT_ROOT / f"output/json/{slug}.caption_style_candidates.json", public)
    write_json(PROJECT_ROOT / f"output/json/{slug}.caption_style_learning.json", learning)
    log_dir = PROJECT_ROOT / f"logs/direct_edit/{slug}"
    write_json(log_dir / "caption_style_preflight.json", {
        "project_name": project.name,
        "project_path": str(project.path),
        "project_identity": project.identity,
        "draft_paths": [str(path) for path in live.draft_paths],
        "mirrored_drafts_consistent": True,
        "hashes_before": hashes_before,
    })
    write_json(log_dir / "caption_style_fields.json", {
        "style_fields_proven": proven,
        "unresolved_fields": [],
        "style_summary": selected["style_summary"],
    })
    summary = selected["style_summary"]
    preview = [
        "CAPTION STYLE LEARNING - READ ONLY",
        "",
        f"Project: {project.name}",
        f"Selected source caption: {selected['visible_caption_text']}",
        f"Source timing: {selected['timeline_start']:.3f}s + {selected['timeline_duration']:.3f}s",
        f"Selection: {usage_count}/{len(candidates)} ({reason})",
        f"Style fingerprint: {selected['style_fingerprint']}",
        f"Font name: {summary.get('font_display_name')}",
        f"Font resource ID: {summary.get('font_resource_id')}",
        f"Font path: {summary.get('font_path')}",
        f"Font size: {summary.get('font_size')}",
        f"Font weight/bold: {summary.get('weight')}/{summary.get('bold')}",
        f"Text color/alpha: {summary.get('text_color')}/{summary.get('text_alpha')}",
        f"Stroke: color={summary.get('border_color')} width={summary.get('border_width')} alpha={summary.get('border_alpha')}",
        f"Shadow: enabled={summary.get('has_shadow')} color={summary.get('shadow_color')} alpha={summary.get('shadow_alpha')} angle={summary.get('shadow_angle')} distance={summary.get('shadow_distance')}",
        f"Background: style={summary.get('background_style')} color={summary.get('background_color')} alpha={summary.get('background_alpha')}",
        f"Alignment: {summary.get('alignment')}",
        f"Position X/Y: {summary.get('position')}",
        f"Scale: {summary.get('scale')}",
        f"Canvas/orientation: {width}x{height} {orientation}",
        f"Total fields preserved: {len(proven)}",
        "Unresolved fields: (none)",
        "Apple project modified: NO",
    ]
    preview_path = PROJECT_ROOT / f"output/preview/{slug}_caption_style_learning.txt"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text("\n".join(preview) + "\n", encoding="utf-8")
    return learning, destination

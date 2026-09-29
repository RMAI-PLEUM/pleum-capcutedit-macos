"""Template-learned, transaction-safe Pattern 1 injection for CapCut drafts."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_caption_registry import load_registry, project_identity_slug, registry_path, stable_hash
from capcut_live_project_reader import LiveProject, read_live_project
from capcut_process_guard import require_capcut_closed
from capcut_write_guard import require_live_project_write_ready
from capcut_project_locator import locate_project
from capcut_project_validator import all_object_ids
from utils import PROJECT_ROOT, atomic_write_text, write_json


US = 1_000_000


def _fresh_id(forbidden: set[str]) -> str:
    while True:
        value = str(uuid.uuid4()).upper()
        if value not in forbidden:
            forbidden.add(value)
            return value


def _materials(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        name: values for name, values in (data.get("materials") or {}).items()
        if isinstance(values, list)
    }


def _material_index(data: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    return {
        str(item["id"]): (collection, item)
        for collection, values in _materials(data).items()
        for item in values if isinstance(item, dict) and item.get("id")
    }


def _decode_text(material: dict[str, Any]) -> str:
    try:
        value = str(json.loads(material.get("content") or "{}").get("text") or "")
    except (json.JSONDecodeError, TypeError):
        value = str(material.get("recognize_text") or "")
    try:
        repaired = value.encode("latin-1").decode("utf-8")
        if repaired:
            value = repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return value


def _update_ranges(value: Any, length: int) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "range" and isinstance(item, list) and len(item) == 2:
                value[key] = [0, length]
            else:
                _update_ranges(item, length)
    elif isinstance(value, list):
        for item in value:
            _update_ranges(item, length)


def _set_text(material: dict[str, Any], text: str) -> None:
    content = json.loads(material["content"])
    content["text"] = text
    _update_ranges(content.get("styles", []), len(text.encode("utf-16-le")) // 2)
    material["content"] = json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _normal_path(value: str) -> str:
    return value.replace("\\", "/").casefold()


def _local_path(value: str) -> Path:
    return Path(value.replace("/", "\\"))


def _video_track(data: dict[str, Any]) -> dict[str, Any]:
    tracks = [item for item in data.get("tracks", []) if item.get("type") == "video"]
    if len(tracks) != 1:
        raise RuntimeError(f"Pattern 1 requires exactly one video track; found {len(tracks)}")
    return tracks[0]


def _sorted_segments(track: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(track.get("segments") or [], key=lambda item: item["target_timerange"]["start"])


def _canvas(data: dict[str, Any]) -> tuple[int, int]:
    config = data.get("canvas_config") or {}
    return int(config.get("width") or 0), int(config.get("height") or 0)


def _load_plan(plan_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("version") != 1 or plan.get("profile") != "Pattern 1":
        raise ValueError("Pattern 1 plan version/profile is invalid")
    return plan


def _reference_templates(reference: LiveProject) -> dict[str, Any]:
    data = reference.primary
    index = _material_index(data)
    audio_tracks = [track for track in data.get("tracks", []) if track.get("type") == "audio"]
    if len(audio_tracks) != 2:
        raise RuntimeError("Reference must contain exactly two Pattern 1 audio tracks")
    audio: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for track in audio_tracks:
        for segment in track.get("segments") or []:
            collection, material = index.get(str(segment.get("material_id")), (None, None))
            if collection != "audios" or not material:
                raise RuntimeError("Reference audio segment has an unresolved material")
            audio.setdefault(str(material.get("name") or ""), (segment, material))
    transitions = {
        str(item.get("name") or ""): item
        for item in data.get("materials", {}).get("transitions", [])
    }
    callout_tracks = [
        track for track in data.get("tracks", [])
        if track.get("type") == "text" and len(track.get("segments") or []) == 1
    ]
    if len(callout_tracks) != 1:
        raise RuntimeError("Reference must contain exactly one single-segment CTA track")
    callout_track = callout_tracks[0]
    callout_segment = callout_track["segments"][0]
    callout_material = index.get(str(callout_segment.get("material_id")))
    if not callout_material or callout_material[0] != "texts":
        raise RuntimeError("Reference CTA text material is unresolved")
    zoom_template = None
    for segment in _sorted_segments(_video_track(data)):
        for container in segment.get("common_keyframes") or []:
            frames = container.get("keyframe_list") or []
            if container.get("property_type") == "KFTypeScaleX" and len(frames) >= 2:
                zoom_template = container
                break
        if zoom_template:
            break
    if not zoom_template:
        raise RuntimeError("Reference contains no proven Pattern 1 scale keyframe template")
    return {
        "index": index,
        "audio_tracks": audio_tracks,
        "audio": audio,
        "transitions": transitions,
        "callout_track": callout_track,
        "callout_segment": callout_segment,
        "callout_material": callout_material[1],
        "zoom": zoom_template,
    }


def _metadata_group(metadata: dict[str, Any], material_type: int) -> dict[str, Any]:
    matches = [item for item in metadata.get("draft_materials") or [] if item.get("type") == material_type]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one draft_materials group type {material_type}")
    return matches[0]


def _clone_metadata_assets(
    reference_meta: dict[str, Any], target_meta: dict[str, Any], required_paths: set[str],
    forbidden: set[str],
) -> list[str]:
    source = _metadata_group(reference_meta, 8).get("value") or []
    target_group = _metadata_group(target_meta, 8)
    target_values = target_group.setdefault("value", [])
    source_by_path = {_normal_path(str(item.get("file_Path") or "")): item for item in source}
    existing = {_normal_path(str(item.get("file_Path") or "")) for item in target_values}
    generated = []
    for path in sorted(required_paths):
        normalized = _normal_path(path)
        if normalized in existing:
            continue
        if not _local_path(path).is_file():
            raise RuntimeError(f"Required Pattern 1 cache asset is missing: {path}")
        template = source_by_path.get(normalized)
        if not template:
            raise RuntimeError(f"Reference metadata does not register required audio asset: {path}")
        cloned = deepcopy(template)
        cloned["id"] = _fresh_id(forbidden)
        target_values.append(cloned)
        existing.add(normalized)
        generated.append(cloned["id"])
    return generated


def _append_auxiliary(
    modified: dict[str, Any], reference_index: dict[str, tuple[str, dict[str, Any]]],
    references: list[str], forbidden: set[str], generated: dict[str, list[str]],
) -> tuple[list[str], set[str]]:
    new_refs, asset_paths = [], set()
    for old_id in references:
        resolved = reference_index.get(str(old_id))
        if not resolved:
            raise RuntimeError(f"Unresolved reference auxiliary material: {old_id}")
        collection, template = resolved
        cloned = deepcopy(template)
        cloned["id"] = _fresh_id(forbidden)
        modified.setdefault("materials", {}).setdefault(collection, []).append(cloned)
        new_refs.append(cloned["id"])
        generated["auxiliary_material_ids"].append(cloned["id"])
        generated["material_ids"].append(cloned["id"])
        beats_path = str(((cloned.get("ai_beats") or {}).get("beats_path")) or "")
        if beats_path:
            asset_paths.add(beats_path)
    return new_refs, asset_paths


def _suppress_cta_caption(
    modified: dict[str, Any], plan: dict[str, Any], caption_registry: dict[str, Any],
) -> dict[str, Any]:
    text_tracks = [track for track in modified.get("tracks", []) if track.get("type") == "text"]
    if not text_tracks:
        raise RuntimeError("Target has no ordinary caption track")
    track = max(text_tracks, key=lambda item: len(item.get("segments") or []))
    material_by_id = {
        str(item.get("id")): item for item in modified.get("materials", {}).get("texts", [])
    }
    expected_start = round(float(plan["cta"]["caption_start"]) * US)
    keyword = str(plan["cta"]["keyword"])
    matches = []
    for segment in track.get("segments") or []:
        material = material_by_id.get(str(segment.get("material_id")))
        if not material:
            continue
        start = int((segment.get("target_timerange") or {}).get("start") or -1)
        if abs(start - expected_start) <= 1_000 and _decode_text(material) == keyword:
            matches.append((segment, material))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one CTA keyword caption at {expected_start / US:.3f}s; found {len(matches)}")
    segment, material = matches[0]
    registered_segments = set(caption_registry.get("generated_segment_ids") or [])
    registered_materials = set(caption_registry.get("generated_material_ids") or [])
    if segment["id"] not in registered_segments or material["id"] not in registered_materials:
        raise RuntimeError("CTA suppression is allowed only on the registered AI caption track")
    auxiliary = list(segment.get("extra_material_refs") or [])
    registered_aux = set(caption_registry.get("generated_auxiliary_material_ids") or [])
    if not set(auxiliary).issubset(registered_aux):
        raise RuntimeError("CTA caption has an auxiliary object not owned by the AI caption registry")
    track["segments"] = [item for item in track["segments"] if item.get("id") != segment["id"]]
    remove_ids = {material["id"], *auxiliary}
    for collection, values in _materials(modified).items():
        modified["materials"][collection] = [item for item in values if item.get("id") not in remove_ids]
    updated = deepcopy(caption_registry)
    updated["generated_segment_ids"] = [
        item for item in caption_registry.get("generated_segment_ids") or []
        if item != segment["id"]
    ]
    updated["generated_material_ids"] = [
        item for item in caption_registry.get("generated_material_ids") or []
        if item != material["id"]
    ]
    updated["generated_auxiliary_material_ids"] = [
        item for item in caption_registry.get("generated_auxiliary_material_ids") or []
        if item not in auxiliary
    ]
    updated["pattern_1_suppressed_caption"] = {
        "segment_id": segment["id"], "material_id": material["id"],
        "auxiliary_material_ids": auxiliary, "text": keyword,
        "start": expected_start / US,
    }
    return updated


def build_pattern1_modified(
    reference: LiveProject, target: LiveProject, plan: dict[str, Any],
    caption_registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    baseline = target.primary
    if _canvas(reference.primary) != _canvas(baseline) or _canvas(baseline) != (1080, 1920):
        raise RuntimeError("Pattern 1 reference and target must share the proven 1080x1920 canvas")
    expected = plan.get("expected") or {}
    if abs(float(baseline.get("duration", 0)) / US - float(expected["duration_seconds"])) > 0.001:
        raise RuntimeError("Target duration differs from the semantic plan")
    video = _video_track(baseline)
    if len(video.get("segments") or []) != int(expected["video_segments"]):
        raise RuntimeError("Target video segment count differs from the semantic plan")
    ordinary = max(
        (track for track in baseline.get("tracks", []) if track.get("type") == "text"),
        key=lambda item: len(item.get("segments") or []), default=None,
    )
    if not ordinary or len(ordinary.get("segments") or []) != int(expected["ordinary_captions_before"]):
        raise RuntimeError("Target ordinary-caption count differs from the semantic plan")
    modified = deepcopy(baseline)
    modified_meta = deepcopy(target.metadata)
    forbidden = set(all_object_ids(modified)) | set(all_object_ids(reference.primary))
    templates = _reference_templates(reference)
    generated: dict[str, Any] = {
        "track_ids": [], "segment_ids": [], "material_ids": [],
        "auxiliary_material_ids": [], "transition_ids": [],
        "zoom_container_ids": [], "zoom_keyframe_ids": [],
        "metadata_material_ids": [],
    }
    updated_caption_registry = _suppress_cta_caption(modified, plan, caption_registry)

    callout_track = deepcopy(templates["callout_track"])
    callout_segment = deepcopy(templates["callout_segment"])
    callout_material = deepcopy(templates["callout_material"])
    callout_track["id"] = _fresh_id(forbidden)
    callout_segment["id"] = _fresh_id(forbidden)
    callout_material["id"] = _fresh_id(forbidden)
    callout_segment["material_id"] = callout_material["id"]
    callout_segment["target_timerange"] = {
        "start": round(float(plan["cta"]["start"]) * US),
        "duration": round((float(plan["cta"]["end"]) - float(plan["cta"]["start"])) * US),
    }
    display_keyword = str(plan["cta"].get("display_keyword") or plan["cta"]["keyword"])
    _set_text(callout_material, f'"{display_keyword}"')
    callout_refs, _ = _append_auxiliary(
        modified, templates["index"], list(callout_segment.get("extra_material_refs") or []),
        forbidden, generated,
    )
    callout_segment["extra_material_refs"] = callout_refs
    callout_track["segments"] = [callout_segment]
    modified.setdefault("materials", {}).setdefault("texts", []).append(callout_material)
    modified.setdefault("tracks", []).append(callout_track)
    generated["track_ids"].append(callout_track["id"])
    generated["segment_ids"].append(callout_segment["id"])
    generated["material_ids"].append(callout_material["id"])

    audio_track_templates = templates["audio_tracks"]
    new_audio_tracks = []
    for template in audio_track_templates:
        track = deepcopy(template)
        track["id"] = _fresh_id(forbidden)
        track["segments"] = []
        new_audio_tracks.append(track)
        generated["track_ids"].append(track["id"])
    required_asset_paths: set[str] = set()
    for event in plan.get("audio_events") or []:
        template_pair = templates["audio"].get(str(event["template"]))
        if not template_pair:
            raise RuntimeError(f"Reference has no audio template named {event['template']}")
        template_segment, template_material = template_pair
        segment, material = deepcopy(template_segment), deepcopy(template_material)
        segment["id"], material["id"] = _fresh_id(forbidden), _fresh_id(forbidden)
        segment["material_id"] = material["id"]
        start = round(float(event["start"]) * US)
        duration = int((template_segment.get("target_timerange") or {}).get("duration") or 0)
        duration = min(duration, int(modified["duration"]) - start)
        if start < 0 or duration <= 0:
            raise RuntimeError(f"Audio event is outside the project: {event}")
        segment["target_timerange"] = {"start": start, "duration": duration}
        if isinstance(segment.get("source_timerange"), dict):
            segment["source_timerange"] = {"start": 0, "duration": duration}
        segment["volume"] = float(event.get("volume", segment.get("volume", 1.0)))
        refs, beat_paths = _append_auxiliary(
            modified, templates["index"], list(segment.get("extra_material_refs") or []),
            forbidden, generated,
        )
        segment["extra_material_refs"] = refs
        path = str(material.get("path") or "")
        if not path or not _local_path(path).is_file():
            raise RuntimeError(f"Audio cache asset is missing: {path or event['template']}")
        required_asset_paths.add(path)
        required_asset_paths.update(beat_paths)
        modified["materials"].setdefault("audios", []).append(material)
        track_number = int(event["track"])
        if track_number not in (1, 2):
            raise RuntimeError("Pattern 1 audio track must be 1 or 2")
        new_audio_tracks[track_number - 1]["segments"].append(segment)
        generated["segment_ids"].append(segment["id"])
        generated["material_ids"].append(material["id"])
    for track in new_audio_tracks:
        track["segments"].sort(key=lambda item: item["target_timerange"]["start"])
        modified["tracks"].append(track)

    target_video = _video_track(modified)
    target_segments = _sorted_segments(target_video)
    for transition in plan.get("transitions") or []:
        template = templates["transitions"].get(str(transition["template"]))
        if not template:
            raise RuntimeError(f"Reference has no transition template named {transition['template']}")
        section = int(transition["after_section"])
        if section < 1 or section >= len(target_segments):
            raise RuntimeError(f"Transition section is invalid: {section}")
        material = deepcopy(template)
        material["id"] = _fresh_id(forbidden)
        path = str(material.get("path") or "")
        if path and not _local_path(path).exists():
            raise RuntimeError(f"Transition cache asset is missing: {path}")
        modified["materials"].setdefault("transitions", []).append(material)
        target_segments[section - 1].setdefault("extra_material_refs", []).append(material["id"])
        generated["transition_ids"].append(material["id"])
        generated["material_ids"].append(material["id"])

    zoom_template = templates["zoom"]
    zoom_base_scales = {}
    for zoom in plan.get("zooms") or []:
        section = int(zoom["section"])
        if section < 1 or section > len(target_segments):
            raise RuntimeError(f"Zoom section is invalid: {section}")
        segment = target_segments[section - 1]
        if any(item.get("property_type") == "KFTypeScaleX" for item in segment.get("common_keyframes") or []):
            raise RuntimeError(f"Zoom section {section} already has a non-owned scale animation")
        base = float((segment.get("clip") or {}).get("scale", {}).get("x") or 1.0)
        if abs(base - float(segment["clip"]["scale"].get("y") or base)) > 1e-9:
            raise RuntimeError(f"Zoom section {section} does not have uniform base scale")
        end = base * (1 + float(zoom["relative_change_percent"]) / 100)
        container = deepcopy(zoom_template)
        container["id"] = _fresh_id(forbidden)
        frames = container.get("keyframe_list") or []
        frames[:] = [deepcopy(frames[0]), deepcopy(frames[-1])]
        frames[0]["id"], frames[-1]["id"] = _fresh_id(forbidden), _fresh_id(forbidden)
        source_range = segment.get("source_timerange") or {}
        first_time = int(source_range.get("start") or 0)
        last_time = first_time + int(source_range.get("duration") or segment["target_timerange"]["duration"])
        frames[0]["time_offset"], frames[-1]["time_offset"] = first_time, last_time
        frames[0]["values"], frames[-1]["values"] = [base], [end]
        segment.setdefault("common_keyframes", []).append(container)
        segment["clip"]["scale"] = {"x": end, "y": end}
        zoom_base_scales[segment["id"]] = base
        generated["zoom_container_ids"].append(container["id"])
        generated["zoom_keyframe_ids"].extend([frames[0]["id"], frames[-1]["id"]])

    generated["metadata_material_ids"] = _clone_metadata_assets(
        reference.metadata, modified_meta, required_asset_paths, forbidden,
    )
    generated["all_ids"] = sorted({
        *generated["track_ids"], *generated["segment_ids"], *generated["material_ids"],
        *generated["zoom_container_ids"], *generated["zoom_keyframe_ids"],
        *generated["metadata_material_ids"],
    })
    generated["zoom_base_scales"] = zoom_base_scales
    return modified, modified_meta, updated_caption_registry, generated


def validate_pattern1_modified(
    baseline: dict[str, Any], modified: dict[str, Any], baseline_meta: dict[str, Any],
    modified_meta: dict[str, Any], plan: dict[str, Any], generated: dict[str, Any],
    caption_registry: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    if baseline.get("duration") != modified.get("duration"):
        errors.append("PROJECT_DURATION_CHANGED")
    if baseline_meta.get("draft_name") != modified_meta.get("draft_name"):
        errors.append("PROJECT_NAME_CHANGED")
    before_video, after_video = _video_track(baseline), _video_track(modified)
    before_segments, after_segments = _sorted_segments(before_video), _sorted_segments(after_video)
    if len(before_segments) != len(after_segments):
        errors.append("VIDEO_SEGMENT_COUNT_CHANGED")
    transition_ids = set(generated["transition_ids"])
    zoom_ids = set(generated["zoom_container_ids"])
    for old, new in zip(before_segments, after_segments):
        restored = deepcopy(new)
        restored["extra_material_refs"] = [
            item for item in restored.get("extra_material_refs") or [] if item not in transition_ids
        ]
        restored["common_keyframes"] = [
            item for item in restored.get("common_keyframes") or [] if item.get("id") not in zoom_ids
        ]
        if new["id"] in generated["zoom_base_scales"]:
            base = generated["zoom_base_scales"][new["id"]]
            restored["clip"]["scale"] = {"x": base, "y": base}
        if restored != old:
            errors.append(f"UNRELATED_VIDEO_CHANGE:{old.get('id')}")
    baseline_track_ids = {item.get("id") for item in baseline.get("tracks", [])}
    generated_tracks = [item for item in modified.get("tracks", []) if item.get("id") not in baseline_track_ids]
    if len(generated_tracks) != 3:
        errors.append("EXPECTED_ONE_CTA_AND_TWO_AUDIO_TRACKS")
    audio_tracks = [item for item in generated_tracks if item.get("type") == "audio"]
    callout_tracks = [item for item in generated_tracks if item.get("type") == "text"]
    if len(audio_tracks) != 2 or sum(len(item.get("segments") or []) for item in audio_tracks) != len(plan["audio_events"]):
        errors.append("AUDIO_EVENT_COUNT_MISMATCH")
    if len(callout_tracks) != 1 or len(callout_tracks[0].get("segments") or []) != 1:
        errors.append("CTA_TRACK_MISMATCH")
    index = _material_index(modified)
    for track in modified.get("tracks", []):
        expected_collection = {"text": "texts", "audio": "audios", "video": "videos"}.get(track.get("type"))
        for segment in track.get("segments") or []:
            material = index.get(str(segment.get("material_id")))
            if not material or (expected_collection and material[0] != expected_collection):
                errors.append(f"UNRESOLVED_SEGMENT_MATERIAL:{segment.get('id')}")
            for ref in segment.get("extra_material_refs") or []:
                if str(ref) not in index:
                    errors.append(f"UNRESOLVED_AUXILIARY:{ref}")
    if len(generated["all_ids"]) != len(set(generated["all_ids"])):
        errors.append("DUPLICATE_GENERATED_ID")
    if set(generated["all_ids"]).intersection(all_object_ids(baseline)):
        errors.append("GENERATED_ID_COLLIDES_WITH_BASELINE")
    text_materials = {item.get("id"): item for item in modified.get("materials", {}).get("texts", [])}
    if callout_tracks:
        segment = callout_tracks[0]["segments"][0]
        material = text_materials.get(segment.get("material_id"), {})
        display_keyword = str(plan["cta"].get("display_keyword") or plan["cta"]["keyword"])
        expected_text = f'"{display_keyword}"'
        if _decode_text(material) != expected_text or material.get("text_color", "").casefold() != "#f4c70f":
            errors.append("CTA_TEXT_OR_COLOR_MISMATCH")
        animations = []
        for ref in segment.get("extra_material_refs") or []:
            animations.extend((index.get(str(ref), ("", {}))[1].get("animations") or []))
        if not any(item.get("name") == plan["cta"]["animation"] for item in animations):
            errors.append("CTA_ANIMATION_MISSING")
    ordinary_tracks = [item for item in modified.get("tracks", []) if item.get("id") in baseline_track_ids and item.get("type") == "text"]
    ordinary = max(ordinary_tracks, key=lambda item: len(item.get("segments") or []), default={})
    if len(ordinary.get("segments") or []) != int(plan["expected"]["ordinary_captions_before"]) - 1:
        errors.append("CTA_ORDINARY_CAPTION_NOT_SUPPRESSED")
    if not caption_registry.get("pattern_1_suppressed_caption"):
        errors.append("CAPTION_REGISTRY_NOT_UPDATED")
    transitions = [item for item in modified.get("materials", {}).get("transitions", []) if item.get("id") in transition_ids]
    if len(transitions) != len(plan["transitions"]):
        errors.append("TRANSITION_COUNT_MISMATCH")
    zoom_count = sum(
        item.get("id") in zoom_ids for segment in after_segments for item in segment.get("common_keyframes") or []
    )
    if zoom_count != len(plan["zooms"]):
        errors.append("ZOOM_COUNT_MISMATCH")
    required_paths = []
    for item in modified.get("materials", {}).get("audios", []):
        if item.get("id") in generated["material_ids"]:
            required_paths.append(str(item.get("path") or ""))
    if any(not path or not _local_path(path).is_file() for path in required_paths):
        errors.append("AUDIO_CACHE_ASSET_MISSING")
    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "duration_unchanged": baseline.get("duration") == modified.get("duration"),
        "video_segment_count": len(after_segments),
        "ordinary_caption_count": len(ordinary.get("segments") or []),
        "callout_count": len(callout_tracks),
        "audio_event_count": sum(len(item.get("segments") or []) for item in audio_tracks),
        "transition_count": len(transitions),
        "zoom_count": zoom_count,
        "generated_id_count": len(generated["all_ids"]),
        "references_resolve": not any("UNRESOLVED" in item for item in errors),
        "asset_paths_resolve": "AUDIO_CACHE_ASSET_MISSING" not in errors,
    }


def _pattern_registry_path(identity: str) -> Path:
    return PROJECT_ROOT / f"state/projects/{project_identity_slug(identity)}/pattern_1.json"


def _remove_registered_pattern1_objects(
    draft: dict[str, Any], metadata: dict[str, Any], registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Remove only objects whose IDs are owned by a Pattern 1 registry."""
    modified = deepcopy(draft)
    modified_meta = deepcopy(metadata)
    generated = registry.get("generated") or {}
    track_ids = set(generated.get("track_ids") or [])
    segment_ids = set(generated.get("segment_ids") or [])
    material_ids = set(generated.get("material_ids") or [])
    material_ids.update(generated.get("auxiliary_material_ids") or [])
    material_ids.update(generated.get("transition_ids") or [])
    zoom_ids = set(generated.get("zoom_container_ids") or [])
    metadata_ids = set(generated.get("metadata_material_ids") or [])
    zoom_base_scales = generated.get("zoom_base_scales") or {}

    modified["tracks"] = [
        track for track in modified.get("tracks") or []
        if str(track.get("id")) not in track_ids
    ]
    removed_zoom_sections = 0
    for track in modified.get("tracks") or []:
        track["segments"] = [
            segment for segment in track.get("segments") or []
            if str(segment.get("id")) not in segment_ids
        ]
        for segment in track.get("segments") or []:
            segment["extra_material_refs"] = [
                ref for ref in segment.get("extra_material_refs") or []
                if str(ref) not in material_ids
            ]
            before = list(segment.get("common_keyframes") or [])
            after = [item for item in before if str(item.get("id")) not in zoom_ids]
            if len(after) != len(before):
                segment["common_keyframes"] = after
                removed_zoom_sections += 1
                base = zoom_base_scales.get(str(segment.get("id")))
                if base is not None:
                    segment.setdefault("clip", {})["scale"] = {
                        "x": float(base), "y": float(base),
                    }

    for collection, values in _materials(modified).items():
        modified["materials"][collection] = [
            item for item in values if str(item.get("id")) not in material_ids
        ]

    for group in modified_meta.get("draft_materials") or []:
        if group.get("type") == 8:
            group["value"] = [
                item for item in group.get("value") or []
                if str(item.get("id")) not in metadata_ids
            ]

    changes = {
        "registered_track_ids": len(track_ids),
        "registered_segment_ids": len(segment_ids),
        "registered_material_ids": len(material_ids),
        "registered_zoom_ids": len(zoom_ids),
        "registered_metadata_ids": len(metadata_ids),
        "removed_zoom_sections": removed_zoom_sections,
    }
    return modified, modified_meta, changes


def remove_pattern1_registered(
    target_project: str, dry_run: bool = False,
) -> tuple[dict[str, Any], Path]:
    """Transactionally clear a stale/previous Pattern 1 layer for a fresh reapply."""
    require_capcut_closed()
    target = read_live_project(locate_project(target_project))
    pattern_registry = _pattern_registry_path(target.project.identity)
    if not pattern_registry.is_file():
        raise RuntimeError("Pattern 1 registry is missing; refusing unowned cleanup")
    registry = json.loads(pattern_registry.read_text(encoding="utf-8-sig"))
    if registry.get("project_identity") != target.project.identity:
        raise RuntimeError("Pattern 1 registry identity does not match the selected project")
    modified, modified_meta, changes = _remove_registered_pattern1_objects(
        target.primary, target.metadata, registry,
    )
    generated_ids = set((registry.get("generated") or {}).get("all_ids") or [])
    remaining_draft_ids = generated_ids.intersection(all_object_ids(modified))
    remaining_meta_ids = {
        str(item.get("id"))
        for group in modified_meta.get("draft_materials") or []
        for item in group.get("value") or [] if isinstance(item, dict)
    }.intersection(generated_ids)
    validation = {
        "valid": not remaining_draft_ids and not remaining_meta_ids,
        "errors": sorted([
            *(f"REGISTERED_DRAFT_ID_REMAINS:{item}" for item in remaining_draft_ids),
            *(f"REGISTERED_METADATA_ID_REMAINS:{item}" for item in remaining_meta_ids),
        ]),
        "duration_unchanged": target.primary.get("duration") == modified.get("duration"),
        "video_segment_count_unchanged": (
            len(_sorted_segments(_video_track(target.primary)))
            == len(_sorted_segments(_video_track(modified)))
        ),
    }
    validation["valid"] = bool(
        validation["valid"]
        and validation["duration_unchanged"]
        and validation["video_segment_count_unchanged"]
    )
    slug = target.project.name.casefold().replace(" ", "_")
    report = {
        "dry_run": dry_run,
        "project_written": False,
        "project": target.project.name,
        "registry_path": str(pattern_registry),
        "changes": changes,
        "validation": validation,
        "elevenlabs_called": False,
    }
    output = PROJECT_ROOT / f"output/json/{slug}.pattern_1_cleanup_preflight.json"
    write_json(output, report)
    if not validation["valid"]:
        raise RuntimeError("Pattern 1 cleanup preflight failed: " + "; ".join(validation["errors"]))
    if dry_run:
        return report, output

    require_live_project_write_ready(target, "pattern_1_direct_write")

    caption_path = registry_path(target.project.identity)
    caption_state = load_registry(target.project.identity)
    updated_caption_state = deepcopy(caption_state) if caption_state else None
    if updated_caption_state is not None:
        updated_caption_state.pop("pattern_1_suppressed_caption", None)
    originals: dict[Path, bytes | None] = {
        **{path: path.read_bytes() for path in target.draft_paths},
        target.project.metadata_path: target.project.metadata_path.read_bytes(),
        pattern_registry: pattern_registry.read_bytes(),
        caption_path: caption_path.read_bytes() if caption_path.exists() else None,
    }
    replacements: list[tuple[Path, Path]] = []
    try:
        for path in target.draft_paths:
            replacements.append((path, _atomic_json(path, modified, ".pattern1_cleanup.tmp")))
        replacements.append((
            target.project.metadata_path,
            _atomic_json(target.project.metadata_path, modified_meta, ".pattern1_cleanup.tmp"),
        ))
        if updated_caption_state is not None:
            replacements.append((
                caption_path,
                _atomic_json(caption_path, updated_caption_state, ".pattern1_cleanup.tmp"),
            ))
        for path, temporary in replacements:
            temporary.replace(path)
        reread = [json.loads(path.read_text(encoding="utf-8-sig")) for path in target.draft_paths]
        if any(item != reread[0] for item in reread[1:]):
            raise RuntimeError("Mirrored drafts differ after Pattern 1 cleanup")
        if generated_ids.intersection(all_object_ids(reread[0])):
            raise RuntimeError("Registered Pattern 1 IDs remain after cleanup")
        pattern_registry.unlink()
    except Exception:
        for path, content in originals.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                restore = path.with_name(path.name + ".pattern1_cleanup_restore.tmp")
                restore.parent.mkdir(parents=True, exist_ok=True)
                restore.write_bytes(content)
                restore.replace(path)
        raise
    finally:
        for _path, temporary in replacements:
            temporary.unlink(missing_ok=True)
    report["dry_run"] = False
    report["project_written"] = True
    report["rollback_status"] = "not_needed"
    output = PROJECT_ROOT / f"output/json/{slug}.pattern_1_cleanup_result.json"
    write_json(output, report)
    return report, output


def _atomic_json(path: Path, value: dict[str, Any], suffix: str) -> Path:
    temporary = path.with_name(path.name + suffix)
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if json.loads(temporary.read_text(encoding="utf-8")) != value:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Temporary parse-back mismatch: {path}")
    return temporary


def apply_pattern1(
    target_project: str, reference_project: str, plan_path: Path,
    dry_run: bool = False, simulate_failure_after: int | None = None,
) -> tuple[dict[str, Any], Path]:
    require_capcut_closed()
    target = read_live_project(locate_project(target_project))
    reference = read_live_project(locate_project(reference_project))
    plan_path = plan_path.resolve()
    plan = _load_plan(plan_path)
    if plan.get("target_project", "").casefold() != target.project.name.casefold():
        raise RuntimeError("Plan target_project does not match selected project")
    if plan.get("reference_project", "").casefold() != reference.project.name.casefold():
        raise RuntimeError("Plan reference_project does not match selected reference")
    pattern_registry = _pattern_registry_path(target.project.identity)
    if pattern_registry.exists():
        raise RuntimeError("Pattern 1 is already registered on this project; refusing duplicate injection")
    caption_state = load_registry(target.project.identity)
    if not caption_state:
        raise RuntimeError("Registered AI captions are required before Pattern 1 injection")
    modified, modified_meta, updated_caption_state, generated = build_pattern1_modified(
        reference, target, plan, caption_state,
    )
    validation = validate_pattern1_modified(
        target.primary, modified, target.metadata, modified_meta, plan, generated,
        updated_caption_state,
    )
    slug = target.project.name.casefold().replace(" ", "_")
    preflight_path = PROJECT_ROOT / f"output/json/{slug}.pattern_1_preflight.json"
    report = {
        "dry_run": dry_run, "project_written": False, "project": target.project.name,
        "reference_project": reference.project.name, "plan_path": str(plan_path),
        "plan_hash": stable_hash(plan), "validation": validation,
        "generated": generated, "elevenlabs_called": False,
    }
    write_json(preflight_path, report)
    write_json(PROJECT_ROOT / f"logs/direct_edit/{slug}/pattern_1_preflight.json", report)
    if not validation["valid"]:
        raise RuntimeError("Pattern 1 preflight failed: " + "; ".join(validation["errors"]))
    if dry_run:
        return report, preflight_path

    require_live_project_write_ready(target, "pattern_1_direct_write")

    caption_path = registry_path(target.project.identity)
    originals: dict[Path, bytes | None] = {
        **{path: path.read_bytes() for path in target.draft_paths},
        target.project.metadata_path: target.project.metadata_path.read_bytes(),
        caption_path: caption_path.read_bytes() if caption_path.exists() else None,
        pattern_registry: None,
    }
    replacements: list[tuple[Path, Path]] = []
    try:
        for path in target.draft_paths:
            replacements.append((path, _atomic_json(path, modified, ".pattern1.tmp")))
        replacements.append((target.project.metadata_path, _atomic_json(target.project.metadata_path, modified_meta, ".pattern1.tmp")))
        replacements.append((caption_path, _atomic_json(caption_path, updated_caption_state, ".pattern1.tmp")))
        for index, (path, temporary) in enumerate(replacements, 1):
            temporary.replace(path)
            if simulate_failure_after == index:
                raise RuntimeError("simulated Pattern 1 write failure")
        reread = [json.loads(path.read_text(encoding="utf-8-sig")) for path in target.draft_paths]
        if any(item != reread[0] for item in reread[1:]):
            raise RuntimeError("Mirrored drafts differ after Pattern 1 injection")
        reread_meta = json.loads(target.project.metadata_path.read_text(encoding="utf-8-sig"))
        reread_caption = json.loads(caption_path.read_text(encoding="utf-8-sig"))
        post = validate_pattern1_modified(
            target.primary, reread[0], target.metadata, reread_meta, plan, generated,
            reread_caption,
        )
        if not post["valid"]:
            raise RuntimeError("Pattern 1 post-write validation failed: " + "; ".join(post["errors"]))
        registry_payload = {
            "version": 1, "profile": "Pattern 1", "project_identity": target.project.identity,
            "project_name": target.project.name, "reference_project": reference.project.name,
            "plan_hash": stable_hash(plan), "plan_path": str(plan_path),
            "generated": generated, "validation": post,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_text(pattern_registry, json.dumps(registry_payload, ensure_ascii=False, indent=2))
    except Exception:
        for path, content in originals.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                restore = path.with_name(path.name + ".pattern1_restore.tmp")
                restore.parent.mkdir(parents=True, exist_ok=True)
                restore.write_bytes(content)
                restore.replace(path)
        raise
    finally:
        for _path, temporary in replacements:
            temporary.unlink(missing_ok=True)
    result = {
        **report, "dry_run": False, "project_written": True,
        "validation": post, "registry_path": str(pattern_registry),
        "rollback_status": "not_needed",
    }
    output = PROJECT_ROOT / f"output/json/{slug}.pattern_1_result.json"
    write_json(output, result)
    write_json(PROJECT_ROOT / f"logs/direct_edit/{slug}/pattern_1_validation.json", post)
    return result, output

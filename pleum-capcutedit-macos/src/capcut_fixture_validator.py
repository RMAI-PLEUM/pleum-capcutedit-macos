"""Validate copied CapCut schema fixtures and their SHA-256 manifest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from capcut_fixture_collector import DESTINATIONS
from capcut_live_project_reader import active_draft_paths
from utils import PROJECT_ROOT


MEDIA_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/]|/)[^\"'\r\n|]+?\.(?:mp4|mov|mkv|avi|m4v|webm|mp3|wav|m4a)",
    re.IGNORECASE,
)
EXPECTED_TEXT = {
    "01_video_only": (),
    "02_one_caption": ("ทดสอบซับภาษาไทย",),
    "03_styled_caption": ("ทดสอบซับภาษาไทย",),
    "04_multiple_captions": ("ประโยคที่หนึ่ง", "ประโยคที่สอง", "ประโยคที่สาม"),
    "05_one_cut": (),
}
ALL_TEST_TEXT = tuple(dict.fromkeys(text for values in EXPECTED_TEXT.values() for text in values))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(path: Path) -> str | None:
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeError, OSError):
            continue
    return None


def _project_files(folder: Path) -> Iterable[Path]:
    for path in folder.rglob("*"):
        if path.is_file():
            yield path


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _scan_text_and_media(folder: Path) -> tuple[list[str], list[str], list[str]]:
    found_text: list[str] = []
    media: set[str] = set()
    readable_json: list[str] = []
    for path in _project_files(folder):
        content = _text(path)
        if content is None:
            continue
        searchable_values = [content]
        if path.suffix.casefold() == ".json":
            try:
                decoded = json.loads(content)
                readable_json.append(path.relative_to(folder).as_posix())
                searchable_values.extend(_walk_strings(decoded))
            except json.JSONDecodeError:
                pass
        for value in searchable_values:
            for expected in ALL_TEST_TEXT:
                if expected in value and expected not in found_text:
                    found_text.append(expected)
            media.update(match.group(0) for match in MEDIA_PATTERN.finditer(value))
    return found_text, sorted(media), readable_json


def _latest_draft(folder: Path) -> tuple[Path, dict[str, Any]]:
    drafts, _storage_format = active_draft_paths(folder)
    drafts = sorted(drafts, key=lambda path: path.stat().st_mtime)
    if not drafts:
        raise FileNotFoundError(f"No active CapCut draft payload in {folder}")
    path = drafts[-1]
    return path, json.loads(path.read_text(encoding="utf-8-sig"))


def _caption_texts(data: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for material in data.get("materials", {}).get("texts", []):
        content = material.get("content")
        if isinstance(content, str):
            try:
                decoded = json.loads(content)
                value = decoded.get("text") if isinstance(decoded, dict) else None
            except json.JSONDecodeError:
                value = content
            if isinstance(value, str) and value and value not in texts:
                texts.append(value)
    return texts


def _style_signature(data: dict[str, Any]) -> list[dict[str, Any]]:
    signatures: list[dict[str, Any]] = []
    keys = (
        "text_color", "text_alpha", "font_name", "font_title", "font_size",
        "font_resource_id", "bold_width", "italic_degree", "underline",
        "border_color", "border_width", "border_alpha", "has_shadow",
        "shadow_color", "shadow_alpha", "shadow_distance", "background_color",
        "background_alpha", "background_style", "alignment", "line_spacing",
        "letter_spacing", "style_name", "preset_id", "text_preset_resource_id",
    )
    for material in data.get("materials", {}).get("texts", []):
        signature = {key: material.get(key) for key in keys}
        content = material.get("content")
        if isinstance(content, str):
            try:
                decoded = json.loads(content)
                signature["rich_styles"] = decoded.get("styles")
            except json.JSONDecodeError:
                pass
        signatures.append(signature)
    return signatures


def _fixture_metrics(folder: Path) -> dict[str, Any]:
    _, data = _latest_draft(folder)
    tracks = data.get("tracks", [])
    video_tracks = [track for track in tracks if track.get("type") == "video"]
    text_tracks = [
        track for track in tracks if track.get("type") in {"text", "caption"}
    ]
    duration = float(data.get("duration") or 0)
    return {
        "duration_seconds": duration / 1_000_000 if duration > 10000 else duration,
        "video_track_count": len(video_tracks),
        "video_segment_count": sum(len(track.get("segments", [])) for track in video_tracks),
        "text_caption_track_count": len(text_tracks),
        "text_caption_segment_count": sum(
            len(track.get("segments", [])) for track in text_tracks
        ),
        "text_material_count": len(data.get("materials", {}).get("texts", [])),
        "caption_texts": _caption_texts(data),
        "style_signature": _style_signature(data),
    }


def _timeline_signature(folder: Path) -> list[dict[str, Any]]:
    _, data = _latest_draft(folder)
    signature = []
    for track in data.get("tracks", []):
        segments = []
        for segment in track.get("segments", []):
            segments.append({
                "source": segment.get("source_timerange"),
                "target": segment.get("target_timerange"),
                "material_id": segment.get("material_id"),
            })
        signature.append({"type": track.get("type"), "segments": segments})
    return signature


def validate_fixtures() -> dict[str, Any]:
    base = PROJECT_ROOT / "sample_capcut_projects"
    manifest_path = base / "fixture_manifest.json"
    errors: list[str] = []
    warnings: list[str] = []
    if not manifest_path.is_file():
        return {"valid": False, "errors": ["fixture_manifest.json is missing"], "warnings": []}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = {item["fixture_name"]: item for item in manifest.get("fixtures", [])}
    results: list[dict[str, Any]] = []
    common_media: set[str] | None = None
    for fixture_name in DESTINATIONS.values():
        folder = base / fixture_name
        item_errors: list[str] = []
        if not folder.is_dir():
            item_errors.append("fixture folder is missing")
            results.append({"fixture_name": fixture_name, "valid": False, "errors": item_errors})
            errors.extend(f"{fixture_name}: {error}" for error in item_errors)
            continue
        files = [path for path in folder.rglob("*") if path.is_file()]
        if not files:
            item_errors.append("fixture folder is empty")
        found_text, media, readable_json = _scan_text_and_media(folder)
        try:
            metrics = _fixture_metrics(folder)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            metrics = {}
            item_errors.append(f"could not inspect timeline metrics: {exc}")
        if not readable_json:
            item_errors.append("no readable project JSON found")
        expected = EXPECTED_TEXT[fixture_name]
        for text in expected:
            if text not in found_text:
                item_errors.append(f"expected caption text not found: {text}")
        if fixture_name == "01_video_only" and found_text:
            item_errors.append(f"unexpected test caption text found: {found_text}")
        record = by_name.get(fixture_name)
        if record is None:
            item_errors.append("fixture is missing from manifest")
        else:
            for file_record in record.get("files", []):
                path = folder / Path(file_record["relative_path"])
                if not path.is_file():
                    item_errors.append(f"manifest file missing: {file_record['relative_path']}")
                    continue
                if path.stat().st_size != file_record["size"]:
                    item_errors.append(f"size mismatch: {file_record['relative_path']}")
                elif _sha256(path) != file_record["sha256"]:
                    item_errors.append(f"SHA-256 mismatch: {file_record['relative_path']}")
        media_basenames = {Path(value.replace("\\", "/")).name.casefold() for value in media}
        if media_basenames:
            common_media = media_basenames if common_media is None else common_media & media_basenames
        else:
            warnings.append(f"{fixture_name}: no source media path found in JSON/metadata")
        results.append({
            "fixture_name": fixture_name,
            "valid": not item_errors,
            "file_count": len(files),
            "caption_texts_found": found_text,
            **metrics,
            "source_media_paths": media,
            "readable_json_files": readable_json,
            "errors": item_errors,
        })
        errors.extend(f"{fixture_name}: {error}" for error in item_errors)
    if common_media is not None and not common_media:
        errors.append("fixtures do not reference a common source media filename")
    first = base / "01_video_only"
    cut = base / "05_one_cut"
    try:
        if _timeline_signature(first) == _timeline_signature(cut):
            errors.append("Schema 05 timeline segment structure does not differ from Schema 01")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"could not compare Schema 01 and Schema 05 timelines: {exc}")
    styled_by_name = {item["fixture_name"]: item for item in results}
    plain_style = styled_by_name.get("02_one_caption", {}).get("style_signature")
    styled_style = styled_by_name.get("03_styled_caption", {}).get("style_signature")
    style_differs = bool(plain_style and styled_style and plain_style != styled_style)
    if not style_differs:
        errors.append("Schema 03 caption style does not differ from Schema 02")
    return {
        "valid": not errors,
        "fixtures": results,
        "common_source_media_filenames": sorted(common_media or []),
        "schema_03_style_differs_from_schema_02": style_differs,
        "errors": errors,
        "warnings": warnings,
    }

"""External ownership registry for AI-generated CapCut caption objects."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import PROJECT_ROOT, write_json


def project_identity_slug(identity: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", identity).strip("_") or "unknown"


def registry_path(identity: str) -> Path:
    return (
        PROJECT_ROOT / "state/projects" / project_identity_slug(identity)
        / "ai_captions.json"
    )


def load_registry(identity: str) -> dict[str, Any] | None:
    path = registry_path(identity)
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("project_identity") != identity:
        raise RuntimeError("AI caption registry identity mismatch.")
    return value


def stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_registry(
    identity: str,
    project_path: Path,
    generated_ids: dict[str, Any],
    caption_plan: dict[str, Any],
    timeline_signature: Any,
) -> Path:
    path = registry_path(identity)
    write_json(path, {
        "project_identity": identity,
        "project_path": str(project_path),
        "generated_text_track_id": generated_ids["track_id"],
        "generated_segment_ids": generated_ids["segment_ids"],
        "generated_material_ids": generated_ids["material_ids"],
        "generated_auxiliary_material_ids": generated_ids.get(
            "auxiliary_material_ids", []
        ),
        "caption_plan_hash": stable_hash(caption_plan),
        "timeline_hash": stable_hash(timeline_signature),
        "generation_timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return path


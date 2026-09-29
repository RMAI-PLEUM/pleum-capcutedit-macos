"""Registry for AI-generated karaoke tracks and materials."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import PROJECT_ROOT, atomic_write_text


def registry_path(project_identity: str) -> Path:
    return PROJECT_ROOT / f"state/projects/{project_identity}/ai_karaoke.json"


def load_karaoke_registry(project_identity: str) -> dict[str, Any] | None:
    path = registry_path(project_identity)
    return (
        json.loads(path.read_text(encoding="utf-8-sig"))
        if path.is_file() else None
    )


def write_karaoke_registry(
    project_identity: str, value: dict[str, Any]
) -> Path:
    path = registry_path(project_identity)
    value = {
        **value,
        "generation_time": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_text(
        path, json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )
    return path

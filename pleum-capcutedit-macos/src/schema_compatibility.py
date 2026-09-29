"""Value-free CapCut schema fingerprint and compatibility gate."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

from utils import PROJECT_ROOT


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        shapes = {_stable(_shape(item)) for item in value[:20]}
        return [json.loads(item) for item in sorted(shapes)]
    return type(value).__name__


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def schema_fingerprint(draft: dict) -> str:
    return hashlib.sha256(_stable(_shape(draft)).encode("utf-8")).hexdigest()


def compatibility_status(draft: dict, feature: str | None = None) -> dict:
    path = PROJECT_ROOT / "config/capcut_compatibility.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    fingerprint = schema_fingerprint(draft)
    current_system = platform.system()
    known = [
        item for item in config.get("tested_schemas", [])
        if item.get("schema_fingerprint") == fingerprint
        and str(item.get("operating_system") or "").casefold().startswith(
            current_system.casefold()
        )
    ]
    validated = [item for item in known if bool(item.get("direct_write_validated", False))]
    write_allowed = any(
        feature is None or feature in item.get("supported_features", [])
        for item in validated
    )
    if write_allowed:
        guidance = None
    elif known and validated and feature:
        guidance = (
            f"Schema is validated, but feature '{feature}' has no macOS "
            "write/reopen evidence. Keep this feature dry-run only."
        )
    elif known:
        guidance = (
            "Known read-only schema: complete controlled write, rollback, and "
            "CapCut reopen validation before enabling direct writes."
        )
    else:
        guidance = "Unknown schema: stop before writing and run controlled fixture learning."
    return {
        "compatible": bool(known), "schema_fingerprint": fingerprint,
        "matches": known,
        "requested_feature": feature,
        "write_allowed": write_allowed, "guidance": guidance,
    }


def require_compatible_schema(draft: dict, feature: str | None = None) -> None:
    status = compatibility_status(draft, feature)
    if not status["write_allowed"]:
        raise RuntimeError(
            "Direct write blocked by CapCut schema compatibility gate. "
            f"Fingerprint: {status['schema_fingerprint']}. "
            f"Feature: {feature or 'unspecified'}. "
            "Run controlled fixture learning; do not guess fields."
        )

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from utils import PROJECT_ROOT


DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "elevenlabs",
    "model_id": "scribe_v2",
    "language_code": "th",
    "timestamps_granularity": "word",
    "diarize": False,
    "subtitle": {
        "max_lines": 1,
        "max_words_per_cue": 16,
        "min_duration": 0.70,
        "max_duration": 4.00,
        "lead_in": 0.03,
        "tail_out": 0.10,
    },
    "timeline": {
        "account_for_trim": True,
        "account_for_speed": True,
        "clamp_to_clip_range": True,
    },
    "caption": {
        "max_lines": 1,
        "max_words_per_cue": 16,
        "min_duration": 0.70,
        "max_duration": 4.00,
    },
    "cut": {
        "silence_threshold": 0.65,
        "speech_padding": 0.12,
        "minimum_cut_duration": 0.40,
        "require_review_below_confidence": 0.85,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    load_dotenv(PROJECT_ROOT / ".env")
    config_path = path or PROJECT_ROOT / "config.yaml"
    supplied = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    config = _merge(DEFAULT_CONFIG, supplied or {})
    if config["provider"] != "elevenlabs":
        raise ValueError("Phase 1 supports only provider: elevenlabs")
    return config

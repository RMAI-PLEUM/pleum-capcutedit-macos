from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from transcript_normalizer import normalize_word_records
from utils import PROJECT_ROOT, write_json


ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"


def load_default_keyterms() -> list[str]:
    path = PROJECT_ROOT / "presets" / "keyterms" / "default.txt"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def transcribe(
    audio_path: Path,
    basename: str,
    config: dict[str, Any],
    keyterms: list[str] | None = None,
    media_duration: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is missing. Copy .env.example to .env and add the key.")
    terms = keyterms if keyterms is not None else load_default_keyterms()
    data: list[tuple[str, str]] = [
        ("model_id", str(config["model_id"])),
        ("language_code", str(config["language_code"])),
        ("timestamps_granularity", str(config["timestamps_granularity"])),
        ("diarize", str(bool(config["diarize"])).lower()),
    ]
    data.extend(("keyterms", term) for term in terms)
    with audio_path.open("rb") as audio:
        response = requests.post(
            ENDPOINT,
            headers={"xi-api-key": api_key},
            data=data,
            files={"file": (audio_path.name, audio, "audio/wav")},
            timeout=(30, 1800),
        )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text[:1000]
        raise RuntimeError(f"ElevenLabs STT failed ({response.status_code}): {detail}") from exc
    raw = response.json()
    words = normalize_word_records(raw, media_duration=media_duration)
    write_json(PROJECT_ROOT / "output/json" / f"{basename}.elevenlabs_raw.json", raw)
    write_json(PROJECT_ROOT / "output/json" / f"{basename}.words.json", words)
    return raw, words

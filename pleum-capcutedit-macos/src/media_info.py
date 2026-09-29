from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from utils import PROJECT_ROOT, write_json


def _duration(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def probe_media(path: Path, basename: str) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe was not found. Install FFmpeg and add it to PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed: {exc.stderr.strip()}") from exc

    raw = json.loads(result.stdout)
    video_stream = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in raw.get("streams", []) if s.get("codec_type") == "audio"), None)
    format_duration = _duration(raw.get("format", {}).get("duration"))
    video_duration = _duration((video_stream or {}).get("duration"))
    audio_duration = _duration((audio_stream or {}).get("duration"))
    target = video_duration if video_duration is not None else format_duration
    target = target if target is not None else audio_duration
    if target is None or target <= 0:
        raise RuntimeError("Unable to determine a positive media duration.")
    info = {
        "path": str(path.resolve()),
        "format_duration": format_duration,
        "video_stream_duration": video_duration,
        "audio_stream_duration": audio_duration,
        "target_duration": target,
        "video_stream": video_stream,
        "audio_stream": audio_stream,
        "ffprobe": raw,
    }
    write_json(PROJECT_ROOT / "logs" / f"{basename}.media_info.json", info)
    return info


def media_duration(path: Path, basename: str | None = None) -> float:
    return float(probe_media(path, basename or path.stem)["target_duration"])

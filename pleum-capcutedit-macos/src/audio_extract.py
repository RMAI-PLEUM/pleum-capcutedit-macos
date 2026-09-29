from __future__ import annotations

import subprocess
from pathlib import Path

from utils import PROJECT_ROOT


def extract_audio(
    media_path: Path, basename: str, max_duration: float | None = None
) -> Path:
    output = PROJECT_ROOT / "temp" / (
        f"{basename}.first_{int(max_duration)}s.wav" if max_duration else f"{basename}.wav"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(media_path),
    ]
    if max_duration is not None:
        if max_duration <= 0:
            raise ValueError("max_duration must be positive")
        command.extend(["-t", f"{max_duration:.6f}"])
    command.extend([
        "-vn",
        "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(output),
    ])
    try:
        subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg was not found. Install FFmpeg and add it to PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"FFmpeg audio extraction failed: {exc.stderr.strip()}") from exc
    return output

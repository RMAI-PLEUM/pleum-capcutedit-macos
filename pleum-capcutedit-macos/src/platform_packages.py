"""Read-only dependency detection used by setup and doctor."""

from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys


def command_version(command: str) -> str | None:
    executable = shutil.which(command)
    if not executable:
        return None
    result = subprocess.run(
        [executable, "-version"], capture_output=True, text=True, errors="replace"
    )
    line = (result.stdout or result.stderr).splitlines()
    return line[0].strip() if line else "installed"


def package_status() -> dict:
    return {
        "operating_system": platform.platform(),
        "architecture": platform.machine(),
        "python_version": sys.version.split()[0],
        "virtual_environment": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "ffmpeg_version": command_version("ffmpeg"),
        "ffprobe_version": command_version("ffprobe"),
        "python_packages": {
            name: importlib.util.find_spec(name) is not None
            for name in ("elevenlabs", "pythainlp", "rapidfuzz", "dotenv", "yaml")
        },
    }

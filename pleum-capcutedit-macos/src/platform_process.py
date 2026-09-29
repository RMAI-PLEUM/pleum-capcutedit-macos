"""Cross-platform CapCut process inspection without terminating processes."""

from __future__ import annotations

import platform
import subprocess


def capcut_process_ids() -> list[int]:
    if platform.system() == "Windows":
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process -Name CapCut -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, encoding="utf-8",
        )
    elif platform.system() == "Darwin":
        # Match the application binary and its helpers without relying on a
        # localized display name. pgrep is available on every supported macOS.
        result = subprocess.run(
            ["pgrep", "-i", "-f", r"(/CapCut\.app/|/CapCut$|CapCut Helper)"],
            capture_output=True, text=True,
        )
    else:
        result = subprocess.run(
            ["pgrep", "-i", "-f", "CapCut"], capture_output=True, text=True
        )
    return [
        int(line.strip()) for line in result.stdout.splitlines()
        if line.strip().isdigit()
    ]

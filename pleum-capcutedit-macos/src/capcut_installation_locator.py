"""Find CapCut installations; candidates are informational until verified."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def installation_candidates() -> list[dict]:
    paths: list[Path] = []
    if platform.system() == "Windows":
        local = os.getenv("LOCALAPPDATA")
        if local:
            apps = Path(local) / "CapCut/Apps"
            if apps.is_dir():
                paths.extend(apps.glob("*/CapCut.exe"))
                paths.append(apps / "CapCut.exe")
    elif platform.system() == "Darwin":
        paths.extend([
            Path("/Applications/CapCut.app"),
            Path.home() / "Applications/CapCut.app",
        ])
    output = []
    for path in paths:
        if path.exists():
            output.append({
                "path": str(path.resolve()), "platform": platform.system(),
                "verified_exists": True,
            })
    return output

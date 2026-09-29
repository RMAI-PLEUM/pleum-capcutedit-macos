"""Cross-platform, verified paths for Edit CapCut machine state and projects."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Iterable


APP_NAME = "edit-capcut"


def user_config_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.getenv("APPDATA") or Path.home() / "AppData/Roaming")
    elif system == "Darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME


def machine_config_path() -> Path:
    return user_config_dir() / "config.json"


def load_machine_config() -> dict:
    path = machine_config_path()
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_machine_config(value: dict) -> Path:
    path = machine_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _candidate_roots() -> Iterable[Path]:
    configured = load_machine_config().get("capcut_project_root")
    if configured:
        yield Path(configured).expanduser()
    override = os.getenv("EDIT_CAPCUT_PROJECT_ROOT")
    if override:
        yield Path(override).expanduser()
    if platform.system() == "Windows":
        local = os.getenv("LOCALAPPDATA")
        if local:
            yield Path(local) / "CapCut/User Data/Projects/com.lveditor.draft"
    elif platform.system() == "Darwin":
        home = Path.home()
        # Candidates only: each must pass metadata verification below.
        yield home / "Movies/CapCut/User Data/Projects/com.lveditor.draft"
        yield home / "Library/Application Support/CapCut/User Data/Projects/com.lveditor.draft"
        yield home / "Library/Containers/com.lemon.lvoverseas/Data/Library/Application Support/CapCut/User Data/Projects/com.lveditor.draft"


def _parseable_project_count(root: Path) -> int:
    count = 0
    if not root.is_dir():
        return 0
    for child in root.iterdir():
        metadata = child / "draft_meta_info.json"
        if not metadata.is_file():
            continue
        try:
            value = json.loads(metadata.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if value.get("draft_name") and value.get("draft_id"):
            count += 1
    return count


def capcut_project_root_candidates() -> list[dict]:
    output, seen = [], set()
    for raw in _candidate_roots():
        path = raw.expanduser().resolve()
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        count = _parseable_project_count(path)
        if count:
            output.append({
                "path": str(path), "parseable_project_count": count,
                "writable": os.access(path, os.W_OK),
            })
    return output


def selected_project_root() -> Path:
    candidates = capcut_project_root_candidates()
    if not candidates:
        raise FileNotFoundError(
            "No verified CapCut project root found. Run `edit-capcut setup` "
            "or pass --capcut-project-root."
        )
    configured = load_machine_config().get("capcut_project_root")
    if configured:
        resolved = str(Path(configured).expanduser().resolve())
        for item in candidates:
            if item["path"] == resolved:
                return Path(resolved)
    if len(candidates) > 1:
        shown = "\n".join(f"- {item['path']}" for item in candidates)
        raise RuntimeError(
            "Multiple verified CapCut roots found; select one during setup:\n" + shown
        )
    return Path(candidates[0]["path"])

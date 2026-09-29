from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def ensure_directories() -> None:
    for relative in (
        "input/media", "input/scripts", "input/assets", "output/srt",
        "output/json", "output/preview", "logs", "backups", "temp",
        "presets/caption_styles", "presets/edit_styles", "presets/keyterms",
        "sample_capcut_projects",
    ):
        (PROJECT_ROOT / relative).mkdir(parents=True, exist_ok=True)


def setup_logging(name: str) -> logging.Logger:
    ensure_directories()
    logger = logging.getLogger("ai_editor_capcut")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(
        PROJECT_ROOT / "logs" / f"{name}.log", encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def safe_basename(path: Path) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", path.stem).strip(" .") or "media"


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def normalize_space(text: str, keep_lines: bool = False) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if keep_lines:
        return "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\s+", " ", text).strip()


def token_count(text: str) -> int:
    try:
        from pythainlp.tokenize import word_tokenize

        return len([
            t for t in word_tokenize(text, engine="newmm", keep_whitespace=False)
            if re.search(r"[A-Za-z0-9\u0E01-\u0E5B]", t)
        ])
    except (ImportError, LookupError):
        return len(re.findall(r"[A-Za-z0-9]+(?:['.-][A-Za-z0-9]+)*|[\u0E00-\u0E7F]+", text))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8-sig")
    temporary.replace(path)

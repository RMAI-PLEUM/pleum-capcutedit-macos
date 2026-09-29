from __future__ import annotations

import re
from typing import Iterable

from utils import normalize_space, token_count


def _tokens(text: str) -> list[str]:
    try:
        from pythainlp.tokenize import word_tokenize

        return [t for t in word_tokenize(text, engine="newmm", keep_whitespace=False) if t.strip()]
    except (ImportError, LookupError):
        return re.findall(r"[A-Za-z0-9]+(?:['.-][A-Za-z0-9]+)*|[\u0E00-\u0E7F]+|[^\s]", text)


def _join(tokens: Iterable[str]) -> str:
    text = ""
    for token in tokens:
        if not text or re.match(r"^[,.;:!?ๆฯ)\]}]", token):
            text += token
        elif re.match(r"^[({\[]$", token):
            text += " " + token
        elif re.search(r"[({\[]$", text):
            text += token
        elif re.match(r"^[\u0E00-\u0E7F]", token) and re.search(r"[\u0E00-\u0E7F]$", text):
            text += token
        else:
            text += " " + token
    return normalize_space(text)


def chunk_script(script: str, max_words: int = 16) -> list[str]:
    chunks: list[str] = []
    normalized = normalize_space(script, keep_lines=True)
    for original_line in normalized.splitlines():
        line = original_line.strip()
        if not line:
            continue
        segments = [s.strip() for s in re.split(r"(?<=[.!?。！？ฯ])\s+", line) if s.strip()]
        for segment in segments:
            tokens = _tokens(segment)
            current: list[str] = []
            for token in tokens:
                candidate = _join(current + [token])
                if current and token_count(candidate) > max_words:
                    chunks.append(_join(current))
                    current = [token]
                else:
                    current.append(token)
            if current:
                chunks.append(_join(current))
    return [chunk for chunk in chunks if chunk]

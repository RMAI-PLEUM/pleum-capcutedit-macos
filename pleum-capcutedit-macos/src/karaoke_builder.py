"""Karaoke caption text helpers using the global Thai renderer."""

from __future__ import annotations

from typing import Any

from thai_caption_text_renderer import (
    attach_mai_yamok_tokens, render_thai_caption_tokens,
)


def build_karaoke_caption_text(
    words: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Return display text and indivisible timed lexical tokens."""
    lexical, _stats = attach_mai_yamok_tokens(words)
    return render_thai_caption_tokens(lexical), lexical

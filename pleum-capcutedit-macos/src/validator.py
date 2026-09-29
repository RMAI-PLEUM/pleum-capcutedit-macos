from __future__ import annotations

from typing import Any

from utils import token_count


def validate_cues(
    cues: list[dict[str, Any]],
    target_duration: float,
    max_words: int = 16,
    script_chunks: list[str] | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not cues:
        errors.append("No subtitle cues were generated.")
    allowed = set(script_chunks) if script_chunks is not None else None
    if script_chunks is not None:
        actual = [str(cue.get("text", "")) for cue in cues]
        if actual != script_chunks:
            errors.append(
                "Script-align output does not contain every script chunk exactly once in original order."
            )
    previous_end = 0.0
    for number, cue in enumerate(cues, 1):
        text = str(cue.get("text", ""))
        start, end = float(cue["start"]), float(cue["end"])
        if not text.strip():
            errors.append(f"Cue {number}: empty text.")
        if "\n" in text or "\r" in text:
            errors.append(f"Cue {number}: text contains a line break.")
        count = token_count(text)
        if count > max_words:
            errors.append(f"Cue {number}: {count} words exceeds limit {max_words}.")
        if start < 0:
            errors.append(f"Cue {number}: start is negative.")
        if end <= start:
            errors.append(f"Cue {number}: end must be after start.")
        if number > 1 and start < previous_end - 0.0005:
            errors.append(f"Cue {number}: overlaps the previous cue.")
        if end > target_duration + 0.0005:
            errors.append(f"Cue {number}: ends after target duration.")
        if allowed is not None and text not in allowed:
            errors.append(f"Cue {number}: text is not an original script chunk.")
        previous_end = end
    if cues and float(cues[-1]["end"]) > target_duration + 0.0005:
        errors.append("Final cue ends after target duration.")
    return not errors, errors


def validation_report(valid: bool, errors: list[str], cue_count: int, target: float) -> str:
    lines = [
        f"Status: {'PASS' if valid else 'FAIL'}",
        f"Cue count: {cue_count}",
        f"Target duration: {target:.3f}",
    ]
    if errors:
        lines.extend(["", "Errors:"] + [f"- {error}" for error in errors])
    else:
        lines.extend(["", "All strict validation checks passed."])
    return "\n".join(lines) + "\n"

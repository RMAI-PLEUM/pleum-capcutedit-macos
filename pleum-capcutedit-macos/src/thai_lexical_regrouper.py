"""Reconstruct Thai lexical tokens from Scribe's timed character fragments."""

from __future__ import annotations

import re
import os
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# Keep PyThaiNLP's implicit cache inside this portable installation.  This is
# important on macOS app/sandbox runners where writing directly under $HOME is
# not necessarily allowed, and it also prevents machine-global state leaks.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PYTHAINLP_DATA", str(PROJECT_ROOT / "state/pythainlp-data"))

from pythainlp.tokenize import word_tokenize
from thai_caption_text_renderer import (
    CANONICAL_REASON, MAI_YAMOK, MaiYamokAttachmentError,
    attach_mai_yamok_tokens, display_normalized_thai,
)


THAI_RE = re.compile(r"[\u0E00-\u0E7F]")
PROTECTED_RE = re.compile(
    r"https?://[^\s]+|www\.[^\s]+|[A-Za-z0-9]+(?:[._/@:+#&'-][A-Za-z0-9]+)*"
)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def is_thai_mark(character: str) -> bool:
    return (
        "\u0E00" <= character <= "\u0E7F"
        and unicodedata.category(character) in {"Mn", "Mc", "Me"}
    )


def _segment_run(text: str, keyterms: list[str]) -> list[str]:
    protected = sorted(
        {nfc(term) for term in keyterms if term.strip()},
        key=len,
        reverse=True,
    )
    alternates = [re.escape(term) for term in protected]
    alternates.append(PROTECTED_RE.pattern)
    protected_re = re.compile("|".join(alternates), re.IGNORECASE) if alternates else PROTECTED_RE
    tokens: list[str] = []
    cursor = 0
    for match in protected_re.finditer(text):
        if match.start() > cursor:
            tokens.extend(word_tokenize(text[cursor:match.start()], engine="newmm"))
        tokens.append(match.group())
        cursor = match.end()
    if cursor < len(text):
        tokens.extend(word_tokenize(text[cursor:], engine="newmm"))
    return [nfc(token) for token in tokens if token]


def lexical_segments(canonical_text: str, keyterms: list[str] | None = None) -> list[tuple[str, int, int]]:
    """Return exact canonical spans, excluding whitespace-only tokens."""
    text = nfc(canonical_text)
    output: list[tuple[str, int, int]] = []
    protected_spans: list[tuple[int, int]] = []
    for term in sorted({nfc(term) for term in keyterms or [] if term.strip()}, key=len, reverse=True):
        for match in re.finditer(re.escape(term), text, re.IGNORECASE):
            if not any(match.start() < end and match.end() > start for start, end in protected_spans):
                protected_spans.append((match.start(), match.end()))
    for match in PROTECTED_RE.finditer(text):
        if not any(match.start() < end and match.end() > start for start, end in protected_spans):
            protected_spans.append((match.start(), match.end()))
    protected_spans.sort()

    cursor = 0
    chunks: list[tuple[int, int, bool]] = []
    for start, end in protected_spans:
        if cursor < start:
            chunks.append((cursor, start, False))
        chunks.append((start, end, True))
        cursor = end
    if cursor < len(text):
        chunks.append((cursor, len(text), False))
    for chunk_start, chunk_end, protected in chunks:
        if protected:
            output.append((text[chunk_start:chunk_end], chunk_start, chunk_end))
            continue
        chunk = text[chunk_start:chunk_end]
        for run_match in re.finditer(r"\S+", chunk):
            absolute_run_start = chunk_start + run_match.start()
            run = run_match.group()
            local_cursor = 0
            for token in _segment_run(run, []):
                position = run.find(token, local_cursor)
                if position < 0:
                    raise RuntimeError(f"Thai tokenizer output could not be mapped: {token!r}")
                start = absolute_run_start + position
                end = start + len(token)
                output.append((token, start, end))
                local_cursor = position + len(token)
    return sorted(output, key=lambda item: item[1])


def _reconcile_duplicate_audio_events(
    canonical: str, reconstructed: str, records: list[dict[str, Any]]
) -> tuple[str, int, bool]:
    """Repair only provably duplicated adjacent non-speech annotations.

    Scribe can repeat an ``audio_event`` in ``text`` while emitting one timed
    record.  Character spans must follow the records, so accept that provider
    inconsistency only when every difference is a deletion from canonical,
    equals a bracketed audio-event record, and duplicates an adjacent event.
    Spoken-word insertions, replacements, or deletions remain fatal.
    """
    if canonical == reconstructed:
        return canonical, 0, True
    audio_events = {
        nfc(str(item.get("text") or ""))
        for item in records if item.get("type") == "audio_event"
    }
    repairs = 0
    for tag, canonical_start, canonical_end, _record_start, _record_end in (
        SequenceMatcher(None, canonical, reconstructed, autojunk=False).get_opcodes()
    ):
        if tag == "equal":
            continue
        missing = canonical[canonical_start:canonical_end]
        duplicate_is_adjacent = (
            canonical[:canonical_start].rstrip().endswith(missing)
            or canonical[canonical_end:].lstrip().startswith(missing)
        )
        if not (
            tag == "delete"
            and missing in audio_events
            and missing.startswith("[")
            and missing.endswith("]")
            and duplicate_is_adjacent
        ):
            raise RuntimeError(
                "Raw word/spacing records do not exactly reconstruct the "
                "canonical transcript."
            )
        repairs += 1
    return reconstructed, repairs, False


def regroup_raw_response(
    raw: dict[str, Any], keyterms: list[str] | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_canonical = nfc(str(raw.get("text") or ""))
    records = raw.get("words") or []
    reconstructed = nfc("".join(str(item.get("text") or "") for item in records))
    canonical, duplicate_audio_event_repairs, exact_before_repair = (
        _reconcile_duplicate_audio_events(
            provider_canonical, reconstructed, records
        )
    )

    fragments: list[dict[str, Any]] = []
    # Some STT responses contain a word record with an exactly zero-length
    # timestamp.  It has a reliable character span, but cannot safely become
    # a timed lexical token on its own.  Keep its span so it can be folded into
    # the preceding timed token instead of being mistaken for missing data.
    untimed_fragments: list[dict[str, Any]] = []
    ignored_non_speech_fragments: list[dict[str, Any]] = []
    cursor = 0
    for raw_index, item in enumerate(records):
        text = nfc(str(item.get("text") or ""))
        start_char, end_char = cursor, cursor + len(text)
        cursor = end_char
        record_type = str(item.get("type") or "")
        if record_type == "audio_event" and text:
            ignored_non_speech_fragments.append({
                "raw_index": raw_index,
                "text": text,
                "char_start": start_char,
                "char_end": end_char,
            })
        if record_type == "word" and text:
            try:
                start_time, end_time = float(item["start"]), float(item["end"])
            except (KeyError, TypeError, ValueError):
                continue
            fragment = {
                "raw_index": raw_index,
                "text": text,
                "char_start": start_char,
                "char_end": end_char,
                "start": start_time,
                "end": end_time,
            }
            if end_time > start_time:
                fragments.append(fragment)
            else:
                untimed_fragments.append(fragment)

    lexical: list[dict[str, Any]] = []
    canonical_mai_yamok_attached = 0
    for token, char_start, char_end in lexical_segments(canonical, keyterms):
        overlapping = [
            fragment for fragment in fragments
            if fragment["char_start"] < char_end and fragment["char_end"] > char_start
        ]
        if not overlapping:
            if any(
                item["char_start"] < char_end and item["char_end"] > char_start
                for item in ignored_non_speech_fragments
            ):
                # Scribe includes annotations such as "[เสียงไอ]" in the
                # canonical transcript.  They describe non-speech audio and
                # must not become lexical words or influence silence/take cuts.
                continue
            zero_length_sources = [
                item for item in untimed_fragments
                if item["char_start"] < char_end and item["char_end"] > char_start
            ]
            if lexical and zero_length_sources:
                lexical[-1]["text"] += token
                lexical[-1]["char_end"] = char_end
                lexical[-1]["source_fragment_indices"].extend(
                    int(item["raw_index"]) for item in zero_length_sources
                )
                lexical[-1]["merge_reason"] = "untimed_fragment_attached"
                continue
            # Punctuation may be emitted without useful timing; attach it to the
            # preceding lexical token without inventing a timestamp.
            if token == MAI_YAMOK:
                if not lexical:
                    raise MaiYamokAttachmentError({
                        "text": token,
                        "start": None,
                        "end": None,
                        "source_fragment_indices": [],
                    }, len(lexical))
                lexical[-1]["text"] = (
                    str(lexical[-1]["text"]).rstrip() + MAI_YAMOK
                )
                lexical[-1]["char_end"] = char_end
                lexical[-1]["merge_reason"] = CANONICAL_REASON
                canonical_mai_yamok_attached += 1
                continue
            if lexical and (
                token in {"ๆ", "ฯ"}
                or (not THAI_RE.search(token) and not token[0].isalnum())
            ):
                lexical[-1]["text"] += token
                lexical[-1]["char_end"] = char_end
                lexical[-1]["merge_reason"] = "punctuation_attached"
                continue
            raise RuntimeError(f"No timed fragment overlaps lexical token {token!r}.")
        source_indices = [int(item["raw_index"]) for item in overlapping]
        small_gap_merge = (
            len(overlapping) > 1
            and all(
                float(right["start"]) - float(left["end"]) <= 0.12
                for left, right in zip(overlapping, overlapping[1:])
            )
            and not re.search(r"\s|[.!?。！？ฯ]", token)
            and canonical[char_start:char_end] == token
        )
        lexical.append({
            "text": token,
            "start": round(float(overlapping[0]["start"]), 6),
            "end": round(float(overlapping[-1]["end"]), 6),
            "source_fragment_indices": source_indices,
            "merge_reason": (
                "canonical_small_gap_merge"
                if small_gap_merge else
                "pythainlp_newmm_character_span"
                if len(source_indices) > 1 else "single_fragment"
            ),
            "char_start": char_start,
            "char_end": char_end,
            "separator_before": canonical[
                lexical[-1]["char_end"] if lexical else 0:char_start
            ],
        })

    lexical, mai_yamok_stats = attach_mai_yamok_tokens(lexical)
    mai_yamok_stats["mai_yamok_attached"] += canonical_mai_yamok_attached
    mai_yamok_stats["standalone_mai_yamok_found"] += canonical_mai_yamok_attached

    for index, token in enumerate(lexical):
        if token["start"] >= token["end"]:
            raise RuntimeError(f"Invalid lexical timing at token {index}: {token['text']!r}")
        if index and token["start"] < lexical[index - 1]["start"]:
            raise RuntimeError("Lexical timings are not chronological.")
        if index and lexical[index - 1]["end"] > token["start"] + 0.000001:
            raise RuntimeError(
                "Lexical timings overlap after Thai Mai Yamok attachment: "
                f"previous={lexical[index - 1]['text']!r} "
                f"{lexical[index - 1]['start']:.6f}-"
                f"{lexical[index - 1]['end']:.6f}; "
                f"current={token['text']!r} {token['start']:.6f}-"
                f"{token['end']:.6f}."
            )
        if token["text"] and is_thai_mark(token["text"][0]):
            raise RuntimeError(f"Standalone Thai combining mark: {token['text']!r}")

    analysis = {
        "canonical_transcript": canonical,
        "display_normalized_canonical_transcript": display_normalized_thai(canonical),
        "canonical_character_count": len(canonical),
        "provider_canonical_character_count": len(provider_canonical),
        "raw_record_count": len(records),
        "raw_record_types": {
            kind: sum(1 for item in records if str(item.get("type")) == kind)
            for kind in sorted({str(item.get("type")) for item in records})
        },
        "raw_record_fields": sorted({
            key for item in records if isinstance(item, dict) for key in item
        }),
        "has_full_transcript": bool(canonical),
        "has_word_records": any(item.get("type") == "word" for item in records),
        "has_spacing_records": any(item.get("type") == "spacing" for item in records),
        "has_punctuation_records": any(
            item.get("type") == "punctuation" for item in records
        ),
        "has_character_timing_information": all(
            key in item for item in records for key in ("start", "end")
        ),
        "records_reconstruct_transcript_exactly": exact_before_repair,
        "duplicate_audio_event_repairs": duplicate_audio_event_repairs,
        "regrouped_lexical_token_count": len(lexical),
        **mai_yamok_stats,
        "character_timestamp_rerun_necessary": False,
        "ignored_non_speech_record_count": len(ignored_non_speech_fragments),
    }
    return lexical, analysis

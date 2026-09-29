from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from caption_word_span_mapper import map_caption_word_spans
from capcut_karaoke_style_preset import (
    apply_highlight_range, load_karaoke_preset,
)
from capcut_caption_style_preset import load_caption_style_preset
from karaoke_state_plan_builder import build_karaoke_state_plan
from karaoke_state_plan_validator import validate_karaoke_state_plan


def word(text: str, start: float, end: float, index: int) -> dict:
    return {
        "text": text, "start": start, "end": end,
        "source_fragment_indices": [index],
    }


def mapped_caption(text: str, words: list[dict], end: float = 3.0) -> dict:
    captions, _stats = map_caption_word_spans(
        [{"id": "caption_0001", "text": text, "start": 0.0, "end": end}],
        words,
    )
    return captions[0]


class KaraokeTests(unittest.TestCase):
    def plan(self, caption: dict) -> dict:
        return build_karaoke_state_plan(
            "Apple", "hash", float(caption["end"]),
            "karaoke-yellow", [caption],
        )

    def test_01_three_words(self) -> None:
        cue = mapped_caption("วันนี้ผมมา", [
            word("วันนี้", .2, .7, 1), word("ผม", .75, 1.05, 2),
            word("มา", 1.1, 1.5, 3),
        ])
        report = validate_karaoke_state_plan(self.plan(cue))
        self.assertTrue(report["valid"])
        self.assertEqual(report["highlight_state_count"], 3)

    def test_02_adjacent_words_have_no_zero_normal(self) -> None:
        cue = mapped_caption("วันนี้ผม", [
            word("วันนี้", .2, 1.0, 1), word("ผม", 1.0, 1.5, 2),
        ])
        states = self.plan(cue)["cues"][0]["states"]
        self.assertFalse(any(s["type"] == "normal" and s["start"] == 1.0 for s in states))

    def test_03_silence_creates_normal_state(self) -> None:
        cue = mapped_caption("วันนี้ผม", [
            word("วันนี้", .2, .7, 1), word("ผม", 1.0, 1.5, 2),
        ])
        self.assertTrue(any(
            s["type"] == "normal" and s["start"] == .7 and s["end"] == 1.0
            for s in self.plan(cue)["cues"][0]["states"]
        ))

    def test_04_mai_yamok_is_one_word(self) -> None:
        cue = mapped_caption("สั้นๆ แล้ว", [
            word("สั้น", .2, .5, 1), word("ๆ", .5, .6, 2),
            word("แล้ว", .7, 1.0, 3),
        ])
        self.assertEqual(cue["words"][0]["text"], "สั้นๆ")
        self.assertEqual(len(cue["words"]), 2)

    def test_05_repeated_words_have_distinct_ranges(self) -> None:
        cue = mapped_caption("วันนี้วันนี้", [
            word("วันนี้", .1, .4, 1), word("วันนี้", .5, .8, 2),
        ])
        self.assertNotEqual(
            cue["words"][0]["utf16_start"], cue["words"][1]["utf16_start"]
        )

    def test_06_thai_combining_marks_stay_in_word(self) -> None:
        cue = mapped_caption("เก่ง", [word("เก่ง", .1, .5, 1)])
        self.assertEqual(cue["words"][0]["utf16_length"], 4)

    def test_07_mixed_thai_english(self) -> None:
        cue = mapped_caption("ทำซ้ำๆ Apple", [
            word("ทำซ้ำ", .1, .4, 1), word("ๆ", .4, .45, 2),
            word("Apple", .5, .8, 3),
        ])
        self.assertEqual([w["text"] for w in cue["words"]], ["ทำซ้ำๆ", "Apple"])

    def test_08_number_is_highlightable(self) -> None:
        cue = mapped_caption("ปี 2026", [
            word("ปี", .1, .3, 1), word("2026", .4, .7, 2),
        ])
        self.assertTrue(cue["words"][1]["highlightable"])

    def test_09_punctuation_is_not_highlightable(self) -> None:
        cue = mapped_caption("จริงๆ,", [
            word("จริง", .1, .3, 1), word("ๆ", .3, .4, 2),
            word(",", .4, .41, 3),
        ])
        self.assertFalse(cue["words"][-1]["highlightable"])

    def test_10_large_overlap_rejected(self) -> None:
        cue = mapped_caption("วันนี้ผม", [
            word("วันนี้", .1, .7, 1), word("ผม", .6, .9, 2),
        ])
        with self.assertRaises(RuntimeError):
            self.plan(cue)

    def test_11_small_overlap_midpoint(self) -> None:
        cue = mapped_caption("วันนี้ผม", [
            word("วันนี้", .1, .7, 1), word("ผม", .69, .9, 2),
        ])
        highlights = [
            s for s in self.plan(cue)["cues"][0]["states"]
            if s["type"] == "highlight"
        ]
        self.assertEqual(highlights[0]["end"], highlights[1]["start"])

    def test_12_utf16_thai_range(self) -> None:
        cue = mapped_caption("หนึ่งสอง", [
            word("หนึ่ง", .1, .3, 1), word("สอง", .4, .7, 2),
        ])
        self.assertEqual(cue["words"][1]["utf16_start"], 5)
        self.assertEqual(cue["words"][1]["utf16_length"], 3)

    def test_13_eight_portrait_words(self) -> None:
        words = [word(f"คำ{i}", i * .1, i * .1 + .08, i) for i in range(8)]
        cue = mapped_caption("".join(w["text"] for w in words), words)
        self.assertEqual(len(cue["words"]), 8)

    def test_14_sixteen_landscape_words(self) -> None:
        words = [word(f"คำ{i}", i * .1, i * .1 + .08, i) for i in range(16)]
        cue = mapped_caption("".join(w["text"] for w in words), words)
        self.assertEqual(len(cue["words"]), 16)

    def test_15_state_ids_are_unique_for_regeneration(self) -> None:
        cue = mapped_caption("หนึ่งสอง", [
            word("หนึ่ง", .1, .3, 1), word("สอง", .4, .7, 2),
        ])
        ids = [s["state_id"] for s in self.plan(cue)["cues"][0]["states"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_16_plan_builder_does_not_mutate_caption(self) -> None:
        cue = mapped_caption("หนึ่ง", [word("หนึ่ง", .1, .3, 1)])
        original = deepcopy(cue)
        self.plan(cue)
        self.assertEqual(cue, original)

    def test_17_continuous_coverage_preserves_timing(self) -> None:
        cue = mapped_caption("หนึ่ง", [word("หนึ่ง", .1, .3, 1)])
        states = self.plan(cue)["cues"][0]["states"]
        self.assertEqual(states[0]["start"], cue["start"])
        self.assertEqual(states[-1]["end"], cue["end"])

    def test_18_highlight_color_and_capcut_range(self) -> None:
        preset = load_karaoke_preset("karaoke-yellow")
        base = load_caption_style_preset("system-default")
        content = json.loads(base["material_template"]["content"])
        content["text"] = "หนึ่ง สอง สาม"
        rendered = apply_highlight_range(content, 6, 3, preset)
        self.assertEqual(rendered["styles"][1]["range"], [6, 10])
        self.assertEqual(
            rendered["styles"][1]["fill"]["content"]["solid"]["color"],
            preset["highlight"]["capcut_color_value"],
        )

    def test_19_highlight_changes_only_fill_and_range(self) -> None:
        preset = load_karaoke_preset("karaoke-yellow")
        base = load_caption_style_preset("system-default")
        content = json.loads(base["material_template"]["content"])
        content["text"] = "one two"
        rendered = apply_highlight_range(content, 4, 3, preset)
        normal = deepcopy(rendered["styles"][0])
        highlight = deepcopy(rendered["styles"][1])
        normal.pop("range", None)
        highlight.pop("range", None)
        normal_fill = normal.pop("fill")
        highlight_fill = highlight.pop("fill")
        self.assertEqual(highlight, normal)
        self.assertNotEqual(highlight_fill, normal_fill)
        self.assertEqual(highlight["size"], 8)


if __name__ == "__main__":
    unittest.main()

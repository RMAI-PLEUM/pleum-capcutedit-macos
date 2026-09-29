from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from caption_plan_builder import build_regrouped_caption_plan
from thai_caption_plan_normalizer import normalize_thai_caption_plan
from thai_caption_text_renderer import (
    MaiYamokAttachmentError, attach_mai_yamok_tokens,
    display_normalized_thai, normalize_thai_caption_text,
    render_thai_caption_tokens, thai_lexical_word_count,
)
from thai_caption_validator import validate_thai_caption_plan


def word(text: str, index: int) -> dict:
    return {
        "text": text,
        "start": index * 0.2,
        "end": index * 0.2 + 0.15,
        "source_fragment_indices": [index],
        "char_start": index,
        "char_end": index + len(text),
    }


class ThaiMaiYamokTests(unittest.TestCase):
    def test_01_separate_token_attaches_and_merges_timing(self) -> None:
        tokens, stats = attach_mai_yamok_tokens([
            word("สั้น", 0), word("ๆ", 1),
        ])
        self.assertEqual(tokens[0]["text"], "สั้นๆ")
        self.assertEqual(tokens[0]["start"], 0.0)
        self.assertEqual(tokens[0]["end"], 0.35)
        self.assertEqual(tokens[0]["source_fragment_indices"], [0, 1])
        self.assertEqual(
            tokens[0]["merge_reason"],
            "THAI_MAI_YAMOK_ATTACHED_TO_PREVIOUS_TOKEN",
        )
        self.assertEqual(stats["mai_yamok_attached"], 1)

    def test_02_boundary_is_repaired(self) -> None:
        plan = {
            "version": 1,
            "source": {"duration": 3.0},
            "captions": [
                {"id": "c1", "start": 0.0, "end": 1.0,
                 "text": "เรียนรู้มาในช่วงเวลาสั้น"},
                {"id": "c2", "start": 1.0, "end": 2.0,
                 "text": "ๆแล้วทำให้ผมรู้สึก"},
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "boundary.caption_plan.json"
            path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            report, output, _preview, _log = normalize_thai_caption_plan(path)
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(report["valid"])
        self.assertEqual(report["caption_boundaries_repaired"], 1)
        self.assertEqual(
            [item["text"] for item in result["captions"]],
            ["เรียนรู้มาในช่วงเวลาสั้นๆ", "แล้วทำให้ผมรู้สึก"],
        )

    def test_03_missing_following_space(self) -> None:
        self.assertEqual(
            normalize_thai_caption_text("สิ่งต่างๆมากมาย")[0],
            "สิ่งต่างๆ มากมาย",
        )

    def test_04_multiple_following_spaces(self) -> None:
        value, stats = normalize_thai_caption_text("สิ่งต่างๆ   มากมาย")
        self.assertEqual(value, "สิ่งต่างๆ มากมาย")
        self.assertEqual(stats["multiple_spaces_normalized_after_mai_yamok"], 1)

    def test_05_leading_whitespace(self) -> None:
        self.assertEqual(normalize_thai_caption_text("สั้น ๆ")[0], "สั้นๆ")

    def test_06_closing_comma(self) -> None:
        self.assertEqual(normalize_thai_caption_text("จริงๆ,")[0], "จริงๆ,")
        self.assertEqual(render_thai_caption_tokens(["จริงๆ", ","]), "จริงๆ,")

    def test_07_exclamation(self) -> None:
        self.assertEqual(normalize_thai_caption_text("มากๆ!")[0], "มากๆ!")

    def test_08_word_count(self) -> None:
        self.assertEqual(
            thai_lexical_word_count([word("สั้น", 0), word("ๆ", 1)]), 1
        )

    def _boundary_plan(self, limit: int) -> dict:
        tokens = [word(f"คำ{index}", index) for index in range(limit - 1)]
        tokens.extend([word("สั้น", limit - 1), word("ๆ", limit)])
        tokens.append(word("ถัดไป", limit + 1))
        return build_regrouped_caption_plan(
            "memory", 20.0, "", tokens,
            config={
                "max_words_per_cue": limit,
                "max_duration": 99.0,
                "silence_boundary": 99.0,
            },
        )

    def test_09_portrait_eight_word_boundary(self) -> None:
        plan = self._boundary_plan(8)
        self.assertTrue(plan["captions"][0]["text"].endswith("สั้นๆ"))
        self.assertFalse(plan["captions"][1]["text"].startswith("ๆ"))

    def test_10_landscape_sixteen_word_boundary(self) -> None:
        plan = self._boundary_plan(16)
        self.assertTrue(plan["captions"][0]["text"].endswith("สั้นๆ"))
        self.assertFalse(plan["captions"][1]["text"].startswith("ๆ"))

    def test_11_invalid_caption_start_fails(self) -> None:
        lexical = [word("แล้ว", 0)]
        plan = {
            "captions": [{"text": "ๆแล้ว", "start": 0.0, "end": 1.0}]
        }
        report = validate_thai_caption_plan(plan, "ๆแล้ว", lexical)
        self.assertFalse(report["valid"])
        self.assertIn("THAI_MAI_YAMOK_STARTS_CAPTION", report["reason_codes"])

    def test_12_no_preceding_token_fails_safely(self) -> None:
        with self.assertRaises(MaiYamokAttachmentError):
            attach_mai_yamok_tokens([word("ๆ", 0)])

    def test_13_thai_english_rendering_and_count(self) -> None:
        tokens = [word("ทำซ้ำๆ", 0), word("Apple", 1), word("Test", 2)]
        self.assertEqual(
            render_thai_caption_tokens(tokens), "ทำซ้ำๆ Apple Test"
        )
        self.assertEqual(thai_lexical_word_count(tokens), 3)

    def test_14_canonical_equivalence(self) -> None:
        self.assertEqual(
            display_normalized_thai("ต่างๆมากมาย"),
            display_normalized_thai("ต่างๆ มากมาย"),
        )

    def test_renderer_required_examples(self) -> None:
        self.assertEqual(
            render_thai_caption_tokens(
                ["แล้วก็", "สิ่ง", "ต่างๆ", "มากมาย", "นะ"]
            ),
            "แล้วก็สิ่งต่างๆ มากมายนะ",
        )
        self.assertEqual(
            render_thai_caption_tokens(
                ["เรียนรู้", "มา", "ใน", "ช่วงเวลา", "สั้นๆ", "แล้ว", "ทำให้"]
            ),
            "เรียนรู้มาในช่วงเวลาสั้นๆ แล้วทำให้",
        )


if __name__ == "__main__":
    unittest.main()

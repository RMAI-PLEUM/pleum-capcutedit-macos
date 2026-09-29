from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from caption_plan_builder import build_regrouped_caption_plan
from caption_plan_validator import validate_caption_plan
from thai_caption_validator import validate_thai_caption_plan


class OneWordCaptionPlanTests(unittest.TestCase):
    def test_fast_words_keep_their_real_intervals_without_dropping_tokens(self) -> None:
        lexical = [
            {"text": "หนึ่ง", "start": 0.00, "end": 0.12},
            {"text": "สอง", "start": 0.12, "end": 0.25},
            {"text": "สาม", "start": 0.25, "end": 0.39},
            {"text": "สี่", "start": 0.39, "end": 0.54},
        ]
        canonical = "หนึ่งสองสามสี่"

        plan = build_regrouped_caption_plan(
            "fixture.mp4",
            0.54,
            canonical,
            lexical,
            config={"max_words_per_cue": 1},
        )

        self.assertEqual([item["text"] for item in plan["captions"]], [
            "หนึ่ง", "สอง", "สาม", "สี่",
        ])
        self.assertEqual(
            [(item["start"], item["end"]) for item in plan["captions"]],
            [(0.0, 0.12), (0.12, 0.25), (0.25, 0.39), (0.39, 0.54)],
        )
        self.assertTrue(
            validate_caption_plan(plan, max_words=1, lexical_words=lexical)["valid"]
        )
        self.assertTrue(
            validate_thai_caption_plan(plan, canonical, lexical, max_words=1)["valid"]
        )


if __name__ == "__main__":
    unittest.main()

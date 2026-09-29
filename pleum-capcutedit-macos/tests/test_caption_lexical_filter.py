from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from caption_lexical_filter import filter_caption_lexical_words


class CaptionLexicalFilterTests(unittest.TestCase):
    def test_configured_fillers_are_removed_as_exact_words_and_phrases(self) -> None:
        words = [
            {"text": "เริ่ม", "start": 0.0, "end": 0.2},
            {"text": "อ่ะ", "start": 0.2, "end": 0.3},
            {"text": "นะ", "start": 0.3, "end": 0.4},
            {"text": "ครับ", "start": 0.4, "end": 0.5},
            {"text": "ต่อ", "start": 0.5, "end": 0.7},
            {"text": "ครับ", "start": 0.7, "end": 0.8},
        ]

        filtered, report = filter_caption_lexical_words(
            words, "อ่ะ,ครับ,นะครับ"
        )

        self.assertEqual([item["text"] for item in filtered], ["เริ่ม", "ต่อ"])
        self.assertEqual(report["removed_token_count"], 4)
        self.assertEqual(report["phrase_match_counts"]["นะ ครับ"], 1)
        self.assertEqual(report["phrase_match_counts"]["ครับ"], 1)
        self.assertFalse(report["audio_modified"])

    def test_filter_does_not_remove_substrings_or_standalone_na(self) -> None:
        words = [
            {"text": "นะ", "start": 0.0, "end": 0.1},
            {"text": "ครับผม", "start": 0.1, "end": 0.3},
            {"text": "อะไหล่", "start": 0.3, "end": 0.5},
        ]

        filtered, report = filter_caption_lexical_words(
            words, "อ่ะ,ครับ,นะครับ"
        )

        self.assertEqual(filtered, words)
        self.assertEqual(report["removed_token_count"], 0)


if __name__ == "__main__":
    unittest.main()

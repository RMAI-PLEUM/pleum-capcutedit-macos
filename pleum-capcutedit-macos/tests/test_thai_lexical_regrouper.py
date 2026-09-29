from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from thai_lexical_regrouper import regroup_raw_response


class ThaiLexicalRegrouperTests(unittest.TestCase):
    def test_zero_length_stt_fragment_attaches_to_previous_timed_token(self) -> None:
        raw = {
            "text": "\u0e44\u0e1b\u0e1b\u0e35",
            "words": [
                {"text": "\u0e44\u0e1b", "type": "word", "start": 0.0, "end": 0.2},
                {"text": "\u0e1b\u0e35", "type": "word", "start": 0.2, "end": 0.2},
            ],
        }

        lexical, _analysis = regroup_raw_response(raw)

        self.assertEqual(len(lexical), 1)
        self.assertEqual(lexical[0]["text"], "\u0e44\u0e1b\u0e1b\u0e35")
        self.assertEqual(lexical[0]["source_fragment_indices"], [0, 1])
        self.assertEqual(lexical[0]["merge_reason"], "untimed_fragment_attached")

    def test_audio_event_annotation_is_not_a_lexical_word(self) -> None:
        raw = {
            "text": "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35 [\u0e40\u0e2a\u0e35\u0e22\u0e07\u0e44\u0e2d] \u0e15\u0e48\u0e2d",
            "words": [
                {"text": "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35", "type": "word", "start": 0.0, "end": 0.4},
                {"text": " ", "type": "spacing", "start": 0.4, "end": 0.4},
                {"text": "[\u0e40\u0e2a\u0e35\u0e22\u0e07\u0e44\u0e2d]", "type": "audio_event", "start": 0.5, "end": 0.8},
                {"text": " ", "type": "spacing", "start": 0.8, "end": 0.8},
                {"text": "\u0e15\u0e48\u0e2d", "type": "word", "start": 0.9, "end": 1.2},
            ],
        }

        lexical, analysis = regroup_raw_response(raw)

        self.assertEqual([item["text"] for item in lexical], ["\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35", "\u0e15\u0e48\u0e2d"])
        self.assertEqual(analysis["ignored_non_speech_record_count"], 1)

    def test_duplicate_provider_audio_event_is_reconciled(self) -> None:
        event = "[\u0e40\u0e2a\u0e35\u0e22\u0e07\u0e44\u0e2d]"
        raw = {
            "text": f"\u0e01\u0e48\u0e2d\u0e19 {event} {event} \u0e2b\u0e25\u0e31\u0e07",
            "words": [
                {"text": "\u0e01\u0e48\u0e2d\u0e19", "type": "word", "start": 0.0, "end": 0.3},
                {"text": " ", "type": "spacing", "start": 0.3, "end": 0.3},
                {"text": event, "type": "audio_event", "start": 0.4, "end": 0.7},
                {"text": "  ", "type": "spacing", "start": 0.7, "end": 0.7},
                {"text": "\u0e2b\u0e25\u0e31\u0e07", "type": "word", "start": 0.8, "end": 1.1},
            ],
        }

        lexical, analysis = regroup_raw_response(raw)

        self.assertEqual([item["text"] for item in lexical], ["\u0e01\u0e48\u0e2d\u0e19", "\u0e2b\u0e25\u0e31\u0e07"])
        self.assertEqual(analysis["duplicate_audio_event_repairs"], 1)
        self.assertFalse(analysis["records_reconstruct_transcript_exactly"])

    def test_missing_spoken_text_is_not_reconciled(self) -> None:
        raw = {
            "text": "\u0e04\u0e33\u0e1e\u0e39\u0e14\u0e2b\u0e32\u0e22",
            "words": [
                {"text": "\u0e04\u0e33\u0e1e\u0e39\u0e14", "type": "word", "start": 0.0, "end": 0.5},
            ],
        }

        with self.assertRaisesRegex(RuntimeError, "do not exactly reconstruct"):
            regroup_raw_response(raw)


if __name__ == "__main__":
    unittest.main()

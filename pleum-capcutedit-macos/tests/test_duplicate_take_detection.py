from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from duplicate_take_detector import detect_duplicate_takes
from take_plan_builder import build_take_plan
from take_restart_detector import find_phrases, repeated_fragment
from take_utterance_builder import build_utterances


CONFIG = json.loads(
    (ROOT / "presets/take_detection/default.json").read_text(encoding="utf-8")
)


def utterance(
    uid, tokens, start, markers=None, speaker=None, confidence=0.95,
    source="seg1", cut_end=False,
):
    end = start + max(1.0, len(tokens) * 0.3)
    return {
        "utterance_id": uid,
        "start": start,
        "end": end,
        "duration": end - start,
        "text": "".join(tokens),
        "normalized_tokens": tokens,
        "meaningful_tokens": [
            token for token in tokens if token not in {"เอ่อ", "อ่า"}
        ],
        "source_segment_ids": [source],
        "average_word_confidence": confidence,
        "internal_silence_seconds": 0.0,
        "restart_markers": markers or [],
        "filler_count": sum(token in {"เอ่อ", "อ่า"} for token in tokens),
        "is_cut_off_start": False,
        "is_cut_off_end": cut_end,
        "word_indices": [],
        "speaker": speaker,
    }


class DuplicateTakeTests(unittest.TestCase):
    def detect(self, items):
        return detect_duplicate_takes(items, dict(CONFIG))

    def test_01_thai_explicit_restart(self):
        first = utterance("utt_0001", ["วันนี้", "ผม", "จะ", "เอ่อ", "เอาใหม่"], 0, ["เอาใหม่"])
        second = utterance("utt_0002", ["วันนี้", "ผม", "จะ", "อธิบาย", "การบริหารเวลา"], 3)
        _, groups = self.detect([first, second])
        self.assertTrue(any(g["category"] == "explicit_restart" for g in groups))
        self.assertIn("utt_0001", groups[0]["recommended_drop_utterance_ids"])

    def test_02_thai_prefix_restart(self):
        first = utterance("utt_0001", ["การลงทุน", "ใน", "อสังหา"], 0, cut_end=True)
        second = utterance("utt_0002", ["การลงทุน", "ใน", "อสังหา", "เป็น", "วิธี", "สร้างรายได้"], 3)
        _, groups = self.detect([first, second])
        self.assertEqual(groups[0]["category"], "prefix_restart")

    def test_03_near_duplicate_complete(self):
        first = utterance("utt_0001", ["วันนี้", "เรา", "จะ", "คุย", "เรื่อง", "การบริหารเงิน"], 0)
        second = utterance("utt_0002", ["วันนี้", "เรา", "จะ", "คุย", "เรื่อง", "การบริหารเงิน"], 5)
        _, groups = self.detect([first, second])
        self.assertEqual(groups[0]["category"], "complete_duplicate")

    def test_04_corrected_numeric_information(self):
        first = utterance("utt_0001", ["ราคา", "อยู่", "ที่", "500000"], 0)
        second = utterance("utt_0002", ["ราคา", "อยู่", "ที่", "600000"], 4, ["ไม่ใช่"])
        _, groups = self.detect([first, second])
        self.assertEqual(groups[0]["category"], "correction_take")
        self.assertGreaterEqual(groups[0]["confidence"], 0.9)

    def test_05_accidental_repeated_word(self):
        item = utterance("utt_0001", ["เรา", "จะ", "เรา", "จะ", "เริ่ม"], 0)
        candidates, groups = self.detect([item])
        self.assertEqual(candidates[0]["category"], "accidental_repeated_fragment")
        self.assertFalse(groups)

    def test_06_deliberate_emphasis_not_deleted(self):
        result = repeated_fragment(["ดี", "ดี", "ดี"])
        self.assertTrue(result["deliberate_emphasis_possible"])
        candidates, groups = self.detect([
            utterance("utt_0001", ["ดี", "ดี", "ดี"], 0)
        ])
        self.assertFalse(candidates)
        self.assertFalse(groups)

    def test_07_different_speakers_are_not_paired(self):
        text = ["วันนี้", "เรา", "คุย", "เรื่อง", "เงิน"]
        _, groups = self.detect([
            utterance("utt_0001", text, 0, speaker="A"),
            utterance("utt_0002", text, 4, speaker="B"),
        ])
        self.assertFalse(groups)

    def test_08_low_confidence_has_no_drop(self):
        text = ["วันนี้", "เรา", "คุย", "เรื่อง", "เงิน"]
        _, groups = self.detect([
            utterance("utt_0001", text, 0, confidence=0.2),
            utterance("utt_0002", text, 4, confidence=0.2),
        ])
        self.assertTrue(groups)
        self.assertFalse(groups[0]["recommended_drop_utterance_ids"])

    def test_09_source_boundary_is_recorded(self):
        words = [
            {"text": "การลงทุน", "start": 0.0, "end": 0.4, "confidence": .9},
            {"text": "ใน", "start": 0.4, "end": 0.6, "confidence": .9},
            {"text": "อสังหา", "start": 0.6, "end": 1.0, "confidence": .9},
            {"text": "การลงทุน", "start": 2.0, "end": 2.4, "confidence": .9},
            {"text": "ใน", "start": 2.4, "end": 2.6, "confidence": .9},
            {"text": "อสังหา", "start": 2.6, "end": 3.0, "confidence": .9},
            {"text": "สร้างรายได้", "start": 3.0, "end": 3.5, "confidence": .9},
        ]
        manifest = {"audible_segments": [
            {"segment_id": "seg1", "target_timerange": {"start": 0, "end": 1}},
            {"segment_id": "seg2", "target_timerange": {"start": 2, "end": 4}},
        ]}
        built = build_utterances(words, manifest, [], [], CONFIG)
        self.assertEqual(built[0]["source_segment_ids"], ["seg1"])
        self.assertEqual(built[1]["source_segment_ids"], ["seg2"])

    def test_10_different_important_facts_not_deleted(self):
        first = utterance("utt_0001", ["ราคา", "อยู่", "ที่", "500000"], 0)
        second = utterance("utt_0002", ["ราคา", "อยู่", "ที่", "600000"], 4)
        _, groups = self.detect([first, second])
        self.assertTrue(groups)
        self.assertFalse(groups[0]["recommended_drop_utterance_ids"])
        self.assertIn("DIFFERENT_IMPORTANT_FACTS", groups[0]["reason_codes"])

    def test_11_restart_marker_does_not_pair_unrelated_followup(self):
        first = utterance(
            "utt_0001", ["\u0e1e\u0e39\u0e14", "\u0e1c\u0e34\u0e14"], 0,
            ["\u0e1e\u0e39\u0e14\u0e1c\u0e34\u0e14"],
        )
        second = utterance(
            "utt_0002",
            ["\u0e17\u0e38\u0e19", "\u0e1b\u0e23\u0e30\u0e01\u0e31\u0e19", "\u0e04\u0e37\u0e2d", "\u0e27\u0e07\u0e40\u0e07\u0e34\u0e19"],
            3,
        )
        _candidates, groups = self.detect([first, second])
        self.assertFalse(groups)

    def test_12_marker_matching_requires_complete_tokens(self):
        self.assertFalse(find_phrases(
            ["\u0e40\u0e02\u0e49\u0e32\u0e43\u0e08\u0e1c\u0e34\u0e14"],
            ["\u0e1c\u0e34\u0e14"],
        ))
        self.assertTrue(find_phrases(
            ["\u0e1e\u0e39\u0e14", "\u0e1c\u0e34\u0e14"],
            ["\u0e1e\u0e39\u0e14\u0e1c\u0e34\u0e14"],
        ))

    def test_13_restart_marker_with_weak_generic_overlap_is_not_duplicate(self):
        first = utterance(
            "utt_0001",
            ["คำถาม", "จริงๆ", "ที่", "ผม", "อยาก", "ถาม", "คือ", "ไม่ใช่"],
            0,
            ["จริงๆ"],
        )
        second = utterance(
            "utt_0002",
            ["แต่", "เรา", "ลอง", "คิด", "กลับกัน", "ถ้า", "ไม่มี", "ประกัน"],
            4,
        )
        _candidates, groups = self.detect([first, second])
        self.assertFalse(groups)

    def test_14_internal_restart_preserves_single_lead_word(self):
        tokens = [
            "เกริ่น",
            "วันนี้", "ผม", "จะ", "พูด", "เรื่อง", "เงิน",
            "วันนี้", "ผม", "จะ", "พูด", "เรื่อง", "เงิน",
        ]
        words = [
            {
                "text": token,
                "start": index * 0.1,
                "end": (index + 1) * 0.1,
                "confidence": 0.9,
            }
            for index, token in enumerate(tokens)
        ]
        manifest = {"audible_segments": [{
            "segment_id": "seg1",
            "target_timerange": {"start": 0, "end": 2},
        }]}
        built = build_utterances(words, manifest, [], [], CONFIG)
        actual_indices = [
            index for item in built for index in item["word_indices"]
        ]
        self.assertEqual(sorted(actual_indices), list(range(len(words))))
        self.assertEqual(len(actual_indices), len(set(actual_indices)))
        self.assertEqual(built[0]["text"], "เกริ่น")


if __name__ == "__main__":
    unittest.main()

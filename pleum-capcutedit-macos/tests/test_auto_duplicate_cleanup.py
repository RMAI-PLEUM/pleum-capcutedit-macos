from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from auto_duplicate_cleanup import (
    apply_auto_cleanup_transaction, build_auto_cleanup_plan,
    transform_multiple_cuts,
)
from capcut_live_project_reader import LiveProject
from capcut_project_locator import CapCutProject
from take_restart_detector import repeated_fragment


CONFIG = json.loads(
    (ROOT / "presets/take_detection/default.json").read_text(encoding="utf-8")
)


def utt(uid, start, end, text=None, source="seg1", speaker=None):
    return {
        "utterance_id": uid, "start": start, "end": end,
        "duration": end - start, "text": text or uid,
        "source_segment_ids": [source], "speaker": speaker,
    }


def group(category="explicit_restart", keep="u2", drop="u1", keep_score=90, drop_score=50,
          reasons=None, gid="g1", confidence=.95):
    return {
        "group_id": gid, "category": category, "confidence": confidence,
        "recommended_keep_utterance_id": keep,
        "reason_codes": reasons or ["EARLIER_TAKE_HAS_RESTART_MARKER"],
        "takes": [
            {"utterance": {"utterance_id": drop}, "quality_score": {"total_score": drop_score}},
            {"utterance": {"utterance_id": keep}, "quality_score": {"total_score": keep_score}},
        ],
    }


def video_draft(duration=20_000_000, media=""):
    return {
        "duration": duration,
        "tracks": [{"id": "tr1", "type": "video", "flag": 0, "attribute": 0, "segments": [{
            "id": "s1", "material_id": "m1", "source_timerange": {"start": 0, "duration": duration},
            "target_timerange": {"start": 0, "duration": duration},
            "render_timerange": {"start": 0, "duration": 0}, "speed": 1.0, "reverse": False,
        }]}],
        "materials": {"videos": [{"id": "m1", "path": media, "has_audio": True}]},
    }


class AutoCleanupTests(unittest.TestCase):
    def plan(self, groups, utterances):
        return build_auto_cleanup_plan(
            "Apple", "hash", groups, utterances, [], CONFIG,
            ["เอ่อ"], ["เอาใหม่"],
        )

    def test_01_explicit_restart_auto_cut(self):
        plan = self.plan([group()], [utt("u1", 1, 3), utt("u2", 3.2, 6)])
        self.assertEqual(len(plan["cut_ranges"]), 1)

    def test_02_incomplete_prefix_auto_cut(self):
        g = group("prefix_restart", reasons=["LATER_TAKE_COMPLETES_PREFIX"])
        self.assertEqual(len(self.plan([g], [utt("u1", 1, 3), utt("u2", 3, 7)])["applied_groups"]), 1)

    def test_03_complete_repeat_auto_cut(self):
        g = group("complete_duplicate", reasons=["NEAR_DUPLICATE_COMPLETE_TAKE"])
        self.assertEqual(len(self.plan([g], [utt("u1", 1, 3), utt("u2", 4, 6)])["cut_ranges"]), 1)

    def test_04_earlier_better_is_kept(self):
        g = group("complete_duplicate", keep="u1", drop="u2", keep_score=95, drop_score=70,
                  reasons=["NEAR_DUPLICATE_COMPLETE_TAKE"])
        plan = self.plan([g], [utt("u1", 1, 3), utt("u2", 4, 6)])
        self.assertEqual(plan["applied_groups"][0]["kept_utterance_id"], "u1")
        self.assertEqual(plan["applied_groups"][0]["removed_utterance_ids"], ["u2"])

    def test_05_later_better_is_kept(self):
        plan = self.plan([group()], [utt("u1", 1, 3), utt("u2", 4, 6)])
        self.assertEqual(plan["applied_groups"][0]["kept_utterance_id"], "u2")

    def test_06_natural_thai_repetition_remains(self):
        self.assertIsNone(repeated_fragment(["มาก", "ๆ"]))
        self.assertFalse(self.plan([], [utt("u1", 1, 2)])["cut_ranges"])

    def test_07_deliberate_emphasis_remains(self):
        self.assertTrue(repeated_fragment(["ดี", "ดี", "ดี"])["deliberate_emphasis_possible"])

    def test_08_different_numbers_skip_unless_correction(self):
        g = group("similar_different_facts", reasons=["DIFFERENT_IMPORTANT_FACTS"])
        plan = self.plan([g], [utt("u1", 1, 3), utt("u2", 4, 6)])
        self.assertFalse(plan["cut_ranges"])
        correction = group("correction_take", reasons=["LATER_TAKE_CORRECTS_INFORMATION"])
        self.assertTrue(self.plan([correction], [utt("u1", 1, 3), utt("u2", 4, 6)])["cut_ranges"])

    def test_09_multiple_cuts_use_descending_ripple(self):
        modified, changes = transform_multiple_cuts(video_draft(), [
            {"start": 2.0, "end": 4.0}, {"start": 10.0, "end": 13.0},
        ])
        self.assertEqual(changes["total_removed"], 5_000_000)
        self.assertEqual(modified["duration"], 15_000_000)
        self.assertEqual(changes["cuts_descending"][0]["cut_start"], 10_000_000)

    def test_10_one_unsafe_one_safe(self):
        safe = group(gid="safe")
        unsafe = group(gid="unsafe", reasons=["DIFFERENT_IMPORTANT_FACTS"])
        plan = self.plan([safe, unsafe], [utt("u1", 1, 3), utt("u2", 4, 6)])
        self.assertEqual(len(plan["applied_groups"]), 1)
        self.assertEqual(len(plan["skipped_groups"]), 1)

    def test_11_overlapping_groups_merge(self):
        first = group(gid="g1")
        second = group(keep="u4", drop="u3", gid="g2")
        plan = self.plan(
            [first, second],
            [utt("u1", 1, 3), utt("u2", 4, 6), utt("u3", 2.8, 4), utt("u4", 7, 9)],
        )
        self.assertEqual(len(plan["cut_ranges"]), 1)
        self.assertEqual(plan["cut_ranges"][0]["group_ids"], ["g1", "g2"])

    def test_12_multi_file_failure_rolls_back(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            folder = Path(tmp); media = folder / "m.wav"; media.write_bytes(b"x")
            data = video_draft(media=str(media))
            first = folder / "draft_content.json"; mirror = folder / "T"; mirror.mkdir()
            second = mirror / "draft_content.json"; metadata = folder / "draft_meta_info.json"
            payload = json.dumps(data).encode(); first.write_bytes(payload); second.write_bytes(payload)
            metadata.write_text(json.dumps({"draft_name": "Apple", "tm_duration": data["duration"]}), encoding="utf-8")
            project = CapCutProject("Apple", folder, "id", 0, metadata)
            live = LiveProject(project, {}, [first, second], [data, data])
            plan = {"timeline_hash": "h", "cut_ranges": [{"start": 2.0, "end": 4.0}]}
            originals = {p: p.read_bytes() for p in (first, second, metadata)}
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                apply_auto_cleanup_transaction(live, plan, "h", False, 2)
            self.assertEqual(originals, {p: p.read_bytes() for p in originals})

    def test_13_overlapping_kept_take_is_skipped(self):
        plan = self.plan([group()], [utt("u1", 2.9, 4.0), utt("u2", 3.0, 6.0)])
        self.assertFalse(plan["cut_ranges"])
        self.assertEqual(
            plan["skipped_groups"][0]["skipped_reasons"],
            ["DROP_RANGE_OVERLAPS_KEPT_TAKE"],
        )

    def test_14_medium_confidence_is_not_auto_cut(self):
        plan = self.plan(
            [group(confidence=.85)],
            [utt("u1", 1, 3), utt("u2", 4, 6)],
        )
        self.assertFalse(plan["cut_ranges"])
        self.assertIn(
            "CONFIDENCE_BELOW_AUTO_THRESHOLD",
            plan["skipped_groups"][0]["skipped_reasons"],
        )


if __name__ == "__main__":
    unittest.main()

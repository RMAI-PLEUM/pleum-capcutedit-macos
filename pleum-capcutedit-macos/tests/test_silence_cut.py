from __future__ import annotations

import unittest

from silence_candidate_builder import build_silence_candidates
from silence_cut_validator import validate_silence_plan
from silence_cut_workflow import retime_raw_transcript
from silence_ripple_transformer import (
    normalize_micro_fragment_cuts, transform_silence_cuts,
)
from timeline_time_mapper import build_time_map, map_time, retime_words


PRESET = {
    "minimum_word_gap_seconds": .55,
    "minimum_detected_silence_seconds": .40,
    "keep_after_previous_word_seconds": .10,
    "keep_before_next_word_seconds": .08,
    "minimum_remaining_gap_seconds": .18,
    "minimum_cut_duration_seconds": .20,
}
TARGET_PRESET = {
    **PRESET,
    "target_remaining_gap_seconds": 1.0,
    "target_remaining_gap_tolerance_seconds": .05,
    "preferred_keep_after_previous_word_seconds": .45,
    "preferred_keep_before_next_word_seconds": .55,
    "minimum_cut_duration_seconds": .15,
}
TIGHT_PRESET = {
    **PRESET,
    "target_remaining_gap_seconds": .10,
    "target_remaining_gap_tolerance_seconds": .02,
    "preferred_keep_after_previous_word_seconds": .05,
    "preferred_keep_before_next_word_seconds": .05,
    "minimum_cut_duration_seconds": .04,
}


def word(text, start, end):
    return {"text": text, "start": start, "end": end}


class SilenceCutTests(unittest.TestCase):
    def candidates(self, words, regions):
        return build_silence_candidates(words, regions, PRESET)

    def test_01_one_second_internal_silence(self):
        valid, _ = self.candidates(
            [word("a", 0, 1), word("b", 2, 3)],
            [{"start": 1, "end": 2, "average_dbfs": -50}],
        )
        self.assertEqual(len(valid), 1)

    def test_02_short_pause_is_ignored(self):
        valid, skipped = self.candidates(
            [word("a", 0, 1), word("b", 1.3, 2)], [])
        self.assertEqual((valid, skipped), ([], []))

    def test_03_short_breath_region_is_rejected(self):
        valid, skipped = self.candidates(
            [word("a", 0, 1), word("b", 2, 3)],
            [{"start": 1.2, "end": 1.4, "average_dbfs": -45}],
        )
        self.assertFalse(valid)
        self.assertTrue(skipped)

    def test_04_next_word_handle_is_preserved(self):
        valid, _ = self.candidates(
            [word("a", 0, 1), word("b", 2, 3)],
            [{"start": 1, "end": 2, "average_dbfs": -50}],
        )
        self.assertAlmostEqual(valid[0]["cut_end"], 1.92)

    def test_05_previous_word_handle_is_preserved(self):
        valid, _ = self.candidates(
            [word("a", 0, 1), word("b", 2, 3)],
            [{"start": 1, "end": 2, "average_dbfs": -50}],
        )
        self.assertAlmostEqual(valid[0]["cut_start"], 1.10)

    def test_06_multiple_silences(self):
        valid, _ = self.candidates(
            [word("a", 0, 1), word("b", 2, 3), word("c", 4, 5)],
            [{"start": 1, "end": 2, "average_dbfs": -50},
             {"start": 3, "end": 4, "average_dbfs": -50}],
        )
        self.assertEqual(len(valid), 2)

    def test_07_time_map_multiple_cuts(self):
        mapping = build_time_map([
            {"cut_start": 1, "cut_end": 2},
            {"cut_start": 4, "cut_end": 4.5},
        ], 10)
        self.assertEqual(map_time(8, mapping), 6.5)

    def test_08_word_after_cut_is_retimed(self):
        mapping = build_time_map([{"cut_start": 1, "cut_end": 2}], 5)
        self.assertEqual(retime_words([word("x", 3, 4)], mapping)[0]["start"], 2)

    def test_09_word_intersection_is_rejected(self):
        mapping = build_time_map([{"cut_start": 1, "cut_end": 2}], 5)
        with self.assertRaises(RuntimeError):
            retime_words([word("x", 1.5, 2.5)], mapping)

    def test_10_mai_yamok_word_is_indivisible(self):
        mapping = build_time_map([{"cut_start": 1, "cut_end": 2}], 5)
        output = retime_words([word("สั้นๆ", 2.1, 2.5)], mapping)
        self.assertEqual(output[0]["text"], "สั้นๆ")

    def test_11_plan_rejects_word_overlap(self):
        plan = {"cuts": [{"cut_id": "c", "cut_start": 1, "cut_end": 2}]}
        self.assertFalse(validate_silence_plan(plan, [word("x", 1.5, 1.7)])["valid"])

    def test_12_plan_rejects_overlapping_cuts(self):
        plan = {"cuts": [
            {"cut_id": "a", "cut_start": 1, "cut_end": 2},
            {"cut_id": "b", "cut_start": 1.5, "cut_end": 3},
        ]}
        self.assertFalse(validate_silence_plan(plan, [])["valid"])

    def test_13_plan_accepts_chronological_cuts(self):
        plan = {"cuts": [
            {"cut_id": "a", "cut_start": 1, "cut_end": 2},
            {"cut_id": "b", "cut_start": 3, "cut_end": 4},
        ]}
        self.assertTrue(validate_silence_plan(plan, [])["valid"])

    def test_14_exact_microsecond_duration(self):
        mapping = build_time_map([{"cut_start": .1, "cut_end": .3}], 1)
        self.assertAlmostEqual(mapping["new_duration"], .8)

    def test_15_candidate_reason_codes(self):
        valid, _ = self.candidates(
            [word("a", 0, 1), word("b", 2, 3)],
            [{"start": 1, "end": 2, "average_dbfs": -50}],
        )
        self.assertIn("LOW_AUDIO_ENERGY", valid[0]["reason_codes"])

    def test_16_nonpositive_plan_cut_rejected(self):
        plan = {"cuts": [{"cut_id": "c", "cut_start": 2, "cut_end": 2}]}
        self.assertFalse(validate_silence_plan(plan, [])["valid"])

    def test_17_ripple_shifts_caption_after_cut(self):
        draft = {"duration": 5_000_000, "tracks": [{
            "id": "t", "type": "text", "segments": [{
                "id": "s", "target_timerange": {"start": 3_000_000, "duration": 500_000}
            }]
        }]}
        modified, _ = transform_silence_cuts(draft, [{
            "cut_id": "c", "cut_start": 1, "cut_end": 2
        }])
        self.assertEqual(modified["tracks"][0]["segments"][0]["target_timerange"]["start"], 2_000_000)

    def test_18_ripple_updates_duration(self):
        draft = {"duration": 5_000_000, "tracks": []}
        modified, _ = transform_silence_cuts(draft, [{
            "cut_id": "c", "cut_start": 1, "cut_end": 2
        }])
        self.assertEqual(modified["duration"], 4_000_000)

    def test_19_no_words_are_deleted(self):
        mapping = build_time_map([{"cut_start": 1, "cut_end": 2}], 5)
        original = [word("a", 0, .5), word("b", 2.5, 3)]
        self.assertEqual(len(retime_words(original, mapping)), len(original))

    def test_20_boundary_word_is_safe(self):
        plan = {"cuts": [{"cut_id": "c", "cut_start": 1, "cut_end": 2}]}
        self.assertTrue(validate_silence_plan(
            plan, [word("a", 0, 1), word("b", 2, 3)]
        )["valid"])

    def test_21_two_second_gap_targets_one(self):
        cuts, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 3, 4)],
            [{"start": 1, "end": 3, "average_dbfs": -50}], TARGET_PRESET)
        self.assertAlmostEqual(sum(c["cut_duration"] for c in cuts), 1)
        self.assertAlmostEqual(reports[-1]["final_gap_seconds"], 1)

    def test_22_three_second_gap_targets_one(self):
        cuts, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 4, 5)],
            [{"start": 1, "end": 4, "average_dbfs": -50}], TARGET_PRESET)
        self.assertAlmostEqual(sum(c["cut_duration"] for c in cuts), 2)
        self.assertTrue(reports[-1]["within_target_tolerance"])

    def test_23_one_point_zero_three_is_idempotent(self):
        cuts, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 2.03, 3)], [], TARGET_PRESET)
        self.assertFalse(cuts)
        self.assertIn("ALREADY_WITHIN_TARGET", reports[-1]["reason_codes"])

    def test_24_point_nine_is_not_shortened(self):
        cuts, _ = build_silence_candidates(
            [word("a", 0, 1), word("b", 1.9, 3)], [], TARGET_PRESET)
        self.assertFalse(cuts)

    def test_25_multiple_low_energy_islands(self):
        cuts, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 3, 4)],
            [{"start": 1.45, "end": 1.94, "average_dbfs": -50},
             {"start": 1.95, "end": 2.55, "average_dbfs": -48}],
            TARGET_PRESET)
        self.assertEqual(len(cuts), 2)
        self.assertAlmostEqual(reports[-1]["final_gap_seconds"], 1.01)

    def test_26_breath_is_preserved_between_islands(self):
        _, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 3, 4)],
            [{"start": 1.45, "end": 1.9, "average_dbfs": -50},
             {"start": 2.1, "end": 2.45, "average_dbfs": -48}],
            TARGET_PRESET)
        self.assertTrue(reports[-1]["protected_breath_noise_regions"])

    def test_27_trailing_speech_handle_is_preserved(self):
        cuts, _ = build_silence_candidates(
            [word("a", 0, 1), word("b", 3, 4)],
            [{"start": 1, "end": 3, "average_dbfs": -50}], TARGET_PRESET)
        self.assertGreaterEqual(cuts[0]["cut_start"], 1.45)

    def test_28_repeated_detection_after_target_has_no_cut(self):
        cuts, _ = build_silence_candidates(
            [word("a", 0, 1), word("b", 2, 3)],
            [{"start": 1, "end": 2, "average_dbfs": -50}], TARGET_PRESET)
        self.assertEqual(cuts, [])

    def test_29_safety_limited_gap_has_reason(self):
        _, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 4, 5)],
            [{"start": 2, "end": 2.2, "average_dbfs": -50}], TARGET_PRESET)
        self.assertIn(
            "TARGET_NOT_REACHED_AUDIO_SAFETY_LIMIT",
            reports[-1]["reason_codes"])

    def test_30_multiple_cuts_retime_karaoke_word(self):
        mapping = build_time_map([
            {"cut_start": 1.45, "cut_end": 1.9},
            {"cut_start": 2.0, "cut_end": 2.55},
        ], 5)
        output = retime_words([word("karaoke", 3, 3.5)], mapping)
        self.assertAlmostEqual(output[0]["start"], 2)

    def test_31_one_second_gap_reduced_to_point_one(self):
        cuts, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 2, 3)],
            [{"start": 1, "end": 2, "average_dbfs": -50}], TIGHT_PRESET)
        self.assertAlmostEqual(sum(c["cut_duration"] for c in cuts), .9)
        self.assertAlmostEqual(reports[-1]["final_gap_seconds"], .1)

    def test_32_two_second_gap_reduced_to_point_one(self):
        cuts, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 3, 4)],
            [{"start": 1, "end": 3, "average_dbfs": -50}], TIGHT_PRESET)
        self.assertAlmostEqual(sum(c["cut_duration"] for c in cuts), 1.9)
        self.assertAlmostEqual(reports[-1]["final_gap_seconds"], .1)

    def test_33_point_eleven_unchanged(self):
        cuts, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 1.11, 2)], [], TIGHT_PRESET)
        self.assertFalse(cuts)
        self.assertTrue(reports[-1]["within_target_tolerance"])

    def test_34_point_zero_seven_unchanged(self):
        cuts, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 1.07, 2)], [], TIGHT_PRESET)
        self.assertFalse(cuts)
        self.assertIn("BELOW_TARGET_NO_CUT", reports[-1]["reason_codes"])

    def test_35_trailing_consonant_handle(self):
        cuts, _ = build_silence_candidates(
            [word("ครับ", 0, 1), word("ต่อ", 2, 3)],
            [{"start": 1, "end": 2, "average_dbfs": -50}], TIGHT_PRESET)
        self.assertGreaterEqual(cuts[0]["cut_start"], 1.05)

    def test_36_breath_before_next_word_protected(self):
        _, reports = build_silence_candidates(
            [word("a", 0, 1), word("b", 2, 3)],
            [{"start": 1.05, "end": 1.7, "average_dbfs": -50}], TIGHT_PRESET)
        self.assertIn("BREATH_PROTECTION", reports[-1]["reason_codes"])

    def test_37_tight_target_idempotent(self):
        cuts, _ = build_silence_candidates(
            [word("a", 0, 1), word("b", 1.1, 2)],
            [{"start": 1, "end": 1.1, "average_dbfs": -50}], TIGHT_PRESET)
        self.assertFalse(cuts)

    def test_38_tight_multiple_cut_karaoke_retime(self):
        mapping = build_time_map([
            {"cut_start": 1.05, "cut_end": 1.45},
            {"cut_start": 1.5, "cut_end": 2.0},
        ], 4)
        self.assertAlmostEqual(
            retime_words([word("สั้นๆ", 2.1, 2.5)], mapping)[0]["start"], 1.2)


    def test_39_micro_right_fragment_is_absorbed_by_cut(self):
        draft = {"tracks": [{"type": "video", "segments": [{
            "id": "v1",
            "target_timerange": {"start": 0, "duration": 4_600_000},
        }]}]}
        cuts, actions = normalize_micro_fragment_cuts(
            draft,
            [{"cut_id": "c", "cut_start": 3.77, "cut_end": 4.59}],
            [word("before", 3.0, 3.7), word("after", 4.64, 5.0)],
        )
        self.assertEqual(cuts[0]["cut_end"], 4.6)
        self.assertEqual(actions[0]["edge"], "cut_end")

    def test_40_micro_fragment_with_word_is_not_absorbed(self):
        draft = {"tracks": [{"type": "video", "segments": [{
            "id": "v1",
            "target_timerange": {"start": 0, "duration": 4_600_000},
        }]}]}
        cuts, actions = normalize_micro_fragment_cuts(
            draft,
            [{"cut_id": "c", "cut_start": 3.77, "cut_end": 4.59}],
            [word("protected", 4.585, 4.6)],
        )
        self.assertEqual(cuts[0]["cut_end"], 4.59)
        self.assertEqual(actions, [])

    def test_41_raw_spacing_is_retimed_with_validated_silence_map(self):
        raw = {
            "text": "a b",
            "audio_duration_secs": 3.0,
            "words": [
                {"text": "a", "type": "word", "start": 0.0, "end": 1.0},
                {"text": " ", "type": "spacing", "start": 1.0, "end": 2.0},
                {"text": "b", "type": "word", "start": 2.0, "end": 3.0},
            ],
        }
        mapping = build_time_map([
            {"cut_start": 1.1, "cut_end": 1.9}
        ], 3.0)
        output = retime_raw_transcript(raw, mapping)
        self.assertAlmostEqual(output["audio_duration_secs"], 2.2)
        self.assertAlmostEqual(output["words"][1]["end"], 1.2)
        self.assertAlmostEqual(output["words"][2]["start"], 1.2)

    def test_42_transcript_free_micro_fragment_between_cuts_is_absorbed(self):
        draft = {"tracks": [{"type": "video", "segments": [{
            "id": "v1",
            "target_timerange": {"start": 0, "duration": 5_000_000},
        }]}]}
        cuts, actions = normalize_micro_fragment_cuts(
            draft,
            [
                {"cut_id": "c1", "cut_start": 1.0, "cut_end": 2.0},
                {"cut_id": "c2", "cut_start": 2.03, "cut_end": 3.0},
            ],
            [word("before", 0.2, 0.8), word("after", 3.2, 3.6)],
        )
        self.assertEqual(len(cuts), 1)
        self.assertEqual(cuts[0]["cut_start"], 1.0)
        self.assertEqual(cuts[0]["cut_end"], 3.0)
        self.assertEqual(cuts[0]["merged_cut_ids"], ["c1", "c2"])
        self.assertEqual(actions[0]["edge"], "inter_cut_gap")
        self.assertAlmostEqual(
            actions[0]["removed_micro_fragment_seconds"], 0.03
        )

    def test_43_personal_profile_removes_longer_internal_speechless_island(self):
        draft = {"tracks": [{"type": "video", "segments": [
            {"id": "v1", "target_timerange": {"start": 0, "duration": 2_000_000}},
            {"id": "v2", "target_timerange": {"start": 2_000_000, "duration": 2_000_000}},
        ]}]}
        cuts, actions = normalize_micro_fragment_cuts(
            draft,
            [{"cut_id": "c", "cut_start": 1.2, "cut_end": 1.6}],
            [word("spoken", 0.2, 1.1), word("next", 2.1, 2.5)],
            remove_internal_transcript_free_residuals=True,
        )
        self.assertEqual(cuts[0]["cut_end"], 2.0)
        self.assertEqual(
            actions[0]["reason"], "TRANSCRIPT_FREE_INTERNAL_RESIDUAL"
        )

    def test_44_personal_profile_preserves_outer_trailing_handle(self):
        draft = {"tracks": [{"type": "video", "segments": [{
            "id": "v1",
            "target_timerange": {"start": 0, "duration": 2_000_000},
        }]}]}
        cuts, _actions = normalize_micro_fragment_cuts(
            draft,
            [{"cut_id": "c", "cut_start": 1.2, "cut_end": 1.6}],
            [word("spoken", 0.2, 1.1)],
            remove_internal_transcript_free_residuals=True,
        )
        self.assertEqual(cuts[0]["cut_end"], 1.6)

    def test_45_overlapping_expanded_cuts_are_coalesced(self):
        draft = {"tracks": [{"type": "video", "segments": [
            {"id": "v1", "target_timerange": {"start": 0, "duration": 2_000_000}},
            {"id": "v2", "target_timerange": {"start": 2_000_000, "duration": 2_000_000}},
            {"id": "v3", "target_timerange": {"start": 4_000_000, "duration": 2_000_000}},
        ]}]}
        cuts, actions = normalize_micro_fragment_cuts(
            draft,
            [
                {"cut_id": "c1", "cut_start": 1.2, "cut_end": 2.2},
                {"cut_id": "c2", "cut_start": 1.8, "cut_end": 3.0},
            ],
            [word("before", 0.2, 1.1), word("after", 4.2, 4.6)],
            remove_internal_transcript_free_residuals=True,
        )
        self.assertEqual(len(cuts), 1)
        self.assertEqual(cuts[0]["cut_start"], 1.2)
        self.assertEqual(cuts[0]["cut_end"], 4.0)
        self.assertIn(
            "OVERLAPPING_NORMALIZED_CUTS_MERGED", cuts[0]["reason_codes"]
        )
        self.assertTrue(any(a["edge"] == "overlapping_cuts" for a in actions))


if __name__ == "__main__":
    unittest.main()

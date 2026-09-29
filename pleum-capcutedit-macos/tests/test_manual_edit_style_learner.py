from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from manual_edit_style_learner import learn_manual_edit_style


def analysis(name: str, ranges: list[tuple[float, float]], media: str = "C:/clip.mp4") -> dict:
    cursor = 0.0
    segments = []
    for index, (start, end) in enumerate(ranges):
        duration = end - start
        segments.append({
            "track_index": 0,
            "segment_id": f"s{index}",
            "media_path": media,
            "source_timerange": {
                "start": start, "end": end, "duration": duration,
            },
            "target_timerange": {
                "start": cursor, "end": cursor + duration, "duration": duration,
            },
        })
        cursor += duration
    return {
        "project_name": name,
        "duration": sum(end - start for start, end in ranges),
        "safe_for_direct_transcription": True,
        "unsupported_structures": [],
        "audible_segments": segments,
    }


class ManualEditStyleLearnerTests(unittest.TestCase):
    def test_selective_reference_profile_and_benchmark(self) -> None:
        profile = learn_manual_edit_style(
            analysis("source", [(0.0, 10.0)]),
            analysis("manual", [(2.0, 4.0), (6.0, 8.0)]),
        )
        self.assertEqual(profile["edit_mode"], "selective_story_compaction")
        self.assertEqual(profile["reference_output_to_source_ratio"], 0.4)
        self.assertEqual(profile["current_skill_benchmark"]["manual_reference_recall"], 1.0)
        self.assertEqual(profile["current_skill_benchmark"]["manual_reference_precision"], 0.4)
        self.assertEqual(profile["cadence"]["kept_segment_count"], 2)
        self.assertTrue(profile["learned_policy"]["deduplicate_before_silence_cleanup"])
        self.assertEqual(
            profile["comparison_ranges"]["current_skill_only"],
            [{"start": 0.0, "end": 2.0, "duration": 2.0},
             {"start": 4.0, "end": 6.0, "duration": 2.0},
             {"start": 8.0, "end": 10.0, "duration": 2.0}],
        )

    def test_reference_transcript_is_measured_on_target_timeline(self) -> None:
        raw = {"words": [
            {"type": "word", "start": 0.02, "end": 0.9},
            {"type": "spacing", "start": 0.9, "end": 1.0},
            {"type": "word", "start": 1.0, "end": 1.9},
        ]}
        profile = learn_manual_edit_style(
            analysis("source", [(0.0, 10.0)]),
            analysis("manual", [(2.0, 3.0), (6.0, 7.0)]),
            raw,
        )
        handles = profile["speech_boundary_handles"]
        self.assertEqual(handles["sample_count"], 2)
        self.assertEqual(handles["lexically_empty_segment_count"], 0)
        self.assertEqual(handles["word_crossing_boundary_count"], 0)
        self.assertAlmostEqual(handles["lead_handle_seconds"]["median"], 0.01)

    def test_reference_reports_speechless_timeline_segment(self) -> None:
        raw = {"words": [
            {"type": "word", "start": 0.1, "end": 0.8},
        ]}
        profile = learn_manual_edit_style(
            analysis("source", [(0.0, 10.0)]),
            analysis("manual", [(2.0, 3.0), (6.0, 7.0)]),
            raw,
        )
        handles = profile["speech_boundary_handles"]
        self.assertEqual(handles["lexically_empty_segment_count"], 1)
        self.assertEqual(handles["lexically_empty_segments"][0]["start"], 1.0)

    def test_different_source_media_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "same dominant media"):
            learn_manual_edit_style(
                analysis("source", [(0.0, 10.0)], "C:/first.mp4"),
                analysis("manual", [(0.0, 5.0)], "C:/second.mp4"),
            )


if __name__ == "__main__":
    unittest.main()

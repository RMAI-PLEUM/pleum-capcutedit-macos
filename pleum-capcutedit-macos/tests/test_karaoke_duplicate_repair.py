from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from capcut_karaoke_injector import _build
from karaoke_state_plan_optimizer import optimize_karaoke_state_plan
from karaoke_state_plan_validator import validate_karaoke_state_plan


def state(kind: str, start: float, end: float, number: int) -> dict:
    return {
        "state_id": f"s{number}", "type": kind, "start": start, "end": end,
        "active_word_id": f"w{number}" if kind == "highlight" else None,
        "active_word_text": "คำ" if kind == "highlight" else None,
        "active_utf16_start": 0 if kind == "highlight" else None,
        "active_utf16_length": 2 if kind == "highlight" else None,
    }


def plan(states: list[dict]) -> dict:
    return {
        "version": 1,
        "preset": "karaoke-yellow",
        "project": {"name": "Apple", "timeline_hash": "h", "duration": 2.0},
        "cues": [{
            "caption_id": "c1", "text": "คำ", "start": 0.0, "end": 2.0,
            "words": [{
                "word_id": "w1", "text": "คำ", "start": .1, "end": .5,
                "utf16_start": 0, "utf16_length": 2, "highlightable": True,
            }],
            "states": states,
        }],
    }


class KaraokeDuplicateRepairTests(unittest.TestCase):
    def test_01_base_plus_karaoke_registry_cleanup(self) -> None:
        baseline = self.baseline()
        with self.registry_patches():
            modified, _generated, changes = _build(baseline, plan([
                state("normal", 0, .1, 0), state("highlight", .1, .5, 1),
                state("normal", .5, 2, 2),
            ]), "fake")
        self.assertFalse(any(t.get("id") == "base-track" for t in modified["tracks"]))
        self.assertEqual(changes["replaced_base_segment_ids"], ["base-segment"])

    def test_02_complete_coverage_allows_base_removal(self) -> None:
        report = validate_karaoke_state_plan(plan([
            state("highlight", 0, 1, 1), state("normal", 1, 2, 2),
        ]))
        self.assertTrue(report["valid"])

    def test_03_incomplete_coverage_fails(self) -> None:
        report = validate_karaoke_state_plan(plan([
            state("highlight", .1, 1, 1), state("normal", 1, 2, 2),
        ]))
        self.assertFalse(report["valid"])

    def test_04_manual_identical_caption_remains(self) -> None:
        baseline = self.baseline()
        with self.registry_patches():
            modified, _generated, _changes = _build(
                baseline, plan([state("highlight", 0, 2, 1)]), "fake"
            )
        self.assertTrue(any(t.get("id") == "manual-track" for t in modified["tracks"]))

    def test_05_unreferenced_base_material_removed(self) -> None:
        baseline = self.baseline()
        with self.registry_patches():
            modified, _generated, changes = _build(
                baseline, plan([state("highlight", 0, 2, 1)]), "fake"
            )
        self.assertFalse(any(m.get("id") == "base-material" for m in modified["materials"]["texts"]))
        self.assertEqual(changes["removed_base_material_ids"], ["base-material"])

    def test_06_shared_manual_material_is_preserved_by_manual_segment(self) -> None:
        baseline = self.baseline()
        baseline["tracks"][0]["segments"][0]["material_id"] = "base-material"
        with self.registry_patches():
            modified, _generated, _changes = _build(
                baseline, plan([state("highlight", 0, 2, 1)]), "fake"
            )
        self.assertTrue(any(
            item.get("id") == "base-material"
            for item in modified["materials"]["texts"]
        ))

    def test_07_empty_registered_base_track_removed(self) -> None:
        baseline = self.baseline()
        with self.registry_patches():
            modified, _generated, changes = _build(
                baseline, plan([state("highlight", 0, 2, 1)]), "fake"
            )
        self.assertNotIn("base-track", [t.get("id") for t in modified["tracks"]])
        self.assertEqual(changes["removed_base_track_id"], "base-track")

    def test_08_direct_highlight_transition(self) -> None:
        optimized, stats = optimize_karaoke_state_plan(plan([
            state("highlight", 0, 1, 1), state("highlight", 1, 2, 2),
        ]))
        states = optimized["cues"][0]["states"]
        self.assertEqual(states[0]["end"], states[1]["start"])
        self.assertEqual(stats["micro_normal_states_removed"], 0)

    def test_09_micro_normal_under_40ms_removed(self) -> None:
        optimized, stats = optimize_karaoke_state_plan(plan([
            state("highlight", 0, 1, 1), state("normal", 1, 1.02, 0),
            state("highlight", 1.02, 2, 2),
        ]))
        self.assertEqual(len(optimized["cues"][0]["states"]), 2)
        self.assertEqual(stats["micro_normal_states_removed"], 1)

    def test_10_zero_duration_removed(self) -> None:
        optimized, stats = optimize_karaoke_state_plan(plan([
            state("highlight", 0, 1, 1), state("normal", 1, 1, 0),
            state("highlight", 1, 2, 2),
        ]))
        self.assertEqual(len(optimized["cues"][0]["states"]), 2)
        self.assertEqual(stats["zero_duration_states_removed"], 1)

    def test_11_optimizer_keeps_state_style_identity(self) -> None:
        source = plan([
            state("highlight", 0, 1, 1), state("normal", 1, 1.01, 0),
            state("highlight", 1.01, 2, 2),
        ])
        optimized, _stats = optimize_karaoke_state_plan(source)
        self.assertEqual(
            optimized["cues"][0]["states"][0]["active_utf16_length"], 2
        )

    def test_12_build_does_not_mutate_baseline(self) -> None:
        baseline = self.baseline()
        original = deepcopy(baseline)
        with self.registry_patches():
            _build(baseline, plan([state("highlight", 0, 2, 1)]), "fake")
        self.assertEqual(baseline, original)

    @staticmethod
    def registry_patches():
        caption = {
            "generated_text_track_id": "base-track",
            "generated_segment_ids": ["base-segment"],
            "generated_material_ids": ["base-material"],
            "generated_auxiliary_material_ids": [],
        }
        karaoke = {
            "generated_text_track_id": None,
            "generated_segment_ids": [],
            "generated_material_ids": [],
            "generated_auxiliary_material_ids": [],
        }
        class Patches:
            def __enter__(self):
                self.a = patch(
                    "capcut_karaoke_injector.load_registry",
                    return_value=caption,
                )
                self.b = patch(
                    "capcut_karaoke_injector.load_karaoke_registry",
                    return_value=karaoke,
                )
                self.a.start(); self.b.start()
            def __exit__(self, *args):
                self.a.stop(); self.b.stop()
        return Patches()

    @staticmethod
    def baseline() -> dict:
        return {
            "duration": 2_000_000,
            "tracks": [
                {
                    "id": "manual-track", "type": "text",
                    "segments": [{
                        "id": "manual-segment", "material_id": "manual-material",
                        "target_timerange": {"start": 0, "duration": 2_000_000},
                    }],
                },
                {
                    "id": "base-track", "type": "text",
                    "segments": [{
                        "id": "base-segment", "material_id": "base-material",
                        "target_timerange": {"start": 0, "duration": 2_000_000},
                    }],
                },
            ],
            "materials": {
                "texts": [
                    {"id": "manual-material", "type": "text", "content": "{}"},
                    {"id": "base-material", "type": "text", "content": "{}"},
                ],
                "material_animations": [],
            },
        }


if __name__ == "__main__":
    unittest.main()

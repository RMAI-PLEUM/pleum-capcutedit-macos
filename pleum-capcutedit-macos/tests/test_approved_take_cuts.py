from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from approved_take_cut_editor import (
    STALE_MESSAGE, apply_approved_cut_transaction, essential_timeline_hash,
    validate_approval,
)
from capcut_live_project_reader import LiveProject
from capcut_project_locator import CapCutProject
from capcut_ripple_cut import apply_ripple_cut


def segment(uid, start, duration, track_type="video"):
    value = {
        "id": uid,
        "material_id": "mat1",
        "target_timerange": {"start": start, "duration": duration},
        "render_timerange": {"start": 0, "duration": 0},
    }
    if track_type in {"video", "audio"}:
        value.update({
            "source_timerange": {"start": start, "duration": duration},
            "speed": 1.0,
            "reverse": False,
        })
    return value


def draft(segments, track_type="video", duration=10_000_000, media_path=""):
    materials = {"videos": [], "audios": [], "texts": []}
    if track_type == "video":
        materials["videos"] = [{
            "id": "mat1", "path": media_path, "has_audio": True,
        }]
    elif track_type == "audio":
        materials["audios"] = [{"id": "mat1", "path": media_path}]
    return {
        "duration": duration,
        "tracks": [{
            "id": "track1", "type": track_type, "flag": 0,
            "attribute": 0, "segments": segments,
        }],
        "materials": materials,
    }


class RippleCutTests(unittest.TestCase):
    def apply(self, data, start=4_000_000, end=6_000_000):
        counter = iter(["fresh1", "fresh2"])
        return apply_ripple_cut(data, start, end, lambda: next(counter))

    def test_01_cut_inside_one_segment(self):
        modified, changes = self.apply(draft([segment("s1", 0, 10_000_000)]))
        output = modified["tracks"][0]["segments"]
        self.assertEqual(len(output), 2)
        self.assertEqual(output[0]["target_timerange"], {"start": 0, "duration": 4_000_000})
        self.assertEqual(output[1]["target_timerange"], {"start": 4_000_000, "duration": 4_000_000})

    def test_02_cut_matching_complete_segment(self):
        data = draft([
            segment("s1", 0, 4_000_000),
            segment("s2", 4_000_000, 2_000_000),
            segment("s3", 6_000_000, 4_000_000),
        ])
        modified, _ = self.apply(data)
        self.assertEqual([x["id"] for x in modified["tracks"][0]["segments"]], ["s1", "s3"])

    def test_03_cut_across_two_sequential_segments(self):
        data = draft([
            segment("s1", 0, 5_000_000),
            segment("s2", 5_000_000, 5_000_000),
        ])
        modified, _ = self.apply(data)
        first, second = modified["tracks"][0]["segments"]
        self.assertEqual(first["target_timerange"]["duration"], 4_000_000)
        self.assertEqual(second["target_timerange"], {"start": 4_000_000, "duration": 4_000_000})

    def test_04_cut_starts_inside_ends_at_boundary(self):
        data = draft([
            segment("s1", 0, 6_000_000),
            segment("s2", 6_000_000, 4_000_000),
        ])
        modified, _ = self.apply(data)
        first, second = modified["tracks"][0]["segments"]
        self.assertEqual(first["target_timerange"]["duration"], 4_000_000)
        self.assertEqual(second["target_timerange"]["start"], 4_000_000)

    def test_05_spanning_segment_gets_fresh_id(self):
        modified, changes = self.apply(draft([segment("s1", 0, 10_000_000)]))
        self.assertEqual(modified["tracks"][0]["segments"][1]["id"], "fresh1")
        self.assertEqual(changes["generated_segment_ids"], ["fresh1"])

    def test_06_caption_after_cut_shifts(self):
        data = draft([segment("t1", 7_000_000, 1_000_000, "text")], "text")
        modified, _ = self.apply(data)
        self.assertEqual(
            modified["tracks"][0]["segments"][0]["target_timerange"]["start"],
            5_000_000,
        )

    def test_07_caption_crossing_cut_is_split(self):
        data = draft([segment("t1", 3_000_000, 5_000_000, "text")], "text")
        modified, changes = self.apply(data)
        self.assertEqual(len(modified["tracks"][0]["segments"]), 2)
        self.assertEqual(changes["generated_segment_ids"], ["fresh1"])

    def test_08_unsupported_overlay_crossing_aborts(self):
        data = draft([segment("x1", 3_000_000, 5_000_000, "compound")], "compound")
        with self.assertRaisesRegex(RuntimeError, "unsupported track type"):
            self.apply(data)

    def test_09_stale_timeline_hash_aborts(self):
        approval = {"version": 1, "project": "Apple", "timeline_hash": "old", "cuts": []}
        with self.assertRaisesRegex(RuntimeError, "timeline changed"):
            validate_approval(approval, "Apple", "new", {"groups": []})

    def test_10_second_file_failure_rolls_back(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            folder = Path(temporary)
            media = folder / "media.wav"
            media.write_bytes(b"fixture")
            data = draft([segment("s1", 0, 10_000_000)], media_path=str(media))
            first = folder / "draft_content.json"
            second_dir = folder / "Timelines/t1"
            second_dir.mkdir(parents=True)
            second = second_dir / "draft_content.json"
            metadata = folder / "draft_meta_info.json"
            payload = json.dumps(data).encode()
            first.write_bytes(payload)
            second.write_bytes(payload)
            metadata.write_text(
                json.dumps({"draft_name": "Apple", "draft_id": "id1", "tm_duration": 10_000_000}),
                encoding="utf-8",
            )
            project = CapCutProject("Apple", folder, "id1", 0.0, metadata)
            live = LiveProject(project, {}, [first, second], [data, data])
            current = essential_timeline_hash(data)
            approval = {
                "version": 1, "project": "Apple", "timeline_hash": current,
                "cuts": [{
                    "approved": True, "source_group_id": "take_group_0001",
                    "start": 4.0, "end": 6.0, "duration": 2.0,
                    "keep_range": {"start": 6.0, "end": 8.0},
                    "reason_codes": ["MANUALLY_REVIEWED"],
                }],
            }
            plan = {"groups": [{"group_id": "take_group_0001"}]}
            originals = {path: path.read_bytes() for path in (first, second, metadata)}
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                apply_approved_cut_transaction(
                    live, approval, plan, dry_run=False, simulate_failure_after=2
                )
            self.assertEqual(
                originals, {path: path.read_bytes() for path in originals}
            )


if __name__ == "__main__":
    unittest.main()

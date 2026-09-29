from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from capcut_live_project_reader import LiveProject
from capcut_project_locator import CapCutProject
from editorial_selection_workflow import (
    apply_editorial_selection_plan, build_editorial_selection_plan,
)


def draft(duration: int = 10_000_000, media: str = "") -> dict:
    return {
        "duration": duration,
        "tracks": [{"id": "track", "type": "video", "flag": 0, "attribute": 0,
                    "segments": [{
                        "id": "segment", "material_id": "media",
                        "source_timerange": {"start": 0, "duration": duration},
                        "target_timerange": {"start": 0, "duration": duration},
                        "render_timerange": {"start": 0, "duration": 0},
                        "speed": 1.0, "reverse": False,
                    }]}],
        "materials": {"videos": [{"id": "media", "path": media, "has_audio": True}]},
    }


class EditorialSelectionWorkflowTests(unittest.TestCase):
    def test_plan_is_exact_complement_of_kept_story_beats(self) -> None:
        plan = build_editorial_selection_plan(
            "Clip", draft(),
            [{"start": 2.0, "end": 4.0, "beat": "hook"},
             {"start": 6.0, "end": 8.0, "beat": "cta"}],
            profile_id="manual-v1",
        )
        self.assertEqual(plan["expected_new_duration"], 4.0)
        self.assertEqual(
            [(item["start"], item["end"]) for item in plan["cut_ranges"]],
            [(0.0, 2.0), (4.0, 6.0), (8.0, 10.0)],
        )

    def test_stale_plan_is_rejected_before_dry_run(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as folder_name:
            folder = Path(folder_name)
            media = folder / "clip.wav"; media.write_bytes(b"x")
            value = draft(media=str(media))
            first = folder / "draft_content.json"
            mirror_folder = folder / "Timelines"; mirror_folder.mkdir()
            second = mirror_folder / "draft_content.json"
            metadata = folder / "draft_meta_info.json"
            payload = json.dumps(value).encode("utf-8")
            first.write_bytes(payload); second.write_bytes(payload)
            metadata.write_text(json.dumps({"draft_name": "Clip"}), encoding="utf-8")
            project = CapCutProject("Clip", folder, "id", 0.0, metadata)
            live = LiveProject(project, {}, [first, second], [value, value])
            plan = build_editorial_selection_plan(
                "Clip", value, [{"start": 2.0, "end": 8.0}], profile_id="manual-v1"
            )
            plan["timeline_hash"] = "stale"
            with self.assertRaisesRegex(RuntimeError, "Timeline changed"):
                apply_editorial_selection_plan(live, plan, dry_run=True)


if __name__ == "__main__":
    unittest.main()

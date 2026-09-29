from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from capcut_caption_style_fingerprint import fingerprint
from capcut_caption_style_learner import _select, discover_caption_candidates
from capcut_caption_style_preset import render_learned_templates, utf16_length


def material(material_id: str, text: str, color: str = "#ffffff") -> dict:
    length = utf16_length(text)
    return {
        "id": material_id,
        "type": "text",
        "content": json.dumps({
            "text": text,
            "styles": [{
                "range": [0, length],
                "font": {"id": "font-resource", "path": "ExampleSans-Regular.ttf"},
                "size": 16,
                "bold": True,
            }],
        }, ensure_ascii=False),
        "font_size": 16.0,
        "font_path": "ExampleSans-Regular.ttf",
        "font_resource_id": "font-resource",
        "fonts": [{"resource_id": "font-resource", "path": "ExampleSans-Regular.ttf"}],
        "text_color": color,
    }


def segment(segment_id: str, material_id: str, start: int) -> dict:
    return {
        "id": segment_id,
        "material_id": material_id,
        "target_timerange": {"start": start, "duration": 1_000_000},
        "render_timerange": {"start": start, "duration": 1_000_000},
        "clip": {
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": -0.4},
            "rotation": 0.0,
            "alpha": 1.0,
        },
        "extra_material_refs": [],
        "render_index": 14000,
    }


class CaptionStyleLearningTests(unittest.TestCase):
    def test_fingerprint_ignores_text_ids_timing_and_utf16_length(self) -> None:
        track_a = {"id": "track-a", "type": "text", "segments": []}
        track_b = {"id": "track-b", "type": "text", "segments": []}
        first = fingerprint(
            track_a, segment("s1", "m1", 0), material("m1", "ไทย")
        )[0]
        second = fingerprint(
            track_b, segment("s2", "m2", 9_000_000),
            material("m2", "Apple Caption 2026"),
        )[0]
        self.assertEqual(first, second)

    def test_discovers_and_selects_dominant_style(self) -> None:
        materials = [
            material("m1", "หนึ่ง"),
            material("m2", "สอง"),
            material("m3", "three", "#ff0000"),
        ]
        track = {
            "id": "track",
            "type": "text",
            "segments": [
                segment("s1", "m1", 0),
                segment("s2", "m2", 1_000_000),
                segment("s3", "m3", 2_000_000),
            ],
        }
        draft = {
            "canvas_config": {"width": 1080, "height": 1920},
            "tracks": [track],
            "materials": {"texts": materials},
        }
        candidates = discover_caption_candidates(draft)
        selected, reason, count = _select(candidates)
        self.assertEqual(count, 2)
        self.assertIn("majority", reason)
        self.assertEqual(selected["visible_caption_text"], "หนึ่ง")

    def test_render_deep_copies_and_regenerates_utf16_ranges(self) -> None:
        source_material = material("source-material", "ต้นฉบับ")
        content = json.loads(source_material["content"])
        content["text"] = ""
        content["styles"][0]["range"] = [0, 0]
        source_material.pop("id")
        source_material["content"] = json.dumps(content, ensure_ascii=False)
        source_segment = segment("source-segment", "source-material", 0)
        for key in ("id", "material_id", "target_timerange", "render_timerange"):
            source_segment.pop(key)
        preset = {
            "preset_id": "test",
            "material_template": source_material,
            "segment_style_template": source_segment,
            "track_template": {"type": "text", "segments": []},
            "auxiliary_material_templates": [],
        }
        baseline = {
            "duration": 10_000_000,
            "tracks": [],
            "materials": {"texts": []},
        }
        captions = [
            {"start": 0.0, "end": 1.0, "text": "ทดสอบ"},
            {"start": 1.1, "end": 2.0, "text": "Apple 2026"},
        ]
        modified, generated, _changes = render_learned_templates(
            baseline, captions, preset
        )
        self.assertEqual(len(set(generated["material_ids"])), 2)
        for caption, rendered in zip(captions, modified["materials"]["texts"]):
            rendered_content = json.loads(rendered["content"])
            self.assertEqual(rendered_content["text"], caption["text"])
            self.assertEqual(
                rendered_content["styles"][0]["range"],
                [0, utf16_length(caption["text"])],
            )
        self.assertEqual(json.loads(source_material["content"])["text"], "")


if __name__ == "__main__":
    unittest.main()

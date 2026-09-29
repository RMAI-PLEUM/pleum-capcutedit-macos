from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pattern1_injector import _decode_text, _set_text, _suppress_cta_caption


def text_material(material_id: str, text: str) -> dict:
    length = len(text.encode("utf-16-le")) // 2
    return {
        "id": material_id,
        "type": "text",
        "content": json.dumps({"text": text, "styles": [{"range": [0, length]}]}, ensure_ascii=False),
    }


class Pattern1InjectorTests(unittest.TestCase):
    def test_set_text_updates_utf16_ranges(self) -> None:
        material = text_material("m1", "เดิม")
        _set_text(material, '"รอคอย"')
        content = json.loads(material["content"])
        self.assertEqual(content["text"], '"รอคอย"')
        self.assertEqual(
            content["styles"][0]["range"],
            [0, len('"รอคอย"'.encode("utf-16-le")) // 2],
        )
        self.assertEqual(_decode_text(material), '"รอคอย"')

    def test_suppress_cta_removes_only_registered_keyword_caption(self) -> None:
        data = {
            "tracks": [{
                "id": "track", "type": "text", "segments": [
                    {"id": "s1", "material_id": "m1", "target_timerange": {"start": 100, "duration": 100}, "extra_material_refs": ["a1"]},
                    {"id": "s2", "material_id": "m2", "target_timerange": {"start": 108_140_000, "duration": 420_000}, "extra_material_refs": ["a2"]},
                ],
            }],
            "materials": {
                "texts": [text_material("m1", "ว่า"), text_material("m2", "รอคอย")],
                "material_animations": [{"id": "a1", "animations": []}, {"id": "a2", "animations": []}],
            },
        }
        registry = {
            "generated_segment_ids": ["s1", "s2"],
            "generated_material_ids": ["m1", "m2"],
            "generated_auxiliary_material_ids": ["a1", "a2"],
        }
        plan = {"cta": {"keyword": "รอคอย", "caption_start": 108.14}}
        updated = _suppress_cta_caption(data, plan, registry)
        self.assertEqual([item["id"] for item in data["tracks"][0]["segments"]], ["s1"])
        self.assertEqual([item["id"] for item in data["materials"]["texts"]], ["m1"])
        self.assertEqual([item["id"] for item in data["materials"]["material_animations"]], ["a1"])
        self.assertEqual(updated["generated_segment_ids"], ["s1"])
        self.assertEqual(updated["generated_material_ids"], ["m1"])
        self.assertEqual(updated["generated_auxiliary_material_ids"], ["a1"])
        self.assertEqual(updated["pattern_1_suppressed_caption"]["text"], "รอคอย")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from capcut_project_validator import validate_injected_data


def _text_material(material_id: str, text: str) -> dict:
    utf16_length = len(text.encode("utf-16-le")) // 2
    return {
        "id": material_id,
        "type": "text",
        "content": json.dumps(
            {"text": text, "styles": [{"range": [0, utf16_length]}]},
            ensure_ascii=False,
        ),
    }


def _fixture(second_material_ref: str = "material-2") -> tuple[dict, dict, dict, dict]:
    baseline = {
        "duration": 2_000_000,
        "tracks": [{"id": "video-track", "type": "video", "segments": []}],
        "materials": {"texts": []},
    }
    plan = {
        "captions": [
            {"id": "caption-1", "start": 0.0, "end": 1.0, "text": "นะครับ"},
            {"id": "caption-2", "start": 1.0, "end": 2.0, "text": "นะครับ"},
        ]
    }
    generated = {
        "track_id": "caption-track",
        "segment_ids": ["segment-1", "segment-2"],
        "material_ids": ["material-1", "material-2"],
        "auxiliary_material_ids": [],
    }
    data = {
        "duration": 2_000_000,
        "tracks": [
            baseline["tracks"][0],
            {
                "id": "caption-track",
                "type": "text",
                "segments": [
                    {
                        "id": "segment-1",
                        "material_id": "material-1",
                        "target_timerange": {"start": 0, "duration": 1_000_000},
                    },
                    {
                        "id": "segment-2",
                        "material_id": second_material_ref,
                        "target_timerange": {"start": 1_000_000, "duration": 1_000_000},
                    },
                ],
            },
        ],
        "materials": {
            "texts": [
                _text_material("material-1", "นะครับ"),
                _text_material("material-2", "นะครับ"),
            ]
        },
    }
    return data, baseline, plan, generated


class CapCutProjectValidatorTests(unittest.TestCase):
    def test_duplicate_caption_texts_are_safe_when_identity_timing_and_order_match(self) -> None:
        data, baseline, plan, generated = _fixture()

        result = validate_injected_data(data, baseline, plan, generated)

        self.assertTrue(result["valid"])
        self.assertTrue(result["texts_match_exactly_once"])

    def test_duplicate_caption_texts_do_not_hide_material_mapping_errors(self) -> None:
        data, baseline, plan, generated = _fixture(second_material_ref="material-1")

        result = validate_injected_data(data, baseline, plan, generated)

        self.assertFalse(result["valid"])
        self.assertFalse(result["texts_match_exactly_once"])
        self.assertIn(
            "caption segment-to-material mapping or order mismatch", result["errors"]
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import platform_paths
from audit_distribution import audit
from capcut_live_project_reader import read_live_project
from capcut_project_locator import CapCutProject
from schema_compatibility import compatibility_status, schema_fingerprint


class PortableTests(unittest.TestCase):
    def test_windows_config_path_normalizes(self):
        with patch("platform.system", return_value="Windows"), patch.dict(
            os.environ, {"APPDATA": "X:/Profiles/Example/AppData/Roaming"}
        ):
            self.assertIn("edit-capcut", str(platform_paths.user_config_dir()))

    def test_macos_config_path_normalizes(self):
        with patch("platform.system", return_value="Darwin"):
            self.assertTrue(
                platform_paths.user_config_dir().as_posix().endswith(
                    "Library/Application Support/edit-capcut"
                )
            )

    def test_parseable_project_root_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "synthetic"
            project.mkdir()
            (project / "draft_meta_info.json").write_text(
                json.dumps({"draft_name": "Synthetic", "draft_id": "fixture-id"}),
                encoding="utf-8",
            )
            with patch("platform_paths._candidate_roots", return_value=[root]):
                found = platform_paths.capcut_project_root_candidates()
            self.assertEqual(found[0]["parseable_project_count"], 1)

    def test_multiple_root_candidates(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            roots = [Path(one), Path(two)]
            for index, root in enumerate(roots):
                project = root / f"p{index}"
                project.mkdir()
                (project / "draft_meta_info.json").write_text(
                    json.dumps({"draft_name": f"P{index}", "draft_id": str(index)}),
                    encoding="utf-8",
                )
            with patch("platform_paths._candidate_roots", return_value=roots):
                self.assertEqual(len(platform_paths.capcut_project_root_candidates()), 2)

    def test_no_capcut_root(self):
        with patch("platform_paths._candidate_roots", return_value=[]):
            self.assertEqual(platform_paths.capcut_project_root_candidates(), [])

    def test_macos_draft_info_uses_active_timeline_mirrors(self):
        with tempfile.TemporaryDirectory() as temporary:
            project_path = Path(temporary) / "Mac Fixture"
            timeline_id = "ACTIVE-TIMELINE"
            timeline = project_path / "Timelines" / timeline_id
            subdraft = project_path / "subdraft" / "UNRELATED"
            timeline.mkdir(parents=True)
            subdraft.mkdir(parents=True)
            metadata_path = project_path / "draft_meta_info.json"
            metadata_path.write_text(
                json.dumps({"draft_name": "Mac Fixture", "draft_id": "mac-id"}),
                encoding="utf-8",
            )
            (project_path / "Timelines/project.json").write_text(
                json.dumps({"main_timeline_id": timeline_id}), encoding="utf-8"
            )
            draft = {"duration": 1_000_000, "tracks": [], "materials": {}}
            for path in (project_path / "draft_info.json", timeline / "draft_info.json"):
                path.write_text(json.dumps(draft), encoding="utf-8")
            (subdraft / "draft_content.json").write_text(
                json.dumps({"duration": 2}), encoding="utf-8"
            )
            project = CapCutProject(
                "Mac Fixture", project_path, "mac-id", 0.0, metadata_path
            )

            live = read_live_project(project)

            self.assertEqual(live.storage_format, "macos_draft_info")
            self.assertEqual(len(live.draft_paths), 2)
            self.assertTrue(all(path.name == "draft_info.json" for path in live.draft_paths))
            self.assertEqual(live.primary, draft)

    def test_legacy_reader_excludes_subdraft_payloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            project_path = Path(temporary) / "Legacy Fixture"
            mirror = project_path / "T"
            subdraft = project_path / "subdraft" / "UNRELATED"
            mirror.mkdir(parents=True)
            subdraft.mkdir(parents=True)
            metadata_path = project_path / "draft_meta_info.json"
            metadata_path.write_text(
                json.dumps({"draft_name": "Legacy Fixture", "draft_id": "legacy-id"}),
                encoding="utf-8",
            )
            draft = {"duration": 1_000_000, "tracks": [], "materials": {}}
            for path in (project_path / "draft_content.json", mirror / "draft_content.json"):
                path.write_text(json.dumps(draft), encoding="utf-8")
            (subdraft / "draft_content.json").write_text(
                json.dumps({"duration": 2}), encoding="utf-8"
            )
            project = CapCutProject(
                "Legacy Fixture", project_path, "legacy-id", 0.0, metadata_path
            )

            live = read_live_project(project)

            self.assertEqual(live.storage_format, "legacy_draft_content")
            self.assertEqual(len(live.draft_paths), 2)
            self.assertEqual(live.primary, draft)

    def test_unknown_schema_fingerprint_is_stable(self):
        first = schema_fingerprint({"tracks": [{"type": "video", "id": "a"}]})
        second = schema_fingerprint({"tracks": [{"type": "video", "id": "b"}]})
        self.assertEqual(first, second)

    def test_skill_frontmatter(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: pleum-capcutedit-macos\n"))
        self.assertIn("\ndescription:", text)
        for name in ("edit-capcut", "pattern-1"):
            nested = (ROOT / f"skills/{name}/SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(nested.startswith(f"---\nname: {name}\n"))

    def test_distribution_audit_synthetic_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "SKILL.md").write_text(
                "---\nname: pleum-capcutedit\ndescription: safe\n---\n", encoding="utf-8"
            )
            self.assertTrue(audit(root)["passed"])

    def test_distribution_audit_rejects_env(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text("SECRET=value", encoding="utf-8")
            self.assertFalse(audit(root)["passed"])

    def test_installer_script_supports_dry_run(self):
        text = (ROOT / "scripts/bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("--dry-run", text)
        self.assertIn("--non-interactive", text)
        installer = (ROOT / "scripts/install_skill.py").read_text(encoding="utf-8")
        self.assertIn('"pleum-capcutedit-macos"', installer)
        self.assertIn('"edit-capcut"', installer)
        self.assertIn('"pattern-1"', installer)

    def test_macos_compatibility_is_feature_scoped(self):
        draft = {"tracks": [{"type": "video", "id": "synthetic"}]}
        fingerprint = schema_fingerprint(draft)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "config/capcut_compatibility.json").write_text(
                json.dumps({
                    "tested_schemas": [{
                        "operating_system": "Darwin (macOS)",
                        "schema_fingerprint": fingerprint,
                        "direct_write_validated": True,
                        "supported_features": ["neutral_caption_injection"],
                    }]
                }),
                encoding="utf-8",
            )
            with patch("schema_compatibility.PROJECT_ROOT", root), patch(
                "schema_compatibility.platform.system", return_value="Darwin"
            ):
                captions = compatibility_status(
                    draft, "neutral_caption_injection"
                )
                karaoke = compatibility_status(draft, "karaoke_direct_write")
            self.assertTrue(captions["write_allowed"])
            self.assertFalse(karaoke["write_allowed"])
            self.assertIn("no macOS", karaoke["guidance"])

    def test_pattern1_runtime_is_bundled(self):
        main = (ROOT / "src/main.py").read_text(encoding="utf-8")
        self.assertIn('"apply-pattern-1"', main)
        self.assertIn('"remove-pattern-1"', main)
        self.assertTrue((ROOT / "src/pattern1_injector.py").is_file())
        self.assertTrue((ROOT / "presets/pattern1/pattern1-plan.example.json").is_file())


if __name__ == "__main__":
    unittest.main()

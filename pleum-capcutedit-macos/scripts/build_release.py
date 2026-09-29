#!/usr/bin/env python3
"""Audit, manifest, checksum, and ZIP Pleum CapCutEdit for macOS."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT.parent
sys.path.insert(0, str(ROOT / "scripts"))
from audit_distribution import PATTERNS, audit


MANUAL = DIST / "START-HERE-Pleum-CapCutEdit-macOS.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def included_files() -> list[Path]:
    excluded = {
        ".git", ".venv", "__pycache__", "output", "logs", "state",
        "temp", "backups", "dist", "input", "sample_capcut_projects",
        "sandbox_capcut_projects",
    }
    return [
        path for path in sorted(ROOT.rglob("*"))
        if path.is_file()
        and path.name != ".env"
        and path.suffix.casefold() not in {".pyc", ".zip"}
        and not any(part in excluded for part in path.relative_to(ROOT).parts)
    ]


def main() -> int:
    audit_path = DIST / "Pleum-CapcutEdit-macOS-audit.json"
    report = audit(ROOT)
    if not MANUAL.is_file():
        report["passed"] = False
        report["findings"].append({
            "file": MANUAL.name, "reason": "distribution_manual_missing"
        })
    else:
        manual_text = MANUAL.read_text(encoding="utf-8", errors="replace")
        manual_findings = [
            {"file": MANUAL.name, "reason": name}
            for name, pattern in PATTERNS.items()
            if pattern.search(manual_text)
        ]
        report["findings"].extend(manual_findings)
        report["passed"] = not report["findings"]
        report["manual"] = MANUAL.name
    audit_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        print(json.dumps(report, indent=2))
        return 1
    files = included_files()
    compatibility = json.loads(
        (ROOT / "config/capcut_compatibility.json").read_text(encoding="utf-8")
    )
    manifest = {
        "name": "pleum-capcutedit-macos",
        "display_name": "Pleum CapCutEdit for macOS",
        "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "bundled_skills": ["pleum-capcutedit-macos", "edit-capcut", "pattern-1"],
        "user_manual": MANUAL.name,
        "included_files": [path.relative_to(ROOT).as_posix() for path in files],
        "required_external_software": ["Python 3.10+", "FFmpeg", "ffprobe", "CapCut Desktop"],
        "optional_dependencies": ["Recipient-owned ElevenLabs API key for uncached transcription"],
        "known_tested_capcut_versions": [
            item["capcut_version"] for item in compatibility["tested_schemas"]
        ],
        "privacy_exclusions": [
            "CapCut projects and drafts", "media", "transcripts", "logs", "state",
            "cache assets", "fonts", "learned local presets", "API keys", "virtual environments",
        ],
        "limitations": [
            "Cartoon workflows are not included",
            "Pattern 1 direct injection requires a recipient-owned local reference project and assets",
            "Unknown CapCut schemas are read-only",
            "Direct writes require an exact macOS schema fingerprint validated for the requested feature",
        ],
    }
    manifest_path = DIST / "Pleum-CapcutEdit-macOS-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zip_path = DIST / "Pleum-CapcutEdit-macOS.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(MANUAL, MANUAL.name)
        for path in files:
            archive.write(path, (Path(ROOT.name) / path.relative_to(ROOT)).as_posix())
    checksum_path = DIST / "Pleum-CapcutEdit-macOS-checksums.txt"
    lines = [
        f"{sha256(path)}  {ROOT.name}/{path.relative_to(ROOT).as_posix()}"
        for path in files
    ]
    lines.extend([
        f"{sha256(MANUAL)}  {MANUAL.name}",
        f"{sha256(zip_path)}  {zip_path.name}",
        f"{sha256(manifest_path)}  {manifest_path.name}",
        f"{sha256(audit_path)}  {audit_path.name}",
    ])
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Built {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

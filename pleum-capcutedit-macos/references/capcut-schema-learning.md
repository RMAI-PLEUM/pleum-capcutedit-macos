# CapCut schema learning on macOS

CapCut structure changes by build and project shape. Fingerprint the selected active draft read-only and compare it with `config/capcut_compatibility.json`. Unknown fingerprints block live writes.

Use only disposable recipient-owned fixtures. Create separate projects for video-only, one neutral caption, several captions, one normal-speed cut, karaoke, duplicate takes, and Pattern 1. For each feature:

1. Close CapCut and copy the entire fixture plus active project registry metadata.
2. Verify exactly two identical active mirrors and record their hashes.
3. Build and validate a timeline-bound dry-run plan.
4. Perform one controlled atomic write on the disposable fixture.
5. Validate IDs, references, tracks, materials, timing, duration, and mirror equality.
6. Roll back and verify byte equality with the original.
7. Reapply, open CapCut, play through the edited boundary, close CapCut, and read both mirrors again.
8. Add the fingerprint and only the proven feature names to compatibility configuration.

Never promote a fingerprint from structural similarity, a successful JSON parse, unit tests alone, or evidence from another operating system. Never distribute fixture projects, media, transcript text, absolute user paths, or local presets.

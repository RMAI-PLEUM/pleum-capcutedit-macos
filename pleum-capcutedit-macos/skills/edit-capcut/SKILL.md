---
name: edit-capcut
description: "Inspect and safely edit local CapCut Desktop projects on macOS with neutral captions, Thai word segmentation, color-only karaoke, duplicate-take cleanup, silence cutting, manual-style learning, editorial selection, validation, recovery, and migration. Use for exact named CapCut project operations on Apple Silicon or Intel Macs that are not Cartoon workflows."
---

# Edit CapCut

Use the runtime from the package root. Read `../../SKILL.md` and `../../references/installation-macos.md` before installation or live writes. Use this skill for ordinary talking-head and caption workflows; Cartoon is out of scope.

## Safety contract

- Inspect before editing and resolve an exact named project.
- Treat unknown CapCut schemas as read-only.
- Require CapCut closed before direct writes.
- Bind plans and caches to the current timeline hash.
- Write both required draft mirrors atomically, keep backups, and validate IDs/timing/tracks after the write.
- Remove or rollback only registry-owned generated objects.
- Never distribute local projects, paths, media, fonts, transcripts, API keys, caches, or learned presets.

## Captions

Use `system-default` unless the recipient requests a locally learned style. It uses no bundled font or personal typography. Set words per caption with `--max-words-per-caption` or the friendly CLI `--max-words`. Preserve Thai combining marks, English, numbers, URLs, and valid UTF-16 ranges. Display-only exclusions may hide configured fillers without cutting their audio.

## Karaoke

Use `karaoke-yellow`. Each state clones the active base caption style and changes only its fill color and UTF-16 range. Font, size, bold, stroke, shadow, spacing, scale, position, and animation must remain unchanged. Validate duplicate objects and style drift after injection.

## Duplicate takes and silence

Select semantic takes before tightening silence. Treat restart markers as evidence, not proof. Prefer a complete fluent take, preserve meaning and terminal phonemes, then inspect no-word gaps with local audio energy. Dry-run first; ripple only supported tracks and reject overlap, tiny debris, stale transcript provenance, or unsupported timeline structures.

## Manual-style learning

Learn only from recipient-owned automatic/manual pairs created from the same source media. Compare source timeranges and semantic selections, not just target positions. Store learned output locally and do not add it to a distributable package.

## References

- [references/privacy-and-sharing.md](references/privacy-and-sharing.md)
- [references/captions.md](references/captions.md)
- [references/thai-caption-rules.md](references/thai-caption-rules.md)
- [references/karaoke.md](references/karaoke.md)
- [references/duplicate-takes.md](references/duplicate-takes.md)
- [references/silence-cut.md](references/silence-cut.md)
- [references/manual-edit-style.md](references/manual-edit-style.md)
- [references/validation-and-recovery.md](references/validation-and-recovery.md)
- [references/capcut-schema-learning.md](references/capcut-schema-learning.md)
- [references/neutral-style-learning.md](references/neutral-style-learning.md)

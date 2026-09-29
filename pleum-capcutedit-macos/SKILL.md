---
name: pleum-capcutedit-macos
description: "Install and operate a privacy-safe CapCut Desktop editing toolkit on macOS. Use when Codex or Claude must discover or inspect local CapCut 9+ projects, transcribe speech with recipient-owned ElevenLabs credentials, generate Thai or neutral captions, add color-only karaoke, remove duplicate takes or silence, learn a local manual style, apply Pattern 1 from recipient-owned references, validate mirrored drafts, or recover registered edits on Apple Silicon or Intel Macs. Cartoon workflows are excluded."
---

# Pleum CapCutEdit for macOS

Operate from this skill directory. Use the bundled `.venv/bin/edit-capcut` CLI after installation. Never copy credentials, projects, media, transcripts, learned presets, caches, or machine paths into a distributable artifact.

## Safety contract

1. Resolve an exact user-visible project name and inspect it before editing.
2. Treat unknown schema fingerprints as read-only; never bypass the compatibility gate on a recipient's only project copy.
3. Bind transcripts and plans to the current timeline hash.
4. Dry-run every edit and inspect its report before writing.
5. Require CapCut to be closed, two identical active `draft_info.json` mirrors, and writable verified paths.
6. Back up every file that will change, replace mirrors atomically, then validate IDs, timing, tracks, materials, registry, and duration.
7. Reopen CapCut and perform a second read-back. Keep rollback metadata until the recipient confirms playback.
8. Remove only objects recorded in this toolkit's registries.

CapCut 9+ on macOS normally stores one active mirror at the project root and another under the `main_timeline_id` in `Timelines/project.json`. Ignore `.bak`, patch, template, temporary, subdraft, and Recycle Bin copies.

## First run

```bash
sh install.sh --check-only
sh install.sh
./.venv/bin/edit-capcut doctor
./.venv/bin/edit-capcut macos-validate
```

Copy `.env.example` to `.env` and let the recipient enter their own `ELEVENLABS_API_KEY` only when fresh transcription is needed. Do not print or inspect the key value.

To install the bundled umbrella and component skills into a repository:

```bash
./.venv/bin/python scripts/install_skill.py \
  --tool codex --project-path "/absolute/path/to/repository" --dry-run
```

Review the destinations, then rerun without `--dry-run`. Read [references/installation-macos.md](references/installation-macos.md) for prerequisites and other supported hosts.

## Operation workflow

1. Run `doctor` and `macos-validate` read-only.
2. Inspect the exact project.
3. Reuse only a timeline-matched transcript cache; otherwise transcribe with Scribe v2.
4. Select semantic takes before tightening silence.
5. Generate and validate a dry-run plan.
6. Write only when the schema reports `write_allowed: true` and all safety checks pass.
7. Reinspect both mirrors, reopen CapCut, and retain the backup.

Common commands:

```bash
./.venv/bin/edit-capcut inspect --project "Exact Project Name"
./.venv/bin/edit-capcut captions --project "Exact Project Name" --preset system-default --dry-run
./.venv/bin/edit-capcut karaoke --project "Exact Project Name" --preset karaoke-yellow --dry-run
./.venv/bin/edit-capcut duplicate-takes --project "Exact Project Name" --dry-run
./.venv/bin/edit-capcut silence-cut --project "Exact Project Name" --preset shorts-clean --dry-run
```

Remove `--dry-run` only after reviewing the report and closing CapCut. Use `system-default` captions unless the recipient explicitly learns a local style. Use `karaoke-yellow` to change only the active word's fill color; never scale or restyle highlighted text.

## macOS compatibility policy

`config/capcut_compatibility.json` is authoritative. Direct writes are enabled only for exact macOS schema fingerprints with `direct_write_validated: true`. This release includes controlled reopen evidence for neutral caption injection and normal-speed silence cuts on the listed CapCut 9.1 schema. Other fingerprints and unlisted features remain dry-run/read-only until a disposable recipient-owned fixture passes write, rollback, reopen, and second read-back.

Read [references/capcut-schema-learning.md](references/capcut-schema-learning.md) before validating a new CapCut build. Never edit the compatibility file from inference alone.

## Capability references

- Captions and Thai text: [references/captions.md](references/captions.md) and [references/thai-caption-rules.md](references/thai-caption-rules.md)
- Karaoke: [references/karaoke.md](references/karaoke.md)
- Duplicate takes and silence: [references/duplicate-takes.md](references/duplicate-takes.md), [references/silence-cut.md](references/silence-cut.md), and [references/natural-pause.md](references/natural-pause.md)
- Cache and ElevenLabs: [references/cache-and-elevenlabs.md](references/cache-and-elevenlabs.md)
- Manual/local styles: [references/manual-edit-style.md](references/manual-edit-style.md) and [references/neutral-style-learning.md](references/neutral-style-learning.md)
- Validation and recovery: [references/validation-and-recovery.md](references/validation-and-recovery.md)
- Pattern 1: read `skills/pattern-1/SKILL.md`; use only recipient-owned local reference assets.

Do not use or recreate Cartoon workflows.

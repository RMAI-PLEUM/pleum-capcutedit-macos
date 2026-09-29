# macOS installation

## Prerequisites

- macOS on Apple Silicon or Intel
- CapCut Desktop 9 or newer
- Python 3.10 or newer
- FFmpeg and ffprobe
- Internet access for installation and uncached ElevenLabs transcription

Homebrew is optional. A typical Homebrew setup is:

```bash
brew install python ffmpeg
```

## Install the runtime

Run from the extracted `pleum-capcutedit-macos` directory:

```bash
sh install.sh --check-only
sh install.sh
./.venv/bin/edit-capcut doctor
```

The installer creates a local `.venv`; it does not modify a CapCut project. Copy `.env.example` to `.env` only when fresh transcription is needed, then let the recipient enter their own ElevenLabs key.

## Select and audit CapCut storage

The setup code verifies candidate roots by parsing project metadata. Common candidates include CapCut data under `Movies`, `Library/Application Support`, and the CapCut sandbox container. Do not hardcode another person's home directory.

```bash
./.venv/bin/edit-capcut setup
./.venv/bin/edit-capcut macos-validate
./.venv/bin/edit-capcut inspect --project "Exact Project Name"
```

CapCut 9+ uses two active `draft_info.json` mirrors: one at the project root and another under the `main_timeline_id` in `Timelines/project.json`. Ignore Recycle Bin, `.bak`, patch, template, temporary, and subdraft files.

## Direct-write gate

`--dry-run` never writes CapCut files. A real write requires CapCut closed, two identical mirrors, a fresh timeline hash, an exact schema fingerprint marked `direct_write_validated`, atomic replacement, and post-write validation. Unknown or read-only fingerprints must remain dry-run until a disposable fixture passes write, rollback, CapCut reopen, and second read-back.

macOS may require the user to approve Terminal, Codex, or Claude access to `Movies` or `Library` in System Settings. Request only the narrow folder access needed for the selected project.

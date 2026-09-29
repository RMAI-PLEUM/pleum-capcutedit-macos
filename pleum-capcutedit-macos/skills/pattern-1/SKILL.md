---
name: pattern-1
description: "Apply Pattern 1 to a non-Cartoon talking-head CapCut project using a recipient-owned local reference. Use for semantic SFX, sparse chapter transitions, subtle clause-level slow zooms, one-word neutral captions, a color-emphasis CTA, dry-run validation, registered cleanup, or safe reapplication after timeline changes."
---

# Pattern 1

Read the sibling `edit-capcut` skill first. Pattern 1 adds deliberate semantic emphasis after speech, take, and silence editing are complete.

## Included behavior

- Map hook, teaching chapters, examples, warning/recap, and CTA.
- Use one spoken word per ordinary caption with the neutral/local base caption style.
- Add sparse SFX, mostly hard cuts, selected chapter transitions, and subtle clause-level zooms.
- Replace one registered CTA keyword caption with a single emphasized callout; do not duplicate it.
- Register every generated object so removal affects only Pattern 1 objects.

No font, SFX, effect, animation, media, or reference project is bundled. The recipient must own a compatible local reference project containing every requested asset/template. Default text remains system-neutral; a CTA may change color only unless the recipient explicitly supplies another local style.

## Workflow

1. Finish and validate speech/take/silence edits.
2. Generate and register captions, normally one word each with `system-default`.
3. Analyze the current timeline and create a semantic plan from `presets/pattern1/pattern1-plan.example.json`.
4. Match every plan template name to a recipient-owned local reference project.
5. Dry-run `apply-pattern-1`; reject duration, segment-count, caption-count, asset, schema, or mirror mismatches.
6. Close CapCut, apply, reopen, and review seams, readability, SFX timing, zoom continuity, and CTA duplication.

## Commands

```bash
./.venv/bin/edit-capcut pattern1-apply --project "Target" --reference-project "Local Pattern Reference" --plan "presets/pattern1/my-plan.json" --dry-run
./.venv/bin/edit-capcut pattern1-apply --project "Target" --reference-project "Local Pattern Reference" --plan "presets/pattern1/my-plan.json"
./.venv/bin/edit-capcut pattern1-remove --project "Target" --dry-run
./.venv/bin/edit-capcut pattern1-remove --project "Target"
```

Read [references/pattern-1-rules.md](references/pattern-1-rules.md) before building a plan.

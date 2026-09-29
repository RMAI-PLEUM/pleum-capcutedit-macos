# Manual edit style learning

Use this workflow only with recipient-owned source and manual-reference projects made from the same dominant media.

1. Prove the media identity and compare source timeranges, not target positions.
2. Run `learn-manual-edit-style` read-only. Inspect semantic recall, precision, retained ranges, cadence, frame grid, speech handles, and timeline integrity.
3. Outline the complete story beats. Group alternate attempts by meaning and role, then keep one complete fluent take per beat in narrative order.
4. Treat restart markers as supporting evidence only. Require semantic duplication, prefix continuation, or strong sequence similarity.
5. Separate an abandoned trailing prefix from an otherwise complete setup. Remove only the abandoned attempt.
6. Refine retained ranges against local waveform/phoneme energy. Provider word timestamps are soft boundaries and may contain quiet leads or tails.
7. Cross a provider timestamp only when the removed part has no audible phoneme, post-edit transcription retains the word, and important meaning is unchanged.
8. Preserve audible terminal words and particles that complete a clause. Keep intentional pauses attached to spoken segments.
9. Remove speechless residual islands and reject overlaps or automatic fragments shorter than two frames.
10. Dry-run the editorial selection plan, apply the same timeline-hash-bound plan, re-transcribe or safely retime, then run silence cleanup.

General observations are guidance, not quotas: retained talking-head sections commonly land around a few seconds, joins are aligned on the frame grid, semantic take selection happens before silence tightening, and output/source ratio is diagnostic only. Learn recipient-specific timing from local examples before direct editing.

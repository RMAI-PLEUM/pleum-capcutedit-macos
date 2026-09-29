"""Registry reconciliation for karaoke segments transformed by ripple cuts."""

from registered_caption_retimer import active_registered_ids


def coalesce_identical_adjacent_states(
    draft: dict, track_id: str | None
) -> tuple[dict, int]:
    """Undo harmless same-material fragments created by a ripple split."""
    from copy import deepcopy
    modified = deepcopy(draft)
    merged_count = 0
    for track in modified.get("tracks", []):
        if track.get("id") != track_id:
            continue
        output = []
        for segment in sorted(
            track.get("segments", []),
            key=lambda item: item.get("target_timerange", {}).get("start", 0),
        ):
            if output:
                previous = output[-1]
                prior_range = previous.get("target_timerange") or {}
                current_range = segment.get("target_timerange") or {}
                prior_end = prior_range.get("start", 0) + prior_range.get("duration", 0)
                if (
                    prior_end == current_range.get("start")
                    and previous.get("material_id") == segment.get("material_id")
                    and {
                        key: value for key, value in previous.items()
                        if key not in {"id", "target_timerange", "render_timerange"}
                    } == {
                        key: value for key, value in segment.items()
                        if key not in {"id", "target_timerange", "render_timerange"}
                    }
                ):
                    prior_range["duration"] += current_range["duration"]
                    if isinstance(previous.get("render_timerange"), dict):
                        previous["render_timerange"]["duration"] = prior_range["duration"]
                    merged_count += 1
                    continue
            output.append(segment)
        track["segments"] = output
    return modified, merged_count


__all__ = ["active_registered_ids", "coalesce_identical_adjacent_states"]

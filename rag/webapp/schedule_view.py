"""Pure presentation helper for /schedule: lays out schedule_builder.py's
blocks by day for the visual grid. No Flask, no file I/O -- takes the same
schedule dict schedule_builder.load()/save() already use."""

from __future__ import annotations

import schedule_builder as SB


def grouped_by_day(schedule: dict) -> list[tuple[str, list[dict]]]:
    """(day, blocks) for every day in SB.DAYS order, blocks sorted by start
    time -- always all 7 days, even empty ones, so the grid has a stable
    7-column shape regardless of what's scheduled. Each block dict carries
    an extra "index" key -- its position in schedule["blocks"], the flat
    list /schedule/remove pops from -- since the same block can appear
    under several days and a day's own sorted order isn't that index --
    plus "top_pct"/"height_pct" (see block_position()) for the drag-and-drop
    hour grid to position it absolutely within its day column."""
    indexed = [dict(block, index=i, **block_position(block)) for i, block in enumerate(schedule["blocks"])]
    return [
        (day, sorted((b for b in indexed if day in b["days"]), key=lambda b: b["start"]))
        for day in SB.DAYS
    ]


HOUR_LABELS = [
    "12 AM" if h == 0 else "12 PM" if h == 12 else f"{h % 12} AM" if h < 12 else f"{h % 12} PM"
    for h in range(24)
]

MINUTES_PER_DAY = 24 * 60


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def analysis_targets(schedule: dict) -> list[tuple[str, str]]:
    """(category, combined_label) for every research-relevant category
    present in the schedule -- one evidence lookup per category, not per
    individual block, so three separate "gym" blocks still produce one
    consolidated question rather than three near-duplicate ones. Sorted by
    category name for a deterministic report order."""
    by_category: dict[str, list[str]] = {}
    for block in schedule["blocks"]:
        if block["category"] not in SB._RESEARCH_RELEVANT_CATEGORIES:
            continue
        labels = by_category.setdefault(block["category"], [])
        if block["label"] not in labels:
            labels.append(block["label"])
    return [(category, ", ".join(by_category[category])) for category in sorted(by_category)]


def block_position(block: dict) -> dict:
    """top_pct/height_pct (0-100, as plain floats) locating this block
    within a day column whose full height represents one 24h day -- used
    for absolute CSS positioning (top: {{ top_pct }}%; height: {{
    height_pct }}%;) in the drag-and-drop grid. A block never spans
    midnight (add_block() already rejects end <= start), so this is exact,
    not a wraparound approximation."""
    start = _minutes(block["start"])
    end = _minutes(block["end"])
    return {
        "top_pct": round(start / MINUTES_PER_DAY * 100, 3),
        "height_pct": round((end - start) / MINUTES_PER_DAY * 100, 3),
    }

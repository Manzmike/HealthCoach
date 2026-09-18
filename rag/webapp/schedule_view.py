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
    under several days and a day's own sorted order isn't that index."""
    indexed = [dict(block, index=i) for i, block in enumerate(schedule["blocks"])]
    return [
        (day, sorted((b for b in indexed if day in b["days"]), key=lambda b: b["start"]))
        for day in SB.DAYS
    ]

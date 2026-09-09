"""Apply lane_map.json's folder->lane assignments to the live chunks table.
Idempotent: re-running re-asserts the same values, never errors or double-counts."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_lane_map() -> dict[str, str]:
    with (HERE / "lane_map.json").open(encoding="utf-8") as f:
        return json.load(f)


def apply(tbl, lane_map: dict[str, str]) -> int:
    """Set tbl.lane = <lane> for every row whose folder is an exact key match.
    Returns the total number of rows updated across all mappings."""
    total = 0
    for folder, lane in lane_map.items():
        escaped = folder.replace("'", "''")
        result = tbl.update(where=f"folder = '{escaped}'", values={"lane": lane})
        total += result.rows_updated
    return total


if __name__ == "__main__":
    import os
    import lancedb

    DBDIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lancedb")
    db = lancedb.connect(DBDIR)
    tbl = db.open_table("chunks")
    n = apply(tbl, load_lane_map())
    print(f"lane_map applied: {n} rows updated across {len(load_lane_map())} folders")

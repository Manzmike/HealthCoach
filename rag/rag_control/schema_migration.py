"""One-shot, idempotent schema migration: adds the control-layer columns
that ingest.py's original schema never had (lane, personal, quarantined,
quarantine_reason, geography). Safe to run multiple times."""

from __future__ import annotations

NEW_COLUMNS = {
    "lane": "CAST(NULL AS STRING)",
    "personal": "false",
    "quarantined": "false",
    "quarantine_reason": "CAST(NULL AS STRING)",
    "geography": "CAST(NULL AS STRING)",
}


def add_control_columns(tbl) -> None:
    """Add the 5 control-layer columns to `tbl` if they are not already present."""
    existing = {f.name for f in tbl.schema}
    missing = {name: expr for name, expr in NEW_COLUMNS.items() if name not in existing}
    if not missing:
        return
    tbl.add_columns(missing)


if __name__ == "__main__":
    import os
    import lancedb

    DBDIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lancedb")
    db = lancedb.connect(DBDIR)
    tbl = db.open_table("chunks")
    before = {f.name for f in tbl.schema}
    add_control_columns(tbl)
    after = {f.name for f in tbl.schema}
    print("added columns:", sorted(after - before) or "(none — already present)")

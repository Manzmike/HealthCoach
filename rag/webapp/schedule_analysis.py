"""Persists the last schedule analysis and tells /schedule whether the
current blocks still match what was analyzed -- the gate that decides
whether .ics download is offered. Private state, same convention as
labs.py's .healthcoach/labs.json (gitignored, this machine only).

Deliberately its own file rather than a new key inside schedule_calendar.json:
schedule_builder.py's CLI tools (and their tests) read/write that file
completely unaware of the web GUI, and should stay that way."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.dirname(__file__))  # rag/
DEFAULT_PATH = Path(HERE) / ".healthcoach" / "schedule_analysis.json"


def load(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save(snapshot: list[dict], results: list[dict], *, analyzed_at: str, path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "snapshot": snapshot, "results": results, "analyzed_at": analyzed_at,
    }, indent=2))


def is_current(schedule: dict, analysis: dict[str, Any]) -> bool:
    """True only when the schedule has at least one block and its blocks
    are byte-for-byte what was last analyzed -- adding, removing, or
    editing any block invalidates it (no partial-credit tracking)."""
    blocks = schedule.get("blocks", [])
    return bool(blocks) and blocks == analysis.get("snapshot")

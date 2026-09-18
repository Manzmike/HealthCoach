"""In-progress weekly-selection draft for /food, keyed by week start date.
week_plan.py's own save() requires one reason for the whole week's diff and
writes straight to history -- exactly right for an explicit "Save this
week" action, wrong for every individual select/unselect click along the
way. This holds those in-between clicks in their own private file (this
machine only) until Save actually commits them through week_plan.save(),
the same draft/baseline distinction week_planner.py's curses UI keeps in
memory for one session -- persisted here instead, since HTTP requests are
stateless across page loads."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.dirname(__file__))  # rag/
DEFAULT_PATH = Path(HERE) / ".healthcoach" / "food_draft.json"


def load_draft(start: str, path: Path = DEFAULT_PATH) -> dict[str, Any] | None:
    """The in-progress week dict for this start date, or None if there is
    no draft on file for it (a fresh baseline should be used instead)."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data.get(start) if isinstance(data, dict) else None


def save_draft(start: str, week: dict[str, Any], path: Path = DEFAULT_PATH) -> None:
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    data[start] = week
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def clear_draft(start: str, path: Path = DEFAULT_PATH) -> None:
    """Called once a draft is actually committed via week_plan.save() (the
    new saved week becomes the baseline, so there's nothing left to draft)
    or explicitly discarded. A no-op if there was never a draft for this
    week -- never an error."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if isinstance(data, dict) and start in data:
        del data[start]
        path.write_text(json.dumps(data, indent=2))

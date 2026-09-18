"""Persists the last food-selection analysis for /food -- advisory only,
same pattern as webapp/schedule_analysis.py, but food has no download gate
attached to it (the .ics gate exists because an external calendar app
imports that file sight-unseen; the food export is a plain-text summary
you read yourself, so there's nothing to gate). Private state, gitignored,
this machine only."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.dirname(__file__))  # rag/
DEFAULT_PATH = Path(HERE) / ".healthcoach" / "food_analysis.json"


def load(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save(foods: list[str], sections: list[dict], *, analyzed_at: str, path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"foods": foods, "sections": sections, "analyzed_at": analyzed_at}, indent=2))

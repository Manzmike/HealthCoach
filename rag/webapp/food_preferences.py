"""Private, durable diet choices for the web food selector.

The rule definitions remain in :mod:`diet_rules`; this module only stores the
user's selected preset and exclusion toggles so the browser flow can apply the
same inspectable gate on every request. The file is local-only and gitignored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import diet_rules as DR

HERE = Path(__file__).resolve().parent.parent
DEFAULT_PATH = HERE / ".healthcoach" / "food_preferences.json"


def default() -> dict[str, Any]:
    return {"diet": "whole_food", "toggles": []}


def normalize(value: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    diet = str(raw.get("diet") or "whole_food").strip()
    if diet not in DR.DIET_PRESETS:
        raise ValueError(f"Unknown diet preset: {diet}")
    raw_toggles = raw.get("toggles", ())
    if isinstance(raw_toggles, str):
        raw_toggles = [raw_toggles]
    if not isinstance(raw_toggles, (list, tuple, set, frozenset)):
        raise ValueError("Diet toggles must be a list")
    toggles = sorted({str(toggle).strip() for toggle in raw_toggles if str(toggle).strip()})
    # Let the canonical rule engine validate names and preserve one source of truth.
    DR.excluded_ids_for(diet, set(toggles))
    return {"diet": diet, "toggles": toggles}


def load(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default()
    try:
        return normalize(value)
    except ValueError:
        return default()


def save(value: Mapping[str, Any], path: Path = DEFAULT_PATH) -> None:
    normalized = normalize(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")

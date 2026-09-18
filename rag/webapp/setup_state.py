"""Small local state store for the browser setup walkthrough.

The walkthrough state is deliberately separate from the health data stores:
resetting setup never deletes or rewrites a diet, goal, lab, symptom, or
schedule record. It only controls whether the first-run orientation is shown.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent.parent
DEFAULT_PATH = HERE / ".healthcoach" / "web_setup.json"
STEPS = ("diet", "goals")


def empty() -> dict[str, Any]:
    return {"complete": False, "steps": {step: False for step in STEPS}}


def _normalize(value: Any) -> dict[str, Any]:
    base = empty()
    if not isinstance(value, dict):
        return base
    steps = value.get("steps", {})
    if isinstance(steps, dict):
        for step in STEPS:
            base["steps"][step] = bool(steps.get(step, False))
    base["complete"] = bool(value.get("complete", False))
    if not all(base["steps"].values()):
        base["complete"] = False
    return base


def _target(path: str | Path | None) -> Path:
    return Path(path) if path is not None else DEFAULT_PATH


def load(path: str | Path | None = None) -> dict[str, Any]:
    try:
        value = json.loads(_target(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return empty()
    return _normalize(value)


def save(value: dict[str, Any], path: str | Path | None = None) -> None:
    target = _target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_normalize(value), indent=2) + "\n", encoding="utf-8")


def mark_step(step: str, *, path: str | Path | None = None) -> dict[str, Any]:
    if step not in STEPS:
        raise ValueError(f"Unknown setup step: {step}")
    state = load(path)
    state["steps"][step] = True
    state["complete"] = all(state["steps"].values())
    save(state, path)
    return state


def mark_complete(*, path: str | Path | None = None) -> dict[str, Any]:
    state = load(path)
    if not all(state["steps"].values()):
        raise ValueError("Complete the required setup steps first.")
    state["complete"] = True
    save(state, path)
    return state


def reset(*, path: str | Path | None = None) -> dict[str, Any]:
    state = empty()
    save(state, path)
    return state

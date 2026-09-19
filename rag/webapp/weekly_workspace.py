"""Local, date-keyed state for the HealthCoach weekly planning workspace.

This module is deliberately framework-free. Flask routes can use it without
making date-window, normalization, or workout-generation behavior depend on
request state, and the same helpers are easy to exercise in isolation.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent.parent
DEFAULT_PATH = HERE / ".healthcoach" / "weekly_workspace.json"
WEEK_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SECTIONS = ("symptoms", "workouts", "lifestyle", "meals")

WORKOUT_LEVELS = (
    ("beginner", "Beginner / returning"),
    ("intermediate", "Intermediate"),
    ("advanced", "Advanced"),
)
WORKOUT_TARGETS = (
    ("build_strength", "Build strength"),
    ("improve_fitness", "Improve fitness"),
    ("support_recovery", "Support recovery"),
    ("build_consistency", "Build consistency"),
)
WORKOUT_FOCUSES = (
    ("full_body", "Full body"),
    ("strength", "Strength"),
    ("conditioning", "Conditioning"),
    ("mobility", "Mobility"),
)
LIFESTYLE_HABITS = (
    ("desk_work", "Mostly desk-based days"),
    ("irregular_sleep", "Irregular sleep schedule"),
    ("high_stress", "High daily stress"),
    ("sleep_consistency", "Consistent sleep and wake time"),
    ("morning_light", "Morning outdoor light"),
    ("walking_breaks", "Walking or movement breaks"),
    ("stress_recovery", "Stress-recovery practice"),
    ("hydration", "Consistent hydration"),
    ("screen_boundaries", "Evening screen boundaries"),
    ("social_connection", "Regular social connection"),
)


def _valid_start(start: str) -> str:
    try:
        return dt.date.fromisoformat(str(start)).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("Week start must use YYYY-MM-DD format.") from exc


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(_text(item) for item in value if _text(item)))


def week_dates(start: str) -> tuple[str, str]:
    normalized = _valid_start(start)
    first = dt.date.fromisoformat(normalized)
    return normalized, (first + dt.timedelta(days=6)).isoformat()


def is_editable(start: str, today: dt.date | None = None) -> bool:
    normalized, end = week_dates(start)
    current = today or dt.date.today()
    return dt.date.fromisoformat(normalized) <= current <= dt.date.fromisoformat(end)


def empty_week(start: str) -> dict[str, Any]:
    normalized = _valid_start(start)
    return {
        "start": normalized,
        "symptoms": {"selected": [], "notes": ""},
        "workouts": {
            "current_level": "beginner",
            "target": "build_consistency",
            "days": ["Mon", "Wed", "Fri"],
            "focus": "full_body",
            "constraints": "",
            "sessions": [],
        },
        "lifestyle": {"current": [], "target": [], "notes": "", "calendar_snapshot": []},
        "meals": [{"name": "", "notes": ""} for _ in range(3)],
        "food_context": [],
        "analysis": {section: {"snapshot": "", "sections": [], "analyzed_at": ""} for section in SECTIONS},
    }


def _meal_rows(raw: Any, count: int) -> list[dict[str, str]]:
    source = raw if isinstance(raw, list) else []
    rows = []
    for item in source[:7]:
        item = item if isinstance(item, Mapping) else {}
        rows.append({"name": _text(item.get("name")), "notes": _text(item.get("notes"))})
    while len(rows) < count:
        rows.append({"name": "", "notes": ""})
    return rows[:count]


def normalize_week(value: Mapping[str, Any] | None, start: str | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    normalized_start = _valid_start(start or raw.get("start"))
    result = empty_week(normalized_start)

    symptoms = raw.get("symptoms") if isinstance(raw.get("symptoms"), Mapping) else {}
    result["symptoms"] = {
        "selected": _unique_strings(symptoms.get("selected")),
        "notes": _text(symptoms.get("notes")),
    }

    workouts = raw.get("workouts") if isinstance(raw.get("workouts"), Mapping) else {}
    levels = {key for key, _ in WORKOUT_LEVELS}
    targets = {key for key, _ in WORKOUT_TARGETS}
    focuses = {key for key, _ in WORKOUT_FOCUSES}
    days = [day for day in _unique_strings(workouts.get("days")) if day in WEEK_DAYS]
    result["workouts"] = {
        "current_level": _text(workouts.get("current_level")) if _text(workouts.get("current_level")) in levels else "beginner",
        "target": _text(workouts.get("target")) if _text(workouts.get("target")) in targets else "build_consistency",
        "days": days or ["Mon", "Wed", "Fri"],
        "focus": _text(workouts.get("focus")) if _text(workouts.get("focus")) in focuses else "full_body",
        "constraints": _text(workouts.get("constraints")),
        "sessions": [dict(session) for session in workouts.get("sessions", []) if isinstance(session, Mapping)],
    }

    lifestyle = raw.get("lifestyle") if isinstance(raw.get("lifestyle"), Mapping) else {}
    habit_keys = {key for key, _ in LIFESTYLE_HABITS}
    result["lifestyle"] = {
        "current": [item for item in _unique_strings(lifestyle.get("current")) if item in habit_keys],
        "target": [item for item in _unique_strings(lifestyle.get("target")) if item in habit_keys],
        "notes": _text(lifestyle.get("notes")),
        "calendar_snapshot": [dict(block) for block in lifestyle.get("calendar_snapshot", []) if isinstance(block, Mapping)],
    }

    raw_meals = raw.get("meals")
    requested_count = raw.get("meal_count")
    if requested_count is None:
        requested_count = min(len(raw_meals), 7) if isinstance(raw_meals, list) and raw_meals else 3
    try:
        meal_count = int(requested_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("Meal count must be a whole number from 1 to 7.") from exc
    if not 1 <= meal_count <= 7:
        raise ValueError("Meal count must be a whole number from 1 to 7.")
    result["meals"] = _meal_rows(raw_meals, meal_count)

    raw_analysis = raw.get("analysis") if isinstance(raw.get("analysis"), Mapping) else {}
    result["food_context"] = _unique_strings(raw.get("food_context"))
    result["analysis"] = {}
    for section in SECTIONS:
        analysis = raw_analysis.get(section) if isinstance(raw_analysis.get(section), Mapping) else {}
        result["analysis"][section] = {
            "snapshot": _text(analysis.get("snapshot")),
            "sections": [dict(item) for item in analysis.get("sections", []) if isinstance(item, Mapping)],
            "analyzed_at": _text(analysis.get("analyzed_at")),
        }
    return result


def _target(path: str | Path | None) -> Path:
    return Path(path) if path is not None else DEFAULT_PATH


def load(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(_target(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, Mapping):
        return {}
    weeks = {}
    for key, value in raw.items():
        try:
            weeks[_valid_start(key)] = normalize_week(value, key)
        except ValueError:
            continue
    return weeks


def save_week(week: Mapping[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    normalized = normalize_week(week)
    target = _target(path)
    weeks = load(target)
    weeks[normalized["start"]] = normalized
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(weeks, indent=2) + "\n", encoding="utf-8")
    return normalized


def get_week(start: str, path: str | Path | None = None) -> dict[str, Any]:
    normalized = _valid_start(start)
    return load(path).get(normalized, empty_week(normalized))


def analysis_snapshot(week: Mapping[str, Any], section: str) -> str:
    if section not in SECTIONS:
        raise ValueError(f"Unknown weekly analysis section: {section}")
    payload = dict(week.get(section, {})) if isinstance(week.get(section), Mapping) else {}
    if section == "workouts":
        payload.pop("sessions", None)
    if section == "meals":
        payload["food_context"] = _unique_strings(week.get("food_context"))
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def analysis_is_current(week: Mapping[str, Any], section: str) -> bool:
    analysis = week.get("analysis", {}).get(section, {}) if isinstance(week.get("analysis"), Mapping) else {}
    return bool(analysis.get("analyzed_at")) and analysis.get("snapshot") == analysis_snapshot(week, section)


def generate_workouts(current_level: str, target: str, days: list[str], focus: str, constraints: str) -> list[dict[str, str]]:
    level_labels = dict(WORKOUT_LEVELS)
    target_labels = dict(WORKOUT_TARGETS)
    focus_labels = dict(WORKOUT_FOCUSES)
    level = level_labels.get(current_level, level_labels["beginner"])
    target_label = target_labels.get(target, target_labels["build_consistency"])
    focus_label = focus_labels.get(focus, focus_labels["full_body"])
    selected = [day for day in WEEK_DAYS if day in set(days)]
    sessions = []
    for index, day in enumerate(selected):
        emphasis = ("Strength + technique", "Conditioning + mobility", "Full-body practice")[index % 3]
        notes = f"{level} plan for {target_label.lower()} with {focus_label.lower()} emphasis."
        if constraints:
            notes += f" Respect this constraint: {constraints}."
        sessions.append({
            "day": day,
            "title": f"{focus_label} · {emphasis}",
            "duration": "30–45 minutes",
            "notes": notes,
        })
    return sessions

"""One-time browser intake and review state.

The browser form is deliberately a draft. Existing local records are shown as
context, the user fills only what is missing, and nothing is committed until
the review screen's explicit confirmation. The small legacy fields that the
food and candidate systems already consume are copied into their existing
stores at commit time; richer context stays in this local intake record until
other views are ready to use it.
"""

from __future__ import annotations

import json
import datetime as dt
from pathlib import Path
from typing import Any, Mapping

import candidate_ledger as CL
import diet_rules as DR
from webapp import food_preferences as FoodP


HERE = Path(__file__).resolve().parent.parent
DEFAULT_PATH = HERE / ".healthcoach" / "web_intake.json"


def empty_dexa() -> dict[str, str]:
    return {
        "scan_date": "",
        "body_fat_pct": "",
        "lean_mass_kg": "",
        "fat_mass_kg": "",
        "visceral_fat": "",
        "bmc_kg": "",
        "notes": "",
    }


def empty() -> dict[str, Any]:
    return {
        "diet": "whole_food",
        "toggles": [],
        "health_goals": [],
        "weight_direction": "unknown",
        "body_goals": "",
        "lifestyle_goals": "",
        "bodyweight_kg": "",
        "height_cm": "",
        "age_years": "",
        "sex": "unknown",
        "current_lifestyle": "",
        "current_sport": "",
        "schedule_notes": "",
        "symptoms": "",
        "dexa": empty_dexa(),
        "updated_at": "",
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize(value: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    result = empty()
    result["diet"] = _text(raw.get("diet")) or result["diet"]
    if result["diet"] not in DR.DIET_PRESETS:
        raise ValueError(f"Unknown diet preset: {result['diet']}")
    toggles = raw.get("toggles", [])
    if isinstance(toggles, str):
        toggles = [toggles]
    result["toggles"] = sorted({_text(item) for item in toggles if _text(item)})
    # The canonical diet engine remains the validator for exclusion names.
    DR.excluded_ids_for(result["diet"], set(result["toggles"]))
    goals = raw.get("health_goals", [])
    if isinstance(goals, str):
        goals = [goals]
    result["health_goals"] = list(dict.fromkeys(_text(item) for item in goals if _text(item)))
    if not result["health_goals"]:
        raise ValueError("Answer every required section: choose at least one health goal, or write the goal that matters most.")
    if len(result["health_goals"]) > 3:
        raise ValueError("Choose no more than three health goals, in priority order.")
    allowed_goals = set(CL.OUTCOME_REASON_KEYS)
    if set(result["health_goals"]) - allowed_goals:
        raise ValueError("Choose health goals from the provided list.")
    result["weight_direction"] = _text(raw.get("weight_direction")) or "unknown"
    if result["weight_direction"] not in CL.WEIGHT_DIRECTIONS:
        raise ValueError("Choose a valid weight direction.")

    for key in ("body_goals", "lifestyle_goals", "current_lifestyle", "current_sport",
                "schedule_notes", "symptoms"):
        result[key] = _text(raw.get(key))
        if not result[key]:
            raise ValueError("Answer every required section, or write 'none' where it does not apply.")

    for key in ("bodyweight_kg", "height_cm", "age_years"):
        result[key] = _text(raw.get(key))
        if not result[key]:
            raise ValueError("Answer every required section, including your current body measurements.")
    # Reuse the ledger's established safety ranges and numeric parsing.
    CL.normalize_intake({
        "goals": result["health_goals"],
        "weight_direction": result["weight_direction"],
        "bodyweight_kg": result["bodyweight_kg"],
        "height_cm": result["height_cm"],
        "age_years": result["age_years"],
        "sex": _text(raw.get("sex")) or "unknown",
    })
    result["sex"] = _text(raw.get("sex")) or "unknown"

    dexa = raw.get("dexa") if isinstance(raw.get("dexa"), Mapping) else raw
    for key in result["dexa"]:
        result["dexa"][key] = _text(dexa.get(key))
    if result["dexa"]["scan_date"] and len(result["dexa"]["scan_date"]) != 10:
        raise ValueError("DEXA scan date must use YYYY-MM-DD format.")
    for key in ("body_fat_pct", "lean_mass_kg", "fat_mass_kg", "visceral_fat", "bmc_kg"):
        raw_number = result["dexa"][key]
        if raw_number:
            try:
                number = float(raw_number)
            except ValueError as exc:
                raise ValueError(f"DEXA {key.replace('_', ' ')} must be a number.") from exc
            if number < 0 or (key == "body_fat_pct" and number > 100):
                raise ValueError(f"DEXA {key.replace('_', ' ')} is out of range.")
    result["updated_at"] = _text(raw.get("updated_at"))
    return result


def load(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else DEFAULT_PATH
    try:
        return normalize(json.loads(target.read_text(encoding="utf-8")))
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError):
        return empty()


def save(value: Mapping[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else DEFAULT_PATH
    normalized = normalize(value)
    normalized["updated_at"] = normalized["updated_at"] or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")
    return normalized


def from_existing(*, ledger: Mapping[str, Any], food_preferences: Mapping[str, Any],
                  schedule_count: int, lab_count: int,
                  path: str | Path | None = None) -> dict[str, Any]:
    """Seed the form from a saved draft, then from the existing canonical data."""
    saved = load(path)
    if saved["updated_at"]:
        return saved
    intake = ledger.get("intake", {}) if isinstance(ledger, Mapping) else {}
    result = empty()
    result["diet"] = food_preferences.get("diet", result["diet"])
    result["toggles"] = list(food_preferences.get("toggles", []))
    result["health_goals"] = list(intake.get("goals", []))
    result["weight_direction"] = intake.get("weight_direction", "unknown")
    for key in ("bodyweight_kg", "height_cm", "age_years"):
        if intake.get(key) is not None:
            result[key] = str(intake[key])
    result["sex"] = intake.get("sex", "unknown")
    # These are honest prompts when the older stores have no structured value.
    result["schedule_notes"] = f"Existing saved schedule found ({schedule_count} block(s)); add changes or write 'keep as is'." if schedule_count else "No saved schedule yet."
    result["symptoms"] = "No saved symptom check-in found."
    if lab_count:
        result["lifestyle_goals"] = "Existing lab values found; add any lifestyle goal or write 'keep as is'."
    return result


def imported_snapshot(*, ledger: Mapping[str, Any], food_preferences: Mapping[str, Any],
                      schedule_count: int, lab_count: int) -> list[dict[str, str]]:
    intake = ledger.get("intake", {}) if isinstance(ledger, Mapping) else {}
    body = []
    if intake.get("bodyweight_kg") is not None:
        body.append(f"{intake['bodyweight_kg']} kg")
    if intake.get("height_cm") is not None:
        body.append(f"{intake['height_cm']} cm")
    return [
        {"label": "Diet", "value": food_preferences.get("diet", "Not found locally")},
        {"label": "Health goals", "value": ", ".join(intake.get("goals", [])) or "Not found locally"},
        {"label": "Body measurements", "value": ", ".join(body) or "Not found locally"},
        {"label": "Schedule", "value": f"{schedule_count} saved block(s)" if schedule_count else "Not found locally"},
        {"label": "Labs", "value": f"{lab_count} saved value(s)" if lab_count else "Not found locally"},
        {"label": "Symptoms", "value": "No structured saved check-in"},
        {"label": "DEXA", "value": "Not found locally"},
    ]


def commit(value: Mapping[str, Any], *, ledger_path: str | Path | None = None,
           food_path: str | Path | None = None, path: str | Path | None = None) -> dict[str, Any]:
    draft = normalize(value)
    ledger = CL.load_ledger(ledger_path)
    intake = dict(ledger["intake"])
    intake.update({
        "goals": draft["health_goals"],
        "weight_direction": draft["weight_direction"],
        "bodyweight_kg": draft["bodyweight_kg"],
        "height_cm": draft["height_cm"],
        "age_years": draft["age_years"],
        "sex": draft["sex"],
    })
    CL.save_ledger(CL.update_intake(ledger, intake), ledger_path)
    FoodP.save({"diet": draft["diet"], "toggles": draft["toggles"]}, food_path or FoodP.DEFAULT_PATH)
    return save(draft, path)

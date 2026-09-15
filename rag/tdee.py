#!/usr/bin/env python3
"""Real TDEE (total daily energy expenditure) estimate: Mifflin-St Jeor BMR, a NEAT activity
multiplier for ordinary daily-living movement, plus real logged workout calories read back
from the weekly check-ins already stored in HEALTHCOACH_REPORT.md (weekly_checkin.py /
bevel_share.py) — not a second generic "active" multiplier layered on top, which would
double-count the same exercise twice.

  TDEE_day = BMR * NEAT_MULTIPLIER[level] + calories_burned from that day's logged session(s)

No height/age/sex/weight on file -> bmr_kcal is None and the caller gets a clear reason why,
never a guessed number. No weekly check-ins logged yet -> workout calories are 0 for every day,
which is honest (nothing was reported burned), not an error.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_REPORT = HERE / "HEALTHCOACH_REPORT.md"

# Standard Mifflin-St Jeor sex constant.
_SEX_CONSTANT = {"male": 5, "female": -161}

# NEAT (non-exercise activity thermogenesis) multiplier for ordinary daily living — deliberately
# excludes structured training, since that's added separately from real logged session calories.
NEAT_MULTIPLIERS: dict[str, float] = {
    "sedentary": 1.2,   # desk job, little incidental walking
    "light": 1.3,       # on your feet some of the day, light walking
    "moderate": 1.4,    # physically active job or a lot of daily walking
    "active": 1.5,      # very physically demanding daily life outside of workouts
}

LEDGER_START = "<!-- HC_BEVEL_WEEKLY_START -->"
LEDGER_END = "<!-- HC_BEVEL_WEEKLY_END -->"
_WEEK_BLOCK_RE = re.compile(
    r"<!-- HC_BEVEL_WEEK_START (?P<week>\d{4}-\d{2}-\d{2}) -->(?P<body>.*?)"
    r"<!-- HC_BEVEL_WEEK_END (?P=week) -->",
    re.S,
)
_JSON_FENCE_RE = re.compile(r"```json\s*(?P<json>.*?)\s*```", re.S)


def mifflin_st_jeor_bmr(sex: str, weight_kg: float, height_cm: float, age_years: float) -> float:
    """Real Mifflin-St Jeor BMR in kcal/day. Callers must resolve sex to 'male'/'female' first —
    this raises rather than silently guessing a constant when sex isn't known."""
    if sex not in _SEX_CONSTANT:
        raise ValueError(f"sex must be 'male' or 'female' to compute BMR, got {sex!r}")
    return 10 * weight_kg + 6.25 * height_cm - 5 * age_years + _SEX_CONSTANT[sex]


def bmr_from_intake(intake: dict[str, Any]) -> tuple[float | None, str]:
    """(bmr_kcal, reason). bmr_kcal is None when any required field is missing/unknown — the
    reason string names exactly what's missing so a caller can prompt for it specifically."""
    missing = []
    weight_kg = intake.get("bodyweight_kg")
    height_cm = intake.get("height_cm")
    age_years = intake.get("age_years")
    sex = intake.get("sex", "unknown")
    if weight_kg is None:
        missing.append("bodyweight_kg")
    if height_cm is None:
        missing.append("height_cm")
    if age_years is None:
        missing.append("age_years")
    if sex not in _SEX_CONSTANT:
        missing.append("sex")
    if missing:
        return None, f"missing intake field(s): {', '.join(missing)}"
    return mifflin_st_jeor_bmr(sex, weight_kg, height_cm, age_years), "computed from intake"


def read_logged_weeks(report_path: Path | str = DEFAULT_REPORT) -> list[dict[str, Any]]:
    """Every real Bevel weekly package currently stored in the report's ledger, oldest first.
    Returns [] when the report doesn't exist yet or no week has ever been logged — that's a
    real, expected state (weekly_checkin.py hasn't been run), not an error."""
    path = Path(report_path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.find(LEDGER_START)
    end = text.find(LEDGER_END)
    if start < 0 or end < 0 or end <= start:
        return []
    ledger_text = text[start + len(LEDGER_START):end]
    packages: list[dict[str, Any]] = []
    for match in _WEEK_BLOCK_RE.finditer(ledger_text):
        body = match.group("body")
        fence = _JSON_FENCE_RE.search(body)
        if not fence:
            continue
        try:
            package = json.loads(fence.group("json"))
        except json.JSONDecodeError:
            continue
        if isinstance(package, dict):
            packages.append(package)
    packages.sort(key=lambda p: str(p.get("week_start", "")))
    return packages


def logged_workout_calories_by_day(report_path: Path | str = DEFAULT_REPORT) -> dict[str, float]:
    """{'YYYY-MM-DD': total calories_burned that day} from every real logged session across
    every stored week. A day with no logged session, or a session logged without a calorie
    figure, is simply absent from the dict — callers should treat a missing day as 0, not
    fabricate a number for it."""
    by_day: dict[str, float] = {}
    for package in read_logged_weeks(report_path):
        for day in package.get("days", []):
            date = day.get("date")
            if not date:
                continue
            total = 0.0
            found = False
            for session in day.get("sessions", []):
                calories = session.get("calories_burned")
                if calories is not None:
                    total += float(calories)
                    found = True
            if found:
                by_day[date] = by_day.get(date, 0.0) + total
    return by_day


def tdee_estimate(intake: dict[str, Any], report_path: Path | str = DEFAULT_REPORT) -> dict[str, Any]:
    """Real TDEE estimate built entirely from data on file — never an invented number.
    neat_kcal is BMR * the NEAT multiplier for intake['neat_activity_level'] (ordinary daily
    living, no structured training). workout_calories_by_day comes straight from real logged
    weekly check-ins. avg_workout_kcal_per_day averages only days that actually have a logged
    entry, so weeks with a rest day aren't diluted by treating silence as a real zero."""
    bmr_kcal, bmr_reason = bmr_from_intake(intake)
    level = intake.get("neat_activity_level", "sedentary")
    multiplier = NEAT_MULTIPLIERS.get(level, NEAT_MULTIPLIERS["sedentary"])
    workout_by_day = logged_workout_calories_by_day(report_path)
    avg_workout = (sum(workout_by_day.values()) / len(workout_by_day)) if workout_by_day else 0.0

    if bmr_kcal is None:
        return {
            "bmr_kcal": None, "bmr_reason": bmr_reason, "neat_activity_level": level,
            "neat_multiplier": multiplier, "neat_kcal": None,
            "workout_calories_by_day": workout_by_day,
            "avg_workout_kcal_per_day": round(avg_workout, 1),
            "tdee_baseline_kcal": None, "tdee_avg_with_workouts_kcal": None,
        }

    neat_kcal = bmr_kcal * multiplier
    return {
        "bmr_kcal": round(bmr_kcal, 1), "bmr_reason": bmr_reason, "neat_activity_level": level,
        "neat_multiplier": multiplier, "neat_kcal": round(neat_kcal, 1),
        "workout_calories_by_day": workout_by_day,
        "avg_workout_kcal_per_day": round(avg_workout, 1),
        "tdee_baseline_kcal": round(neat_kcal, 1),
        "tdee_avg_with_workouts_kcal": round(neat_kcal + avg_workout, 1),
    }


def tdee_for_date(intake: dict[str, Any], date_iso: str, report_path: Path | str = DEFAULT_REPORT) -> dict[str, Any]:
    """Same as tdee_estimate but uses that specific day's real logged workout calories (0 if
    nothing was logged for it) instead of the multi-week average — for a day-by-day food plan."""
    estimate = tdee_estimate(intake, report_path)
    if estimate["bmr_kcal"] is None:
        return estimate
    day_workout = estimate["workout_calories_by_day"].get(date_iso, 0.0)
    estimate = dict(estimate)
    estimate["date"] = date_iso
    estimate["workout_kcal_this_day"] = day_workout
    estimate["tdee_this_day_kcal"] = round(estimate["neat_kcal"] + day_workout, 1)
    return estimate

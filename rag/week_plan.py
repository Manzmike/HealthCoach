"""Private, explicit weekly planning state and transparent dashboard projections.

Weekly selection is not adoption, ingestion, clinician clearance, or measured adherence.
Meal-slot placement is a practical allocation, not evidence of optimal biological timing.
"""

from __future__ import annotations

import copy
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import safety_policy as SP

HERE = Path(__file__).resolve().parent
DEFAULT_PATH = HERE / ".healthcoach" / "week_plan.json"
CATEGORIES = {"food": "Foods", "supplement": "Supplements", "gray": "Peptides / Gray Market", "nootropic": "Nootropics", "other": "Other Items"}
SLOTS = ("Breakfast", "Lunch", "Dinner", "Snack")
LETTERS = ("F", "D", "C", "B", "A")


def monday(day: dt.date) -> str:
    return (day - dt.timedelta(days=day.weekday())).isoformat()


def dates(start: str) -> list[str]:
    day = dt.date.fromisoformat(start)
    return [(day + dt.timedelta(days=i)).isoformat() for i in range(7)]


def category(row: dict) -> str:
    cls = row.get("class", "other")
    return "gray" if cls in {"peptide", "gray_market"} else cls if cls in CATEGORIES else "other"


def selection(row: dict) -> dict:
    return {"name": row["display_name"], "category": category(row), "categories": row.get("browse_categories", [category(row)])}


def empty_week() -> dict:
    return {"selected": {}, "meals": [], "meal_times": {slot: None for slot in SLOTS},
            "meal_basis": None, "allocation": None, "workouts": {}, "item_routines": {}, "history": [], "justifications": {}}


def resource(text: str, kind: str = "research") -> dict:
    return {"id": hashlib.sha256((kind + ":" + text).encode()).hexdigest()[:16], "text": text, "kind": kind}


def rationale(goal: str, personal_reason: str, review_trigger: str, source: dict, available: list[dict]) -> dict:
    """Require a decision record tied to a resource actually offered by the program."""
    if source not in available:
        raise ValueError("Choose a source from this item's actual research/resource list.")
    result = {"goal": goal.strip(), "personal_reason": personal_reason.strip(), "review_trigger": review_trigger.strip(), "source": copy.deepcopy(source)}
    validate_rationale(result)
    return result


def validate_rationale(value) -> None:
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or len(value[key].strip()) < 12 for key in ("goal", "personal_reason", "review_trigger")):
        raise ValueError("A hard reason needs a specific purpose, personal reason, and review trigger (at least 12 characters each).")
    source = value.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("text"), str) or not source["text"].strip() or not isinstance(source.get("kind"), str) or source["kind"] not in {"research", "nutrition", "planning", "recorded_context"} or source != resource(source["text"], source["kind"]):
        raise ValueError("A hard reason must link to a known research, nutrition, planning, or recorded-context resource.")


def clock(value) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        return dt.time.fromisoformat(value).strftime("%H:%M") == value
    except ValueError:
        return False


def validate_week(start: str, week: dict) -> None:
    if monday(dt.date.fromisoformat(start)) != start:
        raise ValueError("A planning week must start on Monday (YYYY-MM-DD).")
    if not isinstance(week, dict) or (set(empty_week()) - {"justifications"}) - set(week):
        raise ValueError("Incomplete weekly state; existing data will not be replaced.")
    valid_dates = dates(start)
    if not isinstance(week.get("justifications", {}), dict):
        raise ValueError("Invalid decision justification state.")
    for field in ("selected", "workouts", "item_routines", "meal_times"):
        if not isinstance(week[field], dict):
            raise ValueError(f"Invalid {field} state.")
    for item_id, item in week["selected"].items():
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip() or item.get("category") not in CATEGORIES or not item_id:
            raise ValueError("Invalid weekly selection.")
        if item.get("rationale") is not None:
            validate_rationale(item["rationale"])
    for value in week.get("justifications", {}).values():
        validate_rationale(value)
    if set(week["meal_times"]) != set(SLOTS) or not all(clock(value) for value in week["meal_times"].values()):
        raise ValueError("Meal times must be HH:MM or unset.")
    if not isinstance(week["meals"], list) or not isinstance(week["history"], list):
        raise ValueError("Invalid meals/history state.")
    for meal in week["meals"]:
        if not isinstance(meal, dict) or meal.get("date") not in valid_dates or meal.get("slot") not in SLOTS or not isinstance(meal.get("food_id"), str):
            raise ValueError("Each meal must name a food, date in this week, and meal slot.")
        amount = meal.get("servings")
        if isinstance(amount, bool) or not isinstance(amount, (float, int)) or not math.isfinite(amount) or not 0 < amount <= 20:
            raise ValueError("Meal servings must be positive finite numbers, at most 20.")
        for field in ("kcal", "protein_g"):
            value = meal.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("Meal nutrition estimates must be finite, nonnegative numbers.")
    if week["meals"]:
        import diet_rules as DR
        import food_serving_guidance as FSG
        import weekly_food_plan as WFP
        daily, weekly = {}, {}
        for meal in week["meals"]:
            key, date = meal["food_id"], meal["date"]
            daily[key, date] = daily.get((key, date), 0) + meal["servings"]
            weekly[key] = weekly.get(key, 0) + meal["servings"]
        for (key, date), amount in daily.items():
            if amount > WFP.DAILY_CEILING_BY_CATEGORY.get(DR.FOOD_CATEGORY.get(key), 2) + 0.000001:
                raise ValueError(f"{key} exceeds its daily planning ceiling on {date}; split the portions across days.")
        for key, amount in weekly.items():
            cap = FSG.serving_guidance(key)["weekly_max_servings"]
            if cap is not None and amount > cap + 0.000001:
                raise ValueError(f"{key} exceeds its recorded weekly moderation cap.")
        if sum(amount for key, amount in weekly.items() if DR.FOOD_CATEGORY.get(key) == "red_meat") > 3.000001:
            raise ValueError("The combined red-meat servings exceed the weekly category cap.")
        if sum(weekly.get(key, 0) for key in ("beef_liver", "chicken_liver")) > 1.000001:
            raise ValueError("The combined liver servings exceed the weekly moderation cap.")
    for date, workout in week["workouts"].items():
        if date not in valid_dates or not isinstance(workout, dict) or not isinstance(workout.get("session"), str):
            raise ValueError("Invalid dated workout.")
        steps = workout.get("steps_target")
        if isinstance(steps, bool) or not isinstance(steps, int) or not 0 <= steps <= 50000:
            raise ValueError("Step target must be an integer from 0 to 50,000.")
        minutes = workout.get("minutes")
        if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= 1440):
            raise ValueError("Workout minutes must be an integer from 0 to 1440, or unset.")
        if not clock(workout.get("time")):
            raise ValueError("Workout time must be HH:MM or unset.")
    for item_id, routine in week["item_routines"].items():
        if not isinstance(routine, dict) or not isinstance(routine.get("text"), str) or not isinstance(routine.get("dates"), list) or any(date not in valid_dates for date in routine["dates"]):
            raise ValueError("Invalid user-recorded item routine.")


def load(path: Path = DEFAULT_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": 1, "weeks": {}, "research": {}}
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("weeks"), dict) or not isinstance(data.get("research"), dict):
        raise ValueError("Unsupported or malformed weekly state; no overwrite allowed.")
    for start, week in data["weeks"].items():
        if isinstance(week, dict):
            week.setdefault("justifications", {})
        validate_week(start, week)
    return data


def changes(before: dict, after: dict) -> list[dict]:
    return [{"field": key, "before": copy.deepcopy(before.get(key)), "after": copy.deepcopy(after.get(key))}
            for key in empty_week() if key != "history" and before.get(key) != after.get(key)]


def change_summary(change: dict) -> list[str]:
    field, before, after = change["field"], change["before"], change["after"]
    if field == "selected":
        before, after = before or {}, after or {}
        return ["Selected: " + (", ".join(after[k]["name"] for k in after.keys() - before.keys()) or "no new items"),
                "Unselected: " + (", ".join(before[k]["name"] for k in before.keys() - after.keys()) or "none"),
                "Item reasons and sources are retained in the selection details and export."]
    if field == "workouts":
        result = []
        for date, workout in (after or {}).items():
            old = (before or {}).get(date, {})
            if old != workout:
                result.append(f"{date}: {old.get('session', 'unset')} / {old.get('steps_target', 'unset')} steps -> "
                              f"{workout['session']} / {workout['steps_target']} steps / {workout.get('time') or 'time unset'}")
        return result
    if field == "meals":
        return [f"Meal portions: {len(before or [])} -> {len(after or [])}. Open Meals for dates, quantities, and reasons."]
    if field == "meal_times":
        return [f"{slot}: {(before or {}).get(slot) or 'unset'} -> {value or 'unset'}" for slot, value in (after or {}).items() if (before or {}).get(slot) != value]
    return [field.replace("_", " ").title() + " updated. Full before/after values are available in Export -> Why The Plan Changed."]


def save(start: str, draft: dict, previous: dict | None, reason: str, path: Path = DEFAULT_PATH) -> dict:
    """Optimistic same-week check; preserve concurrent edits to other weeks and research."""
    validate_week(start, draft)
    for selection in draft["selected"].values():
        try:
            validate_rationale(selection.get("rationale"))
        except ValueError as exc:
            raise ValueError(f"{selection['name']}: justify with j or unselect before saving. {exc}") from exc
    for field in ("meals", "meal_times", "workouts", "item_routines"):
        changed = (previous or empty_week()).get(field) != draft[field]
        is_new_action = bool(draft[field])
        if field == "workouts":
            is_new_action = previous is not None or any(
                w.get("origin") == "USER_PLANNED" or not w.get("session", "").startswith("Not set") or w.get("steps_target") != 10000
                for w in draft[field].values())
        if field == "meal_times":
            is_new_action = any(value is not None for value in draft[field].values())
        if changed and is_new_action:
            validate_rationale(draft.get("justifications", {}).get(field))
    if not reason.strip():
        raise ValueError("A reason is required to save weekly changes.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load(path)
        if data["weeks"].get(start) != previous:
            raise ValueError("This week changed in another session. Reload before saving.")
        result = copy.deepcopy(draft)
        diff = changes(previous or empty_week(), result)
        result["history"] = copy.deepcopy((previous or {}).get("history", []))
        result["history"].append({"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                                  "reason": reason.strip(), "changes": diff})
        data["weeks"][start] = result
        _write(path, data)
        return result


def _write(path: Path, data: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".week-plan-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_research(item_id: str, record: dict, path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load(path)
        data["research"][item_id] = record
        _write(path, data)


def grades(row: dict, intake: dict, food_record: dict | None = None, research: dict | None = None) -> dict:
    """Two independent screen grades. No missing evidence is silently assigned an F."""
    record = research or food_record or {}
    fits = [fit for fit in row.get("reason_evaluations", {}).values() if isinstance(fit, dict)]
    coverage = record.get("coverage") or row.get("last_coverage") or "NONE"
    directions = {fit.get("direction") for fit in fits} - {None, "unknown"}
    direction = record.get("direction") or (next(iter(directions)) if len(directions) == 1 else "mixed" if directions else "unknown")
    overall = record.get("overall_grade") or record.get("grade")
    if overall not in {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F", "F-"}:
        overall = "F" if direction == "harm" else "A" if coverage == "STRONG" and direction == "favor" else "B" if coverage == "WEAK" and direction == "favor" else "C" if coverage != "NONE" else "?"
    if not research and coverage == "NONE" and not record.get("sources_retained") and not record.get("source"):
        overall = "?"
    why = record.get("grade_why") or f"Cached screen: coverage {coverage}; direction {direction}. Not a clinical certainty grade."
    goals = set(intake.get("goals", []))
    supported_goals = set(row.get("reasons", [])) | set(row.get("catalog_reasons", []))
    matches = sorted(goals & supported_goals)
    personal = "?"
    personal_why = "Record goals and relevant evidence before grading personal fit."
    if goals and overall != "?":
        personal = overall if matches else "D"
        personal_why = ("Matches recorded goal(s): " + ", ".join(matches)) if matches else "No match to your currently recorded goals; this is not evidence of harm."
        if any(fit.get("applicability") in {"indirect", "low", "unknown", "not established"} for fit in fits) and personal.startswith("A"):
            personal = "B"
            personal_why += "; applicability is indirect or unresolved."
    if row.get("observed") == "harms":
        personal, personal_why = "F", "You reported harm; review before any plan change."
    elif row.get("blocker", {}).get("present"):
        personal, personal_why = "D", "Unresolved personal blocker: " + (row["blocker"].get("description") or "review required")
    sources = record.get("sources", []) or list(dict.fromkeys(source for fit in fits for source in fit.get("source_trail", [])))
    if not sources:
        sources = list(dict.fromkeys(ref["source"] for key in ("good", "bad") for ref in record.get(key, []) if isinstance(ref, dict) and ref.get("source")))
    return {"overall": overall, "personal": personal, "coverage": coverage, "direction": direction,
            "why": why, "personal_why": personal_why, "sources": sources,
            "updated_at": record.get("updated_at") or "cache date unknown"}


def seed_week(start: str, rows: list[dict], profile: dict) -> dict:
    week = empty_week()
    # Existing choices are labelled as a draft, never silently persisted or reported as use.
    picked = set(profile.get("selected_peptide_keys", [])) | set(profile.get("priority_supplement_keys", [])) | set(profile.get("food_addition_keys", []))
    for row in rows:
        if row.get("user_decision") != "reject" and (row.get("user_decision") == "adopt" or row.get("use_status") == "in_use" or row["id"] in picked):
            week["selected"][row["id"]] = selection(row)
    for date in dates(start):
        day = dt.date.fromisoformat(date).strftime("%A")
        snapshot = profile.get("calendar_snapshot", {}).get(day, {})
        week["workouts"][date] = {"session": snapshot.get("placement") or "Not set; edit your session",
                                  "time": None, "minutes": None, "steps_target": 10000,
                                  "constraint": snapshot.get("status") or "No saved session snapshot; no session inferred.",
                                  "origin": "SAVED_CALENDAR" if snapshot else "NOT_CONFIGURED"}
    return week


def meal_basis(week: dict, intake: dict) -> str:
    payload = {"foods": sorted(key for key, row in week["selected"].items() if row["category"] == "food"), "intake": intake}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def distribute_meals(plan: dict, start: str) -> tuple[list[dict], list[str]]:
    """Distribute supplied weekly portions, preserve totals, and expose unplaceable foods."""
    import diet_rules as DR
    import weekly_food_plan as WFP
    meals, notices = [], list(plan.get("skipped", []))
    if plan.get("note"):
        return [], [*notices, plan["note"]]
    day_load = {day: 0.0 for day in dates(start)}
    slot_load = {(day, slot): 0.0 for day in day_load for slot in SLOTS}
    used = {}
    red_count = liver_count = 0.0
    for food in sorted(plan.get("foods", []), key=lambda f: -f["protein_g_per_serving"]):
        key = food["id"]
        group = DR.FOOD_CATEGORY.get(key, "other")
        remaining = float(food["servings"])
        if group == "red_meat":
            allowed = max(0.0, 3 - red_count)
            if remaining > allowed:
                notices.append(f"{food['name']}: category-wide red-meat cap; not all proposed portions placed.")
            remaining = min(remaining, allowed)
            red_count += remaining
        if key in {"beef_liver", "chicken_liver"}:
            allowed = max(0.0, 1 - liver_count)
            if remaining > allowed:
                notices.append(f"{food['name']}: shared liver moderation cap; review other selections.")
            remaining = min(remaining, allowed)
            liver_count += remaining
        preferred = ("Lunch", "Dinner") if group in {"poultry", "red_meat", "organ_meat", "fish_seafood", "vegetable", "starchy_veg", "legume", "herb_spice", "fermented"} else SLOTS
        while remaining > 0.000001:
            amount = min(1.0, remaining)
            available = [day for day in day_load if used.get((key, day), 0) + amount <= WFP.DAILY_CEILING_BY_CATEGORY.get(group, 2)]
            if not available:
                notices.append(f"{food['name']}: {remaining:g} serving(s) unplaced due to the daily planning ceiling.")
                break
            day = min(available, key=lambda d: (used.get((key, d), 0), day_load[d], d))
            slot = min(preferred, key=lambda s: slot_load[day, s])
            meals.append({"date": day, "slot": slot, "food_id": key, "servings": amount,
                          "name": food["name"], "kcal": round(food["kcal_per_serving"] * amount, 2),
                          "protein_g": round(food["protein_g_per_serving"] * amount, 2),
                          "portion": f"{food['grams_per_serving']:g} g per planning portion",
                          "reason": "Selected food; portions allocated against weekly energy/protein estimates. Slot chosen for distribution and meal practicality, not proven optimal timing."})
            used[key, day] = used.get((key, day), 0) + amount
            calories = food["kcal_per_serving"] * amount
            day_load[day] += calories
            slot_load[day, slot] += calories
            remaining -= amount
    return meals, notices


def overview(week: dict, start: str, day: str | None = None, intake: dict | None = None) -> list[str]:
    lines = ["YOUR WEEK / " + start]
    for key, label in CATEGORIES.items():
        names = [row["name"] for row in week["selected"].values() if key in row.get("categories", [row["category"]])]
        lines.append(f"{label}: " + (", ".join(names) if names else "none selected yet"))
    if day:
        workout = week["workouts"].get(day, {})
        lines.append(f"Training: {workout.get('session', 'not configured')} | Steps target: {workout.get('steps_target', 10000):,}")
        stale = intake is not None and week["meal_basis"] and week["meal_basis"] != meal_basis(week, intake)
        meals = [] if stale else [meal for meal in week["meals"] if meal["date"] == day]
        if stale:
            lines.append("MEALS NEED REBUILD: selections/context changed; previous placements are not current instructions.")
        for slot in SLOTS:
            items = [f"{meal.get('name', meal['food_id'])} x{meal['servings']:g}" for meal in meals if meal["slot"] == slot]
            if items:
                lines.append(f"{slot} {week['meal_times'].get(slot) or '(time unset)'}: " + ", ".join(items))
        if not meals:
            lines.append("Meals: choose Foods, then Meals -> b to build the week's draft.")
        for item_id, routine in week["item_routines"].items():
            if item_id in week["selected"] and day in routine["dates"]:
                lines.append(f"{week['selected'][item_id]['name']} ({routine.get('kind', 'recorded note')}): {routine['text']}")
    return lines

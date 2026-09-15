#!/usr/bin/env python3
"""Read-only Today projection. No models, inferred schedules, doses, or state migrations."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

import daily_log
import week_plan as WP


HERE = Path(__file__).resolve().parent
DEFAULT_REPORT = HERE / "HEALTHCOACH_REPORT.md"
DEFAULT_LEDGER = HERE / ".healthcoach" / "candidate_ledger.json"
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
PLACEMENTS = {
    "plan": "Authored template window selected; no exact session/time stored in this field.",
    "morning": "Morning selected; no exact session/time stored in this field.",
    "evening": "Evening selected; no exact session/time stored in this field.",
    "both": "Both windows selected; this is not a record of two scheduled sessions.",
    "unavailable": "Unavailable selected; no main-session availability for this day.",
}


def display_text(value: Any) -> str:
    return "".join(char if char.isprintable() else " " for char in str(value))


def load_today(
    report: Path = DEFAULT_REPORT,
    ledger: Path | None = None,
    log: Path = daily_log.DEFAULT_LOG,
    day: dt.date | None = None,
    week_path: Path = WP.DEFAULT_PATH,
) -> dict[str, Any]:
    day = day or dt.datetime.now().astimezone().date()
    ledger = ledger if ledger is not None else Path(os.getenv("HC_CANDIDATE_LEDGER") or DEFAULT_LEDGER).expanduser()
    state: dict[str, Any] = {
        "date": day.isoformat(), "weekday": DAYS[day.weekday()],
        "report_available": False, "profile_saved": False, "weeks": [],
        "placement": None, "calendar_snapshot": None, "calendar_validation": None, "active": [], "review": [],
        "daily": None, "daily_available": True, "warnings": [],
        "reassessment": (day + dt.timedelta(days=(7 - day.weekday()) % 7)).isoformat(),
        "first_run": False,
    }
    # Retain only the marked profile block and week identifiers, not report/research prose.
    profile_lines: list[str] = []
    in_profile = False
    profile = {}
    rows = []
    intake = {}
    closed = False
    started = False
    try:
        with report.open(encoding="utf-8") as handle:
            state["report_available"] = True
            for line in handle:
                if line.strip() == "<!-- HC_PROFILE_STATE_START -->":
                    if started:
                        raise ValueError("Duplicate saved profile block.")
                    started = True
                    in_profile = True
                elif line.strip() == "<!-- HC_PROFILE_STATE_END -->":
                    if not in_profile:
                        raise ValueError("Unexpected saved profile end marker.")
                    closed = True
                    in_profile = False
                elif in_profile:
                    profile_lines.append(line)
                week = re.fullmatch(r"<!-- HC_BEVEL_WEEK_START (\d{4}-\d{2}-\d{2}) -->", line.strip())
                if week:
                    state["weeks"].append(week.group(1))
        state["weeks"] = sorted(set(state["weeks"]))
        if profile_lines or closed or in_profile:
            match = re.search(r"```json\s*(\{.*?\})\s*```", "".join(profile_lines), re.S)
            if not closed or in_profile or not match:
                raise ValueError("Malformed saved profile block.")
            profile = json.loads(match.group(1))
            if not isinstance(profile, dict):
                raise ValueError("Saved profile must be an object.")
            state["profile_saved"] = True
            modes = profile.get("calendar_modes", {})
            if not isinstance(modes, dict):
                raise ValueError("Saved calendar must be an object.")
            mode = modes.get(state["weekday"])
            if mode is not None and (not isinstance(mode, str) or mode not in PLACEMENTS):
                raise ValueError("Today's saved calendar placement is invalid.")
            state["placement"] = mode
            snapshots = profile.get("calendar_snapshot", {})
            if not isinstance(snapshots, dict):
                raise ValueError("Saved calendar snapshot must be an object.")
            snapshot = snapshots.get(state["weekday"])
            if snapshot is not None:
                if (not isinstance(snapshot, dict) or snapshot.get("mode") != mode
                        or snapshot.get("origin") != "AUTHORED_TEMPLATE"
                        or not all(isinstance(snapshot.get(key), str) and snapshot[key].strip() for key in ("placement", "status"))):
                    raise ValueError("Saved calendar snapshot does not match the recorded placement.")
                state["calendar_snapshot"] = snapshot
            if isinstance(profile.get("calendar_validation"), str):
                state["calendar_validation"] = profile["calendar_validation"]
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        state["warnings"].append(f"Saved plan unavailable: {exc}")

    try:
        rows: list[dict[str, Any]] = []
        try:
            data = json.loads(ledger.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"schema_version": 2, "candidates": []}
        if not isinstance(data, dict) or data.get("schema_version") not in (1, 2) or not isinstance(data.get("candidates"), list):
            raise ValueError("Unsupported or malformed candidate ledger.")
        seen: set[str] = set()
        intake = data.get("intake", {})
        if not isinstance(intake, dict):
            raise ValueError("Malformed personal context.")
        reviewed_at = intake.get("updated_at")
        if reviewed_at:
            try:
                reviewed_date = dt.datetime.fromisoformat(reviewed_at).date()
                if (day - reviewed_date).days > 30:
                    state["warnings"].append("Personal context was last reviewed over 30 days ago. Review it before changing the plan.")
            except (TypeError, ValueError):
                state["warnings"].append("Personal-context review date is invalid; review it before changing the plan.")
        else:
            state["warnings"].append("Personal-context review date is unknown. Your tracked items remain records, not safety clearance.")
        for row in data["candidates"]:
            if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip() for k in ("id", "display_name")):
                raise ValueError("Malformed candidate identity.")
            if row["id"] in seen:
                raise ValueError("Duplicate candidate identity.")
            seen.add(row["id"])
            if any(row.get(k) is not None and not isinstance(row[k], str) for k in (
                "class", "consideration_scope", "user_decision", "use_status", "user_dose",
            )):
                raise ValueError("Malformed candidate state.")
            rows.append(row)
        try:
            gate = importlib.import_module("safety_policy").candidate_gate
        except (ImportError, AttributeError):
            gate = None
            state["warnings"].append("Policy check unavailable; current items are review-only until it is available.")
        for row in rows:
            if row.get("use_status") != "in_use":
                continue
            allowed = False
            reasons = ["Policy check unavailable."]
            if gate is not None:
                try:
                    result = gate(row)
                    if not isinstance(result, dict) or not isinstance(result.get("active_plan_allowed"), bool) or not isinstance(result.get("reasons"), list):
                        raise ValueError("Malformed policy result")
                    allowed = result["active_plan_allowed"]
                    reasons = [str(reason) for reason in result["reasons"]]
                    if not allowed and not reasons:
                        reasons = ["Shared policy does not allow active-plan placement."]
                except Exception:
                    # A failed policy check must never promote a reported item into the plan.
                    allowed = False
                    reasons = ["Policy check failed; review required."]
            personal = row.get("consideration_scope") == "personal_candidate"
            adopted = row.get("user_decision") == "adopt"
            item = {
                "id": row["id"], "name": row["display_name"], "class": row.get("class") or "unclassified",
                "dose": row.get("user_dose"),
            }
            if personal and adopted and allowed:
                state["active"].append(item)
            else:
                if not personal:
                    reasons.append("Scope is not confirmed personal_candidate.")
                if not adopted:
                    reasons.append("Decision is not adopt.")
                state["review"].append({**item, "reasons": reasons})
    except (OSError, ValueError) as exc:
        state["warnings"].append(f"Candidate state unavailable: {exc}")

    try:
        state["daily"] = daily_log.load_log(log)["days"].get(day.isoformat())
    except (OSError, ValueError) as exc:
        state["daily_available"] = False
        state["warnings"].append(f"Daily log unavailable: {exc}")
    try:
        start = WP.monday(day)
        saved_week = WP.load(week_path)["weeks"].get(start)
        state["planning_week"] = saved_week if saved_week is not None else WP.seed_week(start, rows, profile)
        state["planning_week_saved"] = saved_week is not None
        state["planning_intake"] = intake
    except (OSError, ValueError, TypeError, KeyError) as exc:
        state["warnings"].append(f"Weekly planning state unavailable: {exc}")
    state["first_run"] = not (
        state["report_available"]
        or state["profile_saved"]
        or state["weeks"]
        or any(row.get("use_status") == "in_use" for row in rows)
        or state.get("planning_week_saved", False)
    )
    return state


def dashboard_lines(state: dict) -> list[str]:
    week = state.get("planning_week")
    if week is None:
        return summary_lines(state)
    workout = week["workouts"].get(state["date"], {})
    steps = (state.get("daily") or {}).get("steps")
    lines = [f"TODAY / {state['weekday']} / {state['date']}",
             "TRAINING: " + workout.get("session", "not configured"),
             f"STEPS: {steps if steps is not None else 'unknown'} / {workout.get('steps_target', 10000):,} target (editable)"]
    for category, title in WP.CATEGORIES.items():
        selected = [row["name"] for row in week["selected"].values() if category in row.get("categories", [row["category"]])]
        shown = ", ".join(selected[:3]) or "none chosen"
        extra = f" +{len(selected) - 3} more" if len(selected) > 3 else ""
        lines.append(f"{title.upper()} ({len(selected)}): {shown}{extra}")
    stale = week["meal_basis"] and week["meal_basis"] != WP.meal_basis(week, state.get("planning_intake", {}))
    lines.append("MEALS: " + ("choices/context changed; rebuild in Meals" if stale else f"{sum(m['date'] == state['date'] for m in week['meals'])} portions today; m opens what + when"))
    lines.append("CURRENT: " + ("saved weekly choices" if state.get("planning_week_saved") else "draft from prior choices; open Your Week to review/save"))
    lines.append("DAILY LOG: " + ((state.get("daily") or {}).get("status", "unknown").upper()))
    lines.append("Overall and personal-fit grades: open any category or Your Week. Gray selections are not hidden by review gates.")
    lines.extend("NOTICE: " + warning for warning in state["warnings"])
    return [display_text(line) for line in lines]


def summary_lines(state: dict[str, Any], *, show_review: bool = False) -> list[str]:
    lines = [f"TODAY / {state['weekday']} / {state['date']}"]
    mode = state["placement"]
    snapshot = state.get("calendar_snapshot")
    if snapshot:
        lines.append("SAVED SESSION: " + snapshot["placement"])
        lines.append("CALENDAR: " + snapshot["status"])
    lines.append("SAVED PLACEMENT: " + (mode.upper() if mode else "Not configured. Open Plan to review your calendar."))
    entry = state["daily"]
    if not state["daily_available"]:
        lines.append("DAILY LOG: UNAVAILABLE / existing state could not be read; do not overwrite it")
    elif entry is None:
        lines.append("DAILY LOG: UNKNOWN / no entry for this date")
    else:
        duration = "UNKNOWN" if entry["duration_min"] is None else f"{entry['duration_min']:g} min"
        lines.append(f"DAILY LOG: {entry['status'].upper()} main activity / {duration} / recovery {entry['recovery'].upper()}")
    lines.append(f"CURRENT: {len(state['active'])} adopted / {len(state['review'])} review-only / no timing inferred")
    lines.append(f"NEXT WEEKLY REASSESSMENT: {state['reassessment']} / w completed week")
    if state["warnings"]:
        lines.append(f"STATE NOTICE: {len(state['warnings'])} issue(s); details below")
    lines.extend(("", "PLACEMENT DETAILS"))
    if mode:
        lines.append(PLACEMENTS[mode])
    if snapshot:
        lines.append("Session copied from your saved authored calendar, not a new recommendation.")
    elif mode:
        lines.append("This older plan has no session snapshot. Review/save the plan to include session details here.")
    if state["calendar_validation"]:
        lines.append("Saved validation: " + state["calendar_validation"])
    lines.append("Placement only, not proof of an adopted timed action. No clock defaults added.")
    if entry and entry["note"]:
        lines.append("Recorded note: " + entry["note"])
    lines.extend(("", f"ADOPTED + CURRENT / {len(state['active'])} / timing not recorded"))
    for item in state["active"]:
        dose = "user-recorded dose: " + item["dose"] if item["dose"] else "dose not recorded"
        lines.append(f"- {item['name']} ({item['class']}) / {dose}")
    if not state["active"]:
        lines.append("No eligible adopted/current items. Nothing was auto-added.")
    lines.append("These are current-state records, not instructions to take an item today.")
    lines.extend(("", f"REPORTED CURRENT USE / REVIEW ONLY / {len(state['review'])}"))
    if state["review"]:
        lines.append("Not active-plan instructions; not an automatic stop. Press v for recorded items/reasons.")
        if show_review:
            for item in state["review"]:
                lines.append(f"- {item['name']} ({item['class']}): " + "; ".join(item["reasons"]))
    lines.extend((
        "", "REVIEW: Log/Review -> LOG THE COMPLETED WEEK",
        "Daily facts do not sync into Bevel packages or adjust the plan automatically.",
    ))
    lines.extend("STATE NOTICE: " + warning for warning in state["warnings"])
    return [display_text(line) for line in lines]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show saved Today state without generation or writes")
    parser.add_argument("--date", type=dt.date.fromisoformat)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--log", type=Path, default=daily_log.DEFAULT_LOG)
    parser.add_argument("--review", action="store_true", help="include reported current-use review details")
    args = parser.parse_args(argv)
    state = load_today(args.report, args.ledger, args.log, args.date)
    print("\n".join(summary_lines(state, show_review=args.review)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

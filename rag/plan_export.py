#!/usr/bin/env python3
"""Explicit private Markdown exports of current plan sections or the complete report."""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import sys
import tempfile

import candidate_ledger as CL
import daily_log
import week_plan as W

SECTIONS = {"overview": "Weekly Overview", "food": "Food Choices And Reasons", "gray": "Peptides And Gray Market",
            "nootropic": "Nootropics", "supplement": "Supplements", "other": "Other Items", "meals": "Day-By-Day Meals",
            "training": "Training And Steps", "changes": "Why The Plan Changed", "sources": "Research And Resources",
            "current-plan": "Complete Current Week", "full-report": "Current Week Plus Entire Report"}


def cell(value) -> str:
    return str(value if value is not None else "unknown").replace("|", "/").replace("\n", "; ")


def basis_lines(basis) -> list[str]:
    if not basis:
        return ["**Hard reason missing. Review-only, not a justified plan selection.**"]
    return ["Purpose: " + basis["goal"], "Personal reason: " + basis["personal_reason"],
            "Review trigger: " + basis["review_trigger"],
            f"Supporting {basis['source']['kind']} resource ({basis['source']['id']}): {basis['source']['text']}"]


def render(section: str, start: str, week: dict, rows: list[dict], intake: dict, food_records: dict,
           research: dict, *, daily: dict | None = None, report_text: str | None = None, saved: bool = True) -> str:
    row_map = {row["id"]: row for row in rows}
    grades = {key: W.grades(row, intake, food_records.get(key), research.get(key)) for key, row in row_map.items()}
    lines = [f"# {SECTIONS[section]}", "", f"Week starting {start}. Exported {dt.datetime.now().astimezone().isoformat(timespec='seconds')}.",
             "", "State: " + ("saved weekly snapshot" if saved else "UNSAVED draft from prior selections; not confirmed for this week"),
             "", "Evidence and personal-fit grades are screening heuristics, not certainty or medical clearance. "
             "Selection is separate from actual use. Gray-market review does not authorize a dose or protocol.", ""]
    parts = [section] if section not in {"current-plan", "full-report"} else ["overview", "food", "gray", "nootropic", "supplement", "other", "meals", "training", "changes", "sources"]
    for part in parts:
        lines.extend([f"## {SECTIONS[part]}", ""])
        if part == "overview":
            lines.extend(W.overview(week, start, intake=intake))
            lines.append("Categories can overlap (for example gray-market nootropics); each item is selected only once.")
            lines.extend(["", "| Selected item | Overall screen | For you | Hard reason |", "|---|---|---|---|"])
            for key, selection in week["selected"].items():
                grade = grades.get(key, {"overall": "?", "personal": "?"})
                lines.append(f"| {cell(selection['name'])} | {grade['overall']} | {grade['personal']} | {'Recorded' if selection.get('rationale') else 'REQUIRED'} |")
        elif part in W.CATEGORIES:
            selections = [(key, selected) for key, selected in week["selected"].items() if part in selected.get("categories", [selected["category"]])]
            if not selections:
                lines.append("No items selected in this category.")
            for key, selected in selections:
                row = row_map.get(key, {})
                grade = grades.get(key, {"overall": "?", "personal": "?", "coverage": "NONE", "why": "Current catalog/evidence unavailable.", "personal_why": "Unknown", "sources": []})
                lines.extend(["", "### " + selected["name"], "", f"Overall evidence screen: **{grade['overall']}**. For you: **{grade['personal']}**. Coverage: {grade['coverage']}.",
                              "", "Overall reason: " + grade["why"], "Personal-fit reason: " + grade["personal_why"], "",
                              *basis_lines(selected.get("rationale")), "",
                              f"Ledger decision: {row.get('user_decision', 'not in ledger')}; actual use: {row.get('use_status', 'unknown')}.",
                              "User-recorded amount (not instructions): " + (row.get("user_dose") or "not recorded"),
                              "Catalog review note: " + (row.get("catalog_gate") or "No catalog note available; no clearance implied.")])
                routine = week["item_routines"].get(key)
                if routine:
                    lines.append(f"{routine.get('kind', 'Recorded note')} on {', '.join(routine['dates'])}: {routine['text']}")
                lines.extend("- " + str(source) for source in grade["sources"])
        elif part == "meals":
            stale = week["meal_basis"] and week["meal_basis"] != W.meal_basis(week, intake)
            if stale:
                lines.append("**STALE: choices/context changed. These are previous placements for review, not current meal instructions. Rebuild before use.**")
            lines.extend(basis_lines(week.get("justifications", {}).get("meals")))
            lines.extend(["", "Clock times are user-set; slot placement is practical, not proof of optimal biological timing.", "",
                          "| Date | Meal / Time | Food | Portions | Portion basis | kcal estimate | Protein g estimate |", "|---|---|---|---:|---|---:|---:|"])
            for meal in sorted(week["meals"], key=lambda m: (m["date"], W.SLOTS.index(m["slot"]))):
                values = [meal["date"], f"{meal['slot']} / {week['meal_times'].get(meal['slot']) or 'time unset'}", meal.get("name", meal["food_id"]),
                          meal["servings"], meal["portion"], meal["kcal"], meal["protein_g"]]
                lines.append("| " + " | ".join(cell(value) for value in values) + " |")
            allocation = week.get("allocation") or {}
            targets = allocation.get("targets", {})
            lines.extend(["", f"Weekly target estimates: {targets.get('weekly_kcal', 'unknown')} kcal; {targets.get('weekly_protein_g', 'unknown')} g protein.",
                          f"Placed totals: {sum(m['kcal'] for m in week['meals']):.0f} kcal; {sum(m['protein_g'] for m in week['meals']):.0f} g protein."])
            lines.extend("Unplaced / review: " + notice for notice in allocation.get("notices", []))
            for date in W.dates(start):
                meals = [m for m in week["meals"] if m["date"] == date]
                lines.append(f"{date}: {sum(m['kcal'] for m in meals):.0f} kcal; {sum(m['protein_g'] for m in meals):.0f} g protein (estimates).")
        elif part == "training":
            lines.extend(["10,000 steps is the requested starting target, not a universal medical requirement. Actual steps are separate logged facts.", "",
                          *basis_lines(week.get("justifications", {}).get("workouts")), "",
                          "| Date | Session | Time | Minutes | Steps target | Logged steps | Saved constraint |", "|---|---|---|---:|---:|---:|---|"])
            for date in W.dates(start):
                workout = week["workouts"].get(date, {})
                values = [date, workout.get("session"), workout.get("time"), workout.get("minutes"), workout.get("steps_target", 10000),
                          (daily or {}).get(date, {}).get("steps"), workout.get("constraint", "not recorded")]
                lines.append("| " + " | ".join(cell(value) for value in values) + " |")
        elif part == "changes":
            if not week["history"]:
                lines.append("No saved change history for this week.")
            import json
            for event in week["history"]:
                lines.extend(["", "### " + event["at"], "Reason: " + event["reason"]])
                for change in event["changes"]:
                    lines.extend(["", "Field: " + change["field"], "```json", json.dumps({"before": change["before"], "after": change["after"]}, indent=2, ensure_ascii=True), "```"])
        elif part == "sources":
            sources = []
            for key, selected in week["selected"].items():
                sources.extend(grades.get(key, {}).get("sources", []))
                if selected.get("rationale"):
                    sources.append(selected["rationale"]["source"]["text"])
            sources.extend(basis["source"]["text"] for basis in week.get("justifications", {}).values())
            lines.extend("- " + source for source in dict.fromkeys(sources))
            if not sources:
                lines.append("No supporting resources saved for these choices yet.")
        lines.append("")
    if section == "full-report":
        if report_text is None:
            raise ValueError("The canonical report does not exist. Export the current plan separately or create the report first.")
        lines.extend(["---", "# Entire Existing HealthCoach Report", "",
                      "The following archive is copied from the existing report, not regenerated or retrospectively validated. The current-week snapshot above is separate.", "", report_text])
    return "\n".join(lines) + "\n"


def write_export(text: str, start: str, section: str, directory: Path) -> Path:
    if section not in SECTIONS:
        raise ValueError("Unknown export section.")
    if W.monday(dt.date.fromisoformat(start)) != start:
        raise ValueError("Export week must be a canonical Monday date.")
    directory.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=f"{start}-{section}-", suffix=".md", dir=directory)
    path = Path(filename)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", choices=tuple(SECTIONS))
    parser.add_argument("--week", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--state", type=Path, default=W.DEFAULT_PATH)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--report", type=Path, default=W.HERE / "HEALTHCOACH_REPORT.md")
    parser.add_argument("--daily-log", type=Path, default=daily_log.DEFAULT_LOG)
    parser.add_argument("--directory", type=Path, default=W.HERE / ".healthcoach" / "exports")
    parser.add_argument("--print", action="store_true", dest="print_only")
    args = parser.parse_args(argv)
    try:
        section = args.section
        if section is None:
            for i, (key, label) in enumerate(SECTIONS.items(), 1):
                print(f"{i:2}. {label} ({key})")
            raw = input("Section number, or q cancel: ").strip()
            if raw.lower() == "q":
                return 0
            index = int(raw) - 1
            if not 0 <= index < len(SECTIONS):
                raise ValueError("Choose one of the listed sections.")
            section = list(SECTIONS)[index]
        import supplement_audit as audit
        import week_planner
        import weekly_food_plan
        data = W.load(args.state)
        ledger = CL.load_ledger(args.ledger)
        rows = week_planner.catalog_rows(ledger)
        start = W.monday(args.week)
        saved = data["weeks"].get(start)
        week = saved if saved is not None else W.seed_week(start, rows, audit.load_saved_profile(args.report) or {})
        report_text = args.report.read_text(encoding="utf-8") if section == "full-report" and args.report.exists() else None
        text = render(section, start, week, rows, ledger["intake"], weekly_food_plan._load_food_evidence(), data["research"],
                      daily=daily_log.load_log(args.daily_log)["days"], report_text=report_text, saved=saved is not None)
        if args.print_only:
            print(text)
            return 0
        print("This export may contain private health information. It stays local; nothing is uploaded or copied to the clipboard.")
        if input("Type EXPORT to write a new private Markdown file: ").strip() != "EXPORT":
            print("Cancelled. No export was written.")
            return 0
        path = write_export(text, start, section, args.directory)
        print("Exported: " + str(path))
        return 0
    except (ValueError, OSError, EOFError, KeyboardInterrupt) as exc:
        print(f"No export written: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

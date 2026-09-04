#!/usr/bin/env python3
"""Keyboard-first manual weekly check-in stored in HEALTHCOACH_REPORT.md."""

from __future__ import annotations

import argparse
import curses
import datetime as dt
import sys
import textwrap
from pathlib import Path
from typing import Any

import bevel_share as bevel


HERE = Path(__file__).resolve().parent
DEFAULT_REPORT = HERE / "HEALTHCOACH_REPORT.md"
DAYS = bevel.DAYS
PAGES = (
    ("TRAINING", ("status", "minutes", "avg_hr", "calories", "intensity")),
    ("RECOVERY", ("steps", "weight", "sleep", "rhr")),
    ("FUEL", ("protein", "creatine", "food_plan")),
)
LABELS = {
    "status": "Session", "minutes": "Minutes", "avg_hr": "Avg HR", "calories": "Activity kcal",
    "intensity": "Intensity", "steps": "Steps", "weight": "Weight lb", "sleep": "Sleep h",
    "rhr": "RHR", "protein": "Protein g", "creatine": "Creatine g", "food_plan": "Food plan",
}
TOGGLES = {
    "status": ("UNKNOWN", "DONE", "SKIPPED"),
    "intensity": ("unknown", "easy", "moderate", "hard"),
    "food_plan": ("UNKNOWN", "FOLLOWED", "PARTIAL", "NOT FOLLOWED"),
}
LIMITS = {
    "minutes": (0, 1440), "avg_hr": (20, 250), "calories": (0, 10_000),
    "steps": (0, 200_000), "weight": (50, 1000), "sleep": (0, 24),
    "rhr": (20, 250), "protein": (0, 1000), "creatine": (0, 100),
}


def latest_completed_week(today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    today = today or dt.datetime.now().astimezone().date()
    current_monday = today - dt.timedelta(days=today.weekday())
    start = current_monday - dt.timedelta(days=7)
    return start, start + dt.timedelta(days=6)


def empty_rows() -> list[dict[str, Any]]:
    return [{
        "status": "UNKNOWN", "minutes": None, "avg_hr": None, "calories": None,
        "intensity": "unknown", "steps": None, "weight": None, "sleep": None,
        "rhr": None, "protein": None, "creatine": None, "food_plan": "UNKNOWN",
    } for _ in DAYS]


def edit_number(stdscr, prompt: str, current: Any, low: float, high: float) -> float | None | object:
    height, width = stdscr.getmaxyx()
    curses.echo()
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    try:
        row = height - 2
        stdscr.move(row, 0)
        stdscr.clrtoeol()
        initial = "" if current is None else str(current)
        message = f"{prompt} [{initial or 'UNKNOWN'}] (blank=UNKNOWN, Esc=cancel): "
        stdscr.addnstr(row, 0, message, max(1, width - 1), curses.A_BOLD)
        stdscr.refresh()
        raw = stdscr.getstr(row, min(len(message), width - 2), 18).decode("utf-8", errors="ignore").strip()
    finally:
        curses.noecho()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return current
    if not low <= value <= high:
        return current
    return int(value) if value.is_integer() else value


def collect_week() -> list[dict[str, Any]] | None:
    rows = empty_rows()
    result: list[dict[str, Any]] | None = None

    def run(stdscr) -> None:
        nonlocal result
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        day_index = 0
        field_index = 0
        page_index = 0
        message = ""
        show_help = False
        while True:
            height, width = stdscr.getmaxyx()
            stdscr.erase()
            page_name, fields = PAGES[page_index]
            try:
                stdscr.addnstr(0, 0, "HEALTHCOACH  /  WEEKLY CHECK-IN", max(1, width - 1), curses.A_BOLD)
                stdscr.addnstr(1, 0, "Manual facts only · UNKNOWN stays unknown · stored inside one report", max(1, width - 1), curses.A_DIM)
                page_tabs = "   ".join(
                    f"{'[' if index == page_index else ' '}{name}{']' if index == page_index else ' '}"
                    for index, (name, _) in enumerate(PAGES)
                )
                stdscr.addnstr(3, 0, page_tabs, max(1, width - 1), curses.A_BOLD)
                stdscr.addnstr(4, 0, "Tab page  ↑↓ day  ←→ field  Space toggle  Enter edit  s save  ? help  q cancel", max(1, width - 1), curses.A_DIM)
                col_width = max(12, (width - 12) // len(fields))
                stdscr.addnstr(6, 0, "Day", 10, curses.A_UNDERLINE)
                for index, field in enumerate(fields):
                    stdscr.addnstr(6, 11 + index * col_width, LABELS[field], col_width - 1, curses.A_UNDERLINE)
                for row_index, day in enumerate(DAYS):
                    y = 8 + row_index * 2
                    day_attr = curses.A_BOLD if row_index == day_index else curses.A_NORMAL
                    stdscr.addnstr(y, 0, ("> " if row_index == day_index else "  ") + day[:8], 10, day_attr)
                    for index, field in enumerate(fields):
                        value = rows[row_index][field]
                        shown = "—" if value is None else str(value)
                        attr = curses.A_REVERSE if row_index == day_index and index == field_index else curses.A_NORMAL
                        stdscr.addnstr(y, 11 + index * col_width, shown, col_width - 1, attr)
                    stdscr.addnstr(y + 1, 2, bevel.PLAN[day][0], max(1, width - 3), curses.A_DIM)
                footer = message or "Tip: you can save partial facts. Missing protein, food, or workout data will remain visibly UNKNOWN."
                stdscr.addnstr(height - 1, 0, footer, max(1, width - 1), curses.A_BOLD if message else curses.A_DIM)
                if show_help:
                    help_lines = (
                        "SPACE cycles categorical cells. ENTER edits numbers.",
                        "TRAINING: device calories are workload estimates, never food targets.",
                        "RECOVERY: weight may be entered on only the mornings you weighed.",
                        "FUEL: mark protein/creatine only from your own log; wearables cannot measure them.",
                        "Press any key to close help.",
                    )
                    top = max(1, (height - len(help_lines) - 4) // 2)
                    left = max(1, (width - 74) // 2)
                    for offset, line in enumerate(("WEEKLY CHECK-IN HELP", "", *help_lines)):
                        stdscr.addnstr(top + offset, left, line, min(72, width - left - 1), curses.A_REVERSE)
                stdscr.refresh()
            except curses.error:
                pass
            key = stdscr.getch()
            if show_help:
                show_help = False
                continue
            message = ""
            if key in (ord("q"), ord("Q"), 27):
                return
            if key == ord("?"):
                show_help = True
            elif key in (9, curses.KEY_BTAB):
                page_index = (page_index + ( -1 if key == curses.KEY_BTAB else 1)) % len(PAGES)
                field_index = 0
            elif key in (curses.KEY_UP, ord("k")):
                day_index = (day_index - 1) % len(DAYS)
            elif key in (curses.KEY_DOWN, ord("j")):
                day_index = (day_index + 1) % len(DAYS)
            elif key in (curses.KEY_LEFT, ord("h")):
                field_index = (field_index - 1) % len(fields)
            elif key in (curses.KEY_RIGHT, ord("l")):
                field_index = (field_index + 1) % len(fields)
            elif key == ord(" "):
                field = fields[field_index]
                if field in TOGGLES:
                    options = TOGGLES[field]
                    rows[day_index][field] = options[(options.index(rows[day_index][field]) + 1) % len(options)]
                else:
                    message = "Press Enter to type a number; blank records UNKNOWN."
            elif key in (10, 13, curses.KEY_ENTER):
                field = fields[field_index]
                if field in TOGGLES:
                    options = TOGGLES[field]
                    rows[day_index][field] = options[(options.index(rows[day_index][field]) + 1) % len(options)]
                else:
                    low, high = LIMITS[field]
                    rows[day_index][field] = edit_number(
                        stdscr, f"{DAYS[day_index]} {LABELS[field]}", rows[day_index][field], low, high
                    )
            elif key in (ord("s"), ord("S")):
                result = rows
                return

    curses.wrapper(run)
    return result


def metric(value: Any) -> dict[str, Any]:
    return {"value": value, "origin": "MANUALLY_LOGGED" if value is not None else "UNKNOWN"}


def package_from_rows(rows: list[dict[str, Any]], start: dt.date, end: dt.date) -> dict[str, Any]:
    days: list[dict[str, Any]] = []
    for index, (name, row) in enumerate(zip(DAYS, rows)):
        sessions: list[dict[str, Any]] = []
        notes: list[str] = []
        if row["status"] == "DONE":
            sessions.append({
                "name": bevel.PLAN[name][0],
                "duration_min": row["minutes"],
                "avg_hr_bpm": row["avg_hr"],
                "calories_burned": row["calories"],
                "intensity": row["intensity"],
                "origin": "MANUALLY_LOGGED",
            })
        elif row["status"] == "SKIPPED":
            notes.append("Planned main session manually marked skipped; daily non-session rules are not inferred.")
        foods = [] if row["food_plan"] == "UNKNOWN" else [{
            "name": "HealthCoach day-specific food plan",
            "servings": None,
            "tolerance": row["food_plan"].lower(),
            "origin": "MANUALLY_LOGGED",
        }]
        days.append({
            "day": name,
            "date": (start + dt.timedelta(days=index)).isoformat(),
            "sessions": sessions,
            "steps": metric(row["steps"]),
            "sleep_hours": metric(row["sleep"]),
            "bedtime": {"value": None, "origin": "UNKNOWN"},
            "resting_hr_bpm": metric(row["rhr"]),
            "weight_lb": metric(row["weight"]),
            "protein_g": metric(row["protein"]),
            "creatine_g": metric(row["creatine"]),
            "foods": foods,
            "notes": notes,
        })
    return {
        "schema_version": 1,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "data_sources": ["HealthCoach dashboard manual weekly check-in"],
        "days": days,
        "observations": [],
        "recommendations": [],
        "unknowns": ["Every blank field was deliberately preserved as UNKNOWN."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a manual HealthCoach week inside the canonical report")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = args.report.expanduser().resolve()
    if not report.exists():
        print("No HEALTHCOACH_REPORT.md exists yet. Run ./hc and choose Start/update assessment first.")
        return 2
    start, end = latest_completed_week()
    print(f"Opening the most recently completed week: {start} through {end}")
    rows = collect_week()
    if rows is None:
        print("Weekly check-in cancelled; the report was not changed.")
        return 0
    package = package_from_rows(rows, start, end)
    validation = bevel.validate_package(package)
    if validation:
        print("The manual package failed validation:", file=sys.stderr)
        for error in validation:
            print(f"- {error}", file=sys.stderr)
        return 2
    conflicts = bevel.locked_conflicts(package)
    execution = bevel.execution_findings(package)
    evidence_review, evidence_sources = bevel.evidence_disabled_note()
    block = bevel.exchange_markdown(package, validation, conflicts, execution, evidence_review, evidence_sources)
    bevel.update_report_ledger(report, block, str(package["week_start"]))
    print(f"Saved {start} through {end} inside {report.name}.")
    print("Regenerate from the dashboard when you want the next food plan to use this trajectory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

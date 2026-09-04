#!/usr/bin/env python3
"""One keyboard-first front door for the local HealthCoach workflow."""

from __future__ import annotations

import argparse
import curses
import datetime as dt
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
REPORT = HERE / "HEALTHCOACH_REPORT.md"


@dataclass(frozen=True)
class Action:
    key: str
    title: str
    detail: str
    command: tuple[str, ...]
    destructive: bool = False
    requires_report: bool = False


ACTIONS = (
    Action("assessment", "START / UPDATE MY PLAN", "Resume saved answers, edit the visual week, research selections, and regenerate the one report.", ("./hc-supplements",)),
    Action("weekly", "LOG THE COMPLETED WEEK", "Enter workout duration, HR, activity calories, steps, weight, recovery, protein, creatine, and food-plan completion.", (sys.executable, "weekly_checkin.py"), requires_report=True),
    Action("bevel", "SHARE / VERIFY WITH BEVEL", "Open the weekly clipboard exchange: setup, request, import, verify, and return.", ("./hc-bevel",), requires_report=True),
    Action("report", "OPEN MY REPORT", "Browse chapters and logical pages with Space, search, and arrow keys.", ("./hc-report",), requires_report=True),
    Action("question", "ASK ONE EVIDENCE QUESTION", "Type one focused question and see its local retrieved answer without making extra documents.", (sys.executable, "coach.py")),
    Action("foods", "REFRESH WHOLE-FOOD SOURCES", "Fetch legal open-access human food research, rebuild the local index, and run retrieval checks.", ("./hc-refresh-whole-foods",)),
    Action("nootropics", "REFRESH NOOTROPIC SOURCES", "Refresh ALCAR, citicoline, uridine, Noopept, bromantane, and related source folders.", ("./hc-refresh-nootropics",)),
    Action("experimental", "REFRESH EXPERIMENTAL SOURCES", "Refresh the research-only gray/experimental evidence scope; no use protocol is created.", ("./hc-refresh-experimental",)),
    Action("test", "TEST THE RESEARCH LIBRARY", "Run retrieval smoke tests and show whether the local index is ready.", (sys.executable, "test_retrieval.py")),
    Action("reset", "START OVER FROM GROUND ZERO", "Ignore the saved intake and build a replacement only after a new assessment completes.", ("./hc-supplements", "--start-over"), destructive=True),
)


def status_lines() -> tuple[str, str, str]:
    if not REPORT.exists():
        return "REPORT  NOT CREATED", "PROFILE  NOT SAVED", "WEEKS  0"
    text = REPORT.read_text(encoding="utf-8", errors="replace")
    modified = dt.datetime.fromtimestamp(REPORT.stat().st_mtime).astimezone().strftime("%b %d %H:%M")
    profile = "SAVED" if "HC_PROFILE_STATE_START" in text else "LEGACY / REGENERATE"
    weeks = len(set(re.findall(r"HC_BEVEL_WEEK_START ([0-9-]+)", text)))
    return f"REPORT  {modified}", f"PROFILE  {profile}", f"WEEKS  {weeks}"


def text_input(stdscr, prompt: str, *, max_length: int = 600) -> str:
    height, width = stdscr.getmaxyx()
    curses.echo()
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    try:
        stdscr.move(height - 2, 0)
        stdscr.clrtoeol()
        shown = prompt + ": "
        stdscr.addnstr(height - 2, 0, shown, max(1, width - 1), curses.A_BOLD)
        stdscr.refresh()
        return stdscr.getstr(height - 2, min(len(shown), width - 2), max_length).decode("utf-8", errors="ignore").strip()
    finally:
        curses.noecho()
        try:
            curses.curs_set(0)
        except curses.error:
            pass


def choose_action() -> Action | None:
    chosen: Action | None = None

    def run(stdscr) -> None:
        nonlocal chosen
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        cursor = 0
        query = ""
        message = ""
        show_help = False
        while True:
            height, width = stdscr.getmaxyx()
            visible = [action for action in ACTIONS if query.lower() in (action.title + " " + action.detail).lower()]
            if not visible:
                visible = list(ACTIONS)
                query = ""
            cursor %= len(visible)
            stdscr.erase()
            try:
                stdscr.addnstr(0, 0, "HEALTHCOACH", max(1, width - 1), curses.A_BOLD)
                stdscr.addnstr(1, 0, "ONE REPORT  /  LOCAL EVIDENCE  /  WEEKLY FEEDBACK", max(1, width - 1), curses.A_DIM)
                statuses = "    ".join(status_lines())
                stdscr.addnstr(3, 0, statuses, max(1, width - 1), curses.A_BOLD)
                controls = "↑↓ move   Space/Enter open   / filter   ? help   q quit"
                stdscr.addnstr(5, 0, controls, max(1, width - 1), curses.A_DIM)
                if query:
                    stdscr.addnstr(6, 0, f"FILTER  {query}", max(1, width - 1), curses.A_BOLD)
                row = 8
                page_size = max(1, (height - row - 1) // 3)
                first = max(0, min(cursor - page_size // 2, len(visible) - page_size))
                for index in range(first, min(len(visible), first + page_size)):
                    action = visible[index]
                    attr = curses.A_REVERSE if index == cursor else curses.A_NORMAL
                    marker = ">" if index == cursor else " "
                    stdscr.addnstr(row, 0, f"{marker} {action.title}", max(1, width - 1), attr | curses.A_BOLD)
                    row += 1
                    detail_width = max(24, width - 6)
                    detail = textwrap.wrap(action.detail, detail_width)[0]
                    stdscr.addnstr(row, 4, detail, max(1, width - 5), curses.A_DIM)
                    row += 1
                    row += 1
                footer = message or "Data stays in HEALTHCOACH_REPORT.md unless you explicitly start over."
                stdscr.addnstr(height - 1, 0, footer, max(1, width - 1), curses.A_BOLD if message else curses.A_DIM)
                if show_help:
                    help_lines = (
                        "DASHBOARD HELP",
                        "",
                        "This is the only command you need: ./hc",
                        "Start/update resumes saved answers. Weekly log records facts without guessing.",
                        "Bevel is an explicit clipboard handoff. Source refreshes download legal open-access papers.",
                        "Start over asks for RESET and does not overwrite the report until generation succeeds.",
                        "Press any key to close.",
                    )
                    top = max(1, (height - len(help_lines)) // 2)
                    left = max(1, (width - 80) // 2)
                    for offset, line in enumerate(help_lines):
                        stdscr.addnstr(top + offset, left, line, min(78, width - left - 1), curses.A_REVERSE)
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
            elif key in (curses.KEY_UP, ord("k")):
                cursor = (cursor - 1) % len(visible)
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = (cursor + 1) % len(visible)
            elif key == ord("/"):
                query = text_input(stdscr, "Filter actions", max_length=80)
                cursor = 0
            elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
                action = visible[cursor]
                if action.requires_report and not REPORT.exists():
                    message = "Create the report first: choose START / UPDATE MY PLAN."
                    continue
                if action.destructive:
                    confirmation = text_input(stdscr, "Type RESET to begin a replacement assessment", max_length=16)
                    if confirmation != "RESET":
                        message = "Start-over cancelled; saved data was not changed."
                        continue
                chosen = action
                return

    curses.wrapper(run)
    return chosen


def run_action(action: Action) -> int:
    command = list(action.command)
    if action.key == "question":
        question = input("One evidence question: ").strip()
        if not question:
            print("No question entered.")
            return 0
        command.append(question)
    print(f"\n── {action.title} ──\n")
    return subprocess.run(command, cwd=HERE).returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the HealthCoach dashboard")
    parser.add_argument("--action", choices=tuple(action.key for action in ACTIONS), help="automation/testing shortcut")
    args = parser.parse_args(argv)
    if args.action:
        action = next(item for item in ACTIONS if item.key == args.action)
        if action.requires_report and not REPORT.exists():
            print("No report exists. Run ./hc and choose START / UPDATE MY PLAN first.")
            return 2
        return run_action(action)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("HealthCoach dashboard requires an interactive terminal. Run: ./hc")
        return 2
    while True:
        action = choose_action()
        if action is None:
            print("HealthCoach closed. Your report and saved data were not changed.")
            return 0
        run_action(action)
        try:
            input("\nPress Enter to return to the HealthCoach dashboard…")
        except (EOFError, KeyboardInterrupt):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())

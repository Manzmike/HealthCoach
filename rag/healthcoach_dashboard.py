#!/usr/bin/env python3
"""One keyboard-first front door for the local HealthCoach workflow."""

from __future__ import annotations

import argparse
import curses
import datetime as dt
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import today as T

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
    Action("export", "EXPORT PLAN SECTIONS / ENTIRE REPORT", "Output the overview, meals, training, selected items with grades/reasons, sources, change history, or the complete report to a private local file.", (sys.executable, "plan_export.py")),
    Action("lifestyle", "LIFESTYLE PLAN / MOVE + PLATE + WEEK", "Generate the curated Move/Plate/Week/Constraints/Branches plan from A/B evidence sheets. No kelp, no DHEA/progesterone OTC, no detox.", (sys.executable, "lifestyle_plan.py", "--print")),
    Action("week", "YOUR WEEK / SELECTIONS + GRADES", "See all chosen foods and items, separate overall/personal grades, meals, training, and why changes were made.", (sys.executable, "week_planner.py")),
    Action("gray-review", "PEPTIDES / GRAY-MARKET SELECTIONS", "Choose and compare the full gray-market catalog. Evidence grades, personal fit, current use, and review requirements stay separate.", (sys.executable, "week_planner.py", "--view", "gray")),
    Action("nootropic-review", "NOOTROPIC SELECTIONS", "See selected nootropics, overall and personal grades, sources, and recorded routines or review notes.", (sys.executable, "week_planner.py", "--view", "nootropic")),
    Action("supplement-review", "SUPPLEMENT SELECTIONS", "Compare supplements for this week without turning selection into a dose or a report of actual use.", (sys.executable, "week_planner.py", "--view", "supplement")),
    Action("workouts", "WORKOUTS / 10K STEPS", "Review and realign seven dated workouts and editable step targets. Preserve constraints and save your reason.", (sys.executable, "week_planner.py", "--view", "training")),
    Action("week-changes", "WHY MY WEEK CHANGED", "Review dated before/after edits and your reason for each saved change.", (sys.executable, "week_planner.py", "--view", "changes")),
    Action("today", "SHOW TODAY", "Read saved placement, adopted/current items, and daily facts. No generation, doses, or plan changes.", (sys.executable, "today.py")),
    Action("daily", "LOG TODAY", "Explicitly save main-activity status, optional duration, recovery, and a factual note to a private daily log. Weekly packages are untouched.", (sys.executable, "daily_log.py")),
    Action("assessment", "REVIEW MY PLAN", "Review goals, schedule, and personal context, then explicitly choose whether to generate an updated plan.", ("./hc-supplements",)),
    Action("candidates", "YOUR TRACKED ITEMS", "Review what you use, what you are considering, and what stays in research. Record decisions separately from actual use.", (sys.executable, "candidate_manager.py")),
    Action("weekly", "LOG THE COMPLETED WEEK", "Enter workout duration, HR, activity calories, steps, weight, recovery, protein, creatine, and food-plan completion.", (sys.executable, "weekly_checkin.py"), requires_report=True),
    Action("bevel", "SHARE / VERIFY WITH BEVEL", "Open the weekly clipboard exchange: setup, request, import, verify, and return.", ("./hc-bevel",), requires_report=True),
    Action("report", "WHY / FULL RESEARCH RECORD", "Open the durable plan and research archive. Browse chapters, explanations, and sources on demand.", ("./hc-report",), requires_report=True),
    Action("question", "ASK ONE EVIDENCE QUESTION", "Type one focused question and see its local retrieved answer without making extra documents.", (sys.executable, "coach.py")),
    Action("foods", "REFRESH WHOLE-FOOD SOURCES", "Fetch legal open-access human food research, rebuild the local index, and run retrieval checks.", ("./hc-refresh-whole-foods",)),
    Action("food-review", "FOOD SELECTIONS / OVERALL + FOR YOU", "Choose foods for this week, compare evidence and personal-fit grades, then construct meals from those choices.", (sys.executable, "week_planner.py", "--view", "food")),
    Action("food-plan", "MEAL PLAN / WHAT + WHEN", "Build and review dated meal portions from selected foods, set meal times, move portions, and inspect target gaps.", (sys.executable, "week_planner.py", "--view", "meals")),
    Action("symptoms", "SYMPTOM CHECK-IN", "Pick specific symptoms (dry scalp, joint pain, bloating, brain fog, ...) and get real, already-sourced food/supplement/lifestyle flags — hard warnings, soft bans, and positives. Writes a skim version and a full-detail version.", (sys.executable, "symptom_checkin.py")),
    Action("nootropics", "REFRESH NOOTROPIC SOURCES", "Refresh ALCAR, citicoline, uridine, Noopept, bromantane, and related source folders.", ("./hc-refresh-nootropics",)),
    Action("experimental", "GRAY-MARKET / EXPERIMENTAL RESEARCH SOURCES", "Refresh the research-only gray/experimental evidence scope; no use protocol is created.", ("./hc-refresh-experimental",)),
    Action("test", "TEST THE RESEARCH LIBRARY", "Run retrieval smoke tests and show whether the local index is ready.", (sys.executable, "test_retrieval.py")),
    Action("reset", "START OVER FROM GROUND ZERO", "Ignore the saved intake and build a replacement only after a new assessment completes.", ("./hc-supplements", "--start-over"), destructive=True),
    Action("clear", "CLEAR ALL MY DATA", "Delete the report, ledger, daily log, weekly plans, and caches. You get a completely clean slate.", (sys.executable, "-c", "import os, shutil; [os.remove(p) for p in ['HEALTHCOACH_REPORT.md'] if os.path.exists(p)]; [shutil.rmtree(d, ignore_errors=True) for d in ['.healthcoach', 'logs', 'lancedb']]; print('All personal data removed. Run ./hc to start fresh.')"), destructive=True),
)


GROUPS = {
    "Today": ("week", "food-review", "gray-review", "nootropic-review", "supplement-review", "food-plan", "workouts", "export", "daily", "weekly", "today"),
    "Plan": ("week", "food-review", "food-plan", "lifestyle", "gray-review", "nootropic-review", "supplement-review", "workouts", "week-changes", "export", "assessment", "candidates", "report"),
    "Log/Review": ("daily", "weekly", "bevel", "symptoms"),
    "Research": ("question", "report", "candidates", "experimental", "nootropics", "foods"),
    "Maintenance": ("test", "reset", "clear"),
}


def group_actions(group: str, query: str = "") -> list[Action]:
    if query:
        return [action for action in ACTIONS if query.lower() in (action.key + " " + action.title + " " + action.detail).lower()]
    by_key = {action.key: action for action in ACTIONS}
    return [by_key[key] for key in GROUPS[group]]


def status_lines(state: dict | None = None) -> tuple[str, str, str]:
    state = state if state is not None else T.load_today(report=REPORT)
    return (
        "REPORT  " + ("AVAILABLE" if state["report_available"] else "NOT CREATED"),
        "PROFILE  " + ("SAVED" if state["profile_saved"] else "NOT SAVED"),
        f"WEEKS  {len(state['weeks'])}",
    )


def put(stdscr, y: int, text: str, attr: int = 0) -> None:
    height, width = stdscr.getmaxyx()
    if 0 <= y < height and width > 1:
        try:
            stdscr.addnstr(y, 0, T.display_text(text), width - 1, attr)
        except curses.error:
            pass


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
        group_index = 0
        groups = tuple(GROUPS)
        query = ""
        message = ""
        show_help = False
        show_review = False
        scroll = 0
        state = T.load_today(report=REPORT)
        while True:
            height, width = stdscr.getmaxyx()
            if state["date"] != dt.datetime.now().astimezone().date().isoformat():
                state = T.load_today(report=REPORT)
            group = groups[group_index]
            visible = group_actions(group, query)
            cursor %= max(1, len(visible))
            stdscr.erase()
            if height < 16 or width < 40:
                put(stdscr, 0, "Resize to 40 columns x 16 rows.", curses.A_BOLD)
                put(stdscr, 1, "q quit; no state is changed.")
                stdscr.refresh()
                if stdscr.getch() in (ord("q"), ord("Q"), 27):
                    return
                continue
            put(stdscr, 0, "HEALTHCOACH / PLAN - EXECUTE - LOG - ADJUST", curses.A_BOLD)
            if state.get("first_run"):
                stdscr.erase()
                first_run_text = (
                    "HEALTHCOACH — FIRST RUN",
                    "",
                    "No profile, report, or saved data found.",
                    "",
                    "This is decision support, not medical clearance or a prescription.",
                    "It does not invent doses, protocols, or diagnose conditions.",
                    "All selections require a source-linked reason; grades are screening heuristics.",
                    "",
                    "Your only first action: Plan -> REVIEW MY PLAN",
                    "  (creates profile, calendar, and candidate selections)",
                    "",
                    "Press A to acknowledge and continue, or q to quit.",
                )
                for y, line in enumerate(first_run_text, 3):
                    put(stdscr, y, line, curses.A_BOLD if y == 3 else 0)
                stdscr.refresh()
                key = stdscr.getch()
                if key in (ord("a"), ord("A")):
                    pass  # Continue to normal flow
                elif key in (ord("q"), ord("Q"), 27):
                    return
                else:
                    continue
                # Reload state after acknowledgment
                state = T.load_today(report=REPORT)
            tabs = "  ".join(f"{'[' if i == group_index else ''}{i + 1} {name}{']' if i == group_index else ''}" for i, name in enumerate(groups))
            tab_lines = textwrap.wrap(tabs, width - 1)
            for y, line in enumerate(tab_lines, 2):
                put(stdscr, y, line, curses.A_BOLD)
            row = len(tab_lines) + 3
            put(stdscr, row, "Tab/1-5 group  Up/Down move  Enter open  / find  ? help")
            row += 2
            if not query and group == "Today":
                for line in textwrap.wrap("f Foods | g Peptides/Gray | n Nootropics | s Supplements | m Meals | t Training | c Changes | e Export | l Lifestyle", width - 1):
                    put(stdscr, row, line, curses.A_BOLD)
                    row += 1
            if query:
                put(stdscr, row, f"ALL ACTIONS / {query} / {len(visible)} matches", curses.A_BOLD)
                row += 2
            elif group == "Today":
                content = [part for line in (T.summary_lines(state, show_review=True) if show_review else T.dashboard_lines(state))
                           for part in (textwrap.wrap(line, width - 1) or [""])]
                body_height = max(1, height - row - 7)
                scroll = max(0, min(scroll, max(0, len(content) - body_height)))
                for y, line in enumerate(content[scroll:scroll + body_height], row):
                    put(stdscr, y, line)
                row += body_height
                put(stdscr, row, f"PgUp/PgDn details {scroll + 1}-{min(len(content), scroll + body_height)}/{len(content)}  v review  r refresh", curses.A_DIM)
                row += 1
            else:
                put(stdscr, row, "    ".join(status_lines(state)), curses.A_DIM)
                row += 2
            page_size = max(1, (height - row - 1) // 2)
            if visible:
                first = max(0, min(cursor - page_size // 2, len(visible) - page_size))
                for index in range(first, min(len(visible), first + page_size)):
                    action = visible[index]
                    attr = curses.A_REVERSE if index == cursor else curses.A_NORMAL
                    marker = ">" if index == cursor else " "
                    put(stdscr, row, f"{marker} {action.title}", attr | curses.A_BOLD)
                    row += 1
                    put(stdscr, row, "  " + action.detail, curses.A_DIM)
                    row += 1
            else:
                put(stdscr, row, "No matching action. / search again; Esc clears the search.")
            footer = message or "l log today  w weekly review  Esc back  q quit / Today is read-only"
            put(stdscr, height - 1, footer, curses.A_BOLD if message else curses.A_DIM)
            if show_help:
                stdscr.erase()
                help_text = (
                    "DASHBOARD HELP", "",
                    "Tab/Left/Right or 1-5 changes group. Up/Down selects actions; Enter/Space opens.",
                    "/ searches every action, including research and maintenance. Esc clears search or returns to Today.",
                    "Today: f Foods, g Peptides/Gray, n Nootropics, s Supplements, m Meals, t Training, c Changes, e Export, x Clear all data.",
                    "PgUp/PgDn scrolls facts; v shows reported-use review; r reloads saved state.",
                    "l opens the explicit daily log; w opens the completed-week check-in.",
                    "Daily facts are separate from weekly Bevel packages. Neither opening Today nor logging adjusts the plan.",
                    "Research retains supplements, peptides, nootropics and gray-market topics. A research item is not an adopted action.",
                    "Bevel uses an explicit clipboard handoff. Source refreshes access the network.",
                    "State lives in the report and private .healthcoach files. Start over requires RESET.",
                    "Press any key to close.",
                )
                help_lines = [part for line in help_text for part in (textwrap.wrap(line, width - 1) or [""])]
                for y, line in enumerate(help_lines[:height - 1]):
                    put(stdscr, y, line)
                put(stdscr, height - 1, "Press any key to close help.", curses.A_REVERSE)
            stdscr.refresh()
            key = stdscr.getch()
            if show_help:
                show_help = False
                continue
            message = ""
            if key in (ord("q"), ord("Q")):
                return
            if key == 27:
                if query:
                    query = ""
                    cursor = 0
                elif group_index:
                    group_index = cursor = scroll = 0
                else:
                    return
            elif key == ord("?"):
                show_help = True
            elif key in (9, curses.KEY_RIGHT, curses.KEY_LEFT, curses.KEY_BTAB) or ord("1") <= key <= ord("5"):
                if ord("1") <= key <= ord("5"):
                    group_index = key - ord("1")
                else:
                    group_index = (group_index + (-1 if key in (curses.KEY_LEFT, curses.KEY_BTAB) else 1)) % len(groups)
                query = ""
                cursor = scroll = 0
            elif key == ord("r"):
                state = T.load_today(report=REPORT)
            elif key == ord("v"):
                show_review = not show_review
            elif key in (curses.KEY_NPAGE, curses.KEY_PPAGE):
                scroll += (1 if key == curses.KEY_NPAGE else -1) * max(1, height // 3)
            elif key in (curses.KEY_UP, ord("k")):
                cursor = (cursor - 1) % max(1, len(visible))
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = (cursor + 1) % max(1, len(visible))
            elif key == ord("/"):
                query = text_input(stdscr, "Filter actions", max_length=80)
                cursor = 0
            elif group == "Today" and not query and key in map(ord, "fgnsmtcexy"):
                if state.get("first_run"):
                    message = "First run: choose Plan -> REVIEW MY PLAN to create your profile."
                    continue
                shortcut = {"f": "food-review", "g": "gray-review", "n": "nootropic-review", "s": "supplement-review", "m": "food-plan", "t": "workouts", "c": "week-changes", "e": "export", "x": "clear", "y": "lifestyle"}
                chosen = next(action for action in ACTIONS if action.key == shortcut[chr(key)])
                return
            elif key in (10, 13, curses.KEY_ENTER, ord(" "), ord("l"), ord("w")):
                if key in (ord("l"), ord("w")):
                    action = next(a for a in ACTIONS if a.key == ("daily" if key == ord("l") else "weekly"))
                elif visible:
                    action = visible[cursor]
                else:
                    continue
                if state.get("first_run") and action.key != "assessment":
                    message = "First run: choose Plan -> REVIEW MY PLAN to create your profile."
                    continue
                if action.requires_report and not REPORT.exists():
                    message = "Create the report first: Plan -> REVIEW MY PLAN."
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
            print("No report exists. Run ./hc and choose Plan -> REVIEW MY PLAN first.")
            return 2
        if action.destructive:
            try:
                confirmation = input("Type RESET to begin a replacement assessment: ").strip()
            except (EOFError, KeyboardInterrupt):
                confirmation = ""
            if confirmation != "RESET":
                print("Start-over cancelled; saved data was not changed.")
                return 0
        return run_action(action)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("HealthCoach dashboard requires an interactive terminal. Run: ./hc")
        return 2
    while True:
        action = choose_action()
        if action is None:
            print("HealthCoach closed. Explicitly saved logs and decisions are retained.")
            return 0
        run_action(action)
        try:
            input("\nPress Enter to return to the HealthCoach dashboard…")
        except (EOFError, KeyboardInterrupt):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())

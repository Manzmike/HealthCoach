#!/usr/bin/env python3
"""Create a clipboard-only handoff from HealthCoach to Bevel Intelligence.

Bevel does not publish a chat-ingestion API for this project to call.  This
tool therefore reads the one canonical HealthCoach report, builds a bounded
prompt for a supported Bevel Intelligence workflow, and copies that prompt to
the macOS clipboard.  It never writes another report or a sidecar export.
"""

from __future__ import annotations

import argparse
import curses
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from report_navigator import Chapter, parse_report


HERE = Path(__file__).resolve().parent
DEFAULT_REPORT = HERE / "HEALTHCOACH_REPORT.md"
BEVEL_FILE_NAME = "HealthCoach Operating Context"
CHECK_IN_TITLE = "HealthCoach weekly review"
CHECK_IN_WHEN = "Sunday at 18:30 local time"
HIDDEN_REPORT_LINE = re.compile(r"^\s*<(?:a\s+id=|/?div\b)", re.I)


@dataclass(frozen=True)
class ShareMode:
    key: str
    title: str
    description: str


MODES = (
    ShareMode(
        "setup",
        "SET UP / REFRESH BEVEL",
        "Copy the operating plan, targets, current choices, and a recurring weekly-review request.",
    ),
    ShareMode(
        "weekly",
        "RUN THIS WEEK'S REVIEW",
        "Ask Bevel to compare its measured Monday-Sunday data with the locked HealthCoach plan.",
    ),
    ShareMode(
        "workouts",
        "BUILD BEVEL WORKOUT TEMPLATES",
        "Copy the exact three lifting sessions for Bevel's Strength Builder.",
    ),
)


SETUP_CHAPTERS = (
    "I.02",  # operating-week identity and start-any-day rule
    "I.03",  # locked numbers
    "I.04",  # week at a glance
    "I.05",  # exact daily cards and lift prescriptions
    "I.06",  # desk-day movement
    "I.07",  # heat and bike substitution
    "I.08",  # RED-S and phase rules
    "I.09",  # explicit exclusions
    "II.03",  # nutrition targets
    "II.07",  # default eating day
    "II.16",  # measurement protocol
    "II.17",  # cut brakes
    "II.21",  # heat/electrolytes
    "III.01",  # selected whole-life priorities
    "III.10",  # change control
    "IV.01",  # recorded intake answers
    "IV.02",  # personalized stack changes
    "IV.05",  # evidence shortlist
    "IV.25",  # explicit coverage gaps
)

WEEKLY_CHAPTERS = ("I.03", "I.04", "II.16", "II.17")
WORKOUT_CHAPTERS = ("I.03", "I.04", "I.05", "I.07", "I.08")


def chapter_map(chapters: Sequence[Chapter]) -> dict[str, Chapter]:
    return {chapter.chapter_id: chapter for chapter in chapters}


def selected_context(chapters: Sequence[Chapter], wanted: Sequence[str]) -> str:
    by_id = chapter_map(chapters)
    missing = [chapter_id for chapter_id in wanted if chapter_id not in by_id]
    if missing:
        raise SystemExit(
            "The report is missing required logical chapters: "
            + ", ".join(missing)
            + "\nRegenerate it with ./hc-supplements, then run ./hc-bevel again."
        )
    blocks: list[str] = []
    for chapter_id in wanted:
        chapter = by_id[chapter_id]
        body = "\n".join(
            line for line in chapter.lines if not HIDDEN_REPORT_LINE.match(line)
        ).strip()
        blocks.append(f"## {chapter.title}\n\n{body}")
    return "\n\n".join(blocks)


def setup_prompt(chapters: Sequence[Chapter]) -> str:
    context = selected_context(chapters, SETUP_CHAPTERS)
    return f"""HEALTHCOACH -> BEVEL INTELLIGENCE HANDOFF

I am deliberately sharing the HealthCoach context below with Bevel Intelligence. Treat it as my user-authored plan and constraints, not as a request to invent a replacement program.

YOUR TASK
1. Create or update one Bevel File named "{BEVEL_FILE_NAME}". Preserve all items labeled locked, all medication boundaries, the Monday-Sunday ordering, skip rules, and stop rules exactly.
2. Create or update one recurring Check-in titled "{CHECK_IN_TITLE}" for {CHECK_IN_WHEN}.
3. The check-in must review the Monday-Sunday week that is ending. Compare planned versus completed sessions, steps, sleep duration/consistency, cardio load, easy-versus-hard distribution, resting-heart-rate trend, and weight trend using Bevel's connected data. Include protein, creatine, symptoms, and medication adherence only when I explicitly logged them; never infer them from wearable data.
4. In every review, label each value MEASURED, MANUALLY LOGGED, PLANNED, or UNKNOWN. Do not convert an UNKNOWN into an estimate.
5. Return: (a) a compact adherence table, (b) meaningful trend changes, (c) data-quality gaps, (d) recovery or safety flags, and (e) no more than three changes for the next week. A readiness or strain score may inform the review but may not silently rewrite the locked plan.
6. Never change or advise a dose for tirzepatide or another prescription. Do not add peptides, stimulants, supplements, a fourth lift, punishment cardio, evening caffeine, Friday heavy legs, or a second interval day.
7. If the HealthCoach text conflicts internally, quote the conflicting lines and ask me which one is authoritative. If your live wearable data conflicts with the plan, report the mismatch; do not rewrite history.
8. Confirm the exact File name, Check-in title, day, and time after creating or updating them.

HEALTHCOACH CONTEXT

{context}

END HEALTHCOACH CONTEXT
"""


def weekly_prompt(chapters: Sequence[Chapter]) -> str:
    context = selected_context(chapters, WEEKLY_CHAPTERS)
    return f"""RUN MY HEALTHCOACH WEEKLY REVIEW IN BEVEL INTELLIGENCE

Use the saved Bevel File "{BEVEL_FILE_NAME}" and Bevel's connected health and workout data. Review the Monday-Sunday week that most recently ended, or the current week through today if I say the week is still in progress.

REVIEW RULES
- Compare the planned day with the workout actually recorded; a missing workout is missing, not automatically a rest day.
- Label every field MEASURED, MANUALLY LOGGED, PLANNED, or UNKNOWN. Never claim protein, creatine, symptoms, food intake, or medication adherence unless I logged it.
- Cover sessions, steps, sleep duration/consistency, cardio load and intensity distribution, resting-heart-rate trend, weight trend, and the skip/heat/recovery rules that were used.
- Show a seven-row Monday-Sunday table, then data-quality gaps, safety/recovery flags, and at most three next-week adjustments.
- Preserve the three-lift structure, Thursday as the only quality-aerobic slot, Saturday long run, 20:15 bed, and medication boundaries. Do not prescribe or change drugs, add gray-market compounds, or recommend punishment cardio.
- If the saved File is missing, create it from the locked excerpt below before reviewing.

LOCKED EXCERPT

{context}

END LOCKED EXCERPT
"""


def workouts_prompt(chapters: Sequence[Chapter]) -> str:
    context = selected_context(chapters, WORKOUT_CHAPTERS)
    return f"""CREATE MY THREE HEALTHCOACH STRENGTH TEMPLATES IN BEVEL

Use the HealthCoach context below to create exactly three reusable Strength Builder templates named:
1. HealthCoach Monday - Lift A Lower
2. HealthCoach Wednesday - Lift B Upper
3. HealthCoach Friday - Lift C Light Full/Upper

Copy the exercises, sets, reps, order, RIR, and rest guidance from the source. Do not invent starting weights. Keep Friday deliberately lighter so Saturday's long run remains viable. Do not turn running, biking, walking, mobility, or a skipped lift into a fourth strength template. Show me the parsed templates for confirmation before changing any ambiguous exercise name.

HEALTHCOACH WORKOUT CONTEXT

{context}

END HEALTHCOACH WORKOUT CONTEXT
"""


def build_prompt(mode: str, chapters: Sequence[Chapter]) -> str:
    if mode == "setup":
        return setup_prompt(chapters)
    if mode == "weekly":
        return weekly_prompt(chapters)
    if mode == "workouts":
        return workouts_prompt(chapters)
    raise ValueError(f"Unknown share mode: {mode}")


def choose_mode() -> str | None:
    chosen: str | None = None

    def run(stdscr) -> None:
        nonlocal chosen
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        cursor = 0
        while True:
            height, width = stdscr.getmaxyx()
            stdscr.erase()
            title = "HEALTHCOACH -> BEVEL INTELLIGENCE"
            help_line = "Up/Down choose - Space/Enter copy - q cancel"
            try:
                stdscr.addnstr(0, 0, title, max(1, width - 1), curses.A_BOLD)
                stdscr.addnstr(1, 0, help_line, max(1, width - 1), curses.A_DIM)
                stdscr.addnstr(
                    3,
                    0,
                    "Nothing is uploaded automatically. The selected prompt goes only to your clipboard.",
                    max(1, width - 1),
                )
                row = 5
                for index, mode in enumerate(MODES):
                    prefix = "> " if index == cursor else "  "
                    attr = curses.A_REVERSE if index == cursor else curses.A_NORMAL
                    stdscr.addnstr(row, 0, prefix + mode.title, max(1, width - 1), attr)
                    row += 1
                    for line in textwrap.wrap(mode.description, width=max(20, width - 6)):
                        stdscr.addnstr(row, 4, line, max(1, width - 5), curses.A_DIM)
                        row += 1
                    row += 1
                footer = "Recommended first: SET UP / REFRESH. Use RUN THIS WEEK'S REVIEW afterward."
                stdscr.addnstr(min(height - 1, row), 0, footer, max(1, width - 1), curses.A_BOLD)
            except curses.error:
                pass
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return
            if key in (curses.KEY_UP, ord("k")):
                cursor = (cursor - 1) % len(MODES)
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = (cursor + 1) % len(MODES)
            elif key in (ord(" "), 10, 13, curses.KEY_ENTER):
                chosen = MODES[cursor].key
                return

    curses.wrapper(run)
    return chosen


def copy_to_clipboard(prompt: str) -> None:
    pbcopy = shutil.which("pbcopy")
    if not pbcopy:
        raise SystemExit(
            "macOS pbcopy was not found. Run with --print and copy the displayed prompt manually."
        )
    subprocess.run([pbcopy], input=prompt, text=True, check=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Copy a HealthCoach plan or weekly-review prompt for Bevel Intelligence"
    )
    result.add_argument(
        "--mode",
        choices=tuple(mode.key for mode in MODES),
        help="setup, weekly, or workouts; omit for the arrow-key menu",
    )
    result.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="canonical report path")
    result.add_argument("--print", action="store_true", help="print instead of copying to clipboard")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    report = args.report.expanduser().resolve()
    chapters = parse_report(report)
    mode = args.mode
    if not mode:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            mode = "setup"
        else:
            mode = choose_mode()
            if mode is None:
                print("Nothing copied.")
                return 0
    prompt = build_prompt(mode, chapters)
    if args.print:
        print(prompt)
        return 0
    copy_to_clipboard(prompt)
    label = next(item.title for item in MODES if item.key == mode)
    print(f"Copied: {label}")
    print(f"Source: {report}")
    print(f"Clipboard size: {len(prompt):,} characters; no export file was created.")
    print("Next: open Bevel -> Intelligence -> new chat, paste, and send.")
    if mode == "setup":
        print(
            f'Bevel should confirm File "{BEVEL_FILE_NAME}" and weekly Check-in '
            f'"{CHECK_IN_TITLE}" ({CHECK_IN_WHEN}).'
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

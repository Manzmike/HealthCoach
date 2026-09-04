#!/usr/bin/env python3
"""Keyboard-driven chapter, logical-page, and paragraph navigator for HealthCoach."""

from __future__ import annotations

import argparse
import curses
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
DEFAULT_REPORT = HERE / "HEALTHCOACH_REPORT.md"
CHAPTER_RE = re.compile(
    r"^### CHAPTER\s+(?P<chapter>\S+)\s+·\s+PAGE\s+(?P<page>\d+)\s+—\s+(?P<title>.+?)\s*$"
)
HIDDEN_HTML_RE = re.compile(r"^\s*<(?:a\s+id=|/?div\b)", re.I)


@dataclass(frozen=True)
class Chapter:
    chapter_id: str
    page: str
    title: str
    lines: tuple[str, ...]

    @property
    def searchable(self) -> str:
        return "\n".join((
            self.chapter_id,
            f"chapter {self.chapter_id}",
            self.page,
            f"page {self.page}",
            self.title,
            *self.lines,
        )).lower()


def parse_report(path: Path) -> list[Chapter]:
    if not path.exists():
        raise SystemExit(
            f"Report not found: {path}\nGenerate it first with: cd {HERE} && ./hc-supplements"
        )
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    starts: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = CHAPTER_RE.match(line)
        if match:
            starts.append((index, match))
    if not starts:
        raise SystemExit(
            f"No indexed chapters were found in {path}. Regenerate the report with ./hc-supplements."
        )

    chapters: list[Chapter] = []
    first_start = starts[0][0]
    if first_start:
        chapters.append(Chapter("START", "000", "Report index and document controls", tuple(lines[:first_start])))
    for position, (start, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        chapters.append(Chapter(
            match.group("chapter"),
            match.group("page").zfill(3),
            match.group("title").strip(),
            tuple(lines[start + 1:end]),
        ))
    return chapters


def matching_indices(chapters: Sequence[Chapter], query: str) -> list[int]:
    needle = query.strip().lower()
    if not needle:
        return list(range(len(chapters)))
    return [index for index, chapter in enumerate(chapters) if needle in chapter.searchable]


def clean_line(line: str) -> str:
    if HIDDEN_HTML_RE.match(line):
        return ""
    line = line.replace("<br>", "; ")
    line = re.sub(r"^#{1,6}\s+", "", line)
    line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
    return line.rstrip()


def display_lines(chapter: Chapter, width: int) -> list[str]:
    heading = f"CHAPTER {chapter.chapter_id} · PAGE {chapter.page} — {chapter.title}"
    output = [heading, ""]
    wrap_width = max(20, width - 1)
    for raw in chapter.lines:
        line = clean_line(raw)
        if not line:
            output.append("")
            continue
        indent_match = re.match(r"^(\s*(?:[-*+] |\d+[.)] ))", line)
        subsequent = " " * len(indent_match.group(1)) if indent_match else ""
        output.extend(textwrap.wrap(
            line,
            width=wrap_width,
            subsequent_indent=subsequent,
            replace_whitespace=False,
            drop_whitespace=True,
        ) or [""])
    while output and not output[-1]:
        output.pop()
    return output or [heading]


def match_preview(chapter: Chapter, query: str, limit: int = 90) -> str:
    needle = query.strip().lower()
    if not needle:
        return ""
    for raw in (chapter.title, *chapter.lines):
        cleaned = clean_line(raw).strip(" |-_")
        if needle in cleaned.lower():
            return textwrap.shorten(cleaned, width=limit, placeholder="…")
    return ""


def put(stdscr, y: int, x: int, value: str, attr: int = 0) -> None:
    height, width = stdscr.getmaxyx()
    if not (0 <= y < height and 0 <= x < width):
        return
    try:
        stdscr.addnstr(y, x, value, max(0, width - x - 1), attr)
    except curses.error:
        pass


def ask_search(stdscr, label: str = "Search chapters and paragraph text: ") -> str:
    height, width = stdscr.getmaxyx()
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    curses.echo()
    put(stdscr, height - 1, 0, label)
    try:
        stdscr.clrtoeol()
        raw = stdscr.getstr(height - 1, min(len(label), width - 2), max(1, width - len(label) - 2))
        return raw.decode("utf-8", errors="ignore").strip()
    except curses.error:
        return ""
    finally:
        curses.noecho()
        try:
            curses.curs_set(0)
        except curses.error:
            pass


def view_chapter(stdscr, chapter: Chapter, query: str) -> str:
    top = 0
    active_query = query.strip()
    rendered: list[str] = []
    rendered_width = 0

    while True:
        height, width = stdscr.getmaxyx()
        if width != rendered_width:
            rendered = display_lines(chapter, width)
            rendered_width = width
            top = min(top, max(0, len(rendered) - 1))
            if active_query:
                match = next((i for i, line in enumerate(rendered) if active_query.lower() in line.lower()), 0)
                top = max(0, match - 2)
        body_height = max(1, height - 4)
        top = max(0, min(top, max(0, len(rendered) - body_height)))

        stdscr.erase()
        put(stdscr, 0, 0, f"CHAPTER {chapter.chapter_id} · PAGE {chapter.page} — {chapter.title}", curses.A_BOLD)
        put(stdscr, 1, 0, "↑/↓ scroll • Space/PgDn next screen • b index • [/] chapter • / find • n next • q quit", curses.A_DIM)
        for row, line_index in enumerate(range(top, min(len(rendered), top + body_height)), start=3):
            line = rendered[line_index]
            attr = curses.A_BOLD if active_query and active_query.lower() in line.lower() else 0
            put(stdscr, row, 0, line, attr)
        percent = 100 if len(rendered) <= body_height else int(100 * top / max(1, len(rendered) - body_height))
        put(stdscr, height - 1, 0, f"Line {top + 1}/{len(rendered)} · {percent}%" + (f" · find: {active_query}" if active_query else ""), curses.A_REVERSE)
        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord("q"), ord("Q")):
            return "quit"
        if key in (ord("b"), 27, curses.KEY_BACKSPACE, 127):
            return "back"
        if key in (ord("]"),):
            return "next"
        if key in (ord("["),):
            return "previous"
        if key in (curses.KEY_DOWN, ord("j")):
            top += 1
        elif key in (curses.KEY_UP, ord("k")):
            top -= 1
        elif key in (ord(" "), curses.KEY_NPAGE):
            top += max(1, body_height - 1)
        elif key == curses.KEY_PPAGE:
            top -= max(1, body_height - 1)
        elif key == ord("g"):
            top = 0
        elif key == ord("G"):
            top = max(0, len(rendered) - body_height)
        elif key == ord("/"):
            active_query = ask_search(stdscr, "Find inside this page: ")
            if active_query:
                match = next((i for i, line in enumerate(rendered) if active_query.lower() in line.lower()), 0)
                top = max(0, match - 2)
        elif key == ord("n") and active_query:
            match = next(
                (i for i in range(top + 1, len(rendered)) if active_query.lower() in rendered[i].lower()),
                None,
            )
            if match is not None:
                top = max(0, match - 2)


def interactive_navigator(chapters: Sequence[Chapter]) -> None:
    def run(stdscr) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        query = ""
        cursor = 0
        top = 0

        while True:
            matches = matching_indices(chapters, query)
            height, width = stdscr.getmaxyx()
            visible = max(1, height - 6)
            cursor = max(0, min(cursor, max(0, len(matches) - 1)))
            if cursor < top:
                top = cursor
            if cursor >= top + visible:
                top = cursor - visible + 1

            stdscr.erase()
            put(stdscr, 0, 0, "HEALTHCOACH REPORT NAVIGATOR", curses.A_BOLD)
            put(stdscr, 1, 0, "↑/↓ choose • Space/Enter open • / search all text • r reset • q quit", curses.A_DIM)
            status = f"{len(matches)} chapter(s)" + (f" matching: {query}" if query else " · search a topic, PAGE 017, or CHAPTER II.07")
            put(stdscr, 2, 0, status)

            if not matches:
                put(stdscr, 4, 2, "No chapter or paragraph matched. Press r to reset or / to search again.", curses.A_BOLD)
            for row, position in enumerate(range(top, min(len(matches), top + visible)), start=4):
                chapter = chapters[matches[position]]
                pointer = ">" if position == cursor else " "
                label = f"{pointer} PAGE {chapter.page}  CHAPTER {chapter.chapter_id:<6}  {chapter.title}"
                put(stdscr, row, 0, label, curses.A_REVERSE if position == cursor else 0)

            if matches and query:
                preview = match_preview(chapters[matches[cursor]], query, max(30, width - 9))
                put(stdscr, height - 1, 0, "Match: " + (preview or "title/page match"), curses.A_BOLD)
            else:
                put(stdscr, height - 1, 0, "Space opens the highlighted logical page; b returns here from a page.", curses.A_BOLD)
            stdscr.refresh()
            key = stdscr.getch()

            if key in (ord("q"), ord("Q"), 27):
                return
            if key in (curses.KEY_UP, ord("k")) and matches:
                cursor = (cursor - 1) % len(matches)
            elif key in (curses.KEY_DOWN, ord("j")) and matches:
                cursor = (cursor + 1) % len(matches)
            elif key == curses.KEY_PPAGE and matches:
                cursor = max(0, cursor - visible)
            elif key == curses.KEY_NPAGE and matches:
                cursor = min(len(matches) - 1, cursor + visible)
            elif key == ord("/"):
                query = ask_search(stdscr)
                cursor = top = 0
            elif key == ord("r"):
                query = ""
                cursor = top = 0
            elif key in (ord(" "), 10, 13, curses.KEY_ENTER) and matches:
                chapter_index = matches[cursor]
                while True:
                    action = view_chapter(stdscr, chapters[chapter_index], query)
                    if action == "quit":
                        return
                    if action == "next":
                        chapter_index = min(len(chapters) - 1, chapter_index + 1)
                        query = ""
                        continue
                    if action == "previous":
                        chapter_index = max(0, chapter_index - 1)
                        query = ""
                        continue
                    break
                matches = matching_indices(chapters, query)
                if chapter_index in matches:
                    cursor = matches.index(chapter_index)

    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass


def print_matches(chapters: Sequence[Chapter], query: str = "") -> int:
    matches = matching_indices(chapters, query)
    if not matches:
        print(f"No chapter or paragraph matched: {query}")
        return 1
    for index in matches:
        chapter = chapters[index]
        preview = match_preview(chapter, query)
        print(f"PAGE {chapter.page}  CHAPTER {chapter.chapter_id:<6}  {chapter.title}")
        if preview:
            print(f"  {preview}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browse HealthCoach by chapter, logical page, or paragraph text")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="report Markdown file")
    parser.add_argument("--list", action="store_true", help="print the chapter/page index without opening the navigator")
    parser.add_argument("--search", help="print chapters containing this phrase")
    parser.add_argument("--page", help="print one logical page, such as 017")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    chapters = parse_report(args.report.expanduser().resolve())
    if args.page:
        page = args.page.strip().lower().removeprefix("page").strip().zfill(3)
        match = next((chapter for chapter in chapters if chapter.page == page), None)
        if not match:
            print(f"Logical page not found: {args.page}", file=sys.stderr)
            return 1
        print("\n".join(display_lines(match, 100)))
        return 0
    if args.search is not None:
        return print_matches(chapters, args.search)
    if args.list or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return print_matches(chapters)
    interactive_navigator(chapters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
SCHEDULE BUILDER — conversational schedule construction + .ics export.

Trigger it from coach.py in plain language ("I'd like to make updates to my
schedule"), or run this module directly:

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  python3 schedule_builder.py

Builds up a recurring weekly schedule one block at a time — work hours,
breaks, driving time, gym sessions, free time, obligations like church or
studying, walks, morning sunrise light exposure, evening walks, meals,
sleep, or anything else — stored in schedule_calendar.json, and exportable
at any point to a standard .ics file that Apple Calendar, Google Calendar,
and Outlook can all import directly (one format covers all three; there is
no separate "Google-flavored" export). Floating local time is used
deliberately (no timezone baked into the file): a personal daily routine
should land on the same wall-clock time regardless of which timezone the
importing device is currently set to.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re

HERE = os.path.dirname(__file__)
DEFAULT_PATH = os.path.join(HERE, "schedule_calendar.json")
DEFAULT_ICS_PATH = os.path.join(HERE, "schedule_export.ics")

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_DAY_ALIASES = {
    "monday": "Mon", "mon": "Mon", "m": "Mon",
    "tuesday": "Tue", "tue": "Tue", "tues": "Tue", "t": "Tue",
    "wednesday": "Wed", "wed": "Wed", "w": "Wed",
    "thursday": "Thu", "thu": "Thu", "thurs": "Thu", "th": "Thu",
    "friday": "Fri", "fri": "Fri", "f": "Fri",
    "saturday": "Sat", "sat": "Sat",
    "sunday": "Sun", "sun": "Sun",
}
CATEGORIES = ["work", "gym", "drive", "break", "free", "church", "study",
              "walk", "morning_light", "meal", "sleep", "other"]

# --------------------------------------------------------------------------
# Detecting a construction/update REQUEST (distinct from coach.py's
# looks_like_schedule_question(), which is for a research QUESTION about
# scheduling -- "what should my routine look like" retrieves evidence;
# "update my schedule" launches this builder instead, no retrieval at all).

_UPDATE_REQUEST_PHRASES = (
    "update my schedule", "update the schedule", "change my schedule",
    "edit my schedule", "build my schedule", "build a schedule",
    "create my schedule", "make my schedule", "set up my schedule",
    "make updates to my schedule", "revise my schedule", "adjust my schedule",
    "modify my schedule", "plan my schedule", "construct my schedule",
)


def looks_like_schedule_update_request(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _UPDATE_REQUEST_PHRASES)


# --------------------------------------------------------------------------
# Parsing free-text days and times.

def parse_days(text: str) -> list[str]:
    """"mon/wed/fri", "weekdays", "every day", "tuesday and thursday" ->
    ["Mon", "Wed", ...] in DAYS order, deduplicated. Unrecognized tokens are
    silently dropped; an all-unrecognized input returns []."""
    lower = text.lower().strip()
    if lower in ("every day", "everyday", "daily", "all days", "all"):
        return list(DAYS)
    if lower in ("weekdays", "workdays", "work days"):
        return DAYS[:5]
    if lower in ("weekends", "weekend"):
        return DAYS[5:]
    found: list[str] = []
    for token in re.split(r"[,/&]|\band\b|\s+", lower):
        token = token.strip(". ")
        if not token:
            continue
        day = _DAY_ALIASES.get(token)
        if day and day not in found:
            found.append(day)
    return sorted(found, key=DAYS.index)


_TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?\s*$", re.IGNORECASE)


def parse_time(text: str) -> str:
    """"7am", "7:30 AM", "19:00", "7" -> "HH:MM" 24h. Raises ValueError if
    unparseable or out of range -- callers decide whether to skip or retry,
    this never guesses."""
    m = _TIME_RE.match(text)
    if not m:
        raise ValueError(f"Could not parse a time from {text!r} (try '7am', '19:00', '7:30pm')")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = (m.group(3) or "").lower().replace(".", "")
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Time out of range: {text!r}")
    return f"{hour:02d}:{minute:02d}"


# --------------------------------------------------------------------------
# Schedule data model. One weekly template, not dated instances -- a block
# says "Mon/Wed/Fri 17:00-18:15", not "on 2026-09-21". to_ics() below is
# what turns that into concrete recurring calendar events.

def empty_schedule() -> dict:
    return {"blocks": []}


def add_block(schedule: dict, *, category: str, label: str, start: str, end: str,
              days: list[str]) -> dict:
    """start/end are 'HH:MM' 24h (use parse_time() first for free text).
    Raises ValueError for an unknown category, no days, or an end time that
    isn't after start -- this model has no overnight-spanning block; split
    one into two (e.g. 22:00-23:59 and 00:00-06:00) if you need that."""
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category {category!r}; choose one of {CATEGORIES}")
    if not days:
        raise ValueError("A block needs at least one day")
    if end <= start:
        raise ValueError(f"End time {end} must be after start time {start}")
    block = {"category": category, "label": label.strip() or category.replace("_", " ").title(),
             "start": start, "end": end, "days": list(days)}
    schedule["blocks"].append(block)
    return block


def load(path: str = DEFAULT_PATH) -> dict:
    if not os.path.exists(path):
        return empty_schedule()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(schedule: dict, path: str = DEFAULT_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schedule, f, indent=2)
        f.write("\n")


def summary_lines(schedule: dict) -> list[str]:
    if not schedule["blocks"]:
        return ["(no blocks yet)"]
    lines = []
    for day in DAYS:
        day_blocks = sorted((b for b in schedule["blocks"] if day in b["days"]),
                             key=lambda b: b["start"])
        if not day_blocks:
            continue
        lines.append(f"{day}:")
        for b in day_blocks:
            lines.append(f"  {b['start']}-{b['end']}  {b['label']} ({b['category']})")
    return lines


# --------------------------------------------------------------------------
# .ics export (RFC 5545, hand-rolled -- no external dependency, matching
# this project's stdlib-only convention elsewhere, e.g. fetch_papers.py).

_ICS_DOW = {"Mon": "MO", "Tue": "TU", "Wed": "WE", "Thu": "TH", "Fri": "FR", "Sat": "SA", "Sun": "SU"}
_PY_WEEKDAY = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def _next_occurrence(day: str, today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    delta = (_PY_WEEKDAY[day] - today.weekday()) % 7
    return today + dt.timedelta(days=delta)


def _fold(line: str) -> str:
    """RFC 5545 line folding: no line may exceed 75 octets; a continuation
    line starts with a single space."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    out, rest = line[:75], line[75:]
    while rest:
        out += "\r\n " + rest[:74]
        rest = rest[74:]
    return out


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def to_ics(schedule: dict, *, calendar_name: str = "HealthCoach Schedule",
           now: dt.datetime | None = None, today: dt.date | None = None) -> str:
    """One recurring weekly VEVENT per (block, day it applies to). now/today
    are injectable for deterministic tests; production calls use real
    current time."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HealthCoach//Schedule Export//EN",
              "CALSCALE:GREGORIAN", _fold(f"X-WR-CALNAME:{_escape(calendar_name)}")]
    for i, block in enumerate(schedule["blocks"]):
        for day in block["days"]:
            first = _next_occurrence(day, today)
            start_h, start_m = block["start"].split(":")
            end_h, end_m = block["end"].split(":")
            dtstart = f"{first:%Y%m%d}T{start_h}{start_m}00"
            dtend = f"{first:%Y%m%d}T{end_h}{end_m}00"
            uid = hashlib.sha256(
                f"{i}-{day}-{block['start']}-{block['label']}".encode()).hexdigest()[:16]
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}@healthcoach.local",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{dtstart}",
                f"DTEND:{dtend}",
                f"RRULE:FREQ=WEEKLY;BYDAY={_ICS_DOW[day]}",
                _fold(f"SUMMARY:{_escape(block['label'])}"),
                _fold(f"CATEGORIES:{_escape(block['category'])}"),
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def export_ics(schedule: dict, path: str = DEFAULT_ICS_PATH) -> str:
    if not schedule["blocks"]:
        raise ValueError("Nothing to export -- the schedule has no blocks yet")
    text = to_ics(schedule)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


# --------------------------------------------------------------------------
# Interactive Q&A loop. input_fn/print_fn are injectable so this is fully
# testable without patching builtins.

def _add_block_interactive(schedule: dict, input_fn, print_fn) -> None:
    category = input_fn(f"Category? ({'/'.join(CATEGORIES)}): ").strip().lower().replace(" ", "_")
    if category not in CATEGORIES:
        print_fn(f"Unknown category {category!r}; skipping this block.")
        return
    label = input_fn("Label for this block (e.g. 'Lift A', 'Drive to work'): ").strip()
    days = parse_days(input_fn("Which days? (e.g. 'mon,wed,fri', 'weekdays', 'every day'): "))
    if not days:
        print_fn("Could not parse any days; skipping this block.")
        return
    try:
        start = parse_time(input_fn("Start time (e.g. '7am', '19:00'): "))
        end = parse_time(input_fn("End time: "))
        block = add_block(schedule, category=category, label=label, start=start, end=end, days=days)
        print_fn(f"Added: {','.join(block['days'])} {block['start']}-{block['end']} {block['label']}")
    except ValueError as e:
        print_fn(f"Skipped: {e}")


def _remove_block_interactive(schedule: dict, input_fn, print_fn) -> None:
    if not schedule["blocks"]:
        print_fn("Nothing to remove.")
        return
    for i, b in enumerate(schedule["blocks"]):
        print_fn(f"  [{i}] {','.join(b['days'])} {b['start']}-{b['end']} {b['label']}")
    choice = input_fn("Remove which number? ").strip()
    if choice.isdigit() and 0 <= int(choice) < len(schedule["blocks"]):
        removed = schedule["blocks"].pop(int(choice))
        print_fn(f"Removed: {removed['label']}")
    else:
        print_fn("Not understood; nothing removed.")


def run_builder(schedule: dict | None = None, *, input_fn=input, print_fn=print) -> dict:
    """Add/remove blocks until the user says they're done ('done', or blank
    input), then return the finished schedule. Saving and exporting are the
    caller's job -- this stays pure and testable."""
    schedule = schedule if schedule is not None else load()
    print_fn("Let's build your schedule. Add each part of your day one at a time -- "
              "work, gym, breaks, driving, free time, church, studying, walks, "
              "morning light, evening walk, meals, sleep, or anything else.")
    while True:
        print_fn("\nCurrent schedule:")
        for line in summary_lines(schedule):
            print_fn("  " + line)
        action = input_fn("\nAdd a block, remove one, or done? [add/remove/done]: ").strip().lower()
        if action in ("done", "d", ""):
            break
        if action in ("remove", "r"):
            _remove_block_interactive(schedule, input_fn, print_fn)
        elif action in ("add", "a"):
            _add_block_interactive(schedule, input_fn, print_fn)
        else:
            print_fn(f"Not understood: {action!r}")
    return schedule


def main() -> int:
    import sys
    schedule = load()
    schedule = run_builder(schedule)
    save(schedule)
    print(f"\nSaved to {DEFAULT_PATH}")
    if not schedule["blocks"]:
        print("Nothing to export yet.")
        return 0
    choice = input("Export to .ics now? [Y/n]: ").strip().lower()
    if choice in ("", "y", "yes"):
        path = export_ics(schedule)
        print(f"Exported to {path}")
        print("Import it: Apple Calendar (File > Import...), Google Calendar "
              "(Settings > Import & export), or Outlook (File > Open & Export > Import/Export).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

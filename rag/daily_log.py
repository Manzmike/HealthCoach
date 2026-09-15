#!/usr/bin/env python3
"""Explicit local daily facts. Independent of the report and Bevel weekly packages."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence


DEFAULT_LOG = Path(__file__).resolve().parent / ".healthcoach" / "daily_log.json"
STATUSES = ("unknown", "completed", "skipped")
RECOVERY = ("unknown", "good", "okay", "poor")


def empty_entry() -> dict[str, Any]:
    return {"status": "unknown", "duration_min": None, "recovery": "unknown", "note": "", "steps": None}


def validate_entry(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise ValueError("Each daily entry must be an object.")
    if entry.get("status") not in STATUSES or entry.get("recovery") not in RECOVERY:
        raise ValueError("Choose a listed activity status and recovery value.")
    duration = entry.get("duration_min")
    if duration is not None and (
        isinstance(duration, bool) or not isinstance(duration, (int, float))
        or not math.isfinite(duration) or not 0 <= duration <= 1440
    ):
        raise ValueError("Duration must be 0-1440 minutes or unknown.")
    if not isinstance(entry.get("note"), str) or len(entry["note"]) > 2000:
        raise ValueError("Note must be text, at most 2000 characters.")
    steps = entry.get("steps")
    if steps is not None and (isinstance(steps, bool) or not isinstance(steps, int) or not 0 <= steps <= 100000):
        raise ValueError("Completed steps must be an integer from 0 to 100,000, or unknown.")


def load_log(path: Path = DEFAULT_LOG) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": 1, "days": {}}
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("days"), dict):
        raise ValueError("Unsupported or malformed daily log; the existing file will not be replaced.")
    for date, entry in data["days"].items():
        if dt.date.fromisoformat(date).isoformat() != date:
            raise ValueError("Daily log dates must use YYYY-MM-DD.")
        validate_entry(entry)
    return data


def note_message(note: str) -> str | None:
    try:
        policy = importlib.import_module("safety_policy")
        return policy.urgent_message(note)
    except Exception:
        return "Urgent-symptom screening is unavailable. This log does not assess medical urgency."


def save_entry(day: dt.date, entry: dict[str, Any], path: Path = DEFAULT_LOG) -> str | None:
    """Check the note, retain the reported fact, then atomically replace only this day's entry."""
    validate_entry(entry)
    data = load_log(path)  # Refuse to overwrite unreadable or incompatible state.
    message = note_message(entry["note"])
    data["days"][day.isoformat()] = {
        **entry,
        "origin": "MANUALLY_LOGGED",
        "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".daily-log-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return message


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Log daily facts without changing the plan or weekly packages")
    parser.add_argument("--date", type=dt.date.fromisoformat, default=dt.datetime.now().astimezone().date())
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args(argv)
    try:
        entry = {**empty_entry(), **load_log(args.log)["days"].get(args.date.isoformat(), {})}
        print(f"HEALTHCOACH / DAILY LOG / {args.date}")
        print("Main activity only, not individual supplement doses or whole-plan completion.")
        print("Blank keeps the saved value; ? records unknown (or clears the note). Nothing saves until you type s.")
        for field, label in (
            ("status", "Activity: unknown / completed / skipped"),
            ("duration_min", "Activity minutes"),
            ("recovery", "Recovery: unknown / good / okay / poor"),
            ("note", "Factual note, optional"),
            ("steps", "Steps completed (optional)"),
        ):
            while True:
                current = entry[field]
                shown = "".join(c if c.isprintable() else " " for c in str(current)) if current is not None else "unknown"
                raw = input(f"{label} [{shown}]: ").strip()
                if not raw:
                    break
                value: Any = empty_entry()[field] if raw == "?" else raw
                try:
                    if field == "duration_min" and raw != "?":
                        value = float(raw)
                    elif field == "steps" and raw != "?":
                        value = int(raw)
                    elif field in {"status", "recovery"}:
                        value = value.lower()
                    draft = {**entry, field: value}
                    validate_entry(draft)
                except ValueError as exc:
                    print(str(exc))
                    continue
                entry = draft
                break
        preview_message = note_message(entry["note"])
        if preview_message:
            print(f"\n{preview_message}\n")
        if input("s save this day / anything else cancel: ").strip().lower() != "s":
            print("Cancelled; no facts changed.")
            return 0
        message = save_entry(args.date, entry, args.log)
        if message and message != preview_message:
            print(f"\n{message}\n")
        print(f"Saved daily facts for {args.date}. No plan changes or weekly-package edits were made.")
        print("Next reassessment: dashboard -> Log/Review -> LOG THE COMPLETED WEEK.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; no save requested.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Daily log not saved: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

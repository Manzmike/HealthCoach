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

# A typed category has to match one of these exactly-or-by-alias, or
# _resolve_category() returns None -- never silently guessed. Covers the
# obvious synonyms someone would actually type ("workout", "commute",
# "light") rather than the internal category name.
_CATEGORY_ALIASES = {
    "work": {"job", "working"},
    "gym": {"workout", "training", "train", "lift", "lifting", "exercise", "fitness", "run", "running"},
    "drive": {"commute", "commuting", "driving"},
    "break": {"rest", "pause"},
    "free": {"freetime", "downtime", "off", "relax", "relaxation"},
    "church": {"service", "worship"},
    "study": {"studying", "school", "homework", "class", "anki", "learning"},
    "walk": {"walking"},
    "morning_light": {"sunrise", "sunlight", "light", "outdoorlight", "morninglight"},
    "meal": {"food", "eating", "breakfast", "lunch", "dinner"},
    "sleep": {"bed", "bedtime"},
}


def _resolve_category(text: str) -> str | None:
    """Exact category name, or a known alias, normalized (lowercased,
    spaces/hyphens collapsed to match how CATEGORIES itself is spelled).
    Returns None -- never a guess -- for anything else."""
    key = text.strip().lower().replace(" ", "_").replace("-", "_")
    if key in CATEGORIES:
        return key
    collapsed = key.replace("_", "")
    for category, aliases in _CATEGORY_ALIASES.items():
        if collapsed in aliases:
            return category
    return None


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
# Research-backed placement guidance. Reuses coach.py's real search/critique
# pipeline (and its offer to fetch new sources when nothing's found) rather
# than inventing separate logic -- any scheduling suggestion still goes
# through the same safety critic as a normal coach.py answer (no dosing
# claims, no vaccine-causation claims, etc.), which matters here since
# scheduling questions can stray into supplement/meal-timing territory.

# Categories where research-backed timing guidance is usually worth having;
# offered for every category regardless (the user decides per block), but
# these are named in the prompt so it's clear where it tends to matter.
_RESEARCH_RELEVANT_CATEGORIES = {"gym", "meal", "sleep", "morning_light", "walk", "study", "break"}


class _LazyRag:
    """Loads the RAG stack (embedding model, reranker, LanceDB table, then
    the generation model) at most once per builder session, and only if the
    user actually asks for research-backed guidance on at least one block --
    most of a schedule-building session (adding a church block, a drive
    block) needs none of this."""

    def __init__(self):
        self.coach = None
        self.tbl = None
        self.emb = None
        self.rr = None
        self.model_tok = None

    def ensure_loaded(self, print_fn) -> None:
        if self.coach is not None:
            return
        print_fn("Loading the research pipeline (first time only this session)...")
        import coach as C
        import lancedb
        from sentence_transformers import SentenceTransformer
        self.coach = C
        self.emb = SentenceTransformer(C.EMB_MODEL, device="mps")
        self.tbl = lancedb.connect(C.DBDIR).open_table(C.TABLE)
        self.rr = C.load_reranker()

    def reopen_table(self) -> None:
        """After offer_to_fetch_sources() adds new PDFs and ingests them,
        the already-open table handle is stale -- reopen it to see them."""
        import lancedb
        self.tbl = lancedb.connect(self.coach.DBDIR).open_table(self.coach.TABLE)

    def ensure_model(self, print_fn):
        if self.model_tok is None:
            print_fn("Loading the generation model...")
            from mlx_lm import load
            self.model_tok = load(self.coach.GEN_MODEL)
        return self.model_tok


def _placement_query(schedule: dict, category: str, label: str) -> str:
    """A research question for this block, informed by the schedule so far
    (already-entered work hours or a sleep window) and by the intake
    profile (job, current sleep pattern, caffeine, stress, existing
    exercise habits, etc.) -- not asked in a vacuum."""
    context_bits = [f"{b['category']} is {b['start']}-{b['end']} on {','.join(b['days'])}"
                     for b in schedule["blocks"] if b["category"] in ("work", "sleep")]
    profile = schedule.get("profile", {})
    for key, _prompt, _known_key in _INTAKE_QUESTIONS:  # defined below; same key set, no drift between the two
        if profile.get(key):
            context_bits.append(f"{key.replace('_', ' ')}: {profile[key]}")
    context = " Given: " + "; ".join(context_bits) + "." if context_bits else ""
    return (f"What does the evidence say about the best time and way to schedule "
            f"{label or category} ({category}) for overall health?{context}")


# --------------------------------------------------------------------------
# Intake: job/role, work hours, current sleep pattern, and a handful of
# easy-to-overlook health/daily-life questions, asked once before block-by-
# block schedule construction starts. Prefills from person_state.json (the
# RAG safety layer's own authoritative user-state file) where available, so
# nothing already on file gets re-asked from scratch.

_INTAKE_QUESTIONS = [
    # (profile key, prompt, person_state.json key to prefill from)
    ("job_role", "What's your job/role? (e.g. 'software engineer, desk job')", None),
    ("work_hours", "What are your typical work hours? (e.g. '6am-4pm', or 'varies')", None),
    ("sleep_pattern", "What does your current sleep pattern actually look like? "
                       "(bed/wake time, or describe it if it's irregular)", "sleep_window"),
    ("caffeine", "When's your last caffeine of the day, if any?", "caffeine_last"),
    ("screens_before_bed", "Do you use screens (phone/laptop/TV) in the hour before bed?", None),
    ("stress_level", "How would you describe your stress level most days? (low/moderate/high)", None),
    ("exercise_habits", "What does your current exercise routine actually look like, if any?",
     "training_status"),
    ("commute", "How do you get to work, and how long does it take?", "commute_min"),
    ("alcohol", "Do you drink alcohol? If so, how often and around what time?", "alcohol_pattern"),
    ("other_obligations", "Any recurring obligations I should know about -- family, caregiving, "
                           "church, other commitments?", None),
    ("energy_pattern", "How does your energy/focus actually feel through the day -- fairly steady, "
                        "or a noticeable dip (e.g. early afternoon)?", None),
]


def load_person_context(path: str | None = None) -> dict:
    """A best-effort summary of what's already on file in person_state.json
    (identity/work, sleep windows, caffeine, alcohol, training status), so
    intake can prefill from it instead of re-asking from scratch. A missing
    file, or anything unexpected in it, just means an empty dict -- intake
    still runs fine, it just has nothing to prefill."""
    path = path or os.path.join(HERE, "rag_control", "person_state.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    known: dict = {}
    identity = state.get("identity") or {}
    if identity.get("work"):
        known["work_type"] = str(identity["work"]).replace("_", " ")
    if identity.get("commute_min") is not None:
        known["commute_min"] = f"{identity['commute_min']} min"
    sleep = state.get("sleep") or {}
    if sleep.get("windows"):
        known["sleep_window"] = sleep["windows"][0]
    drugs = state.get("drugs") or {}
    if drugs.get("caffeine_last"):
        known["caffeine_last"] = drugs["caffeine_last"]
    if (drugs.get("alcohol") or {}).get("pattern"):
        known["alcohol_pattern"] = drugs["alcohol"]["pattern"]
    body = state.get("body") or {}
    if body.get("training"):
        known["training_status"] = str(body["training"]).replace("_", " ")
    return known


def run_intake(schedule: dict, known: dict | None = None, *, input_fn=input, print_fn=print) -> dict:
    """Ask the short intake question set once, storing answers in
    schedule['profile']. Each question shows a prefilled default (an
    existing answer from a prior intake, else the matching person_state.json
    value if any) that pressing Enter accepts as-is; typing anything
    replaces it. A question with neither a default nor a typed answer is
    left blank -- this never invents an answer."""
    known = known if known is not None else load_person_context()
    profile = dict(schedule.get("profile") or {})
    if known:
        print_fn("Here's what's already on file for you:")
        for key, value in known.items():
            print_fn(f"  {key.replace('_', ' ')}: {value}")
        print_fn("")
    print_fn("A few questions about your day-to-day, so scheduling guidance is actually informed "
              "by your real situation -- press Enter to keep a shown default, or to skip.")
    for key, prompt, known_key in _INTAKE_QUESTIONS:
        default = profile.get(key) or (known.get(known_key) if known_key else None)
        suffix = f" [{default}]" if default else ""
        answer = input_fn(f"{prompt}{suffix}: ").strip()
        if answer:
            profile[key] = answer
        elif default:
            profile[key] = str(default)
    schedule["profile"] = profile
    return profile


def _offer_research_guidance(schedule: dict, category: str, label: str, rag: "_LazyRag",
                              input_fn, print_fn) -> None:
    hint = " (often worth checking)" if category in _RESEARCH_RELEVANT_CATEGORIES else ""
    check = input_fn(f"Want research-backed guidance on the best timing for this{hint}? [y/N]: ").strip().lower()
    if check not in ("y", "yes"):
        return
    query = _placement_query(schedule, category, label)
    print_fn(f"\nChecking the evidence: {query}\n")
    rag.ensure_loaded(print_fn)
    C = rag.coach
    matched_intents = C.RC.classify(query)
    hits, weak = C.search(rag.tbl, rag.emb, query, 6, rag.rr, matched_intents=matched_intents)
    if not hits:
        print_fn("No sources found for this specific scenario.")
        if C.offer_to_fetch_sources(query):
            rag.reopen_table()
            hits, weak = C.search(rag.tbl, rag.emb, query, 6, rag.rr, matched_intents=matched_intents)
        if not hits:
            print_fn("Still no evidence for this -- place it by your own judgment.")
            return
    model, tok = rag.ensure_model(print_fn)
    answer = C.answer_from_hits(model, tok, query, hits, matched_intents=matched_intents,
                                 action_count=1, primary_count=1)
    print_fn(C._for_terminal(answer))


# --------------------------------------------------------------------------
# Interactive Q&A loop. input_fn/print_fn are injectable so this is fully
# testable without patching builtins.

_CANCEL_WORDS = {"cancel", "skip", "back", "nevermind", "never mind"}
_CANCELLED = object()


def _prompt_until_valid(prompt: str, parse, input_fn, print_fn):
    """Reprompt with `prompt` until `parse(raw)` returns a truthy value,
    instead of silently dropping the whole block on the first bad input --
    that's what made a mistyped category look like the prompt was simply
    ignoring input. `parse` raises ValueError (with a message to show) to
    reject and retry. Returns _CANCELLED if the user types 'cancel' (or
    'skip'/'back'/'nevermind') at this prompt."""
    while True:
        raw = input_fn(prompt).strip()
        if raw.lower() in _CANCEL_WORDS:
            return _CANCELLED
        try:
            value = parse(raw)
        except ValueError as e:
            print_fn(f"{e} Try again, or type 'cancel'.")
            continue
        if value:
            return value
        print_fn("Try again, or type 'cancel'.")


def _add_block_interactive(schedule: dict, input_fn, print_fn, rag: "_LazyRag | None" = None) -> None:
    def parse_category(raw):
        resolved = _resolve_category(raw)
        if resolved is None:
            raise ValueError(f"Not a category I recognize: {raw!r}.\n"
                              f"  Try one of: {', '.join(CATEGORIES)} (synonyms like 'workout' or 'commute' work too).")
        return resolved

    category = _prompt_until_valid(f"Category? ({'/'.join(CATEGORIES)}) [or 'cancel']: ",
                                    parse_category, input_fn, print_fn)
    if category is _CANCELLED:
        print_fn("Cancelled -- no block added.")
        return

    label = input_fn("Label for this block (e.g. 'Lift A', 'Drive to work'): ").strip()

    def parse_day_list(raw):
        found = parse_days(raw)
        if not found:
            raise ValueError(f"Could not parse any days from {raw!r}.\n"
                              "  Try 'mon,wed,fri', 'weekdays', 'weekends', or 'every day'.")
        return found

    days = _prompt_until_valid(
        "Which days? (e.g. 'mon,wed,fri', 'weekdays', 'every day') [or 'cancel']: ",
        parse_day_list, input_fn, print_fn)
    if days is _CANCELLED:
        print_fn("Cancelled -- no block added.")
        return

    if rag is not None:
        _offer_research_guidance(schedule, category, label, rag, input_fn, print_fn)

    start = _prompt_until_valid("Start time (e.g. '7am', '19:00') [or 'cancel']: ",
                                 parse_time, input_fn, print_fn)
    if start is _CANCELLED:
        print_fn("Cancelled -- no block added.")
        return

    def parse_end(raw):
        end = parse_time(raw)
        if end <= start:
            raise ValueError(f"End time {end} must be after start time {start}.")
        return end

    end = _prompt_until_valid("End time [or 'cancel']: ", parse_end, input_fn, print_fn)
    if end is _CANCELLED:
        print_fn("Cancelled -- no block added.")
        return

    block = add_block(schedule, category=category, label=label, start=start, end=end, days=days)
    print_fn(f"Added: {','.join(block['days'])} {block['start']}-{block['end']} {block['label']}")


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


def run_builder(schedule: dict | None = None, *, input_fn=input, print_fn=print,
                 offer_research: bool = True, offer_intake: bool = True) -> dict:
    """Add/remove blocks until the user says they're done ('done', or blank
    input), then return the finished schedule. Saving and exporting are the
    caller's job -- this stays pure and testable.

    offer_intake=True (the default) runs the short intake question set
    (job/role, work hours, current sleep pattern, and a handful of easy-to-
    overlook health/daily-life questions) once before block-by-block
    schedule construction starts, on a schedule with no profile yet --
    every block-placement research query then carries that context, not
    just the blocks already entered this session. A schedule that already
    has a profile (from a prior session) is asked whether to update it
    rather than being silently skipped or silently re-asked.

    offer_research=True offers research-backed placement guidance for each
    block, reusing coach.py's real search/critique pipeline and its offer
    to fetch new sources -- lazily, so a session that never accepts one
    never pays to load any model at all. Tests pass offer_research=False
    and offer_intake=False to stay fully offline."""
    schedule = schedule if schedule is not None else load()
    rag = _LazyRag() if offer_research else None
    if offer_intake:
        if schedule.get("profile"):
            if input_fn("\nUpdate your job/sleep/lifestyle info before continuing? [y/N]: "
                         ).strip().lower() in ("y", "yes"):
                run_intake(schedule, input_fn=input_fn, print_fn=print_fn)
        else:
            run_intake(schedule, input_fn=input_fn, print_fn=print_fn)
    print_fn("\nLet's build your schedule. Add each part of your day one at a time -- "
              "work, gym, breaks, driving, free time, church, studying, walks, "
              "morning light, evening walk, meals, sleep, or anything else. "
              "I can check the research for the best way to place anything health-related "
              "as you go, and search for new sources if nothing's found yet.")
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
            _add_block_interactive(schedule, input_fn, print_fn, rag)
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

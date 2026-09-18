# HealthCoach local web GUI — design

## Motivation
HealthCoach today is CLI-only: `coach.py` for questions, a curses picker for
symptom check-in, a curses schedule builder, and `./hc` (`healthcoach_dashboard.py`)
as a keyboard-first front door to ~24 actions. Curses works but is unforgiving
for freeform text, checkbox-style selection, and anything visual like a weekly
calendar grid. This adds a local, browser-based GUI for the four flows a real
GUI helps most, without touching or replacing the terminal tools.

## Scope (v1)
In scope: `/ask`, `/symptoms`, `/schedule`, `/labs`, plus a `/` home page and a
`/more` reference page.

Out of scope: peptide/nootropic/food catalog browsing, weekly check-in, Bevel
sharing, source refreshes, week planning — everything else currently reachable
through `./hc`. `./hc` is unchanged and keeps working exactly as it does today;
`/more` just lists the terminal command for each of those actions so the web
app remains a complete front door without reimplementing two dozen curses
screens.

## Architecture
A new `rag/webapp/` package:
- `app.py` — Flask app + routes.
- `templates/*.html` — Jinja2, server-rendered. No JS framework, no build step;
  a little vanilla JS for the symptom type-to-filter box.
- `static/style.css` — plain CSS.

A new launcher script `rag/hc-web`, matching the existing `hc`/`hc-report`
pattern: activates `.venv`, then runs the Flask app and opens the default
browser to it.

**Hard constraint: binds to `127.0.0.1` only, never `0.0.0.0`.** This serves
private health data (symptoms, lab values, schedule). No auth is added because
it never leaves loopback; if that constraint ever changes, auth stops being
optional.

Flask is a new dependency (`requirements.txt`); nothing else changes.

## Data flow
The web app is a new *caller* of existing modules — it does not introduce new
storage or a new schema. It reads and writes the exact same files the CLI
tools already use:
- `schedule_calendar.json` via `schedule_builder.load`/`save`/`export_ics`
- `.healthcoach/labs.json` via `labs.load_labs`/`save_labs`/`import_pdf`
- `rag_control/person_state.json` (read-only, via `schedule_builder.load_person_context`)
- the LanceDB `chunks` table (read-only, via `coach.py`'s search pipeline)

A schedule block added in the browser is immediately visible to
`schedule_builder.py`'s CLI, and vice versa — no sync step, because there is
only one file.

## Pages

### `/` — home
Today's saved-schedule presence, whether a report/profile exists (reuse
`today.py`'s `load_today`), and links to the four flows plus `/more`.

### `/ask` (GET form, POST results)
Reuses `coach.py`'s existing pure pipeline unchanged: `split_questions`,
`_topic_for_segment`/`topic_header`, `build_where_clause`, `search`,
`answer_from_hits`, `schedule_breakdown_for`. A small new
`webapp/render.py` helper converts the existing `**bold**`/plain-text answer
into real HTML (`<strong>`, paragraph breaks) — this replaces `_for_terminal`'s
ANSI path for the web case only; `coach.py` itself is untouched.

Multi-part questions render as separate sections with a divider between them,
matching the terminal's `----------` behavior. When a section has no
evidence, a "Search for new sources now" button POSTs to a small wrapper
around the same fetch used by `offer_to_fetch_sources` (blocking call with a
loading state — single local user, no background job queue needed).

### `/symptoms` (GET form, POST report)
The checkbox list is built from `symptom_checkin.grouped_rows(filter_labels(query))`
— same grouping and filtering logic the curses picker uses, now as real
checkboxes with a type-to-filter text box (small vanilla-JS handler, no
round-trip per keystroke needed since the full label list is already on the
page). POST calls `build_report()` + `cluster_alerts()` unchanged and renders
the short report first, with a "show full detail" expand.

### `/schedule` (GET grid + add/remove forms, POST add/remove/export)
A 7-day × hour grid rendered from `schedule_builder.load()`. The add-block
form reuses `_resolve_category`, `parse_days`, `parse_time`, `add_block`
directly; a `ValueError` from any of them re-renders the form with the
message inline instead of the CLI's reprompt loop. Adding a block in a
category from `_RESEARCH_RELEVANT_CATEGORIES` shows a "See what the evidence
says" link (not automatic) that runs `_placement_query` + `_LazyRag`'s search
on demand. "Export .ics" downloads the file straight from `export_ics()`
(`send_file`, no separate download page).

### `/labs` (GET table + forms, POST add/import)
Table of current values from `labs.load_labs()` with `marker_status()`
per row. A manual add-value form and a PDF upload both reuse the logic
inside `labs.add_lab`/`labs.import_pdf` (those currently take an
`argparse.Namespace`; each gets a small extracted core function taking plain
arguments, called by both the CLI's `main()` and the new route — no behavior
change, just removing the argparse coupling). The page states plainly that a
live Function Health/HealthEx connector still requires running `/mcp` inside
Claude Code itself; the web page cannot broker that.

### `/more`
Static list built from `healthcoach_dashboard.ACTIONS` minus the four covered
keys, showing each action's title, detail, and exact terminal command.

## Testing
Flask's test client — no real browser, no server process — for route-level
tests: right template, right status code, form-validation errors surfaced,
correct pure function called with correct arguments (mocked where a test
already exists for that pure function elsewhere, to avoid duplicating
coverage). The business logic under every route is already the well-tested
pure functions in `coach.py`/`schedule_builder.py`/`symptom_checkin.py`/`labs.py`;
these tests check wiring, not re-derive existing coverage.

## Explicitly not doing
- No new persistent storage, schema, or config format.
- No authentication (loopback-only instead).
- No JS build step / SPA framework.
- No reimplementation of the ~20 non-focused dashboard actions.

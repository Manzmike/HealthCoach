# Weekly Planning Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a date-windowed weekly workspace for symptoms, workouts, lifestyle, and meals with sidebar navigation and persisted advisory analysis.

**Architecture:** Add one pure local state module, `webapp/weekly_workspace.py`, keyed by user-selected week start dates. Extend the existing Flask app with focused routes and templates; reuse the current symptom catalog, schedule store, food selection state, and coach analysis pipeline rather than duplicating them.

**Tech Stack:** Python 3, Flask, Jinja templates, vanilla CSS/JavaScript, existing `unittest` suite and Flask test client.

**Spec:** `docs/superpowers/specs/2026-09-18-weekly-planning-workspace.md`

## Global Constraints

- Active editing window is the inclusive seven-day range beginning on the selected date.
- Analysis is explicit, advisory, local, and stale after any analyzed input changes.
- Meal count is limited to 1–7.
- Existing Food, Schedule, Labs, and symptom logic remains compatible.
- No medical diagnosis, clearance, or automatic schedule mutation is added.

---

### Task 1: Weekly state and deterministic generators

**Files:**
- Create: `rag/webapp/weekly_workspace.py`
- Test: `rag/test_webapp_weekly_workspace.py`

**Interfaces:**
- `empty_week(start: str) -> dict`
- `normalize_week(value: Mapping[str, Any], start: str | None = None) -> dict`
- `load(path: str | Path | None = None) -> dict[str, dict]`
- `save_week(week: Mapping[str, Any], path: str | Path | None = None) -> dict`
- `get_week(start: str, path: str | Path | None = None) -> dict`
- `is_editable(start: str, today: date | None = None) -> bool`
- `week_dates(start: str) -> tuple[str, str]`
- `generate_workouts(current_level: str, target: str, days: list[str], focus: str, constraints: str) -> list[dict]`
- `analysis_is_current(week: Mapping[str, Any], section: str) -> bool`

- [x] Write failing tests for exact seven-day boundaries, invalid dates, malformed state recovery, 1–7 meal normalization, stale analysis, and deterministic workout sessions.
- [x] Run the focused test file and confirm the new behavior failed before implementation.
- [x] Implement the normalized weekly JSON record, safe local persistence, date-window helper, workout generator, and snapshot comparison.
- [x] Run the focused test file and confirm it passes.

### Task 2: Sidebar and shared week navigation

**Files:**
- Modify: `rag/webapp/templates/base.html`
- Modify: `rag/webapp/static/style.css`
- Test: `rag/test_webapp_app.py`

- [x] Add Symptoms, Workouts, Lifestyle, and Meals links beside Food, with active page state and mobile overflow behavior.
- [x] Add shared `.week-toolbar`, `.readonly-note`, `.choice-grid`, and planner result styles using existing design tokens.
- [x] Add route-level assertions that all planner links render and active states are present.

### Task 3: Weekly symptoms

**Files:**
- Modify: `rag/webapp/app.py`
- Modify: `rag/webapp/templates/symptoms.html`
- Test: `rag/test_webapp_app.py`

- [x] Add a selected-week query/form field and load the corresponding weekly record.
- [x] Save selected symptoms and notes only when the week is editable; preserve the existing report generation from `symptom_checkin.py`.
- [x] Show the saved report/read-only state outside the active window and provide previous/current/next date navigation.
- [x] Add route tests for saving inside the window and refusing mutation outside it.

### Task 4: Workout planner

**Files:**
- Modify: `rag/webapp/app.py`
- Create: `rag/webapp/templates/workouts.html`
- Test: `rag/test_webapp_app.py`

- [x] Add `/workouts` GET/POST and `/workouts/analyze` routes.
- [x] Render current level, target, days, focus, and constraints; generate sessions on save.
- [x] Include a link to the existing Schedule editor and show generated sessions separately from the calendar until the user chooses to add calendar blocks.
- [x] Build one consolidated advisory query and persist its rendered sections; show stale status after edits.

### Task 5: Lifestyle planner

**Files:**
- Modify: `rag/webapp/app.py`
- Create: `rag/webapp/templates/lifestyle.html`
- Test: `rag/test_webapp_app.py`

- [x] Add `/lifestyle` GET/POST and `/lifestyle/analyze` routes.
- [x] Add current and target habit choices, notes, and a current-calendar summary/link using `schedule_builder.load`.
- [x] Build a consolidated advisory query from the lifestyle state and calendar blocks, persist it, and mark it stale after edits.

### Task 6: Meal slots and analysis

**Files:**
- Modify: `rag/webapp/app.py`
- Create: `rag/webapp/templates/meals.html`
- Test: `rag/test_webapp_app.py`

- [x] Add `/meals` GET/POST and `/meals/analyze` routes.
- [x] Add a 1–7 meal-count control and render that many editable meal slots for the selected week.
- [x] Include selected Food catalog items in the analysis context without changing the existing Food selection store.
- [x] Persist the meal plan and consolidated advisory analysis; show stale status after changes.

### Task 7: Documentation and verification

**Files:**
- Modify: `rag/README.md`
- Modify: `docs/PROJECT_OVERVIEW.md`

- [x] Document the weekly workspace, seven-day window, planner routes, and advisory-analysis behavior.
- [x] Run the focused web tests, browser smoke checks, and `git diff --check`.
- [x] Run the full `rag` test suite and perform the final protected-file review.

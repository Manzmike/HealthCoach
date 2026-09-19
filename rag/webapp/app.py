#!/usr/bin/env python3
"""HealthCoach local web GUI (see docs/superpowers/specs/2026-09-17-
healthcoach-web-gui-design.md). Focused pages cover questions, weekly
symptoms, workouts, lifestyle, meals, foods, schedule, and labs, plus a
home page and a reference list of everything else still reachable through ./hc.

This is a new CALLER of the existing modules, not a new implementation of
their logic: it reads and writes the exact same files the CLI tools already
use (schedule_calendar.json, .healthcoach/labs.json, the LanceDB table), so
editing your schedule here and then asking coach.py about it in the
terminal sees the same file, no sync step.

Run via ../hc-web, not directly -- that script activates the venv and opens
your browser. If you do run it directly, it still binds to 127.0.0.1 only:
this serves private health data and must never be reachable from the
network.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

from flask import Flask, redirect, render_template, request, send_file, url_for

HERE = Path(__file__).resolve().parent
RAG_DIR = HERE.parent
sys.path.insert(0, str(RAG_DIR))

import candidate_ledger as CL  # noqa: E402
import coach  # noqa: E402
import diet_rules as DR  # noqa: E402
import labs as L  # noqa: E402
import schedule_builder as SB  # noqa: E402
import supplement_audit as audit  # noqa: E402
import symptom_checkin as SC  # noqa: E402
import today as T  # noqa: E402
import week_plan as WP  # noqa: E402
import week_planner as WPL  # noqa: E402
import weekly_food_plan as food_plan  # noqa: E402
from healthcoach_dashboard import ACTIONS  # noqa: E402
from webapp import food_analysis as FoodA  # noqa: E402
from webapp import food_draft as FDraft  # noqa: E402
from webapp import food_preferences as FoodP  # noqa: E402
from webapp import intake as Intake  # noqa: E402
from webapp import render as R  # noqa: E402
from webapp import schedule_analysis as SA  # noqa: E402
from webapp import schedule_view as SV  # noqa: E402
from webapp import setup_state as Setup  # noqa: E402
from webapp import weekly_workspace as WW  # noqa: E402

app = Flask(__name__)

REPORT = RAG_DIR / "HEALTHCOACH_REPORT.md"

_COVERED_ACTION_KEYS = {"question", "symptoms", "food-review"}  # schedule/labs have no direct dashboard action

# --------------------------------------------------------------------------
# Lazy RAG-stack cache: loaded at most once per server process, only when
# /ask actually needs it -- same rationale as schedule_builder.py's
# _LazyRag and coach.py's own lazy imports inside main().
_stack_cache: dict = {}
_model_cache: dict = {}


def _get_stack():
    if "value" not in _stack_cache:
        _stack_cache["value"] = coach.load_rag_stack()
    return _stack_cache["value"]


def _reopen_table_after_new_sources() -> None:
    if "value" in _stack_cache:
        import lancedb
        tbl, emb, rr = _stack_cache["value"]
        _stack_cache["value"] = (lancedb.connect(coach.DBDIR).open_table(coach.TABLE), emb, rr)


def _load_model():
    if "value" not in _model_cache:
        _model_cache["value"] = coach._load_gen_model()
    return _model_cache["value"]


@app.route("/")
def home():
    setup = Setup.load()
    if not setup["complete"]:
        return render_template("setup.html", setup=setup)
    state = T.load_today(report=REPORT)
    schedule = _load_schedule()
    return render_template(
        "home.html",
        report_available=state["report_available"],
        profile_saved=state["profile_saved"],
        has_schedule=bool(schedule["blocks"]),
        has_labs=bool(L.load_labs().get("entries")),
        confirmed_intake=Intake.load(),
    )


@app.route("/setup")
def setup():
    return render_template("setup.html", setup=Setup.load())


def _intake_sources() -> dict:
    ledger = CL.load_ledger()
    food_preferences = FoodP.load(FoodP.DEFAULT_PATH)
    schedule = _load_schedule()
    labs = L.load_labs()
    return {
        "ledger": ledger,
        "food_preferences": food_preferences,
        "schedule_count": len(schedule.get("blocks", [])),
        "lab_count": len(labs.get("entries", {})),
    }


def _intake_context(draft: dict, sources: dict, *, error: str | None = None) -> dict:
    return {
        "draft": draft,
        "error": error,
        "imported": Intake.imported_snapshot(**sources),
        "diet_options": DR.DIET_PRESETS,
        "toggle_options": DR.EXCLUSION_TOGGLES,
        "goal_options": [(key, label) for key, label in CL.REASON_OPTIONS
                         if key in CL.OUTCOME_REASON_KEYS],
        "sex_options": CL.SEX_VALUES,
    }


@app.route("/setup/intake", methods=["GET", "POST"])
def setup_intake():
    sources = _intake_sources()
    if request.method == "GET":
        draft = Intake.from_existing(**sources)
        return render_template("setup_intake.html", **_intake_context(draft, sources))
    try:
        draft = Intake.normalize({
            "diet": request.form.get("diet"),
            "toggles": request.form.getlist("toggle"),
            "health_goals": request.form.getlist("health_goal"),
            "weight_direction": request.form.get("weight_direction"),
            "body_goals": request.form.get("body_goals"),
            "lifestyle_goals": request.form.get("lifestyle_goals"),
            "bodyweight_kg": request.form.get("bodyweight_kg"),
            "height_cm": request.form.get("height_cm"),
            "age_years": request.form.get("age_years"),
            "sex": request.form.get("sex"),
            "current_lifestyle": request.form.get("current_lifestyle"),
            "current_sport": request.form.get("current_sport"),
            "schedule_notes": request.form.get("schedule_notes"),
            "symptoms": request.form.get("symptoms"),
            "dexa": {
                key: request.form.get(f"dexa_{key}")
                for key in Intake.empty_dexa()
            },
        })
    except (ValueError, CL.LedgerError) as exc:
        draft = Intake.from_existing(**sources)
        draft.update(request.form.to_dict(flat=True))
        draft["toggles"] = request.form.getlist("toggle")
        draft["health_goals"] = request.form.getlist("health_goal")
        draft["dexa"] = {key: request.form.get(f"dexa_{key}", "") for key in Intake.empty_dexa()}
        return render_template("setup_intake.html", **_intake_context(draft, sources, error=str(exc)))
    Intake.save(draft)
    return redirect(url_for("setup_review"))


@app.route("/setup/review", methods=["GET", "POST"])
def setup_review():
    draft = Intake.load()
    if not draft["updated_at"]:
        return redirect(url_for("setup_intake"))
    sources = _intake_sources()
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "back":
            return redirect(url_for("setup_intake"))
        if action == "clear_dexa":
            draft["dexa"] = Intake.empty_dexa()
            Intake.save(draft)
            return render_template("setup_review.html", draft=draft, imported=Intake.imported_snapshot(**sources), error=None)
        if action == "clear_symptoms":
            draft["symptoms"] = "none"
            Intake.save(draft)
            return render_template("setup_review.html", draft=draft, imported=Intake.imported_snapshot(**sources), error=None)
        if action == "clear_goals":
            draft["body_goals"] = "none"
            draft["lifestyle_goals"] = "none"
            Intake.save(draft)
            return render_template("setup_review.html", draft=draft, imported=Intake.imported_snapshot(**sources), error=None)
        if action == "confirm":
            try:
                Intake.commit(draft)
                Setup.mark_step("diet")
                Setup.mark_step("goals")
                Setup.mark_complete()
            except (ValueError, CL.LedgerError) as exc:
                return render_template("setup_review.html", draft=draft,
                                       imported=Intake.imported_snapshot(**sources), error=str(exc))
            return redirect(url_for("home"))
    return render_template("setup_review.html", draft=draft,
                           imported=Intake.imported_snapshot(**sources), error=None)


@app.route("/setup/complete", methods=["POST"])
def setup_complete():
    try:
        Setup.mark_complete()
    except ValueError as exc:
        return redirect(url_for("setup", error=str(exc)))
    return redirect(url_for("home"))


@app.route("/setup/reset", methods=["POST"])
def setup_reset():
    # This resets only the walkthrough checkpoint. It never deletes health data.
    Setup.reset()
    return redirect(url_for("setup"))


@app.route("/settings")
def settings():
    return render_template("settings.html", setup=Setup.load())


# --------------------------------------------------------------------------
# /ask

@app.route("/ask", methods=["GET", "POST"])
def ask():
    if request.method == "GET":
        return render_template("ask.html", question="", sections=None)
    question = request.form.get("question", "").strip()
    if not question:
        return render_template("ask.html", question="", sections=None)
    sections = _run_question(question)
    return render_template("ask.html", question=question, sections=sections)


@app.route("/ask/fetch-sources", methods=["POST"])
def ask_fetch_sources():
    question = request.form.get("question", "").strip()
    topic_text = request.form.get("topic_text", "").strip() or question
    if topic_text and not coach.looks_like_schedule_question(topic_text):
        coach.fetch_new_sources(topic_text, print_fn=lambda *_: None)
        _reopen_table_after_new_sources()
    sections = _run_question(question) if question else None
    return render_template("ask.html", question=question, sections=sections)


def _sections_from_results(results: list[dict], *, with_schedule_block: bool = False) -> list[dict]:
    sections = []
    for result in results:
        section = {
            "topic": result["topic"],
            "text": result["text"],
            "no_evidence": result["no_evidence"],
            "answer_html": R.pipe_table_to_html(result["answer"]) if not result["no_evidence"] else "",
            "related_html": R.markdown_lite_to_html(result["related"]) if result["related"] else "",
            "offer_fetch": result["no_evidence"] and not coach.looks_like_schedule_question(result["text"]),
        }
        if with_schedule_block:
            section["schedule_html"] = R.pipe_table_to_html(result["schedule_block"]) if result["schedule_block"] else ""
        sections.append(section)
    return sections


def _run_question(question: str) -> list[dict]:
    results = coach.answer_question(question, get_stack=_get_stack, load_model=_load_model)
    return _sections_from_results(results, with_schedule_block=True)


# --------------------------------------------------------------------------
# /symptoms

def _requested_week() -> str:
    raw = request.values.get("week") or request.values.get("week_start") or dt.date.today().isoformat()
    try:
        return WW.week_dates(raw)[0]
    except ValueError:
        return dt.date.today().isoformat()


def _week_context(week_start: str, *, endpoint: str, week: dict, error: str | None = None) -> dict:
    start, end = WW.week_dates(week_start)
    current = dt.date.fromisoformat(start)
    return {
        "week": week,
        "week_start": start,
        "week_end": end,
        "previous_week": (current - dt.timedelta(days=7)).isoformat(),
        "next_week": (current + dt.timedelta(days=7)).isoformat(),
        "editable": WW.is_editable(start),
        "planner_endpoint": endpoint,
        "error": error,
    }


def _render_analysis(week: dict, section: str, results: list[dict]) -> None:
    week["analysis"][section] = {
        "snapshot": WW.analysis_snapshot(week, section),
        "sections": _sections_from_results(results),
        "analyzed_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


@app.route("/symptoms", methods=["GET", "POST"])
def symptoms():
    # The full, unfiltered, grouped list -- the type-to-filter box refines
    # this client-side (JS in symptoms.html) so every keystroke doesn't
    # need a round trip; filter_labels()/grouped_rows() are the same
    # functions the curses picker uses, just rendered as checkboxes here.
    rows = SC.grouped_rows(SC.filter_labels(""))
    week_start = _requested_week()
    week = WW.get_week(week_start, WW.DEFAULT_PATH)
    error = None
    if request.method == "POST":
        if not WW.is_editable(week_start):
            error = "This week is read-only because its seven-day check-in window has ended."
        else:
            week["symptoms"] = {
                "selected": request.form.getlist("symptom"),
                "notes": request.form.get("notes", "").strip(),
            }
            WW.save_week(week, WW.DEFAULT_PATH)
            week = WW.get_week(week_start, WW.DEFAULT_PATH)
    selected = week["symptoms"]["selected"]
    report_html = deep_html = None
    if selected:
        report = SC.build_report(selected)
        report_html = R.lines_to_html(SC.render_short(report))
        deep_html = R.lines_to_html(SC.render_deep(report))
    context = _week_context(week_start, endpoint="symptoms", week=week, error=error)
    context.update(rows=rows, selected=set(selected), report_html=report_html,
                   deep_html=deep_html, notes=week["symptoms"]["notes"])
    return render_template("symptoms.html", **context)


def _workout_context(week_start: str, week: dict, *, error: str | None = None) -> dict:
    context = _week_context(week_start, endpoint="workouts", week=week, error=error)
    analysis = week["analysis"]["workouts"] if WW.analysis_is_current(week, "workouts") else None
    context.update(
        level_options=WW.WORKOUT_LEVELS,
        target_options=WW.WORKOUT_TARGETS,
        focus_options=WW.WORKOUT_FOCUSES,
        analysis=analysis,
        analysis_stale=bool(week["analysis"]["workouts"]["analyzed_at"]) and not analysis,
    )
    return context


@app.route("/workouts", methods=["GET", "POST"])
def workouts():
    week_start = _requested_week()
    week = WW.get_week(week_start, WW.DEFAULT_PATH)
    error = None
    if request.method == "POST":
        if not WW.is_editable(week_start):
            error = "This week is read-only because its seven-day planning window has ended."
        else:
            week["workouts"] = {
                "current_level": request.form.get("current_level", "beginner"),
                "target": request.form.get("target", "build_consistency"),
                "days": request.form.getlist("day"),
                "focus": request.form.get("focus", "full_body"),
                "constraints": request.form.get("constraints", "").strip(),
                "sessions": [],
            }
            week = WW.normalize_week(week, week_start)
            settings = week["workouts"]
            settings["sessions"] = WW.generate_workouts(
                settings["current_level"], settings["target"], settings["days"],
                settings["focus"], settings["constraints"],
            )
            WW.save_week(week, WW.DEFAULT_PATH)
            week = WW.get_week(week_start, WW.DEFAULT_PATH)
    return render_template("workouts.html", **_workout_context(week_start, week, error=error))


@app.route("/workouts/analyze", methods=["POST"])
def workouts_analyze():
    week_start = _requested_week()
    week = WW.get_week(week_start, WW.DEFAULT_PATH)
    settings = week["workouts"]
    sessions = "; ".join(f"{item['day']}: {item['title']} ({item['duration']})" for item in settings["sessions"])
    query = (f"Review this weekly workout plan for a {settings['current_level']} person targeting "
             f"{settings['target']}. Focus: {settings['focus']}. Sessions: {sessions or 'none generated'}. "
             f"Constraints: {settings['constraints'] or 'none recorded'}. Give conservative, advisory recommendations "
             "for progression, recovery, and when to seek professional guidance.")
    results = coach.answer_question(query, get_stack=_get_stack, load_model=_load_model)
    _render_analysis(week, "workouts", results)
    WW.save_week(week, WW.DEFAULT_PATH)
    return redirect(url_for("workouts", week=week_start))


def _calendar_blocks() -> list[dict]:
    return [dict(block) for block in _load_schedule().get("blocks", [])]


def _lifestyle_context(week_start: str, week: dict, *, error: str | None = None) -> dict:
    calendar = _calendar_blocks()
    view_week = WW.normalize_week(week, week_start)
    view_week["lifestyle"]["calendar_snapshot"] = calendar
    context = _week_context(week_start, endpoint="lifestyle", week=view_week, error=error)
    analysis = week["analysis"]["lifestyle"] if WW.analysis_is_current(view_week, "lifestyle") else None
    context.update(
        habit_options=WW.LIFESTYLE_HABITS,
        calendar_blocks=calendar,
        analysis=analysis,
        analysis_stale=bool(week["analysis"]["lifestyle"]["analyzed_at"]) and not analysis,
    )
    return context


@app.route("/lifestyle", methods=["GET", "POST"])
def lifestyle():
    week_start = _requested_week()
    week = WW.get_week(week_start, WW.DEFAULT_PATH)
    error = None
    if request.method == "POST":
        if not WW.is_editable(week_start):
            error = "This week is read-only because its seven-day planning window has ended."
        else:
            week["lifestyle"] = {
                "current": request.form.getlist("current"),
                "target": request.form.getlist("target"),
                "notes": request.form.get("notes", "").strip(),
                "calendar_snapshot": _calendar_blocks(),
            }
            WW.save_week(WW.normalize_week(week, week_start), WW.DEFAULT_PATH)
            week = WW.get_week(week_start, WW.DEFAULT_PATH)
    return render_template("lifestyle.html", **_lifestyle_context(week_start, week, error=error))


@app.route("/lifestyle/analyze", methods=["POST"])
def lifestyle_analyze():
    week_start = _requested_week()
    week = WW.get_week(week_start, WW.DEFAULT_PATH)
    week["lifestyle"]["calendar_snapshot"] = _calendar_blocks()
    lifestyle_state = week["lifestyle"]
    calendar_text = "; ".join(f"{item.get('days', [])}: {item.get('label', '')} {item.get('start', '')}-{item.get('end', '')}" for item in lifestyle_state["calendar_snapshot"])
    query = (f"Review this person's lifestyle change plan. Current habits: {', '.join(lifestyle_state['current']) or 'not selected'}. "
             f"Target habits: {', '.join(lifestyle_state['target']) or 'not selected'}. Notes: {lifestyle_state['notes'] or 'none'}. "
             f"Current calendar blocks: {calendar_text or 'none saved'}. Give practical, incremental recommendations "
             "for improving daily life without assuming medical facts.")
    results = coach.answer_question(query, get_stack=_get_stack, load_model=_load_model)
    _render_analysis(week, "lifestyle", results)
    WW.save_week(week, WW.DEFAULT_PATH)
    return redirect(url_for("lifestyle", week=week_start))


def _selected_food_names_for_week(week_start: str) -> list[str]:
    try:
        state = _food_state()
    except (OSError, ValueError, KeyError):
        return []
    current_start = dt.date.fromisoformat(state["start"])
    requested_start = dt.date.fromisoformat(week_start)
    if not current_start <= requested_start <= current_start + dt.timedelta(days=6):
        return []
    return sorted(selection["name"] for selection in state["week"]["selected"].values()
                  if selection.get("category") == "food")


def _meals_context(week_start: str, week: dict, *, error: str | None = None) -> dict:
    week["food_context"] = _selected_food_names_for_week(week_start)
    context = _week_context(week_start, endpoint="meals", week=week, error=error)
    analysis = week["analysis"]["meals"] if WW.analysis_is_current(week, "meals") else None
    context.update(
        selected_foods=_selected_food_names_for_week(week_start),
        analysis=analysis,
        analysis_stale=bool(week["analysis"]["meals"]["analyzed_at"]) and not analysis,
    )
    return context


@app.route("/meals", methods=["GET", "POST"])
def meals():
    week_start = _requested_week()
    week = WW.get_week(week_start, WW.DEFAULT_PATH)
    error = None
    if request.method == "POST":
        if not WW.is_editable(week_start):
            error = "This week is read-only because its seven-day planning window has ended."
        else:
            try:
                meal_count = int(request.form.get("meal_count", "3"))
                meals_value = [{"name": request.form.get(f"meal_name_{index}", ""),
                                "notes": request.form.get(f"meal_notes_{index}", "")}
                               for index in range(meal_count)]
                week = WW.normalize_week({**week, "meal_count": meal_count, "meals": meals_value}, week_start)
                WW.save_week(week, WW.DEFAULT_PATH)
                week = WW.get_week(week_start, WW.DEFAULT_PATH)
            except ValueError as exc:
                error = str(exc)
    return render_template("meals.html", **_meals_context(week_start, week, error=error))


@app.route("/meals/analyze", methods=["POST"])
def meals_analyze():
    week_start = _requested_week()
    week = WW.get_week(week_start, WW.DEFAULT_PATH)
    foods = _selected_food_names_for_week(week_start)
    week["food_context"] = foods
    meal_text = "; ".join(f"{item['name'] or 'Unnamed meal'}: {item['notes'] or 'no notes'}" for item in week["meals"])
    query = (f"Review this weekly meal plan: {meal_text}. Foods selected in the catalog: {', '.join(foods) or 'none'}. "
             "Give practical advisory recommendations for variety, adequacy, preparation, and fit with the person's goals. "
             "Do not diagnose or prescribe.")
    results = coach.answer_question(query, get_stack=_get_stack, load_model=_load_model)
    _render_analysis(week, "meals", results)
    WW.save_week(week, WW.DEFAULT_PATH)
    return redirect(url_for("meals", week=week_start))

# --------------------------------------------------------------------------
# /schedule

def _load_schedule() -> dict:
    # SB.load()'s own `path: str = SB.DEFAULT_PATH` default is bound once,
    # at function-definition time -- patching SB.DEFAULT_PATH in a test
    # afterwards does NOT change it (confirmed live: a route test's
    # patch.object(SB, "DEFAULT_PATH", tmp_path) silently kept writing to
    # the real rag/schedule_calendar.json). Reading SB.DEFAULT_PATH here,
    # at call time, and passing it explicitly is what test isolation
    # actually needs -- the same reason test_schedule_builder.py always
    # passes an explicit path rather than patching the attribute.
    return SB.load(SB.DEFAULT_PATH)


def _save_schedule(sched: dict) -> None:
    SB.save(sched, SB.DEFAULT_PATH)


def _schedule_context(sched: dict, *, error: str | None = None) -> dict:
    analysis = SA.load(SA.DEFAULT_PATH)
    return {
        "days": SV.grouped_by_day(sched),
        "hour_labels": SV.HOUR_LABELS,
        "categories": SB.CATEGORIES,
        "research_categories": sorted(SB._RESEARCH_RELEVANT_CATEGORIES),
        "error": error,
        "is_analyzed": SA.is_current(sched, analysis),
        "analysis_results": analysis.get("results") if analysis.get("snapshot") else None,
        "analyzed_at": analysis.get("analyzed_at"),
        "has_blocks": bool(sched["blocks"]),
        "edit_mode": False,
    }


@app.route("/schedule")
def schedule():
    sched = _load_schedule()
    context = _schedule_context(sched, error=request.args.get("error"))
    context["edit_mode"] = request.args.get("edit") == "1"
    return render_template("schedule.html", **context)


@app.route("/schedule/add", methods=["POST"])
def schedule_add():
    sched = _load_schedule()
    category_input = request.form.get("category", "")
    label = request.form.get("label", "")
    start_input = request.form.get("start", "")
    end_input = request.form.get("end", "")
    days_input = ",".join(request.form.getlist("days"))
    error = None
    try:
        category = SB._resolve_category(category_input)
        if category is None:
            raise ValueError(f"Unknown category {category_input!r}; choose one of {SB.CATEGORIES}")
        start = SB.parse_time(start_input)
        end = SB.parse_time(end_input)
        days = SB.parse_days(days_input)
        if not days:
            raise ValueError(f"Could not recognize any day in {days_input!r}")
        SB.add_block(sched, category=category, label=label, start=start, end=end, days=days)
        _save_schedule(sched)
    except ValueError as exc:
        error = str(exc)
    if error:
        context = _schedule_context(_load_schedule(), error=error)
        context["edit_mode"] = True
        return render_template("schedule.html", **context)
    added_category = SB._resolve_category(category_input)
    if added_category in SB._RESEARCH_RELEVANT_CATEGORIES:
        return redirect(url_for("schedule_research", category=added_category, label=label))
    return redirect(url_for("schedule"))


@app.route("/schedule/remove", methods=["POST"])
def schedule_remove():
    sched = _load_schedule()
    index = int(request.form["index"])
    if 0 <= index < len(sched["blocks"]):
        sched["blocks"].pop(index)
        _save_schedule(sched)
    return redirect(url_for("schedule"))


@app.route("/schedule/research")
def schedule_research():
    category = request.args.get("category", "")
    label = request.args.get("label", "")
    sched = _load_schedule()
    query = SB._placement_query(sched, category, label)
    results = coach.answer_question(query, get_stack=_get_stack, load_model=_load_model)
    sections = _sections_from_results(results)
    return render_template("schedule_research.html", category=category, label=label, sections=sections)


@app.route("/schedule/analyze", methods=["POST"])
def schedule_analyze():
    """Advisory only -- this NEVER moves, resizes, or removes a block on
    its own. It runs the same evidence-lookup pipeline schedule_research()
    already uses for one new block, once per research-relevant category
    present across the WHOLE current schedule, and persists the result as
    the gate .ics download checks (see schedule_analysis.is_current):
    editing a block after this invalidates the gate until analyzed again."""
    sched = _load_schedule()
    targets = SV.analysis_targets(sched)
    results = []
    for category, label in targets:
        query = SB._placement_query(sched, category, label)
        answered = coach.answer_question(query, get_stack=_get_stack, load_model=_load_model)
        sections = _sections_from_results(answered)
        results.append({"category": category, "label": label, "sections": sections})
    SA.save(sched["blocks"], results, analyzed_at=dt.datetime.now().isoformat(timespec="seconds"),
            path=SA.DEFAULT_PATH)
    return redirect(url_for("schedule"))


@app.route("/schedule/export.ics")
def schedule_export():
    sched = _load_schedule()
    if not sched["blocks"]:
        return redirect(url_for("schedule", error="Add at least one block before exporting."))
    if not SA.is_current(sched, SA.load(SA.DEFAULT_PATH)):
        return redirect(url_for("schedule", error="Analyze the schedule first -- download unlocks once "
                                                    "Analyze has run against your current blocks."))
    # Same call-time-vs-definition-time issue as SB.load()/SB.save() above:
    # SB.export_ics()'s `path` default is bound to SB.DEFAULT_ICS_PATH at
    # definition time too.
    path = SB.export_ics(sched, SB.DEFAULT_ICS_PATH)
    return send_file(path, as_attachment=True, download_name="healthcoach_schedule.ics")


# --------------------------------------------------------------------------
# /labs

def _lab_rows() -> list[dict]:
    entries = L.load_labs().get("entries", {})
    rows = []
    for key, spec in L.MARKERS.items():
        entry = entries.get(key)
        if entry is None:
            continue
        rows.append({
            "name": spec["name"], "value": entry["value"], "unit": entry.get("unit", spec["unit"]),
            "ref_low": spec["low"], "ref_high": spec["high"], "ref_unit": spec["unit"],
            "status": L.marker_status(key, entry["value"]),
            "date": entry.get("date", "unknown"), "source": entry.get("source", "manual"),
        })
    return rows


@app.route("/labs")
def labs_page():
    return render_template("labs.html", rows=_lab_rows(), markers=sorted(L.MARKERS), error=None,
                           candidates=None, edit_mode=request.args.get("edit") == "1")


@app.route("/labs/add", methods=["POST"])
def labs_add():
    error = None
    try:
        L.save_lab_value(
            request.form.get("marker", ""), float(request.form.get("value", "0") or 0),
            unit=request.form.get("unit") or None, date=request.form.get("date") or None,
            confirm_unit=bool(request.form.get("confirm_unit")),
        )
    except (ValueError, SystemExit) as exc:
        error = str(exc)
    if error:
        return render_template("labs.html", rows=_lab_rows(), markers=sorted(L.MARKERS), error=error,
                               candidates=None, edit_mode=True)
    return redirect(url_for("labs_page"))


@app.route("/labs/import", methods=["POST"])
def labs_import():
    upload = request.files.get("pdf")
    error = None
    candidates = None
    filename = ""
    if not upload or not upload.filename:
        error = "Choose a PDF file first."
    else:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, upload.filename)
            upload.save(path)
            try:
                candidates, filename = L.extract_pdf_candidates(path)
            except FileNotFoundError:
                error = "Could not read the uploaded file."
        if candidates == []:
            error = ("No extractable text or no recognized marker names found "
                      "(it may be a scanned image). Try `labs.py add` to enter values manually.")
    if error:
        return render_template("labs.html", rows=_lab_rows(), markers=sorted(L.MARKERS), error=error, candidates=None)
    display = [{"key": c["key"], "name": L.MARKERS[c["key"]]["name"], "value": c["value"],
                "unit": L.MARKERS[c["key"]]["unit"], "snippet": c["snippet"]} for c in candidates]
    return render_template("labs_confirm.html", candidates=display, filename=filename)


@app.route("/labs/import/confirm", methods=["POST"])
def labs_import_confirm():
    filename = request.form.get("filename", "upload.pdf")
    date = request.form.get("date") or None
    date = date or dt.date.today().isoformat()
    saved = 0
    for key in request.form.getlist("save"):
        raw_value = request.form.get(f"value_{key}")
        if raw_value is None:
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        L.save_confirmed_value(key, value, date, f"pdf:{filename}")
        saved += 1
    return redirect(url_for("labs_page"))


# --------------------------------------------------------------------------
# /food -- browse the evidence-graded food catalog and select items for the
# current week with a required source-linked reason, then save with one
# overall reason (or discard). The weekly workspace's meal and workout
# planners deliberately keep their own local state while linking back to
# this evidence-gated Food catalog.

def _food_state() -> dict:
    """Loads everything week_planner.py's curses session would hold in
    memory for the whole session -- resolved fresh on every request instead,
    since HTTP has no equivalent long-lived session here. `week` is the
    current in-progress draft if one exists (see webapp/food_draft.py),
    else the already-saved week if there is one, else a fresh seed."""
    ledger = CL.load_ledger()
    food_preferences = FoodP.load(FoodP.DEFAULT_PATH)
    profile = audit.load_saved_profile(REPORT) or {}
    rows = WPL.catalog_rows(ledger)
    food_records = food_plan._load_food_evidence()
    data = WP.load(WP.DEFAULT_PATH)
    research = data["research"]
    start = WP.monday(dt.date.today())
    previous = data["weeks"].get(start)
    baseline = previous if previous is not None else WP.seed_week(start, rows, profile)
    draft = FDraft.load_draft(start, FDraft.DEFAULT_PATH)
    week = draft if draft is not None else baseline
    # Compared by VALUE against the real baseline, not "does a draft file
    # happen to exist" -- selecting then unselecting the same item leaves a
    # draft file on disk (harmless) whose content is now identical to
    # baseline again, and that must read back as clean, not still dirty.
    dirty = week != baseline
    return {"ledger": ledger, "profile": profile, "rows": rows, "food_records": food_records,
            "research": research, "food_preferences": food_preferences, "start": start,
            "previous": previous, "week": week, "dirty": dirty}


def _food_entries(state: dict) -> list[dict]:
    entries = [row for row in state["rows"] if "food" in row.get("browse_categories", [WP.category(row)])]
    scored = {row["id"]: WP.grades(row, state["ledger"]["intake"], state["food_records"].get(row["id"]),
                                    state["research"].get(row["id"])) for row in entries}
    preferences = state.get("food_preferences", FoodP.default())
    allowed = DR.allowed_food_ids(preferences["diet"], set(preferences["toggles"]))
    diet_label = DR.DIET_PRESETS[preferences["diet"]]["label"]
    return [{"id": row["id"], "name": row["display_name"], "overall": scored[row["id"]]["overall"],
              "personal": scored[row["id"]]["personal"], "coverage": scored[row["id"]]["coverage"],
              "selected": row["id"] in state["week"]["selected"],
              "allowed": row["id"] in allowed,
              "restriction": "Does not fit " + diet_label if row["id"] not in allowed else ""}
             for row in entries]


@app.route("/food")
def food():
    state = _food_state()
    analysis = FoodA.load(FoodA.DEFAULT_PATH)
    selected_foods = sorted(s["name"] for s in state["week"]["selected"].values() if s["category"] == "food")
    return render_template(
        "food.html", entries=_food_entries(state), start=state["start"], dirty=state["dirty"],
        error=request.args.get("error"), current_goals=state["ledger"]["intake"].get("goals", []),
        goal_labels=dict(CL.REASON_OPTIONS),
        food_preferences=state["food_preferences"],
        diet_label=DR.DIET_PRESETS[state["food_preferences"]["diet"]]["label"],
        toggle_labels={key: value["label"] for key, value in DR.EXCLUSION_TOGGLES.items()},
        has_selected_foods=bool(selected_foods),
        analysis=analysis if analysis.get("foods") == selected_foods else None,
    )


@app.route("/food/select/<item_id>", methods=["GET", "POST"])
def food_select(item_id):
    state = _food_state()
    row = next((r for r in state["rows"] if r["id"] == item_id), None)
    if row is None:
        return redirect(url_for("food", error="Item not found in the current catalog."))
    preferences = state["food_preferences"]
    if item_id not in DR.allowed_food_ids(preferences["diet"], set(preferences["toggles"])):
        return redirect(url_for("food", error=f"{row['display_name']} does not fit the selected diet."))
    grade = WP.grades(row, state["ledger"]["intake"], state["food_records"].get(item_id),
                       state["research"].get(item_id))
    sources = WPL.resources_for(row, grade)
    if not sources:
        return redirect(url_for(
            "food", error=f"{row['display_name']}: no usable source/resource on file for this item yet."))
    if request.method == "GET":
        return render_template("food_justify.html", row=row, sources=sources, error=None)
    try:
        source_index = int(request.form.get("source_index", "-1"))
        if not 0 <= source_index < len(sources):
            raise ValueError("Choose one of the listed supporting sources.")
        basis = WP.rationale(request.form.get("goal", ""), request.form.get("personal_reason", ""),
                              request.form.get("review_trigger", ""), sources[source_index], sources)
    except ValueError as exc:
        return render_template("food_justify.html", row=row, sources=sources, error=str(exc))
    week = state["week"]
    week["selected"][item_id] = {**WP.selection(row), "rationale": basis}
    FDraft.save_draft(state["start"], week, FDraft.DEFAULT_PATH)
    return redirect(url_for("food"))


@app.route("/food/unselect/<item_id>", methods=["POST"])
def food_unselect(item_id):
    state = _food_state()
    # Only write a draft when something actually changed -- unselecting an
    # item that was never selected (e.g. a stale page, a double click) is a
    # no-op and must not manufacture "unsaved changes" out of nothing.
    if item_id in state["week"]["selected"]:
        del state["week"]["selected"][item_id]
        FDraft.save_draft(state["start"], state["week"], FDraft.DEFAULT_PATH)
    return redirect(url_for("food"))


@app.route("/food/save", methods=["POST"])
def food_save():
    state = _food_state()
    try:
        WP.save(state["start"], state["week"], state["previous"], request.form.get("reason", ""), WP.DEFAULT_PATH)
    except ValueError as exc:
        return redirect(url_for("food", error=str(exc)))
    FDraft.clear_draft(state["start"], FDraft.DEFAULT_PATH)
    return redirect(url_for("food"))


@app.route("/food/discard", methods=["POST"])
def food_discard():
    state = _food_state()
    FDraft.clear_draft(state["start"], FDraft.DEFAULT_PATH)
    return redirect(url_for("food"))


@app.route("/food/diet", methods=["GET", "POST"])
def food_diet():
    """Choose the diet gate before choosing foods.

    Changing the gate cannot silently strand a current selection: the user
    must remove excluded items first, so the saved weekly plan and the active
    diet never disagree by accident.
    """
    current = FoodP.load(FoodP.DEFAULT_PATH)
    error = None
    source = request.args.get("from", "") or request.form.get("from", "")
    if request.method == "POST":
        try:
            proposed = FoodP.normalize({
                "diet": request.form.get("diet"),
                "toggles": request.form.getlist("toggle"),
            })
            state = _food_state()
            selected_ids = {
                item_id for item_id, selection in state["week"]["selected"].items()
                if selection.get("category") == "food"
            }
            blocked = selected_ids - DR.allowed_food_ids(proposed["diet"], set(proposed["toggles"]))
            if blocked:
                names = [state["week"]["selected"][item_id]["name"] for item_id in sorted(blocked)]
                raise ValueError("Remove or replace selected foods first: " + ", ".join(names) + ".")
            FoodP.save(proposed, FoodP.DEFAULT_PATH)
            if source == "setup":
                Setup.mark_step("diet")
        except ValueError as exc:
            error = str(exc)
            current = locals().get("proposed", current)
        else:
            if source == "setup":
                return redirect(url_for("setup"))
            if source == "settings":
                return redirect(url_for("settings"))
            return redirect(url_for("food"))
    return render_template("food_diet.html", diet_options=DR.DIET_PRESETS,
                           toggle_options=DR.EXCLUSION_TOGGLES, current=current, error=error, source=source)


@app.route("/food/goals", methods=["GET", "POST"])
def food_goals():
    """Sets the SAME intake.goals/weight_direction candidate_manager.py's
    CLI intake wizard writes -- week_plan.grades() already reads these for
    /food's "For you" column, so this doesn't add a parallel concept, just
    a web way to set the one that already exists. Diet eligibility is handled
    separately by diet_rules.py and /food/diet."""
    ledger = CL.load_ledger()
    options = [(key, label) for key, label in CL.REASON_OPTIONS if key in CL.OUTCOME_REASON_KEYS]
    source = request.args.get("from", "") or request.form.get("from", "")
    if request.method == "POST":
        goals = [g for g in request.form.getlist("goal") if g][:3]
        ledger["intake"]["goals"] = goals
        ledger["intake"]["weight_direction"] = request.form.get("weight_direction", "unknown")
        try:
            CL.save_ledger(ledger)
        except CL.LedgerError as exc:
            return render_template("food_goals.html", options=options, weight_directions=CL.WEIGHT_DIRECTIONS,
                                    current_goals=goals,
                                    current_weight_direction=ledger["intake"]["weight_direction"], error=str(exc))
        if source == "setup":
            Setup.mark_step("goals")
            return redirect(url_for("setup"))
        if source == "settings":
            return redirect(url_for("settings"))
        return redirect(url_for("food"))
    intake = CL.normalize_intake(ledger.get("intake"))
    return render_template("food_goals.html", options=options, weight_directions=CL.WEIGHT_DIRECTIONS,
                            current_goals=intake.get("goals", []),
                            current_weight_direction=intake.get("weight_direction", "unknown"),
                            error=None, source=source)


@app.route("/food/analyze", methods=["POST"])
def food_analyze():
    """Advisory only, exactly like /schedule/analyze -- never changes a
    selection on its own. One consolidated evidence question covering all
    currently-selected foods and the recorded goals, not one query per
    food, so this stays fast and doesn't spam near-duplicate lookups."""
    state = _food_state()
    selected_names = [s["name"] for s in state["week"]["selected"].values() if s["category"] == "food"]
    if not selected_names:
        return redirect(url_for("food", error="Select at least one food first."))
    goals = state["ledger"]["intake"].get("goals", [])
    preferences = state.get("food_preferences", FoodP.default())
    diet_label = DR.DIET_PRESETS[preferences["diet"]]["label"]
    toggles = [DR.EXCLUSION_TOGGLES[name]["label"] for name in preferences["toggles"]]
    diet_text = f" Diet gate: {diet_label}." + (f" Exclusions: {', '.join(toggles)}." if toggles else "")
    goal_text = f" Recorded goals, in priority order: {', '.join(goals)}." if goals else ""
    query = (f"What does the evidence say about these foods for overall health: "
             f"{', '.join(selected_names)}?{diet_text}{goal_text}")
    results = coach.answer_question(query, get_stack=_get_stack, load_model=_load_model)
    sections = _sections_from_results(results)
    FoodA.save(sorted(selected_names), sections, analyzed_at=dt.datetime.now().isoformat(timespec="seconds"),
               path=FoodA.DEFAULT_PATH)
    return redirect(url_for("food"))


@app.route("/food/export")
def food_export():
    """A plain-text summary of this week's selected foods, their grades,
    and your recorded reason for each -- the same underlying data
    plan_export.py's fuller report includes, just food-scoped and
    generated on demand rather than requiring the CLI export flow."""
    state = _food_state()
    entries = _food_entries(state)
    by_id = {e["id"]: e for e in entries}
    preferences = state.get("food_preferences", FoodP.default())
    lines = [f"HealthCoach food selections -- week of {state['start']}",
             f"Diet gate: {DR.DIET_PRESETS[preferences['diet']]['label']}", ""]
    for item_id, selection in state["week"]["selected"].items():
        if selection["category"] != "food":
            continue
        entry = by_id.get(item_id)
        lines.append(f"## {selection['name']}")
        if entry:
            lines.append(f"Overall evidence: {entry['overall']} | For you: {entry['personal']} "
                          f"| Coverage: {entry['coverage']}")
        rationale = selection.get("rationale") or {}
        if rationale:
            lines.append(f"Purpose: {rationale.get('goal', '')}")
            lines.append(f"Why it fits: {rationale.get('personal_reason', '')}")
            lines.append(f"Review when: {rationale.get('review_trigger', '')}")
            source = rationale.get("source") or {}
            if source:
                lines.append(f"Source: [{source.get('kind', '')}] {source.get('text', '')}")
        lines.append("")
    body = "\n".join(lines) if len(lines) > 2 else "No foods selected for this week yet.\n"
    return app.response_class(body, mimetype="text/plain")


# --------------------------------------------------------------------------
# /more

@app.route("/more")
def more():
    remaining = [a for a in ACTIONS if a.key not in _COVERED_ACTION_KEYS]
    return render_template("more.html", actions=remaining)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5231, debug=False)

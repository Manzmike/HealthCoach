#!/usr/bin/env python3
"""HealthCoach local web GUI (see docs/superpowers/specs/2026-09-17-
healthcoach-web-gui-design.md). Four focused pages -- ask a question,
symptom check-in, schedule builder, labs -- plus a home page and a
reference list of everything else still reachable through ./hc.

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

import os
import sys
import tempfile
from pathlib import Path

from flask import Flask, redirect, render_template, request, send_file, url_for

HERE = Path(__file__).resolve().parent
RAG_DIR = HERE.parent
sys.path.insert(0, str(RAG_DIR))

import coach  # noqa: E402
import labs as L  # noqa: E402
import schedule_builder as SB  # noqa: E402
import symptom_checkin as SC  # noqa: E402
import today as T  # noqa: E402
from healthcoach_dashboard import ACTIONS  # noqa: E402
from webapp import render as R  # noqa: E402
from webapp import schedule_view as SV  # noqa: E402

app = Flask(__name__)

REPORT = RAG_DIR / "HEALTHCOACH_REPORT.md"

_COVERED_ACTION_KEYS = {"question", "symptoms"}  # schedule/labs have no direct dashboard action

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
    state = T.load_today(report=REPORT)
    schedule = _load_schedule()
    return render_template(
        "home.html",
        report_available=state["report_available"],
        profile_saved=state["profile_saved"],
        has_schedule=bool(schedule["blocks"]),
        has_labs=bool(L.load_labs().get("entries")),
    )


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

@app.route("/symptoms", methods=["GET", "POST"])
def symptoms():
    # The full, unfiltered, grouped list -- the type-to-filter box refines
    # this client-side (JS in symptoms.html) so every keystroke doesn't
    # need a round trip; filter_labels()/grouped_rows() are the same
    # functions the curses picker uses, just rendered as checkboxes here.
    rows = SC.grouped_rows(SC.filter_labels(""))
    if request.method == "GET":
        return render_template("symptoms.html", rows=rows, selected=set(),
                                report_html=None, deep_html=None)
    selected = request.form.getlist("symptom")
    report = SC.build_report(selected)
    report_html = R.lines_to_html(SC.render_short(report))
    deep_html = R.lines_to_html(SC.render_deep(report))
    return render_template("symptoms.html", rows=rows, selected=set(selected),
                            report_html=report_html, deep_html=deep_html)


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


@app.route("/schedule")
def schedule():
    sched = _load_schedule()
    return render_template(
        "schedule.html", days=SV.grouped_by_day(sched), categories=SB.CATEGORIES,
        research_categories=sorted(SB._RESEARCH_RELEVANT_CATEGORIES),
        error=request.args.get("error"),
    )


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
        return render_template(
            "schedule.html", days=SV.grouped_by_day(_load_schedule()), categories=SB.CATEGORIES,
            research_categories=sorted(SB._RESEARCH_RELEVANT_CATEGORIES), error=error,
        )
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


@app.route("/schedule/export.ics")
def schedule_export():
    sched = _load_schedule()
    if not sched["blocks"]:
        return redirect(url_for("schedule", error="Add at least one block before exporting."))
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
    return render_template("labs.html", rows=_lab_rows(), markers=sorted(L.MARKERS), error=None, candidates=None)


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
        return render_template("labs.html", rows=_lab_rows(), markers=sorted(L.MARKERS), error=error, candidates=None)
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
    import datetime as dt
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
# /more

@app.route("/more")
def more():
    remaining = [a for a in ACTIONS if a.key not in _COVERED_ACTION_KEYS]
    return render_template("more.html", actions=remaining)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5231, debug=False)

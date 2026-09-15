#!/usr/bin/env python3
"""Visible weekly choices, evidence/personal grades, meals, training, and change reasons."""

from __future__ import annotations

import argparse
import copy
import curses
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import candidate_ledger as CL
import daily_log
import healthcoach_dashboard as dashboard
import safety_policy as SP
import week_plan as W

VIEWS = {"overview": "Week", "food": "Foods", "gray": "Peptides/Gray", "nootropic": "Nootropics",
         "supplement": "Supplements", "other": "Other", "meals": "Meals", "training": "Training", "changes": "Changes"}


def catalog_rows(ledger: dict) -> list[dict]:
    import supplement_audit as audit
    import weekly_food_plan as food_plan
    from candidate_manager import ISSUE_TO_REASON

    nutrition = food_plan._load_nutrition()
    rows = {}
    for candidate in (*audit.CATALOG, *audit.PEPTIDE_CATALOG, *audit.WHOLE_FOOD_CATALOG):
        row = CL.normalize_row({"id": candidate.key, "display_name": candidate.name,
                                "class": audit.default_ledger_class(candidate), "aliases": candidate.aliases,
                                "folder": candidate.folders[0] if candidate.folders else None})
        row["catalog_reasons"] = list(dict.fromkeys(ISSUE_TO_REASON[i] for i in candidate.issues if i in ISSUE_TO_REASON))
        row["catalog_gate"] = candidate.gate or candidate.policy
        rows[row["id"]] = row
    for saved in ledger["candidates"]:
        candidate, _ = audit.candidate_from_ledger_row(saved)
        rows[saved["id"]] = {**saved, "catalog_reasons": list(dict.fromkeys(ISSUE_TO_REASON[i] for i in candidate.issues if i in ISSUE_TO_REASON)),
                              "catalog_gate": candidate.gate or candidate.policy}
    for row in rows.values():
        candidate, _ = audit.candidate_from_ledger_row(row)
        groups = [W.category(row)]
        if candidate.queue == audit.QUEUE_PEPTIDE:
            groups.append("gray")
        if row["class"] != "food" and ("focus" in candidate.issues or row["class"] == "nootropic"):
            groups.append("nootropic")
        row["browse_categories"] = list(dict.fromkeys(groups))
        nutritional = nutrition.get(row["id"], {})
        row["resources"] = []
        if row["class"] == "food" and isinstance(nutritional.get("fdc_id"), int):
            row["resources"].append(W.resource(
                f"USDA FoodData Central {nutritional['fdc_id']}: {nutritional.get('usda_description', row['display_name'])}; "
                f"https://fdc.nal.usda.gov/food-details/{nutritional['fdc_id']}/nutrients . Composition resource, not proof of a health outcome.", "nutrition"))
    return list(rows.values())


def resources_for(row: dict, grade: dict) -> list[dict]:
    return [*row.get("resources", []), *(W.resource(str(source)) for source in grade.get("sources", []) if source)]


def planning_resources() -> list[dict]:
    return [W.resource(f"{name}: existing authored planning reference; inspect its assumptions, not a certainty rating.", "planning")
            for name in ("SCHEDULE_TIPS.md", "WEEK_OPERATING_PLAN.md", "food_serving_guidance.py") if (W.HERE / name).is_file()]


def ask_rationale(screen, label: str, sources: list[dict]) -> dict:
    if not sources:
        raise ValueError("No usable source/resource for this item. r refreshes research; unsupported items stay browsable, not weekly selections.")
    screen.erase()
    height, width = screen.getmaxyx()
    dashboard.put(screen, 0, "HARD REASON REQUIRED / " + label, curses.A_BOLD)
    dashboard.put(screen, 1, "Choose actual support; nutrition/planning resources do not prove treatment effects.")
    shown = sources[:max(1, height - 7)]
    for i, source in enumerate(shown, 1):
        dashboard.put(screen, i + 2, f"{i}. [{source['kind']}] {source['text']}")
    screen.refresh()
    index = int(dashboard.text_input(screen, "Supporting source number [1]", max_length=4) or "1") - 1
    if not 0 <= index < len(shown):
        raise ValueError("Select one of the displayed supporting resources.")
    goal = dashboard.text_input(screen, "What specific purpose does this support?", max_length=500)
    reason = dashboard.text_input(screen, "Why does that fit you, and what does the source actually support?", max_length=500)
    trigger = dashboard.text_input(screen, "When/what result would make you review or change this?", max_length=500)
    return W.rationale(goal, reason, trigger, shown[index], shown)


def item_detail(row: dict, grade: dict, week: dict) -> list[str]:
    gate = SP.candidate_gate(row)
    return [row["display_name"], f"Overall evidence screen: {grade['overall']} | For you: {grade['personal']}",
            "These are transparent screening grades, not medical certainty or clearance.", "",
            "OVERALL: " + grade["why"], "FOR YOU: " + grade["personal_why"],
            f"Coverage: {grade['coverage']} | direction: {grade['direction']} | {grade['updated_at']}",
            "", "YOUR CHOICES",
            f"This week: {'selected' if row['id'] in week['selected'] else 'not selected'}; ledger decision: {row['user_decision']}; actual use: {row['use_status']}",
            "User-recorded dose: " + (row.get("user_dose") or "not recorded; no amount inferred"),
            "Recorded reason(s): " + (", ".join(row.get("reasons", [])) or "none"),
            "Weekly justification: " + json.dumps(week["selected"].get(row["id"], {}).get("rationale") or "NEEDS HARD REASON; press j to justify", ensure_ascii=True),
            "", "REVIEW / LIMITATIONS",
            "Catalog: " + (row.get("catalog_gate") or "No catalog gate recorded; not proof of safety."),
            "Admission screen: " + (", ".join(gate["reasons"]) or "no restriction found by this limited screen"),
            "Selection stays visible even when routine use requires review. Selection never records ingestion or authorizes a protocol.",
            "", "WHY CHANGE?",
            "Reconsider if your goals, tolerance, recovery, medications, constraints, or source evidence change. Change one controllable variable when practical and record your reason.",
            "", "SOURCES", *(grade["sources"] or ["No source trail in this cache. Use r to retrieve and grade this item."]),
            "", "RECORDED ROUTINE / REVIEW NOTE", json.dumps(week["item_routines"].get(row["id"], {}), ensure_ascii=True)]


def build_meals(week: dict, rows: list[dict], intake: dict, report: Path, start: str, research: dict | None = None) -> dict:
    import weekly_food_plan as food_plan
    import supplement_audit as audit

    result = copy.deepcopy(week)
    by_id = {row["id"]: row for row in rows}
    food_rows, withheld = [], []
    for item_id, selection in week["selected"].items():
        if selection["category"] != "food":
            continue
        try:
            W.validate_rationale(selection.get("rationale"))
        except ValueError:
            withheld.append(selection["name"] + ": needs a source-linked hard reason before meal allocation")
            continue
        row = by_id.get(item_id)
        if row is None:
            withheld.append(selection["name"] + ": no longer present in the catalog/ledger")
            continue
        record = (research or {}).get(item_id, {})
        gate = audit.candidate_plan_gate(row, rows, {"direction": "harm"} if record.get("direction") == "harm" else None)
        if not gate["active_plan_allowed"]:
            withheld.append(row["display_name"] + ": " + ", ".join(gate["reasons"]))
            continue
        # A new explicit food selection is planning intent; do not mutate ledger/use facts.
        planning_reasons = row.get("reasons") or [goal for goal in intake.get("goals", []) if goal in row.get("catalog_reasons", [])]
        food_rows.append({**row, "consideration_scope": "personal_candidate", "reasons": planning_reasons})
    plan = food_plan.plan_week(food_rows, intake, report)
    meals, notices = W.distribute_meals(plan, start)
    result["meals"] = meals
    result["meal_basis"] = W.meal_basis(week, intake)
    result["allocation"] = {"targets": plan["targets"], "notices": [*withheld, *notices],
                             "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    return result


def refresh_item(row: dict, ledger: dict, state_path: Path) -> dict:
    import coach
    import lancedb
    import supplement_audit as audit
    from sentence_transformers import SentenceTransformer
    from candidate_manager import _tally_sources, _letter_from_tally

    print("Refreshing local evidence for " + row["display_name"] + ". This can take a moment; no plan or actual-use change is made.")
    candidate, _ = audit.candidate_from_ledger_row(row)
    emb = SentenceTransformer(coach.EMB_MODEL, device="mps")
    table = lancedb.connect(coach.DBDIR).open_table(coach.TABLE)
    evidence = audit.retrieve_candidate(table, emb, coach.load_reranker(), candidate,
                                        [audit.ISSUES.get(i, i) for i in candidate.issues])
    tally = _tally_sources(evidence, (candidate.name, *candidate.aliases))
    overall, why = _letter_from_tally(tally, evidence.coverage, is_food=row["class"] == "food")
    record = {"overall_grade": overall if evidence.hits else "?", "grade_why": why,
              "coverage": evidence.coverage, "direction": audit.evidence_direction(evidence),
              "sources": coach.EC.source_lines(evidence.hits),
              "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    W.save_research(row["id"], record, state_path)
    return record


def run_ui(args, rows: list[dict], ledger: dict, profile: dict, food_records: dict) -> int:
    data = W.load(args.state)
    start = W.monday(args.week)
    previous = copy.deepcopy(data["weeks"].get(start))
    week = copy.deepcopy(previous) if previous is not None else W.seed_week(start, rows, profile)
    baseline = copy.deepcopy(week)
    row_map = {row["id"]: row for row in rows}
    research = data["research"]

    def run(screen):
        nonlocal week, previous, baseline, start, research
        screen.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        view = args.view
        cursor = scroll = 0
        query = ""
        selected_only = False
        sort_personal = True
        message = "Space chooses for this week. s saves with your reason; nothing changes actual use."
        details = None
        while True:
            height, width = screen.getmaxyx()
            screen.erase()
            if width < 60 or height < 20:
                dashboard.put(screen, 0, "Resize to at least 60 columns x 20 rows. q returns.")
                screen.refresh()
                if screen.getch() in (ord("q"), 27):
                    return
                continue
            dirty = week != baseline
            dashboard.put(screen, 0, f"YOUR WEEK {start} / {'UNSAVED EDITS' if dirty else 'SAVED' if previous is not None else 'DRAFT FROM EXISTING CHOICES'}", curses.A_BOLD)
            tabs = " ".join(f"{'[' if key == view else ''}{i} {label}{']' if key == view else ''}" for i, (key, label) in enumerate(VIEWS.items(), 1))
            wrapped = textwrap.wrap(tabs, width - 1)
            for y, line in enumerate(wrapped, 2):
                dashboard.put(screen, y, line, curses.A_BOLD)
            top = len(wrapped) + 3
            dashboard.put(screen, top, "1-9 areas | [ ] week | / search | p picked | o sort | i goals | s save | q back")
            top += 2
            available = max(1, height - top - 4)
            entries, lines = [], []
            scored = {row["id"]: W.grades(row, ledger["intake"], food_records.get(row["id"]), research.get(row["id"])) for row in rows}
            if details is not None:
                lines = details + ["", "Esc / Enter returns to your choices."]
            elif view in W.CATEGORIES:
                entries = [row for row in rows if view in row.get("browse_categories", [W.category(row)]) and
                           (not selected_only or row["id"] in week["selected"]) and
                           query.lower() in (row["display_name"] + " " + " ".join(row.get("aliases", []))).lower()]
                def order(row):
                    value = scored[row["id"]]["personal" if sort_personal else "overall"]
                    return (row["id"] not in week["selected"], -W.LETTERS.index(value[0]) if value[0] in W.LETTERS else 1, row["display_name"])
                entries.sort(key=order)
                dashboard.put(screen, top - 1, "Space select | j justify | Enter why/sources | r research | e routine/note", curses.A_DIM)
                if entries:
                    cursor %= len(entries)
                    begin = max(0, min(cursor - available // 2, len(entries) - available))
                    for i in range(begin, min(len(entries), begin + available)):
                        row = entries[i]
                        grade = scored[row["id"]]
                        selected = week["selected"].get(row["id"])
                        marker = "x" if selected and selected.get("rationale") else "?" if selected else " "
                        review = " review" if not SP.candidate_gate(row)["active_plan_allowed"] else ""
                        label = f"[{marker}] {row['display_name'][:max(15, width - 44)]:<{max(15, width - 44)}} All {grade['overall']:>2}  You {grade['personal']:>2}  {grade['coverage']}{review}"
                        dashboard.put(screen, top + i - begin, label, curses.A_REVERSE if i == cursor else 0)
                else:
                    lines = ["No matching items. / clears search; p toggles selected-only."]
            elif view == "meals":
                dashboard.put(screen, top - 1, "b build | c meal times | e move/resize portion | Enter why | Up/Down", curses.A_DIM)
                entries = sorted(week["meals"], key=lambda m: (m["date"], W.SLOTS.index(m["slot"]), m.get("name", m["food_id"])))
                if entries:
                    cursor %= len(entries)
                    begin = max(0, min(cursor - available // 2, len(entries) - available))
                    for i in range(begin, min(len(entries), begin + available)):
                        meal = entries[i]
                        time = week["meal_times"][meal["slot"]] or "--:--"
                        label = f"{meal['date'][5:]} {time} {meal['slot'][:6]:<6} {meal.get('name', meal['food_id'])} x{meal['servings']:g}"
                        dashboard.put(screen, top + i - begin, label, curses.A_REVERSE if i == cursor else 0)
                else:
                    lines = ["Choose foods in 2 Foods, then press b here to construct the week.",
                             "A selected food does not need to be marked already eaten to plan it.",
                             "Meal slots are practical placements; clock times are yours to set."]
                if week["meal_basis"] and week["meal_basis"] != W.meal_basis(week, ledger["intake"]):
                    message = "MEALS NEED REBUILD: food choices or personal context changed. Press b to preview a replacement."
            elif view == "training":
                dashboard.put(screen, top - 1, "e edit day | t set weekly step target | Enter why/constraints | Up/Down", curses.A_DIM)
                entries = W.dates(start)
                cursor %= 7
                for i, date in enumerate(entries[:available]):
                    workout = week["workouts"].get(date, {})
                    label = f"{date[5:]} {workout.get('time') or '--:--'} steps {workout.get('steps_target', 10000):,} | {workout.get('session', 'not set')}"
                    dashboard.put(screen, top + i, label, curses.A_REVERSE if i == cursor else 0)
            elif view == "changes":
                lines = ["WHY THIS WEEK CHANGED", "Only explicit saves create history; research refreshes never adjust your plan."]
                for entry in reversed(week["history"]):
                    lines.extend(["", f"{entry['at']}: {entry['reason']}"])
                    for change in entry["changes"]:
                        lines.extend(W.change_summary(change))
                if not week["history"]:
                    lines.append("No saved changes for this week yet.")
            else:
                lines = W.overview(week, start, dt.date.today().isoformat() if dt.date.today().isoformat() in W.dates(start) else W.dates(start)[0], ledger["intake"])
                lines.extend(["", "SELECTED GRADES / overall evidence screen vs fit to your goals"])
                for item_id, item in week["selected"].items():
                    grade = scored.get(item_id, {"overall": "?", "personal": "?"})
                    lines.append(f"{item['name']}: overall {grade['overall']} / for you {grade['personal']}")
                if week["allocation"]:
                    totals = week["allocation"]["targets"]
                    lines.append(f"Weekly target estimates: {totals.get('weekly_kcal')} kcal; {totals.get('weekly_protein_g')} g protein.")
                    lines.append(f"Actually placed: {sum(m['kcal'] for m in week['meals']):.0f} kcal; {sum(m['protein_g'] for m in week['meals']):.0f} g protein.")
                    lines.extend("UNPLACED / REVIEW: " + notice for notice in week["allocation"]["notices"])
                lines.extend(["", "10,000 steps is your requested starting target, not a universal medical requirement.",
                              "Grades are screening heuristics. Gray-market selection remains visible; routine use may still require review."])
            if lines:
                rendered = [part for line in lines for part in (textwrap.wrap(dashboard.T.display_text(line), width - 1) or [""])]
                scroll = max(0, min(scroll, max(0, len(rendered) - available)))
                for y, line in enumerate(rendered[scroll:scroll + available], top):
                    dashboard.put(screen, y, line)
            dashboard.put(screen, height - 3, "PgUp/PgDn details | u discard | x export | j justify | choices != actual use", curses.A_DIM)
            for y, line in enumerate(textwrap.wrap(message, width - 1)[:2], height - 2):
                dashboard.put(screen, y, line, curses.A_BOLD)
            screen.refresh()
            key = screen.getch()
            try:
                if details is not None:
                    if key in (27, 10, 13, ord("q")):
                        details, scroll = None, 0
                    elif key in (curses.KEY_DOWN, curses.KEY_NPAGE):
                        scroll += max(1, available // 2)
                    elif key in (curses.KEY_UP, curses.KEY_PPAGE):
                        scroll -= max(1, available // 2)
                    continue
                if key in (ord("q"), 27):
                    if not dirty or dashboard.text_input(screen, "Type DISCARD to leave unsaved edits", max_length=12) == "DISCARD":
                        return
                elif ord("1") <= key <= ord("9"):
                    view = list(VIEWS)[key - ord("1")]
                    cursor = scroll = 0
                    query = ""
                elif key in (ord("["), ord("]")):
                    if dirty:
                        message = "Save or discard this draft before changing weeks."
                    else:
                        start = (dt.date.fromisoformat(start) + dt.timedelta(days=-7 if key == ord("[") else 7)).isoformat()
                        data = W.load(args.state)
                        previous = copy.deepcopy(data["weeks"].get(start))
                        week = copy.deepcopy(previous) if previous is not None else W.seed_week(start, rows, profile)
                        baseline = copy.deepcopy(week)
                        cursor = scroll = 0
                elif key in (curses.KEY_UP, curses.KEY_DOWN):
                    cursor += -1 if key == curses.KEY_UP else 1
                elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
                    scroll += (-1 if key == curses.KEY_PPAGE else 1) * max(1, available // 2)
                elif key == ord("/"):
                    query = dashboard.text_input(screen, "Find name or alias", max_length=80)
                    cursor = 0
                elif key == ord("p"):
                    selected_only = not selected_only
                    cursor = 0
                elif key == ord("o"):
                    sort_personal = not sort_personal
                    message = "Sorted by " + ("personal fit" if sort_personal else "overall evidence") + "; your selected items stay first."
                elif key == ord("u"):
                    if dashboard.text_input(screen, "Type DISCARD to revert this draft", max_length=12) == "DISCARD":
                        week = copy.deepcopy(baseline)
                        message = "Unsaved edits discarded. Saved history unchanged."
                elif key == ord("s"):
                    reason = dashboard.text_input(screen, "Why save these weekly changes?", max_length=500)
                    if reason and dashboard.text_input(screen, "Type SAVE to commit this week", max_length=8) == "SAVE":
                        week = W.save(start, week, previous, reason, args.state)
                        previous = copy.deepcopy(week)
                        baseline = copy.deepcopy(week)
                        message = "Week saved with your reason. Actual use, daily logs, and Bevel records unchanged."
                elif key == ord("i"):
                    if dirty:
                        message = "Save/discard the weekly draft before updating goals and biometrics."
                        continue
                    curses.def_prog_mode()
                    curses.endwin()
                    try:
                        subprocess.run([sys.executable, str(W.HERE / "candidate_manager.py"), "--ledger", str(CL.ledger_path(args.ledger)), "intake"], cwd=W.HERE)
                        ledger.update(CL.load_ledger(args.ledger))
                        rows[:] = catalog_rows(ledger)
                        row_map.clear()
                        row_map.update({row["id"]: row for row in rows})
                    finally:
                        curses.reset_prog_mode()
                        screen.refresh()
                    message = "Context reloaded. Grades reflect current goals; meal plans may need rebuilding."
                elif key == ord(" ") and view in W.CATEGORIES and entries:
                    row = entries[cursor % len(entries)]
                    if row["id"] in week["selected"]:
                        del week["selected"][row["id"]]
                    else:
                        basis = ask_rationale(screen, row["display_name"], resources_for(row, scored[row["id"]]))
                        week["selected"][row["id"]] = {**W.selection(row), "rationale": basis}
                    message = "Draft selection changed. s saves with a reason; b in Meals rebuilds food placement."
                elif key == ord("j") and view in W.CATEGORIES and entries:
                    row = entries[cursor % len(entries)]
                    if row["id"] not in week["selected"]:
                        raise ValueError("Select the item first, or use Space to select it with a hard reason.")
                    basis = ask_rationale(screen, row["display_name"], resources_for(row, scored[row["id"]]))
                    week["selected"][row["id"]]["rationale"] = basis
                    message = "Source-linked justification recorded in draft. s saves."
                elif key == ord("j") and view in {"training", "meals"}:
                    field = "workouts" if view == "training" else "meals"
                    week.setdefault("justifications", {})[field] = ask_rationale(screen, "Review this " + view + " plan", planning_resources())
                    message = "Supporting resource and hard reason recorded in draft. s saves."
                elif key == ord("x"):
                    if dirty or previous is None:
                        message = "Save a justified week before exporting it here, or use e Export on the home dashboard for a labelled draft."
                        continue
                    curses.def_prog_mode()
                    curses.endwin()
                    try:
                        subprocess.run([sys.executable, str(W.HERE / "plan_export.py"), "--week", start, "--state", str(args.state),
                                        "--ledger", str(CL.ledger_path(args.ledger)), "--report", str(args.report)], cwd=W.HERE)
                        input("Press Enter to return to the weekly workspace.")
                    finally:
                        curses.reset_prog_mode()
                        screen.refresh()
                elif key in (10, 13) and entries:
                    entry = entries[cursor % len(entries)]
                    if view in W.CATEGORIES:
                        details = item_detail(entry, scored[entry["id"]], week)
                    elif view == "meals":
                        details = [entry.get("name", entry["food_id"]), entry["reason"], entry["portion"],
                                   f"{entry['servings']:g} portions; {entry['kcal']:g} kcal; {entry['protein_g']:g} g protein.",
                                   "Changing date/slot is a practical choice for your schedule; no claim that this timing improves the study outcome.",
                                   *scored.get(entry["food_id"], {}).get("sources", [])]
                    elif view == "training":
                        workout = week["workouts"].get(entry, {})
                        details = [entry, workout.get("session", "not set"), "Saved constraint: " + workout.get("constraint", "unknown"),
                                   "Adjust for availability, pain, illness, recovery, or preference. Do not automatically make up missed hard sessions.",
                                   "A step target is a plan, not measured steps. Log completed steps separately."]
                    scroll = 0
                elif key == ord("b") and view in {"food", "meals"}:
                    if week["meals"] and dashboard.text_input(screen, "Type REBUILD to replace draft meal placements", max_length=12) != "REBUILD":
                        continue
                    basis = ask_rationale(screen, "Meal construction", planning_resources())
                    week = build_meals(week, rows, ledger["intake"], args.report, start, research)
                    week.setdefault("justifications", {})["meals"] = basis
                    view, cursor, scroll = "meals", 0, 0
                    notices = week["allocation"]["notices"]
                    message = f"Built {len(week['meals'])} portion placements; {len(notices)} notices. 1 Week shows targets and anything unplaced; s saves."
                elif key == ord("c") and view == "meals":
                    proposed = copy.deepcopy(week["meal_times"])
                    for slot in W.SLOTS:
                        value = dashboard.text_input(screen, f"{slot} HH:MM, ? unset, blank keep [{proposed[slot] or 'unset'}]", max_length=8)
                        if value:
                            proposed[slot] = None if value == "?" else value
                        if not W.clock(proposed[slot]):
                            raise ValueError("Use a valid 24-hour HH:MM clock time.")
                    basis = ask_rationale(screen, "Meal times", planning_resources())
                    week["meal_times"] = proposed
                    week.setdefault("justifications", {})["meal_times"] = basis
                elif key == ord("t") and view == "training":
                    value = int(dashboard.text_input(screen, "Steps target for all seven days (0-50000)", max_length=6))
                    proposed = copy.deepcopy(week)
                    for date in W.dates(start):
                        proposed["workouts"].setdefault(date, {"session": "Not set", "time": None, "minutes": None})["steps_target"] = value
                        proposed["workouts"][date]["origin"] = "USER_PLANNED"
                    proposed.setdefault("justifications", {})["workouts"] = ask_rationale(screen, "Weekly step target", planning_resources())
                    for workout in proposed["workouts"].values():
                        workout["rationale"] = copy.deepcopy(proposed["justifications"]["workouts"])
                    W.validate_week(start, proposed)
                    week = proposed
                elif key == ord("e") and entries:
                    entry = entries[cursor % len(entries)]
                    proposed = copy.deepcopy(week)
                    if view == "training":
                        workout = copy.deepcopy(week["workouts"].get(entry, {"session": "Not set", "time": None, "minutes": None, "steps_target": 10000}))
                        for field, label in (("session", "Session or rest"), ("time", "Start HH:MM (? unset)"), ("minutes", "Minutes (? unset)"), ("steps_target", "Steps target")):
                            value = dashboard.text_input(screen, f"{label} [{workout.get(field) or 'unset'}] blank keeps", max_length=180)
                            if value:
                                workout[field] = None if value == "?" and field in {"time", "minutes"} else int(value) if field in {"minutes", "steps_target"} else value
                        workout["origin"] = "USER_PLANNED"
                        proposed["workouts"][entry] = workout
                        proposed.setdefault("justifications", {})["workouts"] = ask_rationale(screen, "Workout / steps edit", planning_resources())
                        workout["rationale"] = copy.deepcopy(proposed["justifications"]["workouts"])
                        warning = SP.urgent_message(workout["session"])
                        if warning:
                            details = [warning]
                        message = "Workout edited in draft; saved constraints remain visible. Save with your reason."
                    elif view == "meals":
                        if week["meal_basis"] != W.meal_basis(week, ledger["intake"]):
                            raise ValueError("Rebuild stale meals before editing portions.")
                        index = week["meals"].index(entry)
                        date = dashboard.text_input(screen, f"Move to date YYYY-MM-DD [{entry['date']}]", max_length=10) or entry["date"]
                        slot = dashboard.text_input(screen, f"Meal slot {', '.join(W.SLOTS)} [{entry['slot']}]", max_length=12).title() or entry["slot"]
                        amount = float(dashboard.text_input(screen, f"Portions [{entry['servings']:g}], 0 removes this portion", max_length=12) or str(entry["servings"]))
                        if amount == 0:
                            proposed["meals"].pop(index)
                        else:
                            ratio = amount / entry["servings"]
                            proposed["meals"][index] = {**entry, "date": date, "slot": slot, "servings": amount,
                                                       "kcal": round(entry["kcal"] * ratio, 2), "protein_g": round(entry["protein_g"] * ratio, 2),
                                                       "reason": "User changed this portion for the saved change reason. Nutrition scaled from the same planning portion."}
                        proposed.setdefault("justifications", {})["meals"] = ask_rationale(screen, "Meal portion edit", planning_resources())
                        if amount != 0:
                            proposed["meals"][index]["rationale"] = copy.deepcopy(proposed["justifications"]["meals"])
                    elif view in W.CATEGORIES:
                        if entry["id"] not in week["selected"]:
                            raise ValueError("Select the item for this week first.")
                        label = "Existing routine in your own words (not new instructions)" if entry["use_status"] == "in_use" else "Research/review note (not a use protocol)"
                        text = dashboard.text_input(screen, label, max_length=500)
                        day_numbers = dashboard.text_input(screen, "Days 1=Mon to 7=Sun, comma-separated; blank = review Monday", max_length=30) or "1"
                        numbers = [int(n.strip()) for n in day_numbers.split(",")]
                        if any(n < 1 or n > 7 for n in numbers):
                            raise ValueError("Days must be numbers from 1 to 7.")
                        selected_days = [W.dates(start)[n - 1] for n in numbers]
                        if not text or not selected_days:
                            raise ValueError("A note/routine and valid day selection are required.")
                        proposed["item_routines"][entry["id"]] = {"text": text, "dates": list(dict.fromkeys(selected_days)),
                                                                  "kind": "USER_REPORTED_ROUTINE" if entry["use_status"] == "in_use" else "RESEARCH_REVIEW_NOTE"}
                        proposed.setdefault("justifications", {})["item_routines"] = ask_rationale(screen, "Routine/review-note change", resources_for(entry, scored[entry["id"]]))
                        proposed["item_routines"][entry["id"]]["rationale"] = copy.deepcopy(proposed["justifications"]["item_routines"])
                        warning = SP.urgent_message(text)
                        if warning:
                            details = [warning]
                    W.validate_week(start, proposed)
                    week = proposed
                elif key == ord("r") and view in W.CATEGORIES and entries:
                    row = entries[cursor % len(entries)]
                    curses.def_prog_mode()
                    curses.endwin()
                    try:
                        research[row["id"]] = refresh_item(row, ledger, args.state)
                    finally:
                        curses.reset_prog_mode()
                        screen.refresh()
                    message = "Evidence refreshed; week selection and routines unchanged. Enter shows source trail."
            except (ValueError, OSError, KeyError, RuntimeError) as exc:
                message = str(exc)

    curses.wrapper(run)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=tuple(VIEWS), default="overview")
    parser.add_argument("--week", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--state", type=Path, default=W.DEFAULT_PATH)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--report", type=Path, default=W.HERE / "HEALTHCOACH_REPORT.md")
    parser.add_argument("--print", action="store_true", dest="print_only")
    args = parser.parse_args(argv)
    try:
        import supplement_audit as audit
        import weekly_food_plan as food_plan
        ledger = CL.load_ledger(args.ledger)
        profile = audit.load_saved_profile(args.report) or {}
        if not profile.get("calendar_snapshot") and profile.get("calendar_lock_version") == "HC_CALENDAR_V1":
            profile["calendar_snapshot"] = {day: {"placement": audit.calendar_mode_detail(day, mode)[0], "status": audit.calendar_mode_detail(day, mode)[1]}
                                            for day, mode in profile.get("calendar_modes", {}).items()
                                            if day in audit.CALENDAR_DAYS and mode in dict(audit.CALENDAR_MODE_OPTIONS)}
        rows = catalog_rows(ledger)
        if args.print_only:
            start = W.monday(args.week)
            week = W.load(args.state)["weeks"].get(start) or W.seed_week(start, rows, profile)
            print("\n".join(W.overview(week, start, args.week.isoformat(), ledger["intake"])))
            return 0
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("Use an interactive terminal, or pass --print for a read-only weekly overview.")
            return 2
        return run_ui(args, rows, ledger, profile, food_plan._load_food_evidence())
    except (ValueError, OSError, KeyboardInterrupt) as exc:
        print(f"Weekly workspace closed without an automatic save: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

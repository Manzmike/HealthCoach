#!/usr/bin/env python3
"""Pick specific bodily symptoms (dry scalp, stiff leg muscles, poor sleep, ...) and get real,
already-sourced recommendations — not a new evidence system. Every symptom maps to one or more
of the 11 issue tags already used throughout this app (supplement_audit.ISSUES); everything
this module surfaces is data that already exists and is already graded:

  - Foods: real letter grade + sourced good/bad bullets from food_evidence.json, for every
    catalog food whose static `issues` tag matches the symptom.
  - Supplements: your own cached grading from the last time you ran `rank`/`triage`/an
    assessment (ledger row last_coverage/last_suggestion) — real, just not re-computed live.
  - Lifestyle: a pointer to the specific existing guidance section already in this repo
    (SCHEDULE_TIPS.md) that's relevant — never invented advice untethered from something real.

Hard warning = a real strong-harm signal (grade F). Soft ban = evidence leans negative (grade
D+/D/C-) without rising to a forced-F harm signal. Both are advisory framing on top of the SAME
grade you'd see in `rank` — this module doesn't invent a new severity scale.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  python3 symptom_checkin.py
"""
from __future__ import annotations

import curses
import json
from pathlib import Path
from typing import Any

import candidate_ledger as CL
import supplement_audit as audit
import safety_policy as SP

HERE = Path(__file__).resolve().parent
FOOD_EVIDENCE_PATH = HERE / "food_evidence.json"
OUT_SHORT = HERE / "SYMPTOM_CHECKIN_SHORT.md"
OUT_DEEP = HERE / "SYMPTOM_CHECKIN_DEEP.md"

# issue tag -> the specific SCHEDULE_TIPS.md section that already covers it, real pointer not
# invented advice. Tags with no matching section (gi, immune, deficiency) are left unmapped —
# there's genuinely nothing there to point to yet, and an honest "no lifestyle note on file" is
# better than a fabricated one.
LIFESTYLE_POINTER: dict[str, str] = {
    "sleep": "SCHEDULE_TIPS.md — \"Nightly sleep need\"",
    "stress": "SCHEDULE_TIPS.md — \"Caffeine cut-off time\" (a common hidden stress/sleep driver)",
    "endurance": "SCHEDULE_TIPS.md — \"Zone 2 (easy aerobic base)\"",
    "strength": "SCHEDULE_TIPS.md — \"RPE and reps-in-reserve (RIR)\"",
    "cut": "SCHEDULE_TIPS.md — \"Calories: maintenance (TDEE) and deficit\"",
    "heart": "SCHEDULE_TIPS.md — \"Calories: maintenance (TDEE) and deficit\" (weight/cardiometabolic link)",
    "joints": "SCHEDULE_TIPS.md — \"RPE and reps-in-reserve (RIR)\" (training load vs. recovery)",
}

# symptom label -> (body-area group, issue tags it maps to). Multiple symptoms can share an
# issue tag; a symptom can map to more than one tag (e.g. fatigue touches sleep AND deficiency).
# Every tag here MUST be one of the 11 real keys in supplement_audit.ISSUES — that's the only
# vocabulary any catalog item's `issues` tuple can actually contain, so a symptom mapped to
# anything else would silently match nothing. The symptom list is deliberately much larger than
# that 11-tag vocabulary: it's the specific, plain-language front door people actually recognize
# their own complaints through ("dry scalp," not "skin issue") — many symptoms legitimately
# route to the same underlying evidence bucket, and that's fine.
SYMPTOMS: dict[str, tuple[str, tuple[str, ...]]] = {
    # ---- Skin & Hair (skin, deficiency, immune) ----
    "Dry / flaky scalp": ("Skin & Hair", ("skin", "deficiency")),
    "Dandruff": ("Skin & Hair", ("skin",)),
    "Thinning hair / hair loss": ("Skin & Hair", ("skin", "deficiency")),
    "Hair breakage / brittle hair": ("Skin & Hair", ("skin", "deficiency")),
    "Premature graying": ("Skin & Hair", ("skin", "deficiency")),
    "Brittle / ridged nails": ("Skin & Hair", ("skin", "deficiency")),
    "Dry or itchy skin": ("Skin & Hair", ("skin", "deficiency")),
    "Acne / breakouts": ("Skin & Hair", ("skin",)),
    "Eczema flare-ups": ("Skin & Hair", ("skin", "immune")),
    "Rosacea / facial redness": ("Skin & Hair", ("skin",)),
    "Dull / uneven skin tone": ("Skin & Hair", ("skin", "deficiency")),
    "Cracked heels or lips": ("Skin & Hair", ("skin", "deficiency")),
    "Easy bruising": ("Skin & Hair", ("skin", "deficiency")),
    "Slow wound healing": ("Skin & Hair", ("skin", "deficiency", "immune")),

    # ---- Muscles & Joints (joints, strength, endurance) ----
    "Stiff / sore leg muscles": ("Muscles & Joints", ("joints", "strength")),
    "Joint pain or stiffness": ("Muscles & Joints", ("joints",)),
    "Lower back pain": ("Muscles & Joints", ("joints", "strength")),
    "Neck / shoulder tension": ("Muscles & Joints", ("joints", "stress")),
    "Frequent muscle cramps": ("Muscles & Joints", ("joints", "deficiency")),
    "Restless legs": ("Muscles & Joints", ("joints", "deficiency", "sleep")),
    "Muscle weakness": ("Muscles & Joints", ("strength", "deficiency")),
    "Reduced grip strength": ("Muscles & Joints", ("strength",)),
    "Slow recovery after training": ("Muscles & Joints", ("joints", "strength", "endurance")),
    "Soreness that won't resolve (DOMS lingering)": ("Muscles & Joints", ("joints", "strength")),
    "Tendon / connective tissue pain": ("Muscles & Joints", ("joints", "skin")),
    "Reduced range of motion": ("Muscles & Joints", ("joints",)),

    # ---- Digestion (gi) ----
    "Bloating": ("Digestion", ("gi",)),
    "Excess gas": ("Digestion", ("gi",)),
    "Constipation": ("Digestion", ("gi",)),
    "Diarrhea / loose stools": ("Digestion", ("gi",)),
    "Irregular bowel habits": ("Digestion", ("gi",)),
    "Nausea": ("Digestion", ("gi",)),
    "Heartburn / acid reflux": ("Digestion", ("gi",)),
    "Stomach cramps": ("Digestion", ("gi",)),
    "Indigestion after meals": ("Digestion", ("gi",)),
    "Suspected food intolerance": ("Digestion", ("gi", "immune")),

    # ---- Sleep & Energy (sleep, deficiency, cut) ----
    "Trouble falling asleep": ("Sleep & Energy", ("sleep",)),
    "Waking up during the night": ("Sleep & Energy", ("sleep",)),
    "Waking too early": ("Sleep & Energy", ("sleep",)),
    "Non-restorative sleep (tired even after 8h)": ("Sleep & Energy", ("sleep", "deficiency")),
    "Excessive daytime sleepiness": ("Sleep & Energy", ("sleep", "deficiency")),
    "Snoring": ("Sleep & Energy", ("sleep", "heart")),
    "Low energy / fatigue": ("Sleep & Energy", ("sleep", "deficiency", "cut")),
    "Afternoon energy crash": ("Sleep & Energy", ("sleep", "cut")),

    # ---- Mood & Cognition (stress, focus, sleep) ----
    "Anxiety / high stress": ("Mood & Cognition", ("stress",)),
    "Brain fog": ("Mood & Cognition", ("focus", "sleep")),
    "Poor concentration": ("Mood & Cognition", ("focus",)),
    "Memory lapses": ("Mood & Cognition", ("focus", "sleep")),
    "Low mood": ("Mood & Cognition", ("stress", "sleep")),
    "Irritability": ("Mood & Cognition", ("stress", "sleep")),
    "Mood swings": ("Mood & Cognition", ("stress", "sleep")),
    "Feeling overwhelmed / burnt out": ("Mood & Cognition", ("stress", "sleep")),
    "Loss of motivation": ("Mood & Cognition", ("stress", "sleep", "deficiency")),
    "Mental fatigue / can't think straight": ("Mood & Cognition", ("focus", "sleep", "deficiency")),

    # ---- Immune (immune, deficiency, gi) ----
    "Frequent colds / getting sick often": ("Immune", ("immune",)),
    "Slow recovery from illness": ("Immune", ("immune", "deficiency")),
    "Seasonal allergies": ("Immune", ("immune",)),
    "Frequent cold sores / cold-sore-prone": ("Immune", ("immune", "deficiency")),
    "Chronic low-grade inflammation feeling (achy, puffy)": ("Immune", ("immune", "gi")),

    # ---- Heart & Metabolic (heart, cut, deficiency) ----
    "High blood pressure": ("Heart & Metabolic", ("heart",)),
    "High cholesterol / lipids": ("Heart & Metabolic", ("heart",)),
    "Elevated resting heart rate": ("Heart & Metabolic", ("heart", "sleep")),
    "Poor circulation (cold hands/feet)": ("Heart & Metabolic", ("heart", "deficiency")),
    "Swelling / fluid retention (edema)": ("Heart & Metabolic", ("heart",)),
    "Stubborn body fat / plateaued fat loss": ("Heart & Metabolic", ("cut",)),
    "Blood sugar swings": ("Heart & Metabolic", ("cut", "heart")),
    "Unexplained weight gain": ("Heart & Metabolic", ("cut", "deficiency")),
    "Unexplained weight loss": ("Heart & Metabolic", ("deficiency", "gi")),

    # ---- Deficiency / other systemic (deficiency) ----
    "Suspected/known nutrient deficiency": ("Deficiency & Other", ("deficiency",)),
    "Numbness or tingling in hands/feet": ("Deficiency & Other", ("deficiency", "joints")),
    "Muscle twitching": ("Deficiency & Other", ("deficiency", "joints")),
    "Cold intolerance": ("Deficiency & Other", ("deficiency", "heart")),
    "Heat intolerance": ("Deficiency & Other", ("deficiency", "heart")),
    "Excessive thirst": ("Deficiency & Other", ("deficiency", "cut")),
    "Frequent urination": ("Deficiency & Other", ("deficiency", "cut")),
    "Bone / joint aches (possible vitamin D concern)": ("Deficiency & Other", ("deficiency", "joints")),
}


def _load_food_evidence() -> dict[str, Any]:
    if not FOOD_EVIDENCE_PATH.exists():
        return {}
    return json.loads(FOOD_EVIDENCE_PATH.read_text())


_GRADE_BUCKET_ORDER = ("A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F")


def _is_positive_grade(letter: str) -> bool:
    return letter in ("A+", "A", "A-", "B+", "B")


def _is_negative_grade(letter: str) -> bool:
    return letter in ("D+", "D", "D-", "C-")


def issue_matches(catalog_key: str, tag_set: frozenset[str], catalog: tuple[audit.Candidate, ...]) -> bool:
    candidate = next((c for c in catalog if c.key == catalog_key), None)
    return bool(candidate and set(candidate.issues) & tag_set)


def foods_for_tags(tags: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    """{'positive': [...], 'negative': [...], 'hard_warning': [...]} — real foods from
    food_evidence.json whose static issues tag matches, bucketed by their real computed grade."""
    tag_set = frozenset(tags)
    evidence = _load_food_evidence()
    buckets: dict[str, list[dict[str, Any]]] = {"positive": [], "negative": [], "hard_warning": []}
    for candidate in audit.WHOLE_FOOD_CATALOG:
        if not set(candidate.issues) & tag_set:
            continue
        rec = evidence.get(candidate.key)
        if not rec:
            continue
        entry = {"key": candidate.key, "name": candidate.name, "grade": rec["grade"],
                  "grade_why": rec["grade_why"], "good": rec["good"], "bad": rec["bad"]}
        if rec["grade"] == "F":
            buckets["hard_warning"].append(entry)
        elif _is_negative_grade(rec["grade"]):
            buckets["negative"].append(entry)
        elif _is_positive_grade(rec["grade"]):
            buckets["positive"].append(entry)
    for key in buckets:
        buckets[key].sort(key=lambda e: _GRADE_BUCKET_ORDER.index(e["grade"]) if e["grade"] in _GRADE_BUCKET_ORDER else 99)
    return buckets


def supplements_for_tags(tags: tuple[str, ...], ledger: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Same bucketing, but from your own cached last-graded suggestion (last_coverage /
    last_suggestion on the ledger row) rather than a fresh grade — real, just not re-run live."""
    tag_set = frozenset(tags)
    candidates = {candidate.key: candidate for candidate in (*audit.CATALOG, *audit.PEPTIDE_CATALOG)}
    rows_by_id = {row["id"]: row for row in ledger["candidates"]}
    for row in ledger["candidates"]:
        if row.get("class") != "food":
            candidates[row["id"]] = audit.candidate_from_ledger_row(row)[0]
    buckets: dict[str, list[dict[str, Any]]] = {
        "positive": [], "negative": [], "hard_warning": [], "not_evaluated": [], "research_review": [],
    }
    for candidate in candidates.values():
        row = rows_by_id.get(candidate.key)
        tags_for_row = set(candidate.issues)
        if row:
            tags_for_row.update(tag for reason in row.get("reasons", ())
                                for tag in audit.REASON_LEGACY_MATCHES.get(reason, ()))
        if not tags_for_row & tag_set:
            continue
        entry = {"key": candidate.key, "name": candidate.name}
        if row:
            entry["use_status"] = row["use_status"]
            entry["user_dose"] = row.get("user_dose")
        fits = row.get("reason_evaluations", {}).values() if row else ()
        harm = bool(row and row.get("observed") == "harms") or any(
            fit.get("direction") == "harm" for fit in fits if isinstance(fit, dict)
        )
        gate = audit.candidate_plan_gate(row or {
            "id": candidate.key, "display_name": candidate.name,
            "class": audit.default_ledger_class(candidate),
        }, ledger["candidates"], {"direction": "harm" if harm else "unknown"})
        entry["suggestion"] = row.get("last_suggestion") or "NOT_EVALUATED" if row else "NOT_EVALUATED"
        entry["coverage"] = row.get("last_coverage") or "NONE" if row else "NONE"
        entry["why"] = row.get("last_suggestion_reason", "") if row else ""
        if harm:
            entry["why"] = "Reported or cached retrieved harm signal; clinician/pharmacist review, no automatic cessation. " + entry["why"]
            buckets["hard_warning"].append(entry)
            continue
        if not gate["active_plan_allowed"]:
            entry["note"] = "Routine plan admission withheld: " + ", ".join(gate["reasons"]) + ". Research remains available."
            buckets["research_review"].append(entry)
            continue
        if not row or not row.get("last_suggestion"):
            entry["note"] = "not yet evaluated — run an assessment or `rank`/`triage` to grade it"
            buckets["not_evaluated"].append(entry)
            continue
        entry["suggestion"] = row["last_suggestion"]
        entry["coverage"] = row["last_coverage"]
        entry["why"] = row.get("last_suggestion_reason", "")
        if row["last_suggestion"] in ("UNFAVORABLE", "CONDITIONAL"):
            entry["note"] = "Cached suggestion requires review; this alone does not establish harm or negative evidence."
            buckets["research_review"].append(entry)
        elif row["last_suggestion"] in ("CONTINUE_CURRENT", "ADOPT_CANDIDATE"):
            buckets["positive"].append(entry)
        else:
            entry["note"] = f"coverage {row['last_coverage']}: {row.get('last_suggestion_reason', 'not enough evidence yet either way')}"
            buckets["not_evaluated"].append(entry)
    return buckets


def build_report(selected: list[str]) -> dict[str, Any]:
    ledger = None
    sections = []
    for label in selected:
        warning = SP.urgent_message(label)
        if warning:
            sections.append({"symptom": label, "urgent": warning})
            continue
        if ledger is None:
            ledger = CL.load_ledger()
        _group, tags = SYMPTOMS[label]
        foods = foods_for_tags(tags)
        supplements = supplements_for_tags(tags, ledger)
        lifestyle = sorted({LIFESTYLE_POINTER[t] for t in tags if t in LIFESTYLE_POINTER})
        sections.append({
            "symptom": label, "tags": tags, "foods": foods, "supplements": supplements,
            "lifestyle": lifestyle,
        })
    return {"sections": sections}


def render_short(report: dict[str, Any]) -> str:
    lines = ["# Symptom check-in — quick view", "", "Issue-tag matches and cached evidence are not a diagnosis or medical clearance.", ""]
    for s in report["sections"]:
        lines.append(f"## {s['symptom']}")
        if s.get("urgent"):
            lines.extend((s["urgent"], ""))
            continue
        hard = s["foods"]["hard_warning"] + [e for e in s["supplements"]["hard_warning"]]
        soft = s["foods"]["negative"] + s["supplements"]["negative"]
        good = s["foods"]["positive"][:3] + s["supplements"]["positive"][:3]
        if hard:
            lines.append("- **Hard warning:** " + ", ".join(e["name"] for e in hard))
        if soft:
            lines.append("- Soft ban (evidence leans negative): " + ", ".join(e["name"] for e in soft[:5]))
        if good:
            lines.append("- Worth considering: " + ", ".join(e["name"] for e in good))
        review = s["supplements"]["research_review"]
        if review:
            lines.append("- Research / review only (not routine symptom treatment): " + ", ".join(e["name"] for e in review))
        if s["lifestyle"]:
            lines.append("- Lifestyle: " + "; ".join(s["lifestyle"]))
        if not (hard or soft or good or review or s["lifestyle"]):
            lines.append("- Nothing graded on file for this yet.")
        lines.append("")
    return "\n".join(lines)


def render_deep(report: dict[str, Any]) -> str:
    lines = ["# Symptom check-in — full detail", "", "Issue-tag matches and cached evidence are not a diagnosis or medical clearance.", ""]
    for s in report["sections"]:
        if s.get("urgent"):
            lines.extend((f"## {s['symptom']}", "", s["urgent"], ""))
            continue
        lines.append(f"## {s['symptom']}  (issue tags: {', '.join(s['tags'])})")
        lines.append("")
        lines.append("### Foods")
        for bucket_name, title in (("hard_warning", "Hard warning (real harm signal, grade F)"),
                                    ("negative", "Soft ban (evidence leans negative)"),
                                    ("positive", "Worth considering (real positive evidence)")):
            entries = s["foods"][bucket_name]
            if not entries:
                continue
            lines.append(f"**{title}**")
            for e in entries:
                lines.append(f"- {e['name']} — grade {e['grade']}. {e['grade_why']}")
                for g in e["good"][:2]:
                    lines.append(f"  - GOOD: \"{g['text']}\" {g['source']}")
                for b in e["bad"][:2]:
                    lines.append(f"  - BAD: \"{b['text']}\" {b['source']}")
            lines.append("")
        lines.append("### Supplements (from your last graded run)")
        for bucket_name, title in (("hard_warning", "Hard warning"), ("negative", "Soft ban"),
                                    ("positive", "Worth considering"), ("not_evaluated", "Not yet evaluated"),
                                    ("research_review", "Research / review only (not routine symptom treatment)")):
            entries = s["supplements"][bucket_name]
            if not entries:
                continue
            lines.append(f"**{title}**")
            for e in entries:
                if bucket_name in ("not_evaluated", "research_review"):
                    lines.append(f"- {e['name']} — {e['note']}")
                    if bucket_name == "research_review":
                        lines.append(f"  Cached: {e['suggestion']} (coverage {e['coverage']}): {e['why']}")
                else:
                    lines.append(f"- {e['name']} — {e['suggestion']} (coverage {e['coverage']}): {e['why']}")
                if e.get("use_status") == "in_use":
                    lines.append(f"  Reported exposure, not instructions: in_use; user dose {e.get('user_dose') or 'unset'}. No automatic change.")
            lines.append("")
        if s["lifestyle"]:
            lines.append("### Lifestyle")
            for note in s["lifestyle"]:
                lines.append(f"- {note}")
            lines.append("")
    return "\n".join(lines)


def select_symptoms() -> list[str] | None:
    """Grouped checklist, same curses interaction convention as the rest of this app."""
    labels = list(SYMPTOMS)
    selected: set[str] = set()
    result: dict[str, list[str] | None] = {"value": None}

    def run(stdscr) -> None:
        curses.curs_set(0)
        cursor = 0
        while True:
            height, width = stdscr.getmaxyx()
            stdscr.erase()
            stdscr.addnstr(0, 0, "SYMPTOM CHECK-IN — Space toggle · Enter/x apply · q cancel",
                            max(1, width - 1), curses.A_BOLD)
            page_size = max(1, height - 3)
            first = max(0, min(cursor - page_size // 2, len(labels) - page_size))
            last_group = None
            row = 2
            for index in range(first, min(len(labels), first + page_size)):
                label = labels[index]
                group, _tags = SYMPTOMS[label]
                if group != last_group:
                    row += 0
                    last_group = group
                mark = "[x]" if label in selected else "[ ]"
                attr = curses.A_REVERSE if index == cursor else curses.A_NORMAL
                stdscr.addnstr(row, 0, f"{mark} {label}", max(1, width - 1), attr)
                row += 1
                if row >= height - 1:
                    break
            stdscr.addnstr(height - 1, 0, f"{len(selected)} selected", max(1, width - 1), curses.A_DIM)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                cursor = (cursor - 1) % len(labels)
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = (cursor + 1) % len(labels)
            elif key == ord(" "):
                selected.symmetric_difference_update({labels[cursor]})
            elif key in (10, 13, curses.KEY_ENTER, ord("x")):
                result["value"] = list(selected)
                return
            elif key in (ord("q"), 27):
                result["value"] = None
                return

    curses.wrapper(run)
    return result["value"]


def main() -> int:
    selected = select_symptoms()
    if not selected:
        print("No symptoms selected; nothing written.")
        return 0
    report = build_report(selected)
    OUT_SHORT.write_text(render_short(report))
    OUT_DEEP.write_text(render_deep(report))
    print(f"Wrote {OUT_SHORT.name} (skim) and {OUT_DEEP.name} (full detail).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

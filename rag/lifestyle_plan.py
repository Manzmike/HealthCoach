#!/usr/bin/env python3
"""
HealthCoach — Lifestyle Plan Generator.
Produces the structured Move/Plate/Week/Constraints/Branches plan
from the foods_lifestyle_fixes curated xlsx source.

No medical prescriptions, no invented doses, no kelp/DHEA/progesterone OTC protocols.
LT4 adherence + clinician referral language required where applicable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import openpyxl

XLSX_PATH = Path("/Users/michaellindsay/Downloads/foods_lifestyle_fixes_across_conditions.xlsx")


def load_xlsx():
    return openpyxl.load_workbook(XLSX_PATH)


def clean(val):
    return str(val).strip() if val is not None else ""


def read_lifestyle_sheet(wb):
    ws = wb["Lifestyle that cuts across"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[2])]
    data = []
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        row_data = {}
        for i, val in enumerate(row):
            if i < len(headers):
                row_data[headers[i]] = str(val).strip() if val else ""
        if row_data.get("Action"):
            data.append(row_data)
    return data


def read_plate_sheet(wb):
    ws = wb["The plate"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[2])]
    data = []
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        row_data = {}
        for i, val in enumerate(row):
            if i < len(headers):
                row_data[headers[i]] = str(val).strip() if val else ""
        if row_data.get("Food group"):
            data.append(row_data)
    return data


def read_matrix_sheet(wb):
    ws = wb["Food × condition matrix"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[2])]
    data = []
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        row_data = {}
        for i, val in enumerate(row):
            if i < len(headers):
                row_data[headers[i]] = str(val).strip() if val else ""
        if row_data.get("Food"):
            data.append(row_data)
    return data


def read_will_not_fix(wb):
    ws = wb["Will not fix these"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[2])]
    data = []
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        row_data = {}
        for i, val in enumerate(row):
            if i < len(headers):
                row_data[headers[i]] = str(val).strip() if val else ""
        if row_data.get("Claim"):
            data.append(row_data)
    return data


def read_week_sheet(wb):
    ws = wb["What a week looks like"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[2])]
    data = []
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        row_data = {}
        for i, val in enumerate(row):
            if i < len(headers):
                row_data[headers[i]] = str(val).strip() if val else ""
        if row_data.get("Slot"):
            data.append(row_data)
    return data


def read_read_first(wb):
    ws = wb["Read first"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    text = []
    for row in rows:
        for val in row:
            if val and str(val).strip():
                text.append(str(val).strip())
    return "\n\n".join(text)


def render_plan(wb):
    read_first = read_read_first(wb)
    lifestyle = read_lifestyle_sheet(wb)
    plate = read_plate_sheet(wb)
    matrix = read_matrix_sheet(wb)
    will_not_fix = read_will_not_fix(wb)
    week = read_week_sheet(wb)

    lines = []

    lines.append("# Lifestyle Plan — Foods & Lifestyle That Move the Needle")
    lines.append("")
    lines.append("*Generated from curated evidence sheets. Not a prescription. Not medical advice.*")
    lines.append("")

    # Read First / Preamble
    lines.append("## Preamble")
    lines.append("")
    lines.append(read_first)
    lines.append("")

    # Constraints (from Will Not Fix These + constraints in Lifestyle)
    lines.append("## Constraints — What This Plan Does Not Do")
    lines.append("")
    lines.append("| Constraint | Reason |")
    lines.append("|---|---|")
    ws = wb["Will not fix these"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        claim = str(row[0]).strip() if row[0] else ""
        why = str(row[1]).strip() if row[1] else ""
        if claim:
            lines.append(f"| {claim} | {why} |")
    lines.append("")

    # Additional hard constraints from Lifestyle sheet
    lines.append("**Additional hard constraints:**")
    lines.append("- **No kelp/seaweed as thyroid medicine** — use iodized salt only if region is deficient (ATA Rec 32)")
    lines.append("- **No self-start DHEA, progesterone cream, or 'thyroid support' blends** — not a substitute for medical care")
    lines.append("- **No selenium megadose via Brazil nuts** — 1–2 nuts cover selenium; more hits EFSA UL")
    lines.append("- **No liver daily** — vitamin A UL; pregnancy teratogenicity risk")
    lines.append("- **No CoQ10 as mitochondrial cure** — exercise is the A/B intervention")
    lines.append("- **No random probiotic for 'heal the gut'** — AGA: no routine IBS probiotic; diet outranks bottle")
    lines.append("- **No juice cleanse / extreme raw vegan / crash keto as universal fix** — deficit can stop ovulation (RED-S)")
    lines.append("- **No liver daily to 'boost hormones'** — vitamin A UL; pregnancy teratogenicity")
    lines.append("")

    # Lifestyle Moves (The Core)
    lines.append("## Core Lifestyle Moves (A/B Evidence)")
    lines.append("")
    lines.append("| # | Action | Thyroid | Inflammation | IR | Progesterone* | DHEA* | Mitochondria* | Gut | A/B Anchor |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    ws = wb["Lifestyle that cuts across"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        action = str(row[0]).strip() if row[0] else ""
        if not action or action.startswith("*"):
            continue
        thyroid = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        inflam = str(row[2]).strip() if len(row) > 2 and row[2] else ""
        ir = str(row[3]).strip() if len(row) > 3 and row[3] else ""
        prog = str(row[4]).strip() if len(row) > 4 and row[4] else ""
        dhea = str(row[5]).strip() if len(row) > 5 and row[5] else ""
        mito = str(row[6]).strip() if len(row) > 6 and row[6] else ""
        gut = str(row[7]).strip() if len(row) > 7 and row[7] else ""
        anchor = str(row[8]).strip() if len(row) > 8 and row[8] else ""
        url = str(row[9]).strip() if len(row) > 9 and row[9] else ""
        if action:
            lines.append(f"| | {action} | {thyroid} | {inflam} | {ir} | {prog} | {dhea} | {mito} | {gut} | {anchor} |")
    lines.append("")
    lines.append("*Progesterone and DHEA columns: lifestyle can restore ovulation or metabolic context. It does not replace a hormone. Mitochondria column is function (strength, gait, IR), not a consumer mito assay.*")
    lines.append("")

    # The Plate
    lines.append("## The Shared Plate (Med / DASH / DPP Family)")
    lines.append("")
    lines.append("| Food Group | How to Use It | Why A/B |")
    lines.append("|---|---|---|")
    ws = wb["The plate"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        group = str(row[0]).strip() if row[0] else ""
        how = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        why = str(row[2]).strip() if len(row) > 2 and row[2] else ""
        if group:
            lines.append(f"| {group} | {how} | {why} |")
    lines.append("")

    # Food × Condition Matrix (condensed)
    lines.append("## Food × Condition Matrix (A/B Support)")
    lines.append("")
    lines.append("| Food | Thyroid | Inflammation | IR | Prog | DHEA | Mito | Gut | A/B Note |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    ws = wb["Food × condition matrix"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        food = str(row[0]).strip() if row[0] else ""
        if not food or food.startswith("*"):
            continue
        thyroid = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        inflam = str(row[2]).strip() if len(row) > 2 and row[2] else ""
        ir = str(row[3]).strip() if len(row) > 3 and row[3] else ""
        prog = str(row[4]).strip() if len(row) > 4 and row[4] else ""
        dhea = str(row[5]).strip() if len(row) > 5 and row[5] else ""
        mito = str(row[6]).strip() if len(row) > 6 and row[6] else ""
        gut = str(row[7]).strip() if len(row) > 7 and row[7] else ""
        note = str(row[8]).strip() if len(row) > 8 and row[8] else ""
        if food:
            lines.append(f"| {food} | {thyroid} | {inflam} | {ir} | {prog} | {dhea} | {mito} | {gut} | {note} |")
    lines.append("")

    # What a Week Looks Like
    lines.append("## What a Week Looks Like")
    lines.append("")
    ws = wb["What a week looks like"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    for row in rows[3:]:
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        slot = str(row[0]).strip() if row[0] else ""
        do = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        if slot:
            lines.append(f"**{slot}:** {do}")
    lines.append("")

    # Branches / Conditional Guidance
    lines.append("## Conditional Branches")
    lines.append("")
    lines.append("### If hypothyroid")
    lines.append("- Take levothyroxine as prescribed, away from high-fiber/soy/calcium if clinician asked to separate doses.")
    lines.append("- **Do not add kelp.** Food is adjunct, not replacement. (ATA Rec 32–34)")
    lines.append("")
    lines.append("### If cycles vanished or PCOS")
    lines.append("- The food pattern + 7% weight loss if excess mass + training — then see gynecology/endocrinology.")
    lines.append("- Not wild yam, not progesterone cream from wellness aisle.")
    lines.append("")
    lines.append("### If gut blows up (IBS-type)")
    lines.append("- Keep the plate but run a time-limited low-FODMAP under clinician guidance.")
    lines.append("- Add oats/psyllium (soluble fiber); skip bran and random probiotics as first line.")
    lines.append("")
    lines.append("### If hypothyroid on LT4")
    lines.append("- Take as prescribed. Food is adjunct, not replacement. (ATA Rec 32–34, Jonklaas 2014)")
    lines.append("")
    lines.append("### If IBS-type gut symptoms")
    lines.append("- Trial clinician-guided low-FODMAP then reintroduce.")
    lines.append("- Use soluble fiber (oats, psyllium) — not bran. (Lancet Gastro 2025; BMJ 2024)")
    lines.append("")

    # Move section
    lines.append("## Move — The Mito + IR Core")
    lines.append("")
    lines.append("**Walk most days toward 150–300 min/week moderate aerobic activity.** (WHO 2020)")
    lines.append("**Lift or hard bodyweight work 2+ days/week.** (Nutrients 2025 SR/MA; WHO 2020)")
    lines.append("That is the mitochondrial + insulin resistance core.")
    lines.append("")

    # Final disclaimer
    lines.append("---")
    lines.append("")
    lines.append("## Disclaimer")
    lines.append("")
    lines.append("**This is decision support, not medical clearance or a prescription.**")
    lines.append("- Direct hormone replacement (levothyroxine, prescription MHT, diagnosed adrenal failure) is medical care, not a grocery list.")
    lines.append("- Foods do not raise progesterone or DHEA-S back to a 20-year-old's labs.")
    lines.append("- Kelp does not treat hypothyroidism in iodine-sufficient people (ATA).")
    lines.append("- This plan summarizes pattern-level A/B evidence. It does not invent doses, protocols, or diagnose conditions.")
    lines.append("- Always discuss medication changes, hormone therapy, or supplement initiation with your clinician.")
    lines.append("")

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate lifestyle plan from curated xlsx")
    parser.add_argument("--print", action="store_true", dest="print_only", help="Print to stdout")
    parser.add_argument("--output", type=Path, help="Write to file")
    args = parser.parse_args(argv)

    if not XLSX_PATH.exists():
        print(f"ERROR: Source file not found at {XLSX_PATH}")
        return 1

    wb = openpyxl.load_workbook(XLSX_PATH)
    plan_text = render_plan(wb)

    if args.print_only:
        print(plan_text)
        return 0

    if args.output:
        args.output.write_text(plan_text, encoding="utf-8")
        print(f"Written to {args.output}")
        return 0

    # Default: print to stdout
    print(plan_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
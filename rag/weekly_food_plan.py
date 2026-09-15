#!/usr/bin/env python3
"""Weekly serving plan for your adopted whole foods: how many servings of each this week,
built from your real TDEE (tdee.py), the same protein-target convention already used
throughout this repo (SCHEDULE_TIPS.md: 1.6-2.2 g/kg bodyweight, 1.8 g/kg as the repeatable
planning pick within that range), real USDA macros (food_nutrition.json), and each food's real
serving size / weekly-max moderation cap (food_serving_guidance.py).

Transparent greedy allocation, not a black-box optimizer — every number in the output can be
traced back to why it's there:
  1. Every adopted food gets a 1-serving/week floor, so nothing you picked is silently dropped.
  2. If protein is still under target, fill up with more servings of your highest-protein
     adopted foods first (respecting each food's real weekly-max cap).
  3. If calories are still under target, fill the remaining budget starting with foods that
     match your stated intake goals, then everything else, favoring protein-dense foods.
  4. If calories overshoot the target, trim back starting with the least goal-aligned, least
     protein-dense foods first — protein-critical and goal-matched foods are protected.
  5. No food's weekly-max cap is ever exceeded, full stop — that's a real safety guideline,
     not a preference to trade off against hitting a calorie number.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  python3 weekly_food_plan.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import candidate_ledger as CL
import diet_rules as DR
import food_serving_guidance as FSG
import tdee
import safety_policy as SP

HERE = Path(__file__).resolve().parent
NUTRITION_PATH = HERE / "food_nutrition.json"
FOOD_EVIDENCE_PATH = HERE / "food_evidence.json"

# For the evidence-quality score: same letter order used throughout this app (candidate_manager._LETTER_ORDER)
_LETTER_ORDER = ("F-", "F", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+")

PROTEIN_G_PER_KG = 1.8  # repeatable planning pick within SCHEDULE_TIPS.md's 1.6-2.2 g/kg range
DEFICIT_KCAL_PER_DAY = 400  # SCHEDULE_TIPS.md: "~300-500 kcal/day" for fat loss, midpoint pick
SURPLUS_KCAL_PER_DAY = 300  # matching "reasonable planning pick" logic for a lean-gain phase

# Realistic per-food daily-serving ceiling for foods with no real weekly-max guideline — NOT a
# flat number. A flat "3x/day, any food" ceiling let the first greedy fill pile 3 servings/day
# of chicken AND salmon AND almonds AND olive oil onto the SAME day simultaneously, which is
# not how anyone actually eats. These mirror ordinary meal-structure conventions (SCHEDULE_TIPS.md
# already documents ~3-4 protein feedings/day spread across sources — one protein food realistically
# fills at most ~2 of those, not all of them): protein-dense categories cap lower (a given
# meat/fish gets at most 2 meals/day), produce is genuinely fine to lean on more, nuts/fats/
# condiments are calorie-dense in small volume and cap at 1/day.
DAILY_CEILING_BY_CATEGORY: dict[str, int] = {
    "fruit": 2, "vegetable": 3, "starchy_veg": 2, "grain": 2, "legume": 2,
    "nut_seed": 1, "egg": 2, "poultry": 2, "red_meat": 2, "organ_meat": 1,
    "fish_seafood": 2, "dairy": 2, "fermented": 1, "plant_fat": 2,
    "herb_spice": 2, "sweetener": 1,
}

# Real, standard-reference serving weight in grams by category, for computing macros per
# serving. Consistent with food_serving_guidance.SERVING_SIZE_BY_CATEGORY's human-readable
# text; these are the numeric planning amounts behind it — a reasonable planning pick per
# category, not a claim of nutritional precision for every individual food in it (a "1 cup"
# vegetable serving genuinely varies food to food; see food_serving_guidance.py's docstring).
SERVING_GRAMS_BY_CATEGORY: dict[str, float] = {
    "fruit": 150, "vegetable": 85, "starchy_veg": 150, "grain": 90, "legume": 90,
    "nut_seed": 28, "egg": 50, "poultry": 113, "red_meat": 113, "organ_meat": 113,
    "fish_seafood": 113, "dairy": 245, "fermented": 75, "plant_fat": 14,
    "herb_spice": 2, "sweetener": 21,
}


def _load_nutrition() -> dict[str, Any]:
    if not NUTRITION_PATH.exists():
        return {}
    return json.loads(NUTRITION_PATH.read_text())


def _load_food_evidence() -> dict[str, Any]:
    if not FOOD_EVIDENCE_PATH.exists():
        return {}
    return json.loads(FOOD_EVIDENCE_PATH.read_text())


def weekly_targets(intake: dict[str, Any], report_path: Any = None) -> dict[str, Any]:
    """Real weekly calorie + protein targets from your actual biometrics and TDEE. Returns the
    specific missing fields rather than guessing when something's absent."""
    estimate = tdee.tdee_estimate(intake, report_path or tdee.DEFAULT_REPORT)
    weight_kg = intake.get("bodyweight_kg")
    missing: list[str] = []
    if estimate["tdee_avg_with_workouts_kcal"] is None:
        missing.append(estimate["bmr_reason"])
    if weight_kg is None:
        missing.append("bodyweight_kg")
    if missing:
        return {"weekly_kcal": None, "weekly_protein_g": None, "missing": missing, "tdee": estimate}

    daily_kcal = estimate["tdee_avg_with_workouts_kcal"]
    direction = intake.get("weight_direction", "unknown")
    if direction == "lose":
        daily_kcal -= DEFICIT_KCAL_PER_DAY
    elif direction == "gain":
        daily_kcal += SURPLUS_KCAL_PER_DAY
    daily_protein = weight_kg * PROTEIN_G_PER_KG
    return {
        "weekly_kcal": round(daily_kcal * 7),
        "weekly_protein_g": round(daily_protein * 7),
        "daily_kcal": round(daily_kcal),
        "daily_protein_g": round(daily_protein),
        "missing": [],
        "tdee": estimate,
    }


def _food_macros(key: str, nutrition: dict[str, Any]) -> dict[str, float] | None:
    rec = nutrition.get(key)
    if not rec:
        return None
    per100 = rec.get("per_100g", {})
    kcal = per100.get("energy_kcal")
    if kcal is None:
        return None
    category = DR.FOOD_CATEGORY.get(key)
    grams = SERVING_GRAMS_BY_CATEGORY.get(category, 100)
    protein = per100.get("protein_g") or 0.0
    return {
        "grams_per_serving": grams,
        "kcal_per_serving": kcal * grams / 100,
        "protein_g_per_serving": protein * grams / 100,
    }


def plan_week(adopted_rows: list[dict[str, Any]], intake: dict[str, Any], report_path: Any = None) -> dict[str, Any]:
    nutrition = _load_nutrition()
    evidence = _load_food_evidence()
    targets = weekly_targets(intake, report_path)

    foods: list[dict[str, Any]] = []
    skipped: list[str] = []
    for row in adopted_rows:
        if row.get("consideration_scope") != "personal_candidate" or not SP.candidate_gate(row)["active_plan_allowed"]:
            skipped.append(row["display_name"] + " (research/review only; no servings allocated)")
            continue
        macros = _food_macros(row["id"], nutrition)
        if not macros:
            skipped.append(row["display_name"])
            continue
        guidance = FSG.serving_guidance(row["id"])
        category = DR.FOOD_CATEGORY.get(row["id"])
        practical_ceiling = DAILY_CEILING_BY_CATEGORY.get(category, 2) * 7
        weekly_max = guidance["weekly_max_servings"] or practical_ceiling
        goal_matched = bool(set(row.get("reasons", ())) & set(intake.get("goals", ())))
        grade = evidence.get(row["id"], {}).get("grade", "C")
        foods.append({
            "id": row["id"], "name": row["display_name"], "serving_size": guidance["serving_size"],
            "weekly_max_source": guidance["weekly_max_source"], "grade": grade,
            **macros, "weekly_max": weekly_max, "goal_matched": goal_matched, "servings": 0,
        })

    if not foods:
        return {"targets": targets, "foods": [], "skipped": skipped,
                "note": "No adopted foods have USDA nutrition data to plan with yet."}
    if targets["weekly_kcal"] is None:
        return {"targets": targets, "foods": foods, "skipped": skipped,
                "note": "Can't compute a real weekly plan yet — missing: " + "; ".join(targets["missing"])}

    def totals() -> tuple[float, float]:
        kcal = sum(f["kcal_per_serving"] * f["servings"] for f in foods)
        protein = sum(f["protein_g_per_serving"] * f["servings"] for f in foods)
        return kcal, protein

    # 1. Diversity floor — every adopted food appears at least once.
    for f in foods:
        f["servings"] = min(1, f["weekly_max"])
    kcal, protein = totals()

    # 2. Fill the protein gap: highest protein-per-serving foods first.
    by_protein = sorted(foods, key=lambda f: f["protein_g_per_serving"], reverse=True)
    guard = 0
    while protein < targets["weekly_protein_g"] and guard < 5000:
        guard += 1
        progressed = False
        for f in by_protein:
            if f["servings"] >= f["weekly_max"]:
                continue
            f["servings"] += 1
            kcal += f["kcal_per_serving"]
            protein += f["protein_g_per_serving"]
            progressed = True
            if protein >= targets["weekly_protein_g"]:
                break
        if not progressed:
            break  # every food is already at its weekly max — protein target isn't reachable with this list

    # 3. Fill remaining calories: goal-matched foods first, then by protein density.
    priority = sorted(foods, key=lambda f: (not f["goal_matched"], -f["protein_g_per_serving"]))
    guard = 0
    while kcal < targets["weekly_kcal"] and guard < 5000:
        guard += 1
        progressed = False
        for f in priority:
            if f["servings"] >= f["weekly_max"]:
                continue
            if kcal + f["kcal_per_serving"] > targets["weekly_kcal"] * 1.05:
                continue
            f["servings"] += 1
            kcal += f["kcal_per_serving"]
            protein += f["protein_g_per_serving"]
            progressed = True
        if not progressed:
            break

    # 4. Trim any overshoot: least goal-aligned, least protein-dense foods first; never below the floor.
    trim_order = sorted(foods, key=lambda f: (f["goal_matched"], f["protein_g_per_serving"]))
    guard = 0
    while kcal > targets["weekly_kcal"] * 1.10 and guard < 5000:
        guard += 1
        progressed = False
        for f in trim_order:
            if f["servings"] <= 1:
                continue
            f["servings"] -= 1
            kcal -= f["kcal_per_serving"]
            protein -= f["protein_g_per_serving"]
            progressed = True
            if kcal <= targets["weekly_kcal"] * 1.10:
                break
        if not progressed:
            break

    final_kcal, final_protein = totals()
    result = {
        "targets": targets,
        "foods": sorted(foods, key=lambda f: f["servings"], reverse=True),
        "skipped": skipped,
        "totals": {"weekly_kcal": round(final_kcal), "weekly_protein_g": round(final_protein)},
    }
    result["scores"] = score_plan(result)
    return result


def score_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Three separate scores, deliberately not blended into one fake number, because they are
    not the same kind of claim:
      - target_fit_score: 100% real math — how close the plan's actual weekly kcal/protein
        totals land to your actual TDEE-derived targets. No invented claim.
      - evidence_score: 100% real data — the average of your adopted foods' own already-computed
        letter grades (food_evidence.json), weighted by how many servings/week each gets (a food
        you eat 14x/week counts more than one you eat once). No invented claim.
      - meal_prep_score: a PRACTICALITY heuristic, not a health/evidence claim — how batchable
        the plan is (fewer distinct foods eaten more often = less cooking-session switching).
        Labeled separately on purpose so it's never confused with the two sourced scores above.
    overall_score combines only the two real scores (60% target-fit, 40% evidence) — meal_prep
    is reported alongside but deliberately excluded from "overall," since convenience isn't
    evidence and blending them would launder a heuristic into looking like a sourced number.
    """
    foods = plan.get("foods", [])
    targets = plan.get("targets", {})
    if not foods or targets.get("weekly_kcal") is None:
        return {"target_fit_score": None, "evidence_score": None, "meal_prep_score": None, "overall_score": None}

    totals = plan["totals"]
    # Calorie fit: 100 at exact target, penalized for distance either direction (over or under
    # both matter — this is a real deficit/surplus plan, not "more is always better").
    kcal_error_pct = abs(totals["weekly_kcal"] - targets["weekly_kcal"]) / targets["weekly_kcal"]
    kcal_score = max(0.0, 100 * (1 - kcal_error_pct * 2))
    # Protein fit: meeting or exceeding the real target is good (protein overshoot isn't a
    # problem the way calorie overshoot is); only shortfall is penalized.
    protein_ratio = totals["weekly_protein_g"] / targets["weekly_protein_g"]
    protein_score = min(100.0, 100 * protein_ratio)
    target_fit_score = round((kcal_score + protein_score) / 2, 1)

    total_servings = sum(f["servings"] for f in foods)
    if total_servings:
        evidence_score = round(
            sum(_LETTER_ORDER.index(f.get("grade", "C")) * f["servings"] for f in foods)
            / total_servings / (len(_LETTER_ORDER) - 1) * 100, 1,
        )
    else:
        evidence_score = None

    avg_servings_per_food = total_servings / len(foods) if foods else 0
    meal_prep_score = round(min(100.0, 100 * avg_servings_per_food / 7), 1)

    overall_score = round(target_fit_score * 0.6 + (evidence_score or 0) * 0.4, 1) if evidence_score is not None else target_fit_score

    return {
        "target_fit_score": target_fit_score, "evidence_score": evidence_score,
        "meal_prep_score": meal_prep_score, "overall_score": overall_score,
    }


def _print_plan(plan: dict[str, Any]) -> None:
    targets = plan["targets"]
    if targets["weekly_kcal"] is None:
        print("Can't build a real weekly plan yet.")
        print("Missing:", "; ".join(targets["missing"]))
        print("Set these with: python3 candidate_manager.py intake")
        return
    print(f"Weekly target: {targets['weekly_kcal']:.0f} kcal ({targets['daily_kcal']:.0f}/day), "
          f"{targets['weekly_protein_g']:.0f} g protein ({targets['daily_protein_g']:.0f}/day)")
    if plan.get("note"):
        print(plan["note"])
        return
    totals = plan["totals"]
    print(f"Plan totals:   {totals['weekly_kcal']} kcal, {totals['weekly_protein_g']} g protein")
    print()
    print(f"{'Food':<32}{'Servings/wk':<13}{'Serving size':<28}{'kcal/wk':<10}{'Protein g/wk'}")
    for f in plan["foods"]:
        cap_note = f" (capped: {f['weekly_max_source']})" if f["servings"] >= f["weekly_max"] and f["weekly_max_source"] else ""
        print(f"{f['name'][:30]:<32}{f['servings']:<13}{f['serving_size'][:26]:<28}"
              f"{f['kcal_per_serving'] * f['servings']:<10.0f}{f['protein_g_per_serving'] * f['servings']:.0f}{cap_note}")
    if plan["skipped"]:
        print()
        print("Skipped (no USDA nutrition data on file):", ", ".join(plan["skipped"]))

    scores = plan.get("scores", {})
    if scores.get("target_fit_score") is not None:
        print()
        print(f"Target fit:  {scores['target_fit_score']:.0f}/100  (real — how close this plan's actual "
              f"totals land to your recommended {targets['weekly_kcal']:.0f} kcal / {targets['weekly_protein_g']:.0f} g protein per week)")
        print(f"Evidence:    {scores['evidence_score']:.0f}/100  (real — servings-weighted average grade of your adopted foods)")
        print(f"Meal prep:   {scores['meal_prep_score']:.0f}/100  (practicality heuristic, NOT an evidence score — "
              f"how batchable this plan is)")
        print(f"Overall:     {scores['overall_score']:.0f}/100  (target fit + evidence only; meal prep excluded on purpose)")


def main() -> int:
    ledger = CL.load_ledger()
    adopted = [
        row for row in ledger["candidates"]
        if row["class"] == "food" and row["user_decision"] == "adopt" and row["use_status"] == "in_use"
    ]
    if not adopted:
        print("No adopted foods yet. Run:")
        print("  python3 candidate_manager.py rank --categories food --all-decisions --limit 0")
        print("Record adoption intent, then separately confirm foods you actually use, and re-run this.")
        return 0
    plan = plan_week(adopted, ledger["intake"])
    _print_plan(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

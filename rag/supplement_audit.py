#!/usr/bin/env python3
"""Interactive, evidence-bound supplement audit for HealthCoach.

The catalog is deliberately broad. The user's submitted "very / medium / low researched"
groups are discovery queues, not evidence grades. Every item is independently checked against
the local LanceDB corpus, de-duplicated by DOI/source, and assigned coverage from retrieved
human evidence. A local MLX model writes deep cards only from the retrieved passages.

Examples:
  ./hc-supplements
  ./hc-supplements --issues strength,endurance,sleep --deep-limit 12
  ./hc-supplements --items creatine,caffeine,magnesium --evidence-only
  ./hc-supplements --priority-items creatine,omega-3 --peptides tirzepatide,bpc-157
  ./hc-supplements --non-interactive --experimental-policy screen_strong_human --evidence-only
  ./hc-supplements --list
"""

from __future__ import annotations

import argparse
import curses
import datetime as dt
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import coach as HC

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.prompt import Confirm, IntPrompt, Prompt
    from rich.table import Table
except ImportError as exc:  # pragma: no cover - actionable runtime message
    raise SystemExit("Rich is required. Activate .venv and run: pip install -r requirements.txt") from exc


HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "HEALTHCOACH_REPORT.md"
console = Console()

QUEUE_VERY = "Submitted: very researched"
QUEUE_MEDIUM = "Submitted: medium researched"
QUEUE_LOW = "Submitted: low researched"
QUEUE_PEPTIDE = "Selected: peptide / gray-market review"
QUEUE_ORDER = (QUEUE_VERY, QUEUE_MEDIUM, QUEUE_LOW, QUEUE_PEPTIDE)
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "—": 9}

ISSUES = {
    "cut": "Fat loss / appetite / blood sugar",
    "strength": "Strength, muscle retention, or hypertrophy",
    "endurance": "Running, cycling, VO2 max, or repeated efforts",
    "sleep": "Sleep onset, sleep quality, or early waking",
    "stress": "Stress, anxiety, or high workload",
    "focus": "Focus, cognition, or study performance",
    "gi": "Constipation, diarrhea, nausea, or other GI issues",
    "joints": "Joints, tendons, soreness, or injury recovery",
    "heart": "Blood pressure, lipids, or cardiometabolic health",
    "immune": "Frequent illness or immune concerns",
    "skin": "Skin, hair, or connective-tissue goals",
    "deficiency": "Known or suspected nutrient deficiency",
}

MEDICATION_OPTIONS = (
    ("tirzepatide", "Tirzepatide"),
    ("tadalafil", "Tadalafil"),
    ("finasteride", "Finasteride"),
    ("other", "Other prescription or OTC medication"),
)

# This changes research scope only. It never waives medication safety gates or authorizes
# personal use of an unapproved product. The broad option exists so a user can ask the RAG
# library to find unusually strong human evidence without having to know every compound name.
EXPERIMENTAL_POLICY_OPTIONS = (
    (
        "approved_only",
        "Approved medicines and ordinary supplements only — do not broad-scan experimental drugs (recommended)",
    ),
    (
        "screen_strong_human",
        "Research-only broad scan — surface topics only when ≥2 unique A/B human intervention sources survive",
    ),
)

SUPPLEMENT_SOURCE_OPTIONS = (
    (
        "whole_food_first",
        "Whole-food first — use foods whenever the nutrient/compound has a meaningful food route (recommended)",
    ),
    (
        "mixed",
        "Mixed — compare food and isolated products for evidence fit, tolerance, cost, and convenience",
    ),
    (
        "products_allowed",
        "Products allowed — still prefer food where equivalent, but evaluate evidence-supported products",
    ),
)

SAFETY_OPTIONS = (
    ("none_known", "None known"),
    ("kidney", "Kidney disease or reduced kidney function"),
    ("liver", "Liver disease or abnormal liver testing"),
    ("gallbladder", "Gallstones or gallbladder disease"),
    ("pancreas", "Pancreatitis or pancreatic disease"),
    ("high_bp", "High blood pressure"),
    ("low_bp", "Low blood pressure or fainting"),
    ("arrhythmia", "Arrhythmia, palpitations, or unexplained fast heart rate"),
    ("bleeding", "Bleeding disorder or anticoagulant use"),
    ("gi_disease", "Diagnosed gastrointestinal disease"),
    ("allergy", "Medication, food, or supplement allergy"),
    ("mental_health", "Mental-health condition or psychiatric medication"),
)

DIET_GI_OPTIONS = (
    ("none_reported", "No restriction or recurring GI symptom reported"),
    ("constipation", "Constipation"),
    ("diarrhea", "Diarrhea"),
    ("nausea", "Nausea or early fullness"),
    ("reflux", "Reflux or heartburn"),
    ("bloating", "Bloating or gas"),
    ("lactose", "Lactose intolerance or dairy sensitivity"),
    ("vegetarian", "Vegetarian"),
    ("vegan", "Vegan"),
    ("low_fish", "Rarely eats fish"),
    ("low_dairy", "Rarely eats dairy or calcium-rich foods"),
    ("other", "Other food restriction or trigger"),
)

SLEEP_OPTIONS = (
    ("none_reported", "No recurring sleep problem reported"),
    ("sleep_onset", "Difficulty falling asleep"),
    ("sleep_maintenance", "Frequent waking"),
    ("early_waking", "Waking earlier than intended"),
    ("unrefreshing", "Unrefreshing sleep or daytime sleepiness"),
    ("snoring", "Loud or persistent snoring"),
    ("witnessed_pauses", "Witnessed breathing pauses or waking gasping"),
    ("shift_variation", "Large variation in sleep/wake times"),
)

SUBSTANCE_OPTIONS = (
    ("none_reported", "None reported"),
    ("alcohol", "Alcohol"),
    ("nicotine", "Nicotine or tobacco"),
    ("cannabis", "Cannabis"),
    ("energy_drinks", "Energy drinks"),
    ("preworkout", "Stimulant pre-workout"),
    ("other_stimulant", "Other stimulant or recreational substance"),
)

STORE_OPTIONS = (
    ("costco", "Costco"),
    ("sams_club", "Sam's Club"),
    ("bjs", "BJ's Wholesale Club"),
    ("whole_foods", "Whole Foods Market"),
    ("sprouts", "Sprouts Farmers Market"),
    ("trader_joes", "Trader Joe's"),
    ("kroger", "Kroger"),
    ("tom_thumb", "Tom Thumb / Albertsons"),
    ("heb", "H-E-B"),
    ("central_market", "Central Market"),
    ("walmart", "Walmart"),
    ("target", "Target"),
    ("aldi", "ALDI"),
    ("natural_grocers", "Natural Grocers"),
    ("cvs", "CVS"),
    ("walgreens", "Walgreens"),
    ("gnc", "GNC"),
    ("vitamin_shoppe", "The Vitamin Shoppe"),
    ("amazon", "Amazon"),
    ("iherb", "iHerb"),
    ("thrive_market", "Thrive Market"),
    ("manufacturer", "Direct from the manufacturer"),
    ("local_market", "Local grocery, butcher, fish market, or farmers market"),
)

STORE_ROLES = {
    "costco": "Bulk protein, pasteurized dairy, frozen produce, oats, rice, and household staples",
    "sams_club": "Bulk protein, pasteurized dairy, frozen produce, pantry goods, and household staples",
    "bjs": "Bulk food and household staples where locally available",
    "whole_foods": "Specialty dietary items, produce, seafood, pasteurized dairy, and smaller package options",
    "sprouts": "Produce, bulk pantry foods, specialty dietary items, and supplement label comparison",
    "trader_joes": "Smaller frozen, prepared, pantry, and produce options for low-waste meal assembly",
    "kroger": "Full-line grocery coverage, weekly staples, and smaller packages",
    "tom_thumb": "Full-line grocery coverage, weekly staples, pharmacy access, and smaller packages",
    "heb": "Texas full-line grocery coverage, prepared foods, fresh foods, and weekly staples",
    "central_market": "Specialty produce, seafood, meat, dairy, and harder-to-find ingredients",
    "walmart": "Budget comparison, full-line groceries, household goods, and common supplements",
    "target": "Convenience groceries, household goods, and common packaged staples",
    "aldi": "Lower-cost core groceries and compact package comparison",
    "natural_grocers": "Specialty dietary foods and supplement label comparison",
    "cvs": "Pharmacist access and limited medication or supplement shopping",
    "walgreens": "Pharmacist access and limited medication or supplement shopping",
    "gnc": "Supplement comparison only after the evidence verdict and quality check",
    "vitamin_shoppe": "Supplement comparison only after the evidence verdict and quality check",
    "amazon": "Online gap-filling only with seller, lot, expiration, and certification verification",
    "iherb": "Online specialty food or supplement gap-filling with label and quality verification",
    "thrive_market": "Online pantry and specialty-diet gap-filling after price and package comparison",
    "manufacturer": "Exact-form supplement purchasing after verifying the official manufacturer storefront",
    "local_market": "Fresh food, culturally preferred ingredients, and package sizes unavailable at selected chains",
}

PRODUCT_OPTIONS = (
    ("third_party", "Third-party-tested products preferred"),
    ("budget", "Lowest practical cost"),
    ("fewest_items", "Fewest total stack items"),
    ("powder", "Powder preferred"),
    ("capsules", "Capsules/tablets preferred"),
    ("avoid_animal", "Avoid animal-derived products"),
)

INJURY_OPTIONS = (
    ("none_reported", "No current pain or limiting injury"),
    ("knee", "Knee pain or knee-loading limitation"),
    ("shin", "Shin pain / shin splints"),
    ("ankle_foot", "Ankle, Achilles, or foot pain"),
    ("hip", "Hip or groin pain"),
    ("low_back", "Low-back pain"),
    ("shoulder", "Shoulder or pressing/pulling pain"),
    ("other", "Other injury — describe once in final notes"),
)

DEFICIENCY_OPTIONS = (
    ("none_unknown", "None confirmed / unknown"),
    ("vitamin_d", "Clinician-confirmed low 25(OH)D / vitamin D"),
    ("iron", "Clinician-confirmed iron deficiency"),
    ("b12", "Clinician-confirmed vitamin B12 deficiency"),
    ("folate", "Clinician-confirmed folate deficiency"),
    ("other", "Other confirmed abnormal lab — describe once in final notes"),
)

REACTION_OPTIONS = (
    ("none_reported", "No prior supplement reaction reported"),
    ("gi", "Nausea, diarrhea, constipation, or stomach pain"),
    ("sleep_anxiety", "Insomnia, anxiety, or feeling overstimulated"),
    ("heart_bp", "Palpitations, dizziness, or blood-pressure effect"),
    ("allergy", "Rash, swelling, breathing trouble, or other allergy"),
    ("other", "Other reaction — describe once in final notes"),
)

SUPPLEMENT_RESULT_OPTIONS = (
    ("not_tracked", "Results have not been tracked yet"),
    ("helped", "At least one current supplement clearly helped"),
    ("no_effect", "At least one current supplement had no noticeable effect"),
    ("side_effect", "At least one current supplement caused a side effect"),
    ("unsure", "Not sure whether current supplements are doing anything"),
)

TIMELINE_OPTIONS = (
    ("none", "No fixed race or deadline"),
    ("under_8", "Race or deadline within 8 weeks"),
    ("weeks_8_16", "Race or deadline in 8–16 weeks"),
    ("over_16", "Race or deadline more than 16 weeks away"),
    ("other", "Other timing — describe once in final notes"),
)

TRAINING_OPTIONS = (
    ("lifting", "Resistance training / lifting"),
    ("running", "Running"),
    ("cycling", "Cycling / indoor bike"),
    ("walking", "Walking / step target"),
    ("team_sport", "Team or combat sport"),
    ("other", "Other training mode"),
)

CAFFEINE_OPTIONS = (
    ("none", "No caffeine"),
    ("coffee", "Drip coffee or espresso"),
    ("cold_brew", "Cold brew"),
    ("tea", "Tea"),
    ("energy_drink", "Energy drink"),
    ("preworkout", "Pre-workout"),
    ("tablet", "Caffeine tablet or gum"),
)

CARDIO_TIMING_OPTIONS = (
    ("morning", "Morning cardio"),
    ("evening", "Evening cardio around the 17:00 training window"),
    ("both", "Both / split across morning and evening"),
    ("recommend", "Recommend the timing from my schedule, training load, heat, and recovery"),
)

WORKOUT_TIMING_OPTIONS = (
    ("morning", "Morning strength workouts"),
    ("evening", "Evening strength workouts around the 17:00 training window"),
    ("both", "Both / split strength work across morning and evening"),
    ("recommend", "Recommend strength-workout timing from evidence and my schedule"),
)

# These are interest/review selectors, not endorsements.  The authored whole-life module
# evaluates every option and the generated report records which ones the user wants to
# prioritize.  Ambiguous user terms are preserved but explicitly ask for clarification.
FOOD_ADDITION_OPTIONS = (
    ("organic_juice", "Organic / 100% juice"),
    ("butter_stick", "Butter stick or butter-based balm — clarify edible vs topical"),
    ("banana_water", "Banana water — clarify fruit-infused water vs another recipe"),
    ("sea_salt", "Sea salt / sodium source"),
    ("oysters", "Oysters — cooked, not raw"),
    ("honey_treats", "Honey and homemade honey ice cream"),
    ("pasteurized_dairy", "Pasteurized milk, yogurt, or cottage cheese"),
    ("milk_diet", "Milk-heavy or milk-only diet"),
    ("beef_liver", "Beef liver / organ meat"),
    ("coconut", "Coconut and coconut oil"),
    ("carrots", "Carrots"),
    ("potatoes_rice", "Potatoes and rice"),
    ("animal_protein", "Animal protein"),
    ("fruit_carbs", "Fruit carbohydrates: papaya, cherries, mango, melon, oranges"),
    ("orange_juice", "Orange juice"),
    ("calcium_food", "Calcium from food"),
    ("gelatin_broth", "Gelatin/collagen foods and bone broth"),
    ("fiber_food", "Whole-food / viscous fiber"),
    ("cooked_mushrooms", "Cooked culinary mushrooms"),
    ("dark_chocolate", "Dark chocolate"),
    ("fish_eggs", "Fish eggs / roe and traditional foods"),
    ("carb_200", "A fixed 200 g carbohydrate target"),
)

HOME_PRACTICE_OPTIONS = (
    ("bible_prayer", "Bible study, prayer, and learning about Jesus"),
    ("morning_light", "Morning outdoor light / circadian lighting"),
    ("sunbathing", "Sunbathing or sunlight on the abdomen"),
    ("breathwork", "Slow breathwork"),
    ("grass_grounding", "Grass patch / barefoot grounding"),
    ("knees_over_toes", "Knees-over-toes style exercise"),
    ("natural_fibers", "Natural-fiber clothing / linen"),
    ("cold_plunge", "Cold shower, bath, or plunge"),
    ("water_quality", "Water mineral content, filter choice, and sourcing"),
    ("low_edc_home", "Practical endocrine-disruptor exposure reduction"),
    ("feng_shui", "Feng shui for room organization"),
    ("healing_light", "Red/full-spectrum light or photobiomodulation"),
    ("sound_cymatics", "Sound baths / cellular cymatics"),
    ("frequency_devices", "Radionics / biofrequency devices"),
    ("ez_water", "EZ / structured water"),
    ("linen_frequency", "Linen '00 Hz' or frequency fabric claims"),
)

ALTERNATIVE_ITEM_OPTIONS = (
    ("iv_fluids", "IV fluids / vitamin drips"),
    ("arsenicum_album", "Arsenicum album / homeopathy"),
    ("bentonite", "Bentonite clay or internal binders"),
    ("coffee_enema", "Coffee enemas"),
    ("castor_oil", "Castor oil / castor-oil packs"),
    ("digestive_enzymes", "Digestive enzyme supplements"),
    ("hydrochloric_acid", "Betaine HCl / hydrochloric-acid supplements"),
    ("chlorophyll", "Chlorophyll / chlorophyllin drops"),
    ("spore_probiotic", "Spore-based probiotics"),
    ("black_seed_oil", "Black seed oil / Nigella sativa"),
    ("coq10", "CoQ10"),
    ("chanca_piedra", "Chanca piedra / Phyllanthus niruri"),
    ("quercetin", "Quercetin"),
    ("artichoke_leaf", "Artichoke leaf extract"),
    ("liver_flush", "Liver or gallbladder flush"),
    ("tissue_cleanse", "Milk/tissue cleaning or other tissue-cleansing claim"),
    ("cholesterol_energy", "Claim: high cholesterol only means stress / low metabolic energy"),
    ("broda_barnes", "Dr. Broda Barnes thyroid / basal-temperature claims"),
    ("magnesium", "Magnesium — already reviewed in supplement audit"),
    ("natural_digestive", "Food-based digestive aids"),
    ("natural_binders", "Food-based 'natural binder' claims"),
    ("blood_building", "'Blood-building' foods or supplements"),
)

WHOLE_LIFE_VERDICTS = {
    # Food decisions
    "organic_juice": "OPTIONAL FOOD — organic does not make juice unlimited; verify 100% pasteurized juice and serving size.",
    "butter_stick": "CLARIFY — edible butter is a measured saturated-fat food; a topical balm is a cosmetic, not nutrition.",
    "banana_water": "PLANNING ONLY — define the recipe; ordinary water plus a banana is the auditable version.",
    "sea_salt": "FOOD SEASONING — not a trace-mineral supplement; sodium is individualized for heat/sweat.",
    "oysters": "OPTIONAL FOOD — cooked only; raw oysters are not approved by this plan.",
    "honey_treats": "OPTIONAL TREAT — count honey as added sugar and keep the protein/energy plan intact.",
    "pasteurized_dairy": "USEFUL PROTEIN/CALCIUM VEHICLE if tolerated; raw milk stays excluded.",
    "milk_diet": "DO NOT USE AS A SOLE DIET — it displaces food variety and is not a cut strategy.",
    "beef_liver": "OPTIONAL SMALL FOOD — avoid frequent large servings because preformed vitamin A accumulates.",
    "coconut": "OPTIONAL FOOD — coconut oil is not the default cooking fat because it is high in saturated fat.",
    "carrots": "USE AS AN ORDINARY VEGETABLE; no detox claim.",
    "potatoes_rice": "USE AS TRAINING CARBOHYDRATE; portion follows the day, not a food-ban list.",
    "animal_protein": "USE AS ONE PROTEIN VEHICLE; favor varied, leaner and minimally processed choices.",
    "fruit_carbs": "USE WHOLE FRUIT; it supplies carbohydrate without creating a special 'natural fructose' exemption.",
    "orange_juice": "OPTIONAL PASTEURIZED 100% JUICE; whole fruit remains the default.",
    "calcium_food": "FOOD FIRST; pills remain intake/lab/clinician-gated.",
    "gelatin_broth": "OPTIONAL FOOD — collagen/gelatin does not replace complete-protein feedings.",
    "fiber_food": "USE GRADUALLY; exact source and amount depend on GLP-1 GI tolerance.",
    "cooked_mushrooms": "USE AS AN ORDINARY FOOD; no medicinal-mushroom claim is inferred.",
    "dark_chocolate": "OPTIONAL MEASURED TREAT; not a treatment.",
    "fish_eggs": "OPTIONAL TRADITIONAL FOOD; verify refrigeration, pasteurization/cooking advice, and sodium label.",
    "carb_200": "DO NOT LOCK AUTOMATICALLY — calculate from training, total energy, GI tolerance, and results.",
    # Home/practice decisions
    "bible_prayer": "ADD AS A VALUES/PRACTICE BLOCK; history and theology are labeled separately.",
    "morning_light": "KEEP — use outdoor morning light and ordinary evening dimming; no frequency gadget required.",
    "sunbathing": "DO NOT PRESCRIBE TANNING; sunlight on the abdomen has no special established effect.",
    "breathwork": "OPTIONAL LOW-COST PRACTICE — slow, comfortable breathing; stop if dizzy.",
    "grass_grounding": "OPTIONAL RITUAL/OUTDOOR CUE — no proven electron-healing claim.",
    "knees_over_toes": "OPTIONAL PROGRESSION — treat as ordinary graded knee/hip/calf strength, not a branded cure.",
    "natural_fibers": "PREFERENCE/COMFORT — no 'healing frequency' claim.",
    "cold_plunge": "OPTIONAL, NOT REQUIRED — avoid unsupervised extremes and do not place after hypertrophy work by default.",
    "water_quality": "KEEP — use the Dallas water report and a certified filter matched to an actual contaminant/goal.",
    "low_edc_home": "OPTIONAL PRACTICAL REDUCTION — focus on dust, ventilation, heat-safe food storage, and fewer products.",
    "feng_shui": "OPTIONAL ROOM-ORGANIZATION FRAME; no medical claim.",
    "healing_light": "OPTIONAL/REVIEW DEVICE-SPECIFIC EVIDENCE; ordinary circadian light is not the same as PBM.",
    "sound_cymatics": "OPTIONAL RELAXATION/ART ONLY; no cellular-healing claim.",
    "frequency_devices": "SKIP AS MEDICAL TREATMENT — no reliable clinical basis for radionics claims.",
    "ez_water": "SKIP PREMIUM HEALTH CLAIM — choose safe potable water, not molecular marketing.",
    "linen_frequency": "PREFERENCE ONLY — fabric frequency numbers do not establish health benefit.",
    # Alternative/clinical decisions
    "iv_fluids": "CLINICIAN/MEDICAL SETTING ONLY — no apartment IV protocol.",
    "arsenicum_album": "SKIP — no FDA-approved homeopathic product and no demonstrated active-dose benefit.",
    "bentonite": "DO NOT INGEST FOR DETOX — contamination and binding/interaction concerns outweigh an unproven goal.",
    "coffee_enema": "DO NOT USE — no efficacy studies and published adverse-event case reports.",
    "castor_oil": "DO NOT USE AS A DETOX; clarify a specific topical or clinician-directed indication.",
    "digestive_enzymes": "SYMPTOM/DIAGNOSIS-SPECIFIC; not a universal digestion stack.",
    "hydrochloric_acid": "CLINICIAN-GATED — do not self-treat presumed low stomach acid.",
    "chlorophyll": "SKIP FOR DETOX — no clear outcome relevant to this plan.",
    "spore_probiotic": "OPTIONAL ONLY FOR A DEFINED GI PROBLEM/STRAIN; not a generic daily add.",
    "black_seed_oil": "OPTIONAL/REVIEW — human marker data exist but evidence quality and goal fit are limited.",
    "coq10": "SKIP FOR THIS PLAN unless a specific clinician-reviewed indication emerges.",
    "chanca_piedra": "CLINICIAN-ONLY FOR DOCUMENTED STONE CONTEXT; not a liver cleanse.",
    "quercetin": "OPTIONAL/LOW PRIORITY — require outcome-specific human evidence and interaction review.",
    "artichoke_leaf": "OPTIONAL/CLINICIAN REVIEW for documented lipids; not a liver flush.",
    "liver_flush": "DO NOT USE — cleanse evidence is inadequate and it does not treat liver or gallbladder disease.",
    "tissue_cleanse": "REJECT THE CLAIM — milk and foods do not 'clean tissues.'",
    "cholesterol_energy": "REJECT AS A COMPLETE EXPLANATION — LDL is an atherosclerotic risk factor; stress is not an exemption.",
    "broda_barnes": "HISTORICAL CONTEXT ONLY — diagnose thyroid disease with current clinical evaluation, not temperature alone.",
    "magnesium": "USE THE EXISTING INTAKE/KIDNEY/LAB GATE; do not duplicate it here.",
    "natural_digestive": "FOOD PREFERENCE ONLY unless a defined symptom and evidence-backed intervention are identified.",
    "natural_binders": "SKIP DETOX CLAIMS; ordinary fiber is food, not an emergency toxin binder.",
    "blood_building": "TRANSLATE TO A DIAGNOSIS — iron/B12/folate treatment requires diet/lab/clinician context.",
}


def checkbox_prompt(
    title: str,
    choices: Sequence[tuple[str, str]],
    *,
    description: str = "",
    defaults: Sequence[str] = (),
    minimum: int = 0,
    maximum: int | None = None,
    exclusive_groups: Sequence[Sequence[str]] = (),
) -> list[str]:
    """Scrollable terminal checkbox list: arrows/j/k, Space, Enter, / filter."""
    valid = {value for value, _ in choices}
    initial = {value for value in defaults if value in valid}

    def numeric_picker() -> list[str]:
        console.print(f"\n[bold]{title}[/bold]")
        if description:
            console.print(f"[dim]{description}[/dim]")
        for i, (value, label) in enumerate(choices, 1):
            mark = "*" if value in initial else " "
            console.print(f"  [cyan]{i:>2}[/cyan] [{mark}] {label}")
        default_numbers = ",".join(str(i) for i, (value, _) in enumerate(choices, 1) if value in initial)
        raw = Prompt.ask("Numbers, comma-separated", default=default_numbers)
        picked = {
            choices[int(token) - 1][0]
            for token in re.findall(r"\d+", raw)
            if 1 <= int(token) <= len(choices)
        }
        if len(picked) < minimum:
            picked = set(list(initial)[:minimum]) or {choices[0][0]}
        return [value for value, _ in choices if value in picked]

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return numeric_picker()

    def run(stdscr) -> list[str]:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        selected = set(initial)
        exclusive_sets = [set(group) for group in exclusive_groups]
        filtered = list(choices)
        query = ""
        cursor = 0
        top = 0
        warning = ""

        def put(y: int, x: int, value: str, attr: int = 0) -> None:
            height, width = stdscr.getmaxyx()
            if 0 <= y < height and x < width:
                try:
                    stdscr.addnstr(y, x, value, max(0, width - x - 1), attr)
                except curses.error:
                    pass

        while True:
            height, width = stdscr.getmaxyx()
            visible = max(1, height - 7)
            cursor = min(cursor, max(0, len(filtered) - 1))
            if cursor < top:
                top = cursor
            if cursor >= top + visible:
                top = cursor - visible + 1

            stdscr.erase()
            put(0, 0, title, curses.A_BOLD)
            put(1, 0, description or "Choose every answer that applies. Checked boxes are included in your report.", curses.A_DIM)
            put(2, 0, "↑/↓ move • Space select • Enter next • / search • r all • a all • n clear")
            if query:
                put(3, 0, f"Filter: {query}  ({len(filtered)} matches)", curses.A_DIM)
            else:
                put(3, 0, f"Showing {len(filtered)} options", curses.A_DIM)

            for screen_row, index in enumerate(range(top, min(len(filtered), top + visible)), start=4):
                value, label = filtered[index]
                marker = "[x]" if value in selected else "[ ]"
                pointer = ">" if index == cursor else " "
                attr = curses.A_REVERSE if index == cursor else 0
                put(screen_row, 0, f"{pointer} {marker} {label}", attr)

            footer_y = min(height - 2, 4 + visible)
            footer = f"Selected: {len(selected)}"
            if warning:
                footer += f"  •  {warning}"
            put(footer_y, 0, footer, curses.A_BOLD)
            stdscr.refresh()
            key = stdscr.getch()
            warning = ""

            if key in (curses.KEY_UP, ord("k")) and filtered:
                cursor = (cursor - 1) % len(filtered)
            elif key in (curses.KEY_DOWN, ord("j")) and filtered:
                cursor = (cursor + 1) % len(filtered)
            elif key == curses.KEY_PPAGE and filtered:
                cursor = max(0, cursor - visible)
            elif key == curses.KEY_NPAGE and filtered:
                cursor = min(len(filtered) - 1, cursor + visible)
            elif key == ord(" ") and filtered:
                value = filtered[cursor][0]
                if value in selected:
                    selected.remove(value)
                else:
                    if maximum == 1:
                        selected.clear()
                    for group in exclusive_sets:
                        if value in group:
                            selected.difference_update(group)
                    if maximum is None or len(selected) < maximum:
                        selected.add(value)
            elif key in (10, 13, curses.KEY_ENTER):
                if len(selected) >= minimum and (maximum is None or len(selected) <= maximum):
                    return [value for value, _ in choices if value in selected]
                warning = f"Select at least {minimum} option(s)."
            elif key == ord("n"):
                selected.clear()
            elif key == ord("a"):
                if maximum == 1 and filtered:
                    selected = {filtered[cursor][0]}
                else:
                    for value, _ in filtered:
                        for group in exclusive_sets:
                            if value in group:
                                selected.difference_update(group)
                        selected.add(value)
            elif key == ord("r"):
                query = ""
                filtered = list(choices)
                cursor = top = 0
            elif key == ord("/"):
                try:
                    curses.curs_set(1)
                except curses.error:
                    pass
                curses.echo()
                put(height - 1, 0, "Search: ")
                stdscr.clrtoeol()
                try:
                    raw = stdscr.getstr(height - 1, 8, max(1, width - 10))
                    query = raw.decode("utf-8", errors="ignore").strip().lower()
                except curses.error:
                    query = ""
                finally:
                    curses.noecho()
                    try:
                        curses.curs_set(0)
                    except curses.error:
                        pass
                filtered = [item for item in choices if query in item[1].lower()] if query else list(choices)
                cursor = top = 0
                if not filtered:
                    filtered = list(choices)
                    warning = "No matches; filter reset."
                    query = ""
            elif key in (3, 27, ord("q")):
                raise KeyboardInterrupt

    try:
        return curses.wrapper(run)
    except curses.error:
        # Very small or unusual terminals still get a usable numeric selector.
        console.print("[yellow]Interactive checkbox mode is unavailable; using numeric selection.[/yellow]")
        return numeric_picker()


def labels_for(values: Sequence[str], choices: Sequence[tuple[str, str]]) -> list[str]:
    lookup = dict(choices)
    return [lookup[value] for value in values if value in lookup]


def parse_choice_values(raw: str | None, choices: Sequence[tuple[str, str]], defaults: Sequence[str] = ()) -> list[str]:
    """Parse non-interactive comma-separated keys/labels, plus the all/none shorthands."""
    if raw is None:
        return [value for value, _ in choices if value in set(defaults)]
    tokens = [token.strip().lower() for token in raw.split(",") if token.strip()]
    if not tokens or tokens == ["none"]:
        return []
    if "all" in tokens:
        return [value for value, _ in choices]
    selected: list[str] = []
    missing: list[str] = []
    for token in tokens:
        match = next(
            (
                value for value, label in choices
                if token == value.lower() or token == _key(label) or token in label.lower()
            ),
            "",
        )
        if match and match not in selected:
            selected.append(match)
        elif not match:
            missing.append(token)
    if missing:
        raise SystemExit(
            "Unknown whole-life selector value(s): %s. Use 'all', 'none', or the keys printed by --list-lifestyle."
            % ", ".join(missing)
        )
    return [value for value, _ in choices if value in selected]


def whole_life_selection_markdown(profile: dict) -> str:
    groups = (
        ("Food additions", profile.get("food_addition_keys", ()), FOOD_ADDITION_OPTIONS),
        ("Apartment/home practices", profile.get("home_practice_keys", ()), HOME_PRACTICE_OPTIONS),
        ("Alternative/clinical claims", profile.get("alternative_item_keys", ()), ALTERNATIVE_ITEM_OPTIONS),
    )
    lines = [
        "These selections are requests for analysis, not endorsements. The verdict controls whether an item can change the operating plan.",
        "",
        "| Selected class | Item | Compiler verdict |",
        "|---|---|---|",
    ]
    any_selected = False
    for group, values, choices in groups:
        for value in values:
            any_selected = True
            label = dict(choices).get(value, value)
            verdict = WHOLE_LIFE_VERDICTS.get(value, "REVIEW — no precompiled verdict")
            lines.append(f"| {group} | {label} | {verdict} |")
    if not any_selected:
        lines.append("| None | No whole-life priority selected | The complete evidence matrix remains available below. |")
    return "\n".join(lines)


def store_sourcing_markdown(profile: dict) -> str:
    """Turn selected retailers into logistics without inventing store-specific health claims."""
    selected = profile.get("store_keys", ())
    labels = dict(STORE_OPTIONS)
    lines = [
        "**PLANNING / RETAILER LOGISTICS:** store selection changes where the shopping list is searched, not the evidence target or safety verdict. Prices, inventory, formulations, and sellers can change, so verify the current listing and the physical package before purchase.",
        "",
        "| Selected store | Best role in this plan | What to verify |",
        "|---|---|---|",
    ]
    if not selected:
        lines.append(
            "| No retailer selected | Use the food and product specifications without a chain preference | Current label, package condition, storage needs, price per usable serving, and supplement quality certification where applicable |"
        )
    for key in selected:
        label = labels.get(key, key)
        role = STORE_ROLES.get(key, "Search for items that match the report specifications")
        if key in {"cvs", "walgreens"}:
            verify = "Use the pharmacist for medication questions; verify exact ingredient, amount, lot, expiration, and certification"
        elif key in {"gnc", "vitamin_shoppe", "amazon", "iherb", "manufacturer"}:
            verify = "Exact ingredient/form/amount, seller identity, lot, expiration, and current third-party certification; reject proprietary blends when amounts are hidden"
        elif key == "thrive_market":
            verify = "Ingredient and nutrition labels, package size, subscription terms, storage space, and delivered cost"
        else:
            verify = "Ingredient and nutrition labels, pasteurization where relevant, package condition/date, storage space, and price per usable serving"
        lines.append(f"| {label} | {role} | {verify} |")
    lines.extend([
        "",
        "**PLANNING DEFAULT:** choose one selected store as the first stop for the core list, then use the other selected stores only for missing items, a safer verified product, a practical package size, or a meaningful price difference. Warehouse quantities are optional; apartment storage and likely food waste outrank bulk pricing.",
    ])
    return "\n".join(lines)


@dataclass(frozen=True)
class Candidate:
    key: str
    name: str
    queue: str
    folders: tuple[str, ...]
    issues: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    gate: str = ""
    policy: str = ""


@dataclass
class Evidence:
    coverage: str
    best_grade: str
    unique_papers: int
    unique_dois: int
    fit: str
    hits: list[dict]


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def S(
    name: str,
    queue: str,
    folders: Sequence[str] | str,
    issues: Sequence[str],
    *,
    aliases: Sequence[str] = (),
    gate: str = "",
    policy: str = "",
) -> Candidate:
    if isinstance(folders, str):
        folders = (folders,) if folders else ()
    return Candidate(_key(name), name, queue, tuple(folders), tuple(issues), tuple(aliases), gate, policy)


CATALOG: tuple[Candidate, ...] = (
    # The labels below preserve the user's requested queues. They are not evidence conclusions.
    S("Creatine monohydrate", QUEUE_VERY, "07_supplements/creatine", ("strength", "focus"),
      aliases=("creatine",), policy="CORE/KEEP"),
    S("Protein / whey", QUEUE_VERY,
      ("07_supplements/eaa_bcaa", "07_supplements/general_ods_position_stands",
       "01_food_inflammation/foods_for_body_composition", "01_food_inflammation/milk_body_composition"),
      ("cut", "strength", "endurance"), aliases=("whey", "protein"), policy="FOOD/KEEP"),
    S("Caffeine", QUEUE_VERY, "04_cognition_learning/caffeine", ("endurance", "focus"),
      aliases=("caffeine", "coffee"), policy="OPTIONAL; no use after the locked 11:15 cutoff"),
    S("Omega-3 EPA and DHA", QUEUE_VERY, "01_food_inflammation/omega3", ("heart", "joints"),
      aliases=("omega-3", "omega 3", "epa", "dha")),
    S("Vitamin D3", QUEUE_VERY, ("07_supplements/vitamin_d3", "12_population_AA"),
      ("deficiency", "immune", "strength"), aliases=("vitamin d", "25(oh)d", "cholecalciferol"),
      gate="Test 25(OH)D or establish clinician-documented deficiency; do not assume from skin tone or indoor work.",
      policy="DEFICIENCY-GATED"),
    S("Magnesium", QUEUE_VERY, "07_supplements/magnesium", ("deficiency", "sleep"),
      aliases=("magnesium",), gate="Intake/deficiency and kidney-function gate; not an automatic sleep supplement.",
      policy="INTAKE/CLINICIAN-GATED"),
    S("Melatonin", QUEUE_VERY, ("07_supplements/melatonin", "03_sleep_stress/sleep_food_supplement_lifestyle"),
      ("sleep",), aliases=("melatonin",)),
    S("Zinc", QUEUE_VERY, "07_supplements/zinc", ("deficiency", "immune"), aliases=("zinc",),
      gate="Deficiency/intake gate; chronic excess and copper balance require review.", policy="DEFICIENCY-GATED"),
    S("Beta-alanine", QUEUE_VERY, "07_supplements/beta_alanine", ("endurance",),
      aliases=("beta-alanine", "beta alanine"), policy="SPORT-SPECIFIC"),
    S("Iron if deficient", QUEUE_VERY, "07_supplements/iron", ("deficiency", "endurance"), aliases=("iron", "ferritin"),
      gate="CBC/iron studies and clinician review required; never a blind add.", policy="CLINICIAN-GATED"),
    S("Vitamin B12 if deficient", QUEUE_VERY, "07_supplements/vitamin_b12_folate", ("deficiency",),
      aliases=("vitamin b12", "b12", "cobalamin"), gate="Diet/lab/clinical deficiency gate.", policy="DEFICIENCY-GATED"),
    S("Folate / methylfolate if deficient", QUEUE_VERY, "07_supplements/vitamin_b12_folate", ("deficiency",),
      aliases=("folate", "methylfolate", "folic acid"), gate="Diet/lab/clinical deficiency gate; assess B12 context.",
      policy="DEFICIENCY-GATED"),
    S("Calcium with vitamin D if intake is low", QUEUE_VERY,
      ("07_supplements/calcium_vitamin_k2", "07_supplements/vitamin_d3"), ("deficiency",),
      aliases=("calcium", "vitamin d"), gate="Estimate dietary calcium and assess vitamin D status before considering pills.",
      policy="INTAKE/CLINICIAN-GATED"),
    S("Dietary nitrate / beetroot", QUEUE_VERY, "01_food_inflammation/beets_dietary_nitrate", ("endurance",),
      aliases=("dietary nitrate", "beetroot", "beet juice"), policy="SPORT-SPECIFIC"),
    S("Sodium bicarbonate", QUEUE_VERY, "07_supplements/sodium_bicarbonate", ("endurance",),
      aliases=("sodium bicarbonate", "bicarbonate"), policy="SPORT-SPECIFIC; GI and sodium-load review"),
    S("Psyllium / viscous fiber", QUEUE_VERY,
      ("01_food_inflammation/gut_fiber_ibs", "01_food_inflammation/oats_beta_glucan"),
      ("cut", "gi", "heart"), aliases=("psyllium", "viscous fiber", "soluble fiber"),
      gate="Increase only as tolerated; medication timing and GLP-1 GI symptoms must be considered."),

    S("Ashwagandha (KSM-66 or Sensoril)", QUEUE_MEDIUM, "07_supplements/ashwagandha", ("stress", "sleep", "strength"),
      aliases=("ashwagandha", "ksm-66", "sensoril")),
    S("L-theanine", QUEUE_MEDIUM, "07_supplements/l_theanine", ("focus", "stress"),
      aliases=("l-theanine", "theanine")),
    S("Curcumin / turmeric extract", QUEUE_MEDIUM, ("01_food_inflammation/curcumin", "07_supplements/interactions_stacking"),
      ("joints",), aliases=("curcumin", "turmeric")),
    S("Tart cherry", QUEUE_MEDIUM, "07_supplements/tart_cherry", ("joints", "sleep"), aliases=("tart cherry", "cherry")),
    S("Berberine", QUEUE_MEDIUM, "07_supplements/berberine", ("heart", "cut"), aliases=("berberine",),
      gate="Medication/GI review required, especially with an active glucose-lowering prescription.", policy="MEDICATION-REVIEW"),
    S("Glycine", QUEUE_MEDIUM, "07_supplements/glycine", ("sleep",), aliases=("glycine",)),
    S("Probiotics", QUEUE_MEDIUM,
      ("01_food_inflammation/fermented_foods_overview", "01_food_inflammation/gut_fiber_ibs",
       "01_food_inflammation/fermented_veg_sauerkraut_kimchi"), ("gi", "immune"),
      aliases=("probiotic", "probiotics"), gate="Strain-, condition-, and symptom-specific; not one interchangeable product class."),
    S("Rhodiola rosea", QUEUE_MEDIUM, "07_supplements/rhodiola", ("stress", "endurance", "focus"),
      aliases=("rhodiola", "rhodiola rosea")),
    S("NAC", QUEUE_MEDIUM, "07_supplements/nac", ("immune",), aliases=("n-acetylcysteine", "n-acetyl cysteine", "nac")),
    S("Saffron", QUEUE_MEDIUM, "", ("stress",), aliases=("saffron", "crocin", "safranal")),
    S("Taurine", QUEUE_MEDIUM, "07_supplements/taurine", ("endurance", "heart"), aliases=("taurine",)),
    S("Citrulline / citrulline malate", QUEUE_MEDIUM, "07_supplements/citrulline_arginine", ("strength", "endurance"),
      aliases=("citrulline", "citrulline malate")),
    S("HMB", QUEUE_MEDIUM, "07_supplements/hmb", ("strength", "cut"), aliases=("hmb", "beta-hydroxy-beta-methylbutyrate")),
    S("Collagen peptides for joints and skin", QUEUE_MEDIUM, "07_supplements/collagen_vitc_tendon", ("joints", "skin"),
      aliases=("collagen", "gelatin")),
    S("Vitamin C for cold duration", QUEUE_MEDIUM, "07_supplements/vitamin_c", ("immune",),
      aliases=("vitamin c", "ascorbic acid"), policy="CONDITION-SPECIFIC"),
    S("Garlic", QUEUE_MEDIUM, "", ("heart",), aliases=("garlic", "allium sativum")),
    S("Green tea extract / EGCG", QUEUE_MEDIUM, "07_supplements/egcg_green_tea", ("cut", "heart"),
      aliases=("egcg", "green tea extract", "epigallocatechin"),
      gate="Extract safety differs from brewed tea; liver-risk passages control the verdict.", policy="SAFETY-REVIEW"),
    S("CoQ10", QUEUE_MEDIUM, "07_supplements/coq10_ubiquinol", ("heart", "endurance"),
      aliases=("coq10", "coenzyme q10", "ubiquinol")),
    S("Astaxanthin", QUEUE_MEDIUM, "07_supplements/astaxanthin", ("joints", "skin"), aliases=("astaxanthin",)),
    S("Boswellia", QUEUE_MEDIUM, "07_supplements/boswellia", ("joints",), aliases=("boswellia",)),
    S("Ginger", QUEUE_MEDIUM, "", ("gi", "joints"), aliases=("ginger", "zingiber officinale")),
    S("Phosphatidylserine", QUEUE_MEDIUM, "07_supplements/phosphatidylserine", ("focus", "stress"),
      aliases=("phosphatidylserine",)),
    S("L-tyrosine when sleep-deprived or stressed", QUEUE_MEDIUM, "07_supplements/tyrosine", ("focus", "stress"),
      aliases=("l-tyrosine", "tyrosine"), policy="CONDITION-SPECIFIC"),
    S("Lavender oil / Silexan", QUEUE_MEDIUM, "", ("stress", "sleep"), aliases=("silexan", "lavender oil", "lavandula")),
    S("Beta-glucans", QUEUE_MEDIUM, "01_food_inflammation/oats_beta_glucan", ("heart", "cut", "immune"),
      aliases=("beta-glucan", "beta glucan")),
    S("Polyphenol-rich foods (tart cherry tracked separately)", QUEUE_MEDIUM,
      ("01_food_inflammation/anti_inflammatory_patterns", "01_food_inflammation/whole_foods_nutrient_dense"),
      ("heart", "joints"), aliases=("polyphenol", "polyphenols"), policy="FOOD-FIRST"),
    S("Potassium from food first", QUEUE_MEDIUM, "07_supplements/electrolytes_hydration", ("heart", "endurance"),
      aliases=("potassium",), policy="FOOD-FIRST; supplements require medication/kidney review"),

    S("Lion's mane", QUEUE_LOW, "07_supplements/lions_mane", ("focus",), aliases=("lion's mane", "hericium erinaceus")),
    S("Cordyceps", QUEUE_LOW, "", ("endurance",), aliases=("cordyceps",)),
    S("Turkey tail", QUEUE_LOW, "", ("immune",), aliases=("turkey tail", "trametes versicolor")),
    S("Reishi", QUEUE_LOW, "", ("immune", "sleep"), aliases=("reishi", "ganoderma lucidum")),
    S("Chaga", QUEUE_LOW, "", ("immune",), aliases=("chaga", "inonotus obliquus")),
    S("Tongkat ali", QUEUE_LOW, "07_supplements/tongkat_ali", ("strength", "stress"), aliases=("tongkat", "eurycoma longifolia")),
    S("Tribulus", QUEUE_LOW, "07_supplements/tribulus", ("strength",), aliases=("tribulus", "tribulus terrestris")),
    S("Fenugreek", QUEUE_LOW, "07_supplements/fenugreek", ("strength", "heart"), aliases=("fenugreek",)),
    S("Maca", QUEUE_LOW, "07_supplements/maca", ("stress",), aliases=("maca", "lepidium meyenii")),
    S("Apigenin", QUEUE_LOW, "07_supplements/apigenin", ("sleep",), aliases=("apigenin",)),
    S("Alpha-GPC", QUEUE_LOW, "07_supplements/alpha_gpc", ("focus", "strength"), aliases=("alpha-gpc", "alpha gpc")),
    S("Citicoline", QUEUE_LOW, "07_supplements/citicoline_cdp", ("focus",), aliases=("citicoline", "cdp-choline")),
    S("Acetyl-L-carnitine (ALCAR)", QUEUE_LOW, "07_supplements/l_carnitine_alcar",
      ("focus", "endurance"), aliases=("acetyl-l-carnitine", "acetyl l carnitine", "alcar"),
      gate="Healthy-young-adult cognition and performance evidence must be separated from dementia, depression, or liver-disease studies.",
      policy="LOW-PRIORITY / COVERAGE REQUIRED"),
    S("Uridine monophosphate", QUEUE_LOW, "07_supplements/uridine", ("focus",),
      aliases=("uridine", "uridine monophosphate", "ump"),
      gate="Single-ingredient evidence must be separated from citicoline metabolism and multi-ingredient choline/DHA formulas.",
      policy="LOW-PRIORITY / COVERAGE REQUIRED"),
    S("Phosphatidylcholine", QUEUE_LOW, "", ("focus",), aliases=("phosphatidylcholine",)),
    S("Shilajit", QUEUE_LOW, "07_supplements/shilajit", ("strength",), aliases=("shilajit",)),
    S("Mucuna pruriens", QUEUE_LOW, "", ("focus",), aliases=("mucuna", "mucuna pruriens", "levodopa"),
      gate="Dopaminergic/medication interaction review required.", policy="MEDICATION-REVIEW"),
    S("DHEA", QUEUE_LOW, "", ("strength",), aliases=("dhea", "dehydroepiandrosterone"), policy="CLINICIAN-ONLY"),
    S("Boron", QUEUE_LOW, "07_supplements/boron", ("strength",), aliases=("boron",)),
    S("Ginkgo", QUEUE_LOW, "07_supplements/ginkgo_biloba", ("focus",), aliases=("ginkgo", "ginkgo biloba")),
    S("Panax ginseng", QUEUE_LOW, "07_supplements/panax_ginseng", ("focus", "endurance"), aliases=("panax ginseng", "ginseng")),
    S("Eleuthero", QUEUE_LOW, "", ("stress", "endurance"), aliases=("eleuthero", "eleutherococcus")),
    S("Valerian", QUEUE_LOW, "", ("sleep",), aliases=("valerian", "valeriana officinalis")),
    S("5-HTP", QUEUE_LOW, "07_supplements/l_tryptophan_5htp", ("sleep", "stress"), aliases=("5-htp", "5 htp", "hydroxytryptophan"),
      gate="Serotonergic medication and mental-health review required.", policy="MEDICATION-REVIEW"),
    S("Oral GABA", QUEUE_LOW, "", ("sleep", "stress"), aliases=("oral gaba", "gamma-aminobutyric acid")),
    S("CBD", QUEUE_LOW, "", ("sleep", "stress", "joints"), aliases=("cbd", "cannabidiol"),
      gate="Medication, sedation, product-quality, and legal/workplace review required.", policy="MEDICATION-REVIEW"),
    S("NMN", QUEUE_LOW, "07_supplements/nad_nmn", ("heart",), aliases=("nmn", "nicotinamide mononucleotide")),
    S("NR", QUEUE_LOW, "07_supplements/nad_nmn", ("heart",), aliases=("nicotinamide riboside", " nr ")),
    S("Resveratrol", QUEUE_LOW, "07_supplements/resveratrol", ("heart",), aliases=("resveratrol",)),
    S("Quercetin", QUEUE_LOW, "07_supplements/quercetin", ("immune", "heart"), aliases=("quercetin",)),
    S("Fisetin", QUEUE_LOW, "07_supplements/fisetin", ("heart",), aliases=("fisetin",)),
    S("Spermidine", QUEUE_LOW, "07_supplements/spermidine", ("heart",), aliases=("spermidine",)),
    S("Elderberry", QUEUE_LOW, "", ("immune",), aliases=("elderberry", "sambucus")),
    S("Echinacea", QUEUE_LOW, "", ("immune",), aliases=("echinacea",)),
    S("MSM", QUEUE_LOW, "07_supplements/msm_joint", ("joints",), aliases=("methylsulfonylmethane", " msm ")),
    S("Glucosamine", QUEUE_LOW, "07_supplements/glucosamine_chondroitin", ("joints",), aliases=("glucosamine",)),
    S("Chondroitin", QUEUE_LOW, "07_supplements/glucosamine_chondroitin", ("joints",), aliases=("chondroitin",)),
    S("Hyaluronic acid", QUEUE_LOW, "", ("joints", "skin"), aliases=("hyaluronic acid", "hyaluronan")),
    S("Copper bicarbonate", QUEUE_LOW, "", ("deficiency",), aliases=("copper bicarbonate",), policy="SKIP / COVERAGE REQUIRED"),
    S("Colloidal minerals", QUEUE_LOW, "", ("deficiency",), aliases=("colloidal mineral", "colloidal minerals"), policy="SKIP / COVERAGE REQUIRED"),
    S("Adrenal cocktails", QUEUE_LOW, "14_hormones_thyroid_heart/what_not_to_optimize", ("stress",),
      aliases=("adrenal cocktail", "adrenal fatigue"), policy="SKIP"),
    S("Cortisol detox blends", QUEUE_LOW,
      ("14_hormones_thyroid_heart/what_not_to_optimize", "13_detox/no_detox_protocol"),
      ("stress",), aliases=("cortisol detox", "detox"), policy="SKIP"),
    S("Fat-burner blends", QUEUE_LOW,
      ("07_supplements/supplement_contamination_testing", "14_hormones_thyroid_heart/what_not_to_optimize"),
      ("cut", "heart"), aliases=("fat burner", "fat-burner", "thermogenic"), policy="SKIP"),
    S("Proprietary focus blends", QUEUE_LOW, "07_supplements/supplement_contamination_testing", ("focus",),
      aliases=("proprietary blend", "focus blend"), policy="SKIP"),
    S("High-dose vitamin E", QUEUE_LOW, ("07_supplements/vitamin_e_tocotrienols", "07_supplements/general_ods_position_stands"),
      ("deficiency",), aliases=("vitamin e", "tocopherol"), policy="SKIP unless clinician-indicated"),
    S("High-dose vitamin A", QUEUE_LOW, "07_supplements/general_ods_position_stands", ("deficiency",),
      aliases=("vitamin a", "retinol"), policy="SKIP unless clinician-indicated"),
    S("Beta-carotene in smokers", QUEUE_LOW, "07_supplements/general_ods_position_stands", ("heart",),
      aliases=("beta-carotene", "beta carotene", "smoker"), policy="SKIP"),
    S("BCAAs when protein is already high", QUEUE_LOW, "07_supplements/eaa_bcaa", ("strength",),
      aliases=("bcaa", "branched-chain amino"), policy="SKIP when adequate complete protein is established"),
)

# Separate from the supplement catalog. These are displayed in a dedicated searchable selector.
# Manual selection requests an evidence review. The optional broad research policy scans every
# entry, then surfaces only entries that pass the same two-source human-intervention gate. Neither
# path is interpreted as intent or permission to use a gray-market compound.
PEPTIDE_CATALOG: tuple[Candidate, ...] = (
    S("Tirzepatide (current prescription)", QUEUE_PEPTIDE, "05_fat_loss_drugs/tirzepatide_incretins",
      ("cut", "gi", "heart"), aliases=("tirzepatide",), policy="KEEP-PRESCRIPTION"),
    S("Semaglutide (do not stack with tirzepatide)", QUEUE_PEPTIDE, "08_peptides_gray/semaglutide",
      ("cut", "gi"), aliases=("semaglutide",), policy="SKIP — DO NOT STACK INCRETINS"),
    S("Retatrutide (do not stack with tirzepatide)", QUEUE_PEPTIDE, "08_peptides_gray/retatrutide",
      ("cut", "gi"), aliases=("retatrutide",), policy="SKIP — DO NOT STACK INCRETINS"),
    S("Liraglutide (do not stack with tirzepatide)", QUEUE_PEPTIDE, "05_fat_loss_drugs/liraglutide",
      ("cut", "gi"), aliases=("liraglutide", "saxenda", "victoza"), policy="SKIP — DO NOT STACK INCRETINS"),
    S("Cagrilintide / CagriSema-style combination", QUEUE_PEPTIDE, "05_fat_loss_drugs/cagrilintide",
      ("cut", "gi"), aliases=("cagrilintide", "cagrisema", "amylin analog"),
      policy="SKIP — INVESTIGATIONAL/DO NOT STACK WITH TIRZEPATIDE"),
    S("Survodutide", QUEUE_PEPTIDE, "05_fat_loss_drugs/survodutide",
      ("cut", "gi"), aliases=("survodutide",), policy="SKIP — INVESTIGATIONAL/DO NOT STACK INCRETINS"),
    S("Tesofensine", QUEUE_PEPTIDE, "05_fat_loss_drugs/tesofensine",
      ("cut", "heart"), aliases=("tesofensine",),
      gate="Stimulant/catecholamine, blood-pressure, heart-rate, medication, and regulatory review required.",
      policy="SKIP — UNAPPROVED FAT-LOSS DRUG; NO PERSONAL PROTOCOL"),
    S("MK-677 / ibutamoren", QUEUE_PEPTIDE, "08_peptides_gray/mk677_ibutamoren",
      ("strength", "sleep"), aliases=("mk-677", "mk677", "ibutamoren"), policy="CLINICIAN-ONLY"),
    S("Tesamorelin", QUEUE_PEPTIDE, "08_peptides_gray/tesamorelin",
      ("cut",), aliases=("tesamorelin",), policy="CLINICIAN-ONLY"),
    S("Semax / Selank", QUEUE_PEPTIDE, "08_peptides_gray/semax_selank",
      ("focus", "stress"), aliases=("semax", "selank"), policy="SKIP — NO PERSONAL PROTOCOL"),
    S("Noopept / omberacetam", QUEUE_PEPTIDE,
      ("08_peptides_gray/noopept", "08_peptides_gray/uncertified_quality_risk"),
      ("focus",), aliases=("noopept", "omberacetam", "gvs-111"),
      gate="Unapproved-product identity, label accuracy, interactions, and the lack of direct healthy-user evidence control the verdict.",
      policy="SKIP — GRAY-MARKET NOOTROPIC; NO PERSONAL PROTOCOL"),
    S("Bromantane / Ladasten", QUEUE_PEPTIDE,
      ("08_peptides_gray/bromantane", "08_peptides_gray/uncertified_quality_risk"),
      ("focus", "endurance"), aliases=("bromantane", "bromantan", "ladasten", "actoprotector"),
      gate="Russian asthenia studies are not evidence of benefit for a healthy athlete; product legality, sport rules, and stimulant risk require review.",
      policy="SKIP — UNAPPROVED/SPORT-RULE RISK; NO PERSONAL PROTOCOL"),
    S("BPC-157", QUEUE_PEPTIDE, "08_peptides_gray/bpc157",
      ("joints", "gi"), aliases=("bpc-157", "bpc157"), policy="SKIP — NO PERSONAL PROTOCOL"),
    S("CJC-1295 / ipamorelin", QUEUE_PEPTIDE,
      ("08_peptides_gray/cjc1295", "08_peptides_gray/ipamorelin"),
      ("strength", "sleep"), aliases=("cjc-1295", "cjc1295", "ipamorelin"), policy="CLINICIAN-ONLY"),
    S("Agomelatine", QUEUE_PEPTIDE, "08_peptides_gray/agomelatine",
      ("sleep", "stress"), aliases=("agomelatine",), policy="CLINICIAN-ONLY"),
    S("AICAR", QUEUE_PEPTIDE, "08_peptides_gray/aicar",
      ("endurance", "cut"), aliases=("aicar", "acadesine"), policy="SKIP — RESEARCH DRUG; NO PERSONAL PROTOCOL"),
    S("Aniracetam", QUEUE_PEPTIDE, "08_peptides_gray/aniracetam",
      ("focus",), aliases=("aniracetam",), policy="SKIP — UNAPPROVED NOOTROPIC; NO PERSONAL PROTOCOL"),
    S("AOD-9604", QUEUE_PEPTIDE, "08_peptides_gray/aod9604",
      ("cut",), aliases=("aod-9604", "aod9604"), policy="SKIP — RESEARCH PEPTIDE; NO PERSONAL PROTOCOL"),
    S("Cerebrolysin", QUEUE_PEPTIDE, "08_peptides_gray/cerebrolysin",
      ("focus",), aliases=("cerebrolysin",), policy="CLINICIAN-ONLY"),
    S("Dihexa", QUEUE_PEPTIDE, "08_peptides_gray/dihexa",
      ("focus",), aliases=("dihexa",), policy="SKIP — RESEARCH COMPOUND; NO PERSONAL PROTOCOL"),
    S("DSIP", QUEUE_PEPTIDE, "08_peptides_gray/dsip",
      ("sleep",), aliases=("dsip", "delta sleep inducing peptide"), policy="SKIP — RESEARCH PEPTIDE; NO PERSONAL PROTOCOL"),
    S("Epitalon", QUEUE_PEPTIDE, "08_peptides_gray/epitalon",
      ("sleep",), aliases=("epitalon", "epithalon"), policy="SKIP — RESEARCH PEPTIDE; NO PERSONAL PROTOCOL"),
    S("5-amino-1MQ", QUEUE_PEPTIDE, "08_peptides_gray/five_amino_1mq",
      ("cut",), aliases=("5-amino-1mq", "5 amino 1mq", "nnmt inhibitor"), policy="SKIP — RESEARCH COMPOUND; NO PERSONAL PROTOCOL"),
    S("Follistatin / follistatin gene or peptide products", QUEUE_PEPTIDE, "08_peptides_gray/follistatin",
      ("strength",), aliases=("follistatin",), policy="SKIP — RESEARCH/GROWTH-PATHWAY RISK; NO PERSONAL PROTOCOL"),
    S("GHK-Cu", QUEUE_PEPTIDE, "08_peptides_gray/ghk_cu",
      ("skin",), aliases=("ghk-cu", "ghk cu", "copper peptide"), policy="CLINICIAN-ONLY"),
    S("GHRP-2 / GHRP-6", QUEUE_PEPTIDE, "08_peptides_gray/ghrp2_6",
      ("strength", "sleep"), aliases=("ghrp-2", "ghrp-6", "ghrp2", "ghrp6"), policy="CLINICIAN-ONLY"),
    S("Hexarelin", QUEUE_PEPTIDE, "08_peptides_gray/hexarelin",
      ("strength", "sleep"), aliases=("hexarelin",), policy="CLINICIAN-ONLY"),
    S("Humanin", QUEUE_PEPTIDE, "08_peptides_gray/humanin",
      ("heart",), aliases=("humanin",), policy="SKIP — RESEARCH PEPTIDE; NO PERSONAL PROTOCOL"),
    S("IGF-1 LR3", QUEUE_PEPTIDE, "08_peptides_gray/igf1_lr3",
      ("strength",), aliases=("igf-1 lr3", "igf1 lr3", "long r3 igf"), policy="SKIP — GROWTH-PATHWAY RESEARCH DRUG; NO PERSONAL PROTOCOL"),
    S("ISRIB", QUEUE_PEPTIDE, "08_peptides_gray/isrib",
      ("focus",), aliases=("isrib", "integrated stress response inhibitor"), policy="SKIP — RESEARCH COMPOUND; NO PERSONAL PROTOCOL"),
    S("KPV", QUEUE_PEPTIDE, "08_peptides_gray/kpv",
      ("gi", "skin"), aliases=("kpv", "lys-pro-val"), policy="SKIP — RESEARCH PEPTIDE; NO PERSONAL PROTOCOL"),
    S("LL-37", QUEUE_PEPTIDE, "08_peptides_gray/ll37",
      ("immune", "skin"), aliases=("ll-37", "ll37", "cathelicidin"), policy="SKIP — RESEARCH PEPTIDE; NO PERSONAL PROTOCOL"),
    S("Melanotan", QUEUE_PEPTIDE, "08_peptides_gray/melanotan",
      ("skin",), aliases=("melanotan", "melanotan ii", "melanotan 2"), policy="SKIP — UNAPPROVED PEPTIDE; NO PERSONAL PROTOCOL"),
    S("Methylene blue", QUEUE_PEPTIDE, "08_peptides_gray/methylene_blue",
      ("focus",), aliases=("methylene blue", "methylthioninium"),
      gate="Medication, serotonergic, product-grade, and indication review required.", policy="CLINICIAN-ONLY"),
    S("MGF / PEG-MGF", QUEUE_PEPTIDE, "08_peptides_gray/mgf_mechano_growth",
      ("strength",), aliases=("mechano growth factor", "peg-mgf", "mgf"), policy="SKIP — GROWTH-PATHWAY RESEARCH PEPTIDE; NO PERSONAL PROTOCOL"),
    S("MOTS-c", QUEUE_PEPTIDE, "08_peptides_gray/mots_c",
      ("endurance", "heart"), aliases=("mots-c", "mots c"), policy="SKIP — RESEARCH PEPTIDE; NO PERSONAL PROTOCOL"),
    S("Oxytocin (off-label/experimental optimization)", QUEUE_PEPTIDE, "08_peptides_gray/oxytocin",
      ("stress",), aliases=("oxytocin",), policy="CLINICIAN-ONLY"),
    S("Peptide bioregulators / Khavinson products", QUEUE_PEPTIDE,
      "08_peptides_gray/peptide_bioregulators_khavinson", ("heart", "sleep"),
      aliases=("khavinson", "peptide bioregulator"), policy="SKIP — RESEARCH/PRODUCT-IDENTITY GAP"),
    S("Phenibut", QUEUE_PEPTIDE, "08_peptides_gray/phenibut",
      ("sleep", "stress"), aliases=("phenibut", "beta-phenyl-gaba"),
      gate="Dependence, withdrawal, sedation, and medication/substance interaction review required.",
      policy="SKIP — DEPENDENCE/WITHDRAWAL RISK; NO PERSONAL PROTOCOL"),
    S("PT-141 / bremelanotide", QUEUE_PEPTIDE, "08_peptides_gray/pt141_bremelanotide",
      ("heart",), aliases=("pt-141", "pt141", "bremelanotide"), policy="CLINICIAN-ONLY"),
    S("Racetams (class)", QUEUE_PEPTIDE, "08_peptides_gray/racetams",
      ("focus",), aliases=("racetam", "racetams", "piracetam"), policy="SKIP — UNAPPROVED CLASS; NO PERSONAL PROTOCOL"),
    S("Sermorelin", QUEUE_PEPTIDE, "08_peptides_gray/sermorelin",
      ("strength", "sleep"), aliases=("sermorelin",), policy="CLINICIAN-ONLY"),
    S("SLU-PP-332", QUEUE_PEPTIDE, "08_peptides_gray/slu_pp_332",
      ("endurance", "cut"), aliases=("slu-pp-332", "slu pp 332"), policy="SKIP — PRECLINICAL RESEARCH COMPOUND"),
    S("TAK-653", QUEUE_PEPTIDE, "08_peptides_gray/tak_653",
      ("focus",), aliases=("tak-653", "tak653"), policy="SKIP — INVESTIGATIONAL DRUG; NO PERSONAL PROTOCOL"),
    S("TB-500 / thymosin beta-4", QUEUE_PEPTIDE, "08_peptides_gray/tb500_thymosin_b4",
      ("joints",), aliases=("tb-500", "tb500", "thymosin beta-4", "thymosin beta 4"),
      policy="SKIP — RESEARCH PEPTIDE; NO PERSONAL PROTOCOL"),
    S("Thymosin alpha-1", QUEUE_PEPTIDE, "08_peptides_gray/thymosin_alpha1",
      ("immune",), aliases=("thymosin alpha-1", "thymosin alpha 1", "thymalfasin"), policy="CLINICIAN-ONLY"),
    S("SARMs / non-prescribed anabolic-androgenic drugs (class harm review)", QUEUE_PEPTIDE,
      "08_peptides_gray/ped_sarms_aas_harms", ("strength", "heart"),
      aliases=("sarms", "selective androgen receptor modulator", "anabolic androgenic steroids", "aas"),
      policy="SKIP — CLASS HARM/LEGAL/SPORT-RULE REVIEW; NO CYCLE OR PROTOCOL"),
)

# These are planning routes, not claims that a food recreates an isolated study product or dose.
# The distinction is deliberately explicit: "direct" means ordinary foods provide the nutrient
# or food itself; "partial" means related food constituents exist but are not interchangeable
# with the isolated/standardized form. Unmapped items fail closed as having no practical food
# equivalent established by this planner.
FOOD_DIRECT = "WHOLE-FOOD ROUTE"
FOOD_PARTIAL = "FOOD EXISTS; NOT FORM/DOSE EQUIVALENT"
FOOD_LOCKED = "FOOD EXISTS; LOCKED PRODUCT EXCEPTION"
FOOD_NONE = "NO PRACTICAL WHOLE-FOOD EQUIVALENT MAPPED"

FOOD_SOURCE_ROUTES: dict[str, tuple[str, str]] = {
    "creatine_monohydrate": (FOOD_LOCKED, "Meat and fish contain creatine, but the user's chosen 5 g/day creatine monohydrate remains the locked product."),
    "protein_whey": (FOOD_DIRECT, "Milk/yogurt/cottage cheese, eggs, poultry, fish, lean meat, soy foods, beans, and lentils; whey is a dairy-derived convenience food."),
    "caffeine": (FOOD_DIRECT, "Coffee or tea; keep the locked 11:15 cutoff."),
    "omega_3_epa_and_dha": (FOOD_DIRECT, "Fatty fish such as salmon, sardines, trout, herring, or mackerel."),
    "vitamin_d3": (FOOD_DIRECT, "Fatty fish, egg yolk, and fortified pasteurized dairy or fortified alternatives; deficiency treatment remains lab/clinician-gated."),
    "magnesium": (FOOD_DIRECT, "Pumpkin seeds, nuts, beans/lentils, whole grains, and leafy greens."),
    "melatonin": (FOOD_PARTIAL, "Some foods contain small amounts, but they are not equivalent to a standardized melatonin product."),
    "zinc": (FOOD_DIRECT, "Oysters and other shellfish, beef, dairy, beans, and pumpkin seeds."),
    "beta_alanine": (FOOD_PARTIAL, "Meat, poultry, and fish supply carnosine-related amino acids, not a standardized beta-alanine protocol."),
    "iron_if_deficient": (FOOD_DIRECT, "Meat, shellfish, beans/lentils, tofu, and iron-fortified foods; a confirmed deficiency remains clinician-gated."),
    "vitamin_b12_if_deficient": (FOOD_DIRECT, "Fish, shellfish, meat, eggs, dairy, and B12-fortified foods; a confirmed deficiency remains clinician-gated."),
    "folate_methylfolate_if_deficient": (FOOD_DIRECT, "Leafy greens, beans/lentils, asparagus, avocado, citrus, and fortified grains; methylfolate products are not the same as these foods."),
    "calcium_with_vitamin_d_if_intake_is_low": (FOOD_DIRECT, "Pasteurized milk/yogurt/cottage cheese, calcium-set tofu, sardines with bones, and fortified alternatives."),
    "dietary_nitrate_beetroot": (FOOD_DIRECT, "Beets, arugula, spinach, lettuce, and other nitrate-rich vegetables."),
    "psyllium_viscous_fiber": (FOOD_PARTIAL, "Oats, barley, beans/lentils, chia, flax, fruit, and vegetables provide fiber; psyllium husk is a separate concentrated fiber."),
    "l_theanine": (FOOD_PARTIAL, "Tea naturally contains L-theanine, but amounts vary and are not equivalent to a standardized extract."),
    "curcumin_turmeric_extract": (FOOD_PARTIAL, "Turmeric is a culinary spice; a standardized curcumin extract is not equivalent to seasoning food."),
    "tart_cherry": (FOOD_DIRECT, "Tart cherries, frozen tart cherries, or pasteurized tart-cherry juice."),
    "glycine": (FOOD_DIRECT, "Protein foods plus gelatin-rich foods such as cooked connective tissue or gelatin; amounts vary."),
    "probiotics": (FOOD_PARTIAL, "Pasteurized-culture yogurt/kefir and fermented vegetables can provide live cultures, but strains and counts differ from products."),
    "saffron": (FOOD_PARTIAL, "Saffron is a culinary spice, but food use is not equivalent to a standardized trial extract."),
    "taurine": (FOOD_DIRECT, "Shellfish, fish, dark poultry meat, and red meat."),
    "citrulline_citrulline_malate": (FOOD_PARTIAL, "Watermelon contains citrulline, but is not equivalent to a standardized citrulline or citrulline-malate product."),
    "collagen_peptides_for_joints_and_skin": (FOOD_PARTIAL, "Fish skin, poultry skin, gelatin, and connective-tissue cuts contain collagen-related proteins; hydrolyzed collagen peptides are a processed form."),
    "vitamin_c_for_cold_duration": (FOOD_DIRECT, "Citrus, kiwi, berries, peppers, broccoli, and potatoes."),
    "garlic": (FOOD_DIRECT, "Fresh or cooked garlic."),
    "green_tea_extract_egcg": (FOOD_PARTIAL, "Brewed green tea supplies catechins, but it is not dose-equivalent to concentrated EGCG extract."),
    "coq10": (FOOD_PARTIAL, "Organ meats, sardines, meat, and some nuts contain CoQ10 in food amounts, not standardized product amounts."),
    "astaxanthin": (FOOD_DIRECT, "Salmon, trout, shrimp, crab, and other red/orange seafood."),
    "ginger": (FOOD_DIRECT, "Fresh, frozen, or dried culinary ginger."),
    "phosphatidylserine": (FOOD_PARTIAL, "Soy foods, egg yolk, fish, and organ meats contain phospholipids; they are not equivalent to a standardized phosphatidylserine product."),
    "l_tyrosine_when_sleep_deprived_or_stressed": (FOOD_DIRECT, "Protein foods such as dairy, eggs, poultry, fish, meat, soy, beans, and lentils."),
    "beta_glucans": (FOOD_DIRECT, "Oats, barley, and edible mushrooms; beta-glucan structure differs by source."),
    "polyphenol_rich_foods_tart_cherry_tracked_separately": (FOOD_DIRECT, "Berries, cherries, grapes, cocoa, tea, herbs, spices, and colorful vegetables."),
    "potassium_from_food_first": (FOOD_DIRECT, "Potatoes, beans/lentils, yogurt, fruit, leafy greens, squash, and other vegetables."),
    "lion_s_mane": (FOOD_PARTIAL, "The edible fruiting body can be used as food; extracts are not equivalent."),
    "cordyceps": (FOOD_PARTIAL, "Whole culinary cordyceps products exist, but species, identity, and extracts are not interchangeable."),
    "turkey_tail": (FOOD_PARTIAL, "Whole mushroom/tea preparations exist, but are not ordinary food or equivalent to standardized extracts."),
    "reishi": (FOOD_PARTIAL, "Whole mushroom/tea preparations exist, but are not ordinary food or equivalent to standardized extracts."),
    "chaga": (FOOD_PARTIAL, "Whole tea preparations exist, but are not ordinary food or equivalent to standardized extracts."),
    "fenugreek": (FOOD_PARTIAL, "Fenugreek seed is a culinary spice/food; standardized extracts are not equivalent."),
    "maca": (FOOD_PARTIAL, "Maca root powder is food-like; concentrated extracts are not equivalent."),
    "apigenin": (FOOD_PARTIAL, "Parsley, celery, and chamomile contain apigenin-related flavonoids in variable food amounts."),
    "phosphatidylcholine": (FOOD_DIRECT, "Egg yolks, soy foods, meat, fish, and dairy provide phosphatidylcholine/choline."),
    "boron": (FOOD_DIRECT, "Prunes/raisins, avocado, nuts, beans/lentils, and fruit."),
    "resveratrol": (FOOD_PARTIAL, "Grapes, berries, and peanuts contain resveratrol in food amounts; alcohol is not required."),
    "quercetin": (FOOD_DIRECT, "Onions, apples, capers, berries, and leafy vegetables."),
    "fisetin": (FOOD_PARTIAL, "Strawberries, apples, grapes, and persimmon contain fisetin in variable food amounts."),
    "spermidine": (FOOD_DIRECT, "Wheat germ, mushrooms, legumes, whole grains, and aged cheese."),
    "elderberry": (FOOD_PARTIAL, "Commercial cooked elderberry foods exist; they are not equivalent to a standardized extract."),
    "glucosamine": (FOOD_PARTIAL, "Shellfish shells/cartilage foods and broths are not reliable equivalents to a standardized glucosamine product."),
    "chondroitin": (FOOD_PARTIAL, "Animal cartilage and connective-tissue foods are not reliable equivalents to a standardized chondroitin product."),
    "hyaluronic_acid": (FOOD_PARTIAL, "Skin/connective-tissue foods and broths are not reliable equivalents to an oral hyaluronic-acid product."),
    "copper_bicarbonate": (FOOD_PARTIAL, "Liver, shellfish, nuts, seeds, cocoa, and legumes provide copper; they do not provide a reason to use copper bicarbonate."),
    "high_dose_vitamin_e": (FOOD_DIRECT, "Nuts, seeds, avocado, and plant oils provide vitamin E; this does not justify a high-dose product."),
    "high_dose_vitamin_a": (FOOD_DIRECT, "Liver, eggs, and dairy provide preformed vitamin A; carrots, sweet potatoes, and greens provide carotenoids; this does not justify a high-dose product."),
    "beta_carotene_in_smokers": (FOOD_DIRECT, "Carrots, sweet potatoes, squash, and leafy greens provide food carotenoids; this is not a supplement recommendation."),
    "bcaas_when_protein_is_already_high": (FOOD_DIRECT, "Complete protein foods such as dairy, eggs, meat, fish, poultry, and soy already provide BCAAs."),
}


def food_source_for(candidate: Candidate) -> tuple[str, str]:
    if candidate.queue == QUEUE_PEPTIDE:
        return FOOD_NONE, "Experimental drugs/peptides are not replaced by foods; keep the clinical or skip verdict."
    return FOOD_SOURCE_ROUTES.get(
        candidate.key,
        (FOOD_NONE, "No meaningful ordinary whole-food equivalent is established in this planner; do not invent one."),
    )


def _normal(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _contains(text: str, terms: Iterable[str]) -> bool:
    norm = " " + _normal(text) + " "
    for term in terms:
        t = _normal(term)
        if t and (" " + t + " ") in norm:
            return True
    return False


def _matches_entry(candidate: Candidate, entries: str) -> bool:
    terms = (candidate.name, candidate.key.replace("_", " "), *candidate.aliases)
    return _contains(entries, terms)


def candidate_is_current(candidate: Candidate, profile: dict) -> bool:
    if candidate.key in set(profile.get("current_supplement_keys", ())):
        return True
    if _matches_entry(candidate, profile.get("current_supplements", "")):
        return True
    if candidate.key == "caffeine":
        caffeine = profile.get("caffeine", "").lower()
        return bool(caffeine) and "no caffeine" not in caffeine and not caffeine.startswith("none")
    if candidate.policy == "KEEP-PRESCRIPTION":
        return _matches_entry(candidate, profile.get("medications", ""))
    return False


def select_from_catalog(raw: str | None, catalog: Sequence[Candidate], *, default_all: bool) -> list[Candidate]:
    if not raw:
        return list(catalog) if default_all else []
    if raw.strip().lower() in {"none", "off", "no"}:
        return []
    wanted = [x.strip() for x in raw.split(",") if x.strip()]
    selected: list[Candidate] = []
    missing: list[str] = []
    for value in wanted:
        target = _normal(value)
        exact = [
            c for c in catalog
            if target in {_normal(c.key), _normal(c.name), *(_normal(alias) for alias in c.aliases)}
        ]
        matches = exact or [
            c for c in catalog
            if _contains(c.name + " " + " ".join(c.aliases), (value,))
        ]
        if not matches:
            missing.append(value)
            continue
        for c in matches:
            if c not in selected:
                selected.append(c)
    if missing:
        raise SystemExit("Unknown --items value(s): %s. Use --list to see catalog names." % ", ".join(missing))
    return selected


def select_candidates(raw: str | None) -> list[Candidate]:
    return select_from_catalog(raw, CATALOG, default_all=True)


def parse_issue_codes(raw: str) -> list[str]:
    out = []
    for token in [x.strip().lower() for x in raw.split(",") if x.strip()]:
        if token.isdigit() and 1 <= int(token) <= len(ISSUES):
            key = list(ISSUES)[int(token) - 1]
        else:
            key = next((k for k, label in ISSUES.items() if token == k or token in label.lower()), "")
        if key and key not in out:
            out.append(key)
    return out


def ask_profile_quick() -> dict:
    """Default guided assessment: short explained sections and almost no typing."""
    console.print(Panel.fit(
        "[bold]HealthCoach Guided Assessment[/bold]\n\n"
        "You will see 9 short, explained sections. Checked answers are included in your report.\n"
        "Use ↑/↓ to move, Space to change a box, / to search long lists, and Enter to continue.\n"
        "Pressing Enter keeps the checked defaults. Selecting an item asks HealthCoach to evaluate it;\n"
        "it does not automatically recommend or prescribe it. A final review appears before research starts.",
        border_style="bright_cyan", padding=(1, 3),
    ))

    supplement_options = [(c.key, c.name) for c in CATALOG]
    peptide_options = tuple((c.key, c.name) for c in PEPTIDE_CATALOG)
    selected: list[str] = []

    def run_step(
        number: int,
        title: str,
        description: str,
        groups: Sequence[tuple[str, str, Sequence[tuple[str, str]], Sequence[str]]],
        *,
        exclusive: Sequence[str] = (),
    ) -> None:
        choices: list[tuple[str, str]] = []
        defaults: list[str] = []
        group_values: dict[str, list[str]] = {}
        for prefix, display, options, group_defaults in groups:
            group_values[prefix] = []
            for value, label in options:
                qualified = f"{prefix}::{value}"
                choices.append((qualified, f"{display:<18} │ {label}"))
                group_values[prefix].append(qualified)
                if value in group_defaults:
                    defaults.append(qualified)
        selected.extend(checkbox_prompt(
            f"STEP {number} OF 9 — {title}",
            choices,
            description=description,
            defaults=defaults,
            exclusive_groups=tuple(group_values[prefix] for prefix in exclusive),
        ))

    run_step(1, "GOALS AND CURRENT ACTIVITY",
             "Choose your goals and the activities currently in your week.", (
        ("issue", "GOAL", tuple(ISSUES.items()), ("cut", "strength", "endurance")),
        ("training", "DOING NOW", TRAINING_OPTIONS, ("lifting", "running", "cycling", "walking")),
    ))
    run_step(2, "SCHEDULE AND INJURIES",
             "Choose one cardio time, one strength time, and any pain areas.", (
        ("cardio", "CARDIO · ONE", CARDIO_TIMING_OPTIONS, ("recommend",)),
        ("workout", "STRENGTH · ONE", WORKOUT_TIMING_OPTIONS, ("recommend",)),
        ("injury", "PAIN / INJURY", INJURY_OPTIONS, ("none_reported",)),
    ), exclusive=("cardio", "workout"))
    run_step(3, "WHAT YOU TAKE NOW",
             "Select only supplements you use now. Press / to search by name.", (
        ("taking", "TAKING NOW", supplement_options, ("creatine_monohydrate",)),
    ))
    run_step(4, "MEDICINES AND SAFETY",
             "Record results, medicines, known risks, confirmed labs, and reactions.", (
        ("result", "RESULT SO FAR", SUPPLEMENT_RESULT_OPTIONS, ("not_tracked",)),
        ("medication", "MEDICATION", MEDICATION_OPTIONS, ("tirzepatide",)),
        ("safety", "HEALTH FLAG", SAFETY_OPTIONS, ("none_known",)),
        ("deficiency", "CONFIRMED LAB", DEFICIENCY_OPTIONS, ("none_unknown",)),
        ("reaction", "PAST REACTION", REACTION_OPTIONS, ("none_reported",)),
    ))
    run_step(5, "SUPPLEMENTS TO INVESTIGATE",
             "Choose one intake route, then topics to research. Food-first applies only where a meaningful whole-food route exists; it never invents a food substitute for a drug or isolated compound.", (
        ("supplement_source", "SOURCE · ONE", SUPPLEMENT_SOURCE_OPTIONS, ("whole_food_first",)),
        ("review", "RESEARCH", supplement_options, (
            "creatine_monohydrate", "protein_whey", "caffeine",
            "omega_3_epa_and_dha", "vitamin_d3", "magnesium",
        )),
    ), exclusive=("supplement_source",))
    run_step(6, "PEPTIDE / GRAY-MARKET RESEARCH",
             "Choose one research boundary, then optionally select named items. Broad scan means evidence triage—not approval, compatibility, or a dosing plan.", (
        ("experimental", "BOUNDARY · ONE", EXPERIMENTAL_POLICY_OPTIONS, ("approved_only",)),
        ("peptide", "RESEARCH", peptide_options, ("tirzepatide_current_prescription",)),
    ), exclusive=("experimental",))
    run_step(7, "FOOD, SLEEP, CAFFEINE, AND SUBSTANCES",
             "Choose current patterns or symptoms so the plan avoids conflicts.", (
        ("diet", "FOOD / GI", DIET_GI_OPTIONS, ("none_reported",)),
        ("sleep", "SLEEP", SLEEP_OPTIONS, ("none_reported",)),
        ("caffeine", "CAFFEINE", CAFFEINE_OPTIONS, ("coffee",)),
        ("substance", "OTHER USE", SUBSTANCE_OPTIONS, ("none_reported",)),
    ))
    run_step(8, "FOOD, HOME, FAITH, AND OTHER IDEAS",
             "Choose ideas to evaluate or fit into the plan—not endorse.", (
        ("food", "FOOD IDEA", FOOD_ADDITION_OPTIONS, ("pasteurized_dairy", "potatoes_rice", "animal_protein", "fruit_carbs", "fiber_food")),
        ("home", "HOME / FAITH", HOME_PRACTICE_OPTIONS, ("bible_prayer", "morning_light", "water_quality", "breathwork")),
        ("alternative", "CLAIM TO CHECK", ALTERNATIVE_ITEM_OPTIONS, ()),
    ))
    run_step(9, "SHOPPING AND DEADLINE",
             "Choose your stores, buying priorities, and one deadline answer.", (
        ("store", "STORE · MULTI", STORE_OPTIONS, ("costco",)),
        ("preference", "BUYING RULE", PRODUCT_OPTIONS, ("third_party", "fewest_items")),
        ("timeline", "DEADLINE · ONE", TIMELINE_OPTIONS, ("none",)),
        ("detail", "OPTIONAL NOTE", (("add_note", "I need to add one short detail not covered above"),), ()),
    ), exclusive=("timeline",))

    def picked(prefix: str) -> list[str]:
        marker = f"{prefix}::"
        return [value[len(marker):] for value in selected if value.startswith(marker)]

    def without_sentinel(values: list[str], sentinel: str) -> list[str]:
        return [value for value in values if value != sentinel] if len(values) > 1 else values

    def one(prefix: str, fallback: str) -> str:
        values = picked(prefix)
        non_default = [value for value in values if value != fallback]
        return non_default[-1] if non_default else (values[-1] if values else fallback)

    issues = picked("issue") or ["cut", "strength", "endurance"]
    training_modes = picked("training") or ["lifting", "running", "cycling", "walking"]
    cardio_timing = one("cardio", "recommend")
    workout_timing = one("workout", "recommend")
    injury_keys = without_sentinel(picked("injury") or ["none_reported"], "none_reported")
    current_supplement_keys = picked("taking") or ["creatine_monohydrate"]
    result_keys = without_sentinel(picked("result") or ["not_tracked"], "not_tracked")
    interest_keys = picked("review")
    supplement_source = one("supplement_source", "whole_food_first")
    peptide_keys = picked("peptide")
    experimental_policy = one("experimental", "approved_only")
    medication_keys = picked("medication") or ["tirzepatide"]
    condition_keys = without_sentinel(picked("safety") or ["none_known"], "none_known")
    deficiency_keys = without_sentinel(picked("deficiency") or ["none_unknown"], "none_unknown")
    reaction_keys = without_sentinel(picked("reaction") or ["none_reported"], "none_reported")
    diet_keys = without_sentinel(picked("diet") or ["none_reported"], "none_reported")
    sleep_keys = without_sentinel(picked("sleep") or ["none_reported"], "none_reported")
    caffeine_keys = without_sentinel(picked("caffeine") or ["coffee"], "none")
    substance_keys = without_sentinel(picked("substance") or ["none_reported"], "none_reported")
    food_addition_keys = picked("food")
    home_practice_keys = picked("home")
    alternative_item_keys = picked("alternative")
    store_keys = picked("store")
    preference_keys = picked("preference")
    timeline_keys = [one("timeline", "none")]

    detail_needs: list[str] = []
    if cardio_timing in {"morning", "both"} or workout_timing in {"morning", "both"}:
        detail_needs.append("exact available morning window / what may move")
    if any(value != "none_reported" for value in injury_keys):
        detail_needs.append("injury location, severity, and aggravating movement")
    if any(value != "creatine_monohydrate" for value in current_supplement_keys):
        detail_needs.append("amount/form of non-creatine supplements currently taken")
    if any(value != "not_tracked" for value in result_keys):
        detail_needs.append("which supplement caused each reported result")
    if "other" in medication_keys:
        detail_needs.append("other medication name")
    if any(value != "none_known" for value in condition_keys):
        detail_needs.append("selected medical/safety-flag context")
    if any(value != "none_unknown" for value in deficiency_keys):
        detail_needs.append("lab name, value/units, and date if known")
    if any(value != "none_reported" for value in reaction_keys):
        detail_needs.append("product and reaction")
    if "other" in training_modes or "other" in diet_keys:
        detail_needs.append("selected other training/diet item")
    if any(value != "none_reported" for value in substance_keys):
        detail_needs.append("substance amount, frequency, and latest time")
    if timeline_keys != ["none"]:
        detail_needs.append("race/deadline and exact date if known")
    if {"butter_stick", "banana_water", "milk_diet"}.intersection(food_addition_keys):
        detail_needs.append("ambiguous food/recipe meaning")
    if picked("detail"):
        detail_needs.append("your extra note")

    # Only ambiguous or safety-relevant selections unlock one consolidated text
    # field; the guided path never starts a chain of open-ended questions.
    if detail_needs:
        console.print(Panel(
            "One short line is needed to interpret the selected answers safely:\n- "
            + "\n- ".join(dict.fromkeys(detail_needs)),
            title="Limited detail needed", border_style="yellow",
        ))
        notes = Prompt.ask(
            "One concise detail line (Enter records unknown)",
            default="unknown/not provided",
        ).strip() or "unknown/not provided"
    else:
        notes = "none needed; checkbox answers were sufficient"

    current_names = []
    for c in CATALOG:
        if c.key not in current_supplement_keys:
            continue
        if c.key == "creatine_monohydrate":
            current_names.append("Creatine monohydrate 5 g/day")
        else:
            current_names.append(f"{c.name} (amount/form not entered in guided assessment)")

    cardio_clock = (
        "morning selection must preserve or explicitly resolve the locked 04:50–05:50 Anki block"
        if cardio_timing in {"morning", "both"}
        else "use the locked 17:00 training window; no additional timing limit selected"
    )
    workout_clock = (
        "morning selection must preserve or explicitly resolve the locked 04:50–05:50 Anki block"
        if workout_timing in {"morning", "both"}
        else "use the locked 17:00 training window; no additional timing limit selected"
    )
    issue_labels = [ISSUES[x] for x in issues]
    profile = {
        "assessment_mode": "Nine-step guided assessment with at most one conditional detail line",
        "assessment_notes": notes,
        "name": "Michael",
        "age": 26,
        "height": "unknown/not entered in guided assessment",
        "location": "Dallas, Texas",
        "body_context": "about 230 lb; Phase A goal 200 lb; Phase B goal 190 lb",
        "issues": issues,
        "issue_labels": issue_labels,
        "goals": "; ".join(issue_labels),
        "priorities": "1) keep muscle/strength, 2) lose fat, 3) improve running; revise in final note if needed",
        "training": f"{'; '.join(labels_for(training_modes, TRAINING_OPTIONS))}; locked three-lift hybrid week; detailed mileage not entered",
        "cardio_timing": cardio_timing,
        "cardio_timing_label": dict(CARDIO_TIMING_OPTIONS)[cardio_timing],
        "cardio_clock_constraints": cardio_clock,
        "workout_timing": workout_timing,
        "workout_timing_label": dict(WORKOUT_TIMING_OPTIONS)[workout_timing],
        "workout_clock_constraints": workout_clock,
        "injuries": "; ".join(labels_for(injury_keys, INJURY_OPTIONS)) or "none reported",
        "current_supplements": "; ".join(current_names) or "none selected",
        "current_supplement_keys": current_supplement_keys,
        "supplement_results": "; ".join(labels_for(result_keys, SUPPLEMENT_RESULT_OPTIONS)) or "not tracked",
        "priority_supplement_keys": interest_keys,
        "priority_supplements": [c.name for c in CATALOG if c.key in interest_keys],
        "supplement_source": supplement_source,
        "supplement_source_label": dict(SUPPLEMENT_SOURCE_OPTIONS)[supplement_source],
        "selected_peptide_keys": peptide_keys,
        "selected_peptides": [c.name for c in PEPTIDE_CATALOG if c.key in peptide_keys],
        "experimental_policy": experimental_policy,
        "experimental_policy_label": dict(EXPERIMENTAL_POLICY_OPTIONS)[experimental_policy],
        "medications": "; ".join(labels_for(medication_keys, MEDICATION_OPTIONS)) or "none reported",
        "confirmed_deficiencies_or_labs": "; ".join(labels_for(deficiency_keys, DEFICIENCY_OPTIONS)) or "none/unknown",
        "conditions_and_safety_flags": "; ".join(labels_for(condition_keys, SAFETY_OPTIONS)) or "none known",
        "vitals": "unknown/not entered in guided assessment",
        "prior_reactions": "; ".join(labels_for(reaction_keys, REACTION_OPTIONS)) or "none reported",
        "diet_and_gi": "; ".join(labels_for(diet_keys, DIET_GI_OPTIONS)) or "none reported",
        "food_addition_keys": food_addition_keys,
        "food_additions": labels_for(food_addition_keys, FOOD_ADDITION_OPTIONS),
        "home_practice_keys": home_practice_keys,
        "home_practices": labels_for(home_practice_keys, HOME_PRACTICE_OPTIONS),
        "alternative_item_keys": alternative_item_keys,
        "alternative_items": labels_for(alternative_item_keys, ALTERNATIVE_ITEM_OPTIONS),
        "store_keys": store_keys,
        "shopping_stores": labels_for(store_keys, STORE_OPTIONS),
        "whole_life_details": f"apartment now; include house options; Christian Bible/Jesus learning; assessment detail: {notes}",
        "caffeine": f"{'; '.join(labels_for(caffeine_keys, CAFFEINE_OPTIONS)) or 'none'}; amount not entered; none after 11:15",
        "sleep": f"{'; '.join(labels_for(sleep_keys, SLEEP_OPTIONS)) or 'none reported'}; locked target 20:15–04:30",
        "substances": "; ".join(labels_for(substance_keys, SUBSTANCE_OPTIONS)) or "none reported",
        "preferences": "; ".join(labels_for(preference_keys, PRODUCT_OPTIONS)) or "none selected",
        "timeline": "; ".join(labels_for(timeline_keys, TIMELINE_OPTIONS)),
        "locked_context": "tirzepatide unchanged; creatine 5 g/day; caffeine cutoff 11:15; no gray-market protocols",
    }

    def summary(values: Sequence[str], limit: int = 4) -> str:
        clean = [str(value) for value in values if value]
        if not clean:
            return "None selected"
        suffix = f"; +{len(clean) - limit} more" if len(clean) > limit else ""
        return "; ".join(clean[:limit]) + suffix

    review = Table(title="Review before HealthCoach starts the research", box=box.ROUNDED, border_style="bright_cyan")
    review.add_column("Section", style="bold cyan", no_wrap=True)
    review.add_column("Recorded answer", overflow="fold")
    review.add_row("Goals", summary(profile["issue_labels"]))
    review.add_row("Current activity", summary(labels_for(training_modes, TRAINING_OPTIONS)))
    review.add_row("Training time", f"Cardio: {profile['cardio_timing_label']}; strength: {profile['workout_timing_label']}")
    review.add_row("Pain / injury", profile["injuries"])
    review.add_row("Taking now", summary(current_names))
    review.add_row("Supplement research", summary(profile["priority_supplements"]))
    review.add_row("Supplement source", profile["supplement_source_label"])
    review.add_row("Peptide research", summary(profile["selected_peptides"]))
    review.add_row("Experimental boundary", profile["experimental_policy_label"])
    review.add_row("Medicines / safety", f"{profile['medications']}; {profile['conditions_and_safety_flags']}")
    review.add_row("Food / sleep", f"{profile['diet_and_gi']}; {profile['sleep']}")
    review.add_row("Stores", summary(profile["shopping_stores"]))
    review.add_row("Extra detail", notes)
    console.print("\n", review)
    console.print("[dim]Generate uses these answers. Restart repeats the guided assessment. Cancel exits without changing the report.[/dim]")
    action = Prompt.ask(
        "What should HealthCoach do?",
        choices=("generate", "restart", "cancel"),
        default="generate",
        show_choices=True,
    )
    if action == "restart":
        return ask_profile_quick()
    if action == "cancel":
        raise SystemExit("Assessment cancelled; the existing report was not changed.")
    return profile


def ask_profile_detailed() -> dict:
    console.print(Panel.fit(
        "[bold]Personalized Supplement Evidence Audit[/bold]\n"
        "Use ↑/↓ to move, Space to select, and Enter to finish each checklist.\n"
        "Your answers stay on this Mac. This does not diagnose deficiencies or change prescriptions.",
        border_style="bright_cyan", padding=(1, 3),
    ))
    name = Prompt.ask("Name for the report", default="Michael")
    height = Prompt.ask("Height (or 'unknown')", default="unknown")

    console.rule("[bold bright_cyan]Goals and training[/bold bright_cyan]")
    issues = checkbox_prompt(
        "What do you want help with?",
        list(ISSUES.items()),
        defaults=("cut", "strength", "endurance"),
        minimum=1,
    )
    goals = Prompt.ask("Describe the top 1–3 problems in your own words", default="preserve muscle while cutting and improve running")
    priorities = Prompt.ask(
        "Rank the outcomes that matter most",
        default="1) keep muscle/strength, 2) lose fat, 3) improve running",
    )
    training_modes = checkbox_prompt(
        "Which training and movement modes are currently in the week?",
        TRAINING_OPTIONS,
        defaults=("lifting", "running", "cycling", "walking"),
        minimum=1,
    )
    cardio_timing_values = checkbox_prompt(
        "When should cardio be scheduled? Choose one.",
        CARDIO_TIMING_OPTIONS,
        defaults=("recommend",),
        minimum=1,
        maximum=1,
    )
    cardio_timing = cardio_timing_values[0]
    if cardio_timing in {"morning", "both"}:
        cardio_clock = Prompt.ask(
            "A full morning session conflicts with the locked 04:50–05:50 Anki block. What may move or how much morning time is truly available?",
            default="do not move the 04:30 wake or Anki block; use only a short easy morning movement slot",
        )
    else:
        cardio_clock = Prompt.ask(
            "Any timing limits beyond the 17:00 training and 20:15 bed windows?",
            default="none additional",
        )
    workout_timing_values = checkbox_prompt(
        "When should strength workouts be scheduled? Choose one.",
        WORKOUT_TIMING_OPTIONS,
        defaults=("recommend",),
        minimum=1,
        maximum=1,
    )
    workout_timing = workout_timing_values[0]
    if workout_timing in {"morning", "both"}:
        workout_clock = Prompt.ask(
            "Morning strength work also conflicts with the locked Anki block. What may move, or what exact morning window is available?",
            default="do not move the 04:30 wake or Anki block; keep full strength sessions in the evening",
        )
    else:
        workout_clock = Prompt.ask(
            "Any strength-workout timing limits beyond 17:00 training and 20:15 bed?",
            default="none additional",
        )
    training = Prompt.ask(
        "Add weekly frequency, running mileage, longest recent run, experience, and consistency",
        default="3 lifting days; returning to running; current mileage unknown",
    )
    injuries = Prompt.ask("Current pain, recent injuries, or movements that aggravate symptoms", default="none reported")

    console.rule("[bold bright_cyan]Stack and medical gates[/bold bright_cyan]")
    supplement_choices = [
        (c.key, f"{c.name}  ·  {c.queue.replace('Submitted: ', '')}") for c in CATALOG
    ]
    current_supplement_keys = checkbox_prompt(
        "Which supplements are currently being used?",
        supplement_choices,
        defaults=("creatine_monohydrate",),
    )
    current_names = [c.name for c in CATALOG if c.key in current_supplement_keys]
    current_details = Prompt.ask(
        "Amounts/forms/brands for selected supplements, plus anything not listed",
        default="creatine monohydrate 5 g/day" if current_supplement_keys else "none",
    )
    current = "; ".join(current_names + ([current_details] if current_details and current_details != "none" else [])) or "none"
    supplement_results = Prompt.ask(
        "Observed result for each current supplement (benefit, no effect, side effect, duration, and whether it matters)",
        default="no results recorded yet",
    )

    interest_keys = checkbox_prompt(
        "Which supplement topics must receive priority deep reviews?",
        supplement_choices,
        defaults=(
            "creatine_monohydrate", "protein_whey", "caffeine",
            "omega_3_epa_and_dha", "vitamin_d3", "magnesium",
        ),
    )
    interest_names = [c.name for c in CATALOG if c.key in interest_keys]
    supplement_source_values = checkbox_prompt(
        "How should HealthCoach source nutrients and supplement-like compounds? Choose one.",
        SUPPLEMENT_SOURCE_OPTIONS,
        defaults=("whole_food_first",),
        minimum=1,
        maximum=1,
    )
    supplement_source = supplement_source_values[0]

    peptide_choices = [(c.key, c.name) for c in PEPTIDE_CATALOG]
    experimental_policy_values = checkbox_prompt(
        "Should HealthCoach broad-scan experimental/unapproved drugs? Choose one. This changes research scope only.",
        EXPERIMENTAL_POLICY_OPTIONS,
        defaults=("approved_only",),
        minimum=1,
        maximum=1,
    )
    experimental_policy = experimental_policy_values[0]
    peptide_keys = checkbox_prompt(
        "Which peptides, incretins, or gray-market compounds should be reviewed? Selection is research-only.",
        peptide_choices,
        defaults=("tirzepatide_current_prescription",),
    )
    peptide_names = [c.name for c in PEPTIDE_CATALOG if c.key in peptide_keys]

    medication_keys = checkbox_prompt(
        "Which medications or prescriptions are currently used?",
        MEDICATION_OPTIONS,
        defaults=("tirzepatide",),
    )
    medication_names = labels_for(medication_keys, MEDICATION_OPTIONS)
    medication_details = Prompt.ask(
        "Medication details needed for interaction screening (names are enough; dose is optional)",
        default="none additional",
    )
    medications = "; ".join(
        medication_names + ([medication_details] if medication_details and medication_details != "none additional" else [])
    ) or "none reported"
    deficiencies = Prompt.ask(
        "Clinician-confirmed deficiencies or abnormal labs, including date/units if known",
        default="none/unknown",
    )
    condition_keys = checkbox_prompt(
        "Which medical or safety flags apply?",
        SAFETY_OPTIONS,
        defaults=("none_known",),
    )
    if len(condition_keys) > 1 and "none_known" in condition_keys:
        condition_keys.remove("none_known")
    condition_details = Prompt.ask("Details for selected safety flags", default="none additional")
    conditions = "; ".join(
        labels_for(condition_keys, SAFETY_OPTIONS)
        + ([condition_details] if condition_details and condition_details != "none additional" else [])
    ) or "none reported"
    vitals = Prompt.ask("Known recent blood pressure, resting heart rate, or other relevant measurements", default="unknown")
    reactions = Prompt.ask("Prior supplement side effects, allergies, or products that did not agree with you", default="none reported")

    console.rule("[bold bright_cyan]Food, sleep, and lifestyle[/bold bright_cyan]")
    diet_keys = checkbox_prompt(
        "Which diet patterns or GI symptoms apply?",
        DIET_GI_OPTIONS,
        defaults=("none_reported",),
    )
    if len(diet_keys) > 1 and "none_reported" in diet_keys:
        diet_keys.remove("none_reported")
    diet_details = Prompt.ask("Food exclusions, GI timing, frequency, and known triggers", default="none additional")
    diet = "; ".join(
        labels_for(diet_keys, DIET_GI_OPTIONS)
        + ([diet_details] if diet_details and diet_details != "none additional" else [])
    ) or "none reported"

    console.rule("[bold bright_cyan]Food additions and apartment/home practices[/bold bright_cyan]")
    food_addition_keys = checkbox_prompt(
        "Which food additions should the report evaluate and fit into the plan?",
        FOOD_ADDITION_OPTIONS,
        defaults=("pasteurized_dairy", "potatoes_rice", "animal_protein", "fruit_carbs", "fiber_food"),
    )
    home_practice_keys = checkbox_prompt(
        "Which apartment/home practices should the report evaluate?",
        HOME_PRACTICE_OPTIONS,
        defaults=("bible_prayer", "morning_light", "water_quality", "breathwork"),
    )
    alternative_item_keys = checkbox_prompt(
        "Which alternative products or claims should receive an evidence/safety verdict?",
        ALTERNATIVE_ITEM_OPTIONS,
        defaults=(),
    )
    whole_life_details = Prompt.ask(
        "Clarify selected ambiguous items, housing limits (balcony/drainage/lease), faith tradition, or desired outcome",
        default="apartment now; also show house options; Christian Bible/Jesus learning; no additional clarification",
    )

    caffeine_keys = checkbox_prompt(
        "Which caffeine sources are used?",
        CAFFEINE_OPTIONS,
        defaults=("coffee",),
    )
    if len(caffeine_keys) > 1 and "none" in caffeine_keys:
        caffeine_keys.remove("none")
    caffeine_details = Prompt.ask(
        "Daily caffeine amount and latest usual time",
        default="amount unknown; none after 11:15",
    )
    caffeine = "; ".join(labels_for(caffeine_keys, CAFFEINE_OPTIONS) + [caffeine_details])

    sleep_keys = checkbox_prompt(
        "Which sleep or breathing flags apply?",
        SLEEP_OPTIONS,
        defaults=("none_reported",),
    )
    if len(sleep_keys) > 1 and "none_reported" in sleep_keys:
        sleep_keys.remove("none_reported")
    sleep_details = Prompt.ask("Actual average sleep duration and any additional details", default="20:15–04:30 target")
    sleep = "; ".join(labels_for(sleep_keys, SLEEP_OPTIONS) + [sleep_details])

    substance_keys = checkbox_prompt(
        "Which substances or additional stimulants are used?",
        SUBSTANCE_OPTIONS,
        defaults=("none_reported",),
    )
    if len(substance_keys) > 1 and "none_reported" in substance_keys:
        substance_keys.remove("none_reported")
    substance_details = Prompt.ask("Amount, frequency, and latest time for selected items", default="none additional")
    substances = "; ".join(
        labels_for(substance_keys, SUBSTANCE_OPTIONS)
        + ([substance_details] if substance_details and substance_details != "none additional" else [])
    ) or "none reported"

    store_keys = checkbox_prompt(
        "Which stores are you willing to search? Select every option that applies.",
        STORE_OPTIONS,
        defaults=("costco",),
        minimum=1,
    )
    preference_keys = checkbox_prompt(
        "Which buying and product constraints matter?",
        PRODUCT_OPTIONS,
        defaults=("third_party", "fewest_items"),
    )
    preference_details = Prompt.ask("Additional budget, format, testing, or product constraints", default="none additional")
    preferences = "; ".join(
        labels_for(preference_keys, PRODUCT_OPTIONS)
        + ([preference_details] if preference_details and preference_details != "none additional" else [])
    ) or "none reported"
    timeline = Prompt.ask("Deadline, race date, or other time constraint", default="none reported")
    return {
        "assessment_mode": "Detailed assessment",
        "assessment_notes": "Captured in the individual detailed fields below",
        "name": name,
        "age": 26,
        "height": height,
        "location": "Dallas, Texas",
        "body_context": "about 230 lb; Phase A goal 200 lb; Phase B goal 190 lb",
        "issues": issues,
        "issue_labels": [ISSUES[x] for x in issues],
        "goals": goals,
        "priorities": priorities,
        "training": f"{'; '.join(labels_for(training_modes, TRAINING_OPTIONS))}; {training}",
        "cardio_timing": cardio_timing,
        "cardio_timing_label": dict(CARDIO_TIMING_OPTIONS)[cardio_timing],
        "cardio_clock_constraints": cardio_clock,
        "workout_timing": workout_timing,
        "workout_timing_label": dict(WORKOUT_TIMING_OPTIONS)[workout_timing],
        "workout_clock_constraints": workout_clock,
        "injuries": injuries,
        "current_supplements": current,
        "current_supplement_keys": current_supplement_keys,
        "supplement_results": supplement_results,
        "priority_supplement_keys": interest_keys,
        "priority_supplements": interest_names,
        "supplement_source": supplement_source,
        "supplement_source_label": dict(SUPPLEMENT_SOURCE_OPTIONS)[supplement_source],
        "selected_peptide_keys": peptide_keys,
        "selected_peptides": peptide_names,
        "experimental_policy": experimental_policy,
        "experimental_policy_label": dict(EXPERIMENTAL_POLICY_OPTIONS)[experimental_policy],
        "medications": medications,
        "confirmed_deficiencies_or_labs": deficiencies,
        "conditions_and_safety_flags": conditions,
        "vitals": vitals,
        "prior_reactions": reactions,
        "diet_and_gi": diet,
        "food_addition_keys": food_addition_keys,
        "food_additions": labels_for(food_addition_keys, FOOD_ADDITION_OPTIONS),
        "home_practice_keys": home_practice_keys,
        "home_practices": labels_for(home_practice_keys, HOME_PRACTICE_OPTIONS),
        "alternative_item_keys": alternative_item_keys,
        "alternative_items": labels_for(alternative_item_keys, ALTERNATIVE_ITEM_OPTIONS),
        "store_keys": store_keys,
        "shopping_stores": labels_for(store_keys, STORE_OPTIONS),
        "whole_life_details": whole_life_details,
        "caffeine": caffeine,
        "sleep": sleep,
        "substances": substances,
        "preferences": preferences,
        "timeline": timeline,
        "locked_context": "tirzepatide unchanged; creatine 5 g/day; caffeine cutoff 11:15; no gray-market protocols",
    }


def default_profile(args: argparse.Namespace) -> dict:
    issues = parse_issue_codes(args.issues or "cut,strength,endurance")
    cardio_timing = (args.cardio_timing or "recommend").strip().lower()
    if cardio_timing not in dict(CARDIO_TIMING_OPTIONS):
        raise SystemExit("--cardio-timing must be morning, evening, both, or recommend")
    workout_timing = (args.workout_timing or "recommend").strip().lower()
    if workout_timing not in dict(WORKOUT_TIMING_OPTIONS):
        raise SystemExit("--workout-timing must be morning, evening, both, or recommend")
    priority = select_from_catalog(
        args.priority_items or "creatine_monohydrate,protein_whey,caffeine,omega_3_epa_and_dha,vitamin_d3,magnesium",
        CATALOG,
        default_all=False,
    )
    peptides = select_from_catalog(
        args.peptides or "tirzepatide_current_prescription", PEPTIDE_CATALOG, default_all=False
    )
    experimental_policy = (args.experimental_policy or "approved_only").strip().lower()
    if experimental_policy not in dict(EXPERIMENTAL_POLICY_OPTIONS):
        raise SystemExit("--experimental-policy must be approved_only or screen_strong_human")
    supplement_source = (args.supplement_source or "whole_food_first").strip().lower()
    if supplement_source not in dict(SUPPLEMENT_SOURCE_OPTIONS):
        raise SystemExit("--supplement-source must be whole_food_first, mixed, or products_allowed")
    current_text = args.current or "creatine monohydrate 5 g/day"
    current_candidates = [c for c in CATALOG if _matches_entry(c, current_text)]
    food_addition_keys = parse_choice_values(
        args.food_additions,
        FOOD_ADDITION_OPTIONS,
        defaults=("pasteurized_dairy", "potatoes_rice", "animal_protein", "fruit_carbs", "fiber_food"),
    )
    home_practice_keys = parse_choice_values(
        args.home_practices,
        HOME_PRACTICE_OPTIONS,
        defaults=("bible_prayer", "morning_light", "water_quality", "breathwork"),
    )
    alternative_item_keys = parse_choice_values(args.alternative_items, ALTERNATIVE_ITEM_OPTIONS)
    store_keys = parse_choice_values(args.stores, STORE_OPTIONS, defaults=("costco",))
    return {
        "assessment_mode": "Non-interactive flags/defaults",
        "assessment_notes": args.notes or "none",
        "name": args.name or "Michael",
        "age": 26,
        "height": args.height or "unknown",
        "location": "Dallas, Texas",
        "body_context": "about 230 lb; Phase A goal 200 lb; Phase B goal 190 lb",
        "issues": issues,
        "issue_labels": [ISSUES[x] for x in issues],
        "goals": args.goals or "preserve muscle while cutting and improve running",
        "priorities": args.priorities or "1) keep muscle/strength, 2) lose fat, 3) improve running",
        "training": args.training or "3 lifting days; returning to running; current mileage unknown",
        "cardio_timing": cardio_timing,
        "cardio_timing_label": dict(CARDIO_TIMING_OPTIONS)[cardio_timing],
        "cardio_clock_constraints": args.cardio_clock or "no additional timing constraint reported",
        "workout_timing": workout_timing,
        "workout_timing_label": dict(WORKOUT_TIMING_OPTIONS)[workout_timing],
        "workout_clock_constraints": args.workout_clock or "no additional timing constraint reported",
        "injuries": args.injuries or "none reported",
        "current_supplements": current_text,
        "current_supplement_keys": [c.key for c in current_candidates],
        "supplement_results": args.supplement_results or "no results recorded yet",
        "priority_supplement_keys": [c.key for c in priority],
        "priority_supplements": [c.name for c in priority],
        "supplement_source": supplement_source,
        "supplement_source_label": dict(SUPPLEMENT_SOURCE_OPTIONS)[supplement_source],
        "selected_peptide_keys": [c.key for c in peptides],
        "selected_peptides": [c.name for c in peptides],
        "experimental_policy": experimental_policy,
        "experimental_policy_label": dict(EXPERIMENTAL_POLICY_OPTIONS)[experimental_policy],
        "medications": args.medications or "tirzepatide",
        "confirmed_deficiencies_or_labs": args.deficiencies or "none/unknown",
        "conditions_and_safety_flags": args.conditions or "none",
        "vitals": args.vitals or "unknown",
        "prior_reactions": args.reactions or "none reported",
        "diet_and_gi": args.diet or "none reported",
        "food_addition_keys": food_addition_keys,
        "food_additions": labels_for(food_addition_keys, FOOD_ADDITION_OPTIONS),
        "home_practice_keys": home_practice_keys,
        "home_practices": labels_for(home_practice_keys, HOME_PRACTICE_OPTIONS),
        "alternative_item_keys": alternative_item_keys,
        "alternative_items": labels_for(alternative_item_keys, ALTERNATIVE_ITEM_OPTIONS),
        "store_keys": store_keys,
        "shopping_stores": labels_for(store_keys, STORE_OPTIONS),
        "whole_life_details": args.whole_life_details or "apartment now; also show house options; Christian Bible/Jesus learning",
        "caffeine": args.caffeine or "optional morning coffee; none after 11:15",
        "sleep": args.sleep or "none reported",
        "substances": args.substances or "none reported",
        "preferences": args.preferences or "practical value; third-party tested when available; fewest useful items",
        "timeline": args.timeline or "none reported",
        "locked_context": "tirzepatide unchanged; creatine 5 g/day; caffeine cutoff 11:15; no gray-market protocols",
    }


def sql_folder_filter(folders: Sequence[str]) -> str:
    vals = ", ".join("'%s'" % f.replace("'", "''") for f in folders)
    return "folder IN (%s)" % vals


def hit_is_on_topic(candidate: Candidate, hit: dict) -> bool:
    folder = hit.get("folder", "")
    dedicated = any(folder == f and _contains(f.rsplit("/", 1)[-1], (candidate.name, *candidate.aliases)) for f in candidate.folders)
    if dedicated:
        return True
    haystack = " ".join((hit.get("text", "")[:1800], folder, os.path.basename(hit.get("source_pdf", ""))))
    return _contains(haystack, (candidate.name, *candidate.aliases))


def retrieve_candidate(
    tbl, emb, reranker, candidate: Candidate, issue_labels: Sequence[str], medications: str = ""
) -> Evidence:
    issue_text = "; ".join(issue_labels[:4])
    query = (f"{candidate.name} human supplementation systematic review randomized trial efficacy effect size "
             f"dose form duration adverse effects interaction with {medications or 'medications'}; goals: {issue_text}")
    qv = emb.encode(HC.Q_PREFIX + query, normalize_embeddings=True).tolist()
    shared_safety_folders = (
        "07_supplements/interactions_stacking",
        "07_supplements/supplement_contamination_testing",
        "05_fat_loss_drugs/tirzepatide_incretins",
        "08_peptides_gray/uncertified_quality_risk",
        "08_peptides_gray/research_peptides_reviews",
        "08_peptides_gray/ped_sarms_aas_harms",
    )
    candidate_where = sql_folder_filter(candidate.folders) if candidate.folders else None
    safety_where = sql_folder_filter(shared_safety_folders)

    def run(where_clause: str | None) -> list[dict]:
        try:
            s = tbl.search(query_type="hybrid").vector(qv).text(query)
            if where_clause:
                s = s.where(where_clause, prefilter=True)
            return s.limit(40).to_list()
        except Exception:
            s = tbl.search(qv)
            if where_clause:
                s = s.where(where_clause, prefilter=True)
            return s.limit(40).to_list()

    # Search efficacy and safety scopes independently so generic interaction passages cannot
    # crowd the supplement's own papers out of the top-k result window.
    rows = run(candidate_where) if candidate_where else []
    rows += run(safety_where)
    rows = [h for h in rows if hit_is_on_topic(candidate, h)]
    if not rows:
        rows = [h for h in run(None) if hit_is_on_topic(candidate, h)]
    if reranker and rows:
        scores = reranker.predict([(query, h.get("text", "")[:700]) for h in rows])
        for h, score in zip(rows, scores):
            h["_audit_score"] = float(score)
        rows.sort(key=lambda h: h["_audit_score"], reverse=True)

    # Keep multiple passages when useful, but never let duplicate hardlinks inflate coverage.
    hits: list[dict] = []
    per_source: dict[str, int] = {}
    for h in rows:
        source_key = h.get("doi") or h.get("source_pdf") or h.get("text", "")[:120]
        if per_source.get(source_key, 0) >= 2:
            continue
        per_source[source_key] = per_source.get(source_key, 0) + 1
        hits.append(h)
        if len(hits) >= 12:
            break

    human_sources: dict[str, dict] = {}
    for h in hits:
        if h.get("grade") not in ("A", "B"):
            continue
        if candidate.queue == QUEUE_PEPTIDE:
            # For the experimental catalog, an A/B filename grade is not enough. A paper must
            # come from the candidate's own folder and contain an explicit human/clinical signal.
            # Animal and in-vitro papers remain in ev.hits for mechanistic risk flags but cannot
            # make an experimental topic pass the human-evidence gate.
            if h.get("folder") not in candidate.folders or not experimental_human_intervention_hit(h):
                continue
        source_key = h.get("doi") or h.get("source_pdf") or h.get("text", "")[:120]
        human_sources[source_key] = h
    n_human = len(human_sources)
    coverage = "STRONG" if n_human >= 2 else "WEAK" if n_human == 1 else "NONE"
    grades = [h.get("grade", "—") for h in human_sources.values()]
    best = min(grades, key=lambda g: GRADE_ORDER.get(g, 8)) if grades else "—"
    dois = {h.get("doi") for h in human_sources.values() if h.get("doi")}
    cohorts = {h.get("cohort", "general") for h in human_sources.values()}
    if candidate.queue == QUEUE_PEPTIDE and human_sources:
        fit = "human intervention retrieved; indication/population fit requires passage-level review"
    else:
        fit = "direct/general" if "general" in cohorts else "indirect/older-only" if cohorts else "not established"
    return Evidence(coverage, best, n_human, len(dois), fit, hits)


TIMING_FOLDERS = (
    "02_training_desk/concurrent_hybrid_lift_run",
    "02_training_desk/compressed_4x10_schedule",
    "02_training_desk/energy_availability_reds",
    "02_training_desk/heat_acclimatization",
    "02_training_desk/running_injury_load",
    "03_sleep_stress/schedule_consistency_circadian",
    "03_sleep_stress/sleep_best_practices",
    "03_sleep_stress/sunlight_circadian",
    "10_recovery_fascia/muscle_skeletal_recovery",
)


def retrieve_timing_evidence(tbl, emb, reranker, profile: dict) -> Evidence:
    queries = (
        "morning versus evening resistance exercise training time of day strength hypertrophy performance human trial review",
        "morning versus evening endurance cardio running training time of day performance adaptation human trial review",
        "concurrent strength endurance training same session order separation hours different days interference human review",
        "evening exercise proximity bedtime sleep quality resistance endurance human trial review",
        "heat acclimatization exercise time of day morning evening endurance performance human guidance",
    )
    query = " ; ".join(queries)
    where = sql_folder_filter(TIMING_FOLDERS)
    rows: list[dict] = []
    for subquery in queries:
        qv = emb.encode(HC.Q_PREFIX + subquery, normalize_embeddings=True).tolist()
        try:
            found = tbl.search(query_type="hybrid").vector(qv).text(subquery).where(where, prefilter=True).limit(35).to_list()
        except Exception:
            found = tbl.search(qv).where(where, prefilter=True).limit(35).to_list()
        rows.extend(found)

    def on_topic(h: dict) -> bool:
        text = " ".join((h.get("text", "")[:2200], os.path.basename(h.get("source_pdf", "")))).lower()
        activity = any(term in text for term in (
            "exercise", "training", "resistance", "endurance", "running", "cycling", "athlete"
        ))
        timing = any(term in text for term in (
            "morning", "evening", "time of day", "diurnal", "circadian", "bedtime",
            "same session", "separate day", "different day", "concurrent", "interference", "heat"
        ))
        supplement_only = any(term in os.path.basename(h.get("source_pdf", "")).lower() for term in (
            "melatonin", "smartphone", "caffeine"
        ))
        return activity and timing and not supplement_only

    rows = [h for h in rows if on_topic(h)]
    if reranker and rows:
        scores = reranker.predict([(query, h.get("text", "")[:900]) for h in rows])
        for h, score in zip(rows, scores):
            h["_timing_score"] = float(score)
        rows.sort(key=lambda h: h["_timing_score"], reverse=True)

    hits: list[dict] = []
    seen: set[str] = set()
    for h in rows:
        source_key = h.get("doi") or h.get("source_pdf") or h.get("text", "")[:120]
        if source_key in seen:
            continue
        seen.add(source_key)
        hits.append(h)
        if len(hits) >= 14:
            break
    human = [h for h in hits if h.get("grade") in ("A", "B")]
    coverage = "STRONG" if len(human) >= 2 else "WEAK" if len(human) == 1 else "NONE"
    grades = [h.get("grade", "—") for h in human]
    best = min(grades, key=lambda g: GRADE_ORDER.get(g, 8)) if grades else "—"
    dois = {h.get("doi") for h in human if h.get("doi")}
    comparative = [
        h for h in human
        if h.get("folder", "").startswith("02_training_desk/")
        if "morning" in (h.get("text", "") + h.get("source_pdf", "")).lower()
        and "evening" in (h.get("text", "") + h.get("source_pdf", "")).lower()
    ]
    fit = "direct comparison present" if comparative else "indirect timing evidence" if human else "not established"
    # A/B human sources control the recommendation. C-grade material is shown only when
    # no A/B timing passage exists, and then coverage remains NONE.
    return Evidence(coverage, best, len(human), len(dois), fit, human or hits)


def preliminary_decisions(candidates: Sequence[Candidate], evidence: dict[str, Evidence], profile: dict) -> dict[str, str]:
    decisions: dict[str, str] = {}
    eligible: list[tuple[int, Candidate]] = []
    user_issues = set(profile["issues"])
    for c in candidates:
        ev = evidence[c.key]
        is_current = candidate_is_current(c, profile)
        if c.policy == "KEEP-PRESCRIPTION":
            decisions[c.key] = "KEEP-PRESCRIPTION — PRESCRIBER MANAGED; DO NOT CHANGE DOSE"
        elif c.policy.startswith("SKIP"):
            decisions[c.key] = "REVIEW CURRENT USE" if is_current else "SKIP"
        elif c.policy == "CLINICIAN-ONLY":
            decisions[c.key] = "CLINICIAN-ONLY"
        elif c.policy in {"DEFICIENCY-GATED", "INTAKE/CLINICIAN-GATED", "CLINICIAN-GATED"}:
            decisions[c.key] = "TEST / INTAKE / CLINICIAN GATE"
        elif c.policy in {"MEDICATION-REVIEW", "SAFETY-REVIEW"}:
            decisions[c.key] = "CLINICIAN / PHARMACIST REVIEW"
        elif ev.coverage == "NONE":
            decisions[c.key] = "SKIP — COVERAGE GAP"
        elif is_current:
            decisions[c.key] = "KEEP / REVIEW AGAINST EVIDENCE"
        elif c.policy.startswith("FOOD-FIRST"):
            decisions[c.key] = "FOOD-FIRST"
        elif c.policy.startswith("FOOD/KEEP"):
            decisions[c.key] = "FOOD VEHICLE / OPTIONAL"
        elif ev.coverage == "WEAK":
            decisions[c.key] = "OPTIONAL — WEAK COVERAGE"
        else:
            overlap = len(user_issues.intersection(c.issues))
            score = overlap * 5 + (2 if ev.best_grade == "A" else 1)
            if c.policy.startswith("SPORT-SPECIFIC") and "endurance" in user_issues:
                score += 2
            if overlap:
                eligible.append((score, c))
                decisions[c.key] = "OPTIONAL — NOT SHORTLISTED"
            else:
                decisions[c.key] = "OPTIONAL — NO CURRENT NEED"

    # Hard cap: at most three new OTC candidates beyond creatine and whey-as-food.
    eligible.sort(key=lambda x: (-x[0], x[1].name.lower()))
    for _, c in eligible[:3]:
        decisions[c.key] = "SHORTLIST FOR REVIEW"
    return decisions


def choose_deep_candidates(
    candidates: Sequence[Candidate], evidence: dict[str, Evidence], profile: dict, decisions: dict[str, str], limit: int
) -> list[Candidate]:
    if limit <= 0:
        return []
    anchor = {"creatine_monohydrate", "protein_whey", "caffeine", "omega_3_epa_and_dha", "vitamin_d3", "magnesium"}
    explicitly_selected = set(profile.get("priority_supplement_keys", ())) | set(profile.get("selected_peptide_keys", ()))
    user_issues = set(profile["issues"])

    def score(c: Candidate) -> tuple[int, str]:
        ev = evidence[c.key]
        n = 0
        if c.key in explicitly_selected:
            n += 100
        if (
            profile.get("experimental_policy") == "screen_strong_human"
            and c.queue == QUEUE_PEPTIDE
            and ev.coverage == "STRONG"
        ):
            n += 85
        if c.key in anchor:
            n += 30
        if decisions[c.key] == "SHORTLIST FOR REVIEW":
            n += 40
        if candidate_is_current(c, profile):
            n += 35
        n += 8 * len(user_issues.intersection(c.issues))
        n += {"STRONG": 8, "WEAK": 3, "NONE": -20}[ev.coverage]
        if c.gate:
            n += 4
        return (-n, c.name.lower())

    return sorted(candidates, key=score)[:limit]


def profile_markdown(profile: dict) -> str:
    return "\n".join([
        f"- Assessment path: {profile.get('assessment_mode', 'not recorded')}; limited detail: {profile.get('assessment_notes', 'none')}.",
        f"- Name: **{profile['name']}**; age **{profile['age']}**; height **{profile['height']}**; location **{profile['location']}**.",
        f"- Body context: {profile['body_context']}.",
        f"- Selected issues: {', '.join(profile['issue_labels'])}.",
        f"- Problems/goals: {profile['goals']}.",
        f"- Priority order: {profile['priorities']}.",
        f"- Training history/load: {profile['training']}.",
        f"- Cardio timing selection: {profile['cardio_timing_label']}; clock details: {profile['cardio_clock_constraints']}.",
        f"- Strength-workout timing selection: {profile['workout_timing_label']}; clock details: {profile['workout_clock_constraints']}.",
        f"- Pain/injuries: {profile['injuries']}.",
        f"- Current supplements: {profile['current_supplements']}.",
        f"- Reported supplement results: {profile['supplement_results']}.",
        f"- Priority supplement evidence reviews: {', '.join(profile['priority_supplements']) or 'none selected'}.",
        f"- Preferred supplement/nutrient source: {profile.get('supplement_source_label', 'Whole-food first')}.",
        f"- Selected peptide/gray evidence reviews: {', '.join(profile['selected_peptides']) or 'none selected'}.",
        f"- Experimental/unapproved research boundary: {profile.get('experimental_policy_label', 'Approved-only default')}.",
        f"- Medications: {profile['medications']}.",
        f"- Confirmed deficiencies/labs: {profile['confirmed_deficiencies_or_labs']}.",
        f"- Conditions/safety flags: {profile['conditions_and_safety_flags']}.",
        f"- Known vitals/measurements: {profile['vitals']}.",
        f"- Prior supplement reactions: {profile['prior_reactions']}.",
        f"- Diet/GI: {profile['diet_and_gi']}.",
        f"- Selected food additions: {', '.join(profile.get('food_additions', ())) or 'none selected'}.",
        f"- Selected apartment/home practices: {', '.join(profile.get('home_practices', ())) or 'none selected'}.",
        f"- Selected alternative claims/items: {', '.join(profile.get('alternative_items', ())) or 'none selected'}.",
        f"- Whole-life/housing/faith details: {profile.get('whole_life_details', 'none reported')}.",
        f"- Caffeine: {profile['caffeine']}; sleep: {profile['sleep']}.",
        f"- Alcohol/nicotine/cannabis/energy drinks: {profile['substances']}.",
        f"- Stores willing to search: {', '.join(profile.get('shopping_stores', ())) or 'none selected'}.",
        f"- Product/budget preferences: {profile['preferences']}.",
        f"- Deadline/race date: {profile['timeline']}.",
    ])


def questionnaire_markdown(profile: dict) -> str:
    """Preserve the intake questions and their exact answers inside the one report."""
    rows = [
        ("Which assessment path produced this profile?", profile.get("assessment_mode", "not recorded")),
        ("What optional final note was supplied?", profile.get("assessment_notes", "none")),
        ("Who is this report for?", f"{profile['name']}, age {profile['age']}, height {profile['height']}, {profile['location']}"),
        ("What is the current body-composition context?", profile["body_context"]),
        ("Which issue areas need help?", "; ".join(profile["issue_labels"])),
        ("What are the top problems or goals in the user's own words?", profile["goals"]),
        ("How are those outcomes ranked?", profile["priorities"]),
        ("What is the current training load, mileage, experience, and recent consistency?", profile["training"]),
        ("Which cardio timing was selected?", f"{profile['cardio_timing_label']}; {profile['cardio_clock_constraints']}"),
        ("Which strength-workout timing was selected?", f"{profile['workout_timing_label']}; {profile['workout_clock_constraints']}"),
        ("What pain, injuries, or aggravating movements are present?", profile["injuries"]),
        ("What supplements are currently used?", profile["current_supplements"]),
        ("What benefits, no-effects, or side effects were reported for current supplements?", profile["supplement_results"]),
        ("Which supplements were selected for priority deep review?", "; ".join(profile["priority_supplements"]) or "none selected"),
        ("Should supplement-like nutrients come from whole foods, a mixed approach, or products?", profile.get("supplement_source_label", "Whole-food first")),
        ("Which peptides/incretins/gray compounds were selected for evidence review?", "; ".join(profile["selected_peptides"]) or "none selected"),
        ("May HealthCoach broad-scan experimental/unapproved drugs?", profile.get("experimental_policy_label", "Approved-only default")),
        ("What medications or prescriptions are currently used?", profile["medications"]),
        ("Which deficiencies or abnormal labs are clinician-confirmed?", profile["confirmed_deficiencies_or_labs"]),
        ("Which conditions or safety flags apply?", profile["conditions_and_safety_flags"]),
        ("What recent vitals or measurements are known?", profile["vitals"]),
        ("Which supplements caused prior side effects or were poorly tolerated?", profile["prior_reactions"]),
        ("Which diet restrictions, low-intake foods, or GI triggers apply?", profile["diet_and_gi"]),
        ("Which food additions were selected for plan-fit review?", "; ".join(profile.get("food_additions", ())) or "none selected"),
        ("Which apartment/home practices were selected for review?", "; ".join(profile.get("home_practices", ())) or "none selected"),
        ("Which alternative products or claims were selected for an evidence/safety verdict?", "; ".join(profile.get("alternative_items", ())) or "none selected"),
        ("What housing, faith-tradition, sourcing, or ambiguous-item details were recorded?", profile.get("whole_life_details", "none reported")),
        ("What is the caffeine pattern?", profile["caffeine"]),
        ("What is the sleep pattern, and are snoring/apnea symptoms present?", profile["sleep"]),
        ("What alcohol, nicotine, cannabis, energy-drink, or other stimulant use applies?", profile["substances"]),
        ("Which stores is the user willing to search?", "; ".join(profile.get("shopping_stores", ())) or "none selected"),
        ("What budget, format, testing, or product constraints apply?", profile["preferences"]),
        ("What deadline, race date, or time constraint applies?", profile["timeline"]),
    ]
    lines = ["| Intake question | Recorded answer |", "|---|---|"]
    for question, answer in rows:
        q = str(question).replace("|", "/").replace("\n", " ")
        a = str(answer).replace("|", "/").replace("\n", "<br>")
        lines.append(f"| {q} | {a} |")
    return "\n".join(lines)


def embedded_module(path: Path) -> str:
    """Embed an authored Markdown module while keeping one valid heading hierarchy."""
    if not path.exists():
        return f"_(Source module missing: `{path.name}`.)_"
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    return re.sub(r"^(#{1,4})\s+", lambda m: "##" + m.group(1) + " ", text, flags=re.M)


def evidence_context(candidate: Candidate, ev: Evidence) -> tuple[str, set[str]]:
    blocks = []
    allowed_dois: set[str] = set()
    for h in ev.hits[:10]:
        doi = h.get("doi") or "no-doi"
        if doi != "no-doi":
            allowed_dois.add(doi.lower())
        blocks.append("[%s | %s | %s | cohort=%s]\n%s" % (
            h.get("grade", "—"), h.get("folder", "unknown"), doi,
            h.get("cohort", "unknown"), h.get("text", "")[:1250],
        ))
    return "\n\n".join(blocks), allowed_dois


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def strip_unretrieved_dois(text: str, allowed: set[str]) -> str:
    def repl(match: re.Match) -> str:
        value = match.group(0).rstrip(".,;)")
        suffix = match.group(0)[len(value):]
        return (value if value.lower() in allowed else "unretrieved-doi-removed") + suffix
    return DOI_RE.sub(repl, text)


CARD_FIELDS = (
    "OUTCOMES",
    "STUDY_USE",
    "MECHANISM",
    "SAFETY",
    "APPLICABILITY",
    "CONVERGENCE",
)


def numbered_evidence_context(ev: Evidence) -> tuple[str, dict[str, str], set[str]]:
    blocks: list[str] = []
    tags: dict[str, str] = {}
    allowed_dois: set[str] = set()
    for i, h in enumerate(ev.hits[:10], 1):
        sid = f"S{i}"
        doi = h.get("doi") or "no-doi"
        tag = "[%s | %s | %s]" % (h.get("grade", "—"), h.get("folder", "unknown"), doi)
        tags[sid] = tag
        if doi != "no-doi":
            allowed_dois.add(doi.lower())
        blocks.append(
            f"{sid} {tag} cohort={h.get('cohort', 'unknown')}\n{h.get('text', '')[:1250]}"
        )
    return "\n\n".join(blocks), tags, allowed_dois


def parse_card_rows(text: str, valid_ids: set[str]) -> dict[str, tuple[list[str], str]] | None:
    """Parse FIELD|S1,S2|claim rows; source IDs are later replaced with exact tags."""
    rows: dict[str, tuple[list[str], str]] = {}
    for raw in text.splitlines():
        line = raw.strip().strip("`")
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        field, raw_ids, claim = parts[0].strip().upper(), parts[1].strip().upper(), parts[2].strip()
        if field not in CARD_FIELDS or field in rows or not claim:
            continue
        if raw_ids in ("NONE", "NOT_ESTABLISHED", "NOT ESTABLISHED"):
            ids: list[str] = []
            claim = "Not established in retrieved passages."
        else:
            ids = [x.strip().upper() for x in raw_ids.split(",") if x.strip()]
            if not ids or any(x not in valid_ids for x in ids):
                return None
        rows[field] = (ids, claim)
    return rows if set(rows) == set(CARD_FIELDS) else None


def render_card_rows(candidate: Candidate, ev: Evidence, decision: str, rows: dict[str, tuple[list[str], str]], tags: dict[str, str]) -> str:
    labels = {
        "OUTCOMES": "Outcomes and magnitude",
        "STUDY_USE": "Retrieved studies used",
        "MECHANISM": "Mechanism",
        "SAFETY": "Safety/interactions",
        "APPLICABILITY": "Applicability",
        "CONVERGENCE": "Convergence",
    }
    lines = [
        f"### What does the retrieved evidence show for {candidate.name}?", "",
        f"- **Coverage:** {ev.coverage}; best retrieved grade {ev.best_grade}; "
        f"{ev.unique_papers} unique A/B human source(s); population fit {ev.fit}.",
    ]
    for field in CARD_FIELDS:
        ids, claim = rows[field]
        cited = list(dict.fromkeys(tags[x] for x in ids))
        if field == "CONVERGENCE":
            cited = [tag for tag in cited if tag.startswith("[A |") or tag.startswith("[B |")]
            if len(cited) < 2:
                claim, cited = "Not established in retrieved passages.", []
        citations = " ".join(cited)
        lines.append(f"- **{labels[field]}:** {claim}" + (f" {citations}" if citations else ""))
    if candidate.gate:
        lines.append(f"- **Predeclared gate:** {candidate.gate}")
    lines.append(f"- **Bottom line:** {decision}. This is an evidence-screening decision, not a prescription.")
    return "\n".join(lines) + "\n"


def deterministic_deep_fallback(candidate: Candidate, ev: Evidence, decision: str) -> str:
    """Fail closed: expose short tagged evidence excerpts instead of an ungrounded synthesis."""
    lines = [
        f"### What does the retrieved evidence show for {candidate.name}?", "",
        f"- **Coverage:** {ev.coverage}; best retrieved grade {ev.best_grade}; "
        f"{ev.unique_papers} unique A/B human source(s); population fit {ev.fit}.",
    ]
    seen: set[str] = set()
    for h in ev.hits:
        source_key = h.get("doi") or h.get("source_pdf") or h.get("text", "")[:120]
        if source_key in seen:
            continue
        seen.add(source_key)
        snippet = re.sub(r"\s+", " ", h.get("text", "")).strip()[:420].rstrip()
        tag = "[%s | %s | %s]" % (h.get("grade", "—"), h.get("folder", "unknown"), h.get("doi") or "no-doi")
        lines.append(f"- **Retrieved evidence excerpt:** {snippet}… {tag}")
        if len(seen) >= 4:
            break
    lines.extend([
        f"- **Safety/interaction gate:** {candidate.gate or 'not established in retrieved passages.'}",
        f"- **Bottom line:** {decision}. Model synthesis was withheld because it failed the citation validator; inspect the tagged excerpts and source trail below.",
    ])
    return "\n".join(lines) + "\n"


def deep_card(model, tok, candidate: Candidate, ev: Evidence, decision: str, profile: dict, max_tokens: int) -> str:
    if ev.coverage == "NONE":
        return (
            f"### What does the retrieved evidence show for {candidate.name}?\n\n"
            "- **Coverage:** NONE — no on-topic A/B human passage survived retrieval and DOI/source de-duplication.\n"
            f"- **Gate:** {candidate.gate or 'No evidence-based personal use case can be established from this library.'}\n"
            f"- **Decision:** {decision}.\n"
        )
    ctx, source_tags, allowed_dois = numbered_evidence_context(ev)
    system = (
        "You are the evidence compiler inside a local supplement audit. Use ONLY the supplied retrieved passages. "
        "The submitted queue label is not an evidence grade. Do not use outside memory. Do not invent a dose, form, "
        "effect size, interaction, population, or citation. Trial amounts may appear only as 'Retrieved studies used'. "
        "Do not prescribe or change medications. Every evidence claim must end with the exact passage tag "
        "Do not write citations yourself. Cite claims only with the supplied short source IDs (S1, S2, etc.); the program "
        "will replace those IDs with exact tags. If the passages do not answer a field, use NOT_ESTABLISHED. Separate "
        "outcomes from mechanisms and flag indirect populations. Never say there are more studies than the programmatic "
        "unique-source count."
    )
    user = (
        f"ITEM: {candidate.name}\nSUBMITTED QUEUE: {candidate.queue}\nPROGRAMMATIC COVERAGE: {ev.coverage}; "
        f"best grade {ev.best_grade}; {ev.unique_papers} unique A/B sources; fit {ev.fit}.\n"
        f"PRELIMINARY DECISION: {decision}\nSAFETY/DEFICIENCY GATE: {candidate.gate or 'none predeclared'}\n\n"
        f"USER:\n{profile_markdown(profile)}\n\nRETRIEVED PASSAGES:\n{ctx}\n\n"
        "Return exactly six plain-text lines and nothing else. Each line must be FIELD|SOURCE_IDS|CLAIM. Required fields, "
        "one each: OUTCOMES, STUDY_USE, MECHANISM, SAFETY, APPLICABILITY, CONVERGENCE. SOURCE_IDS must be comma-separated "
        "IDs from the supplied passages, or NOT_ESTABLISHED. Keep each CLAIM under 80 words. Do not use Markdown, headings, "
        "nested lists, DOI strings, or unsupported facts. CONVERGENCE must say whether two independent human papers point "
        "in the same direction; otherwise use NOT_ESTABLISHED."
    )
    if getattr(tok, "chat_template", None):
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            add_generation_prompt=True, tokenize=False,
        )
    else:
        prompt = system + "\n\n" + user + "\n\nANSWER:"
    from mlx_lm import generate
    out = strip_unretrieved_dois(generate(model, tok, prompt=prompt, max_tokens=max_tokens, verbose=False).strip(), allowed_dois)
    rows = parse_card_rows(out, set(source_tags))
    if rows is None:
        correction = (
            user + "\n\nYour previous response failed the parser. Return only the six required "
            "FIELD|SOURCE_IDS|CLAIM lines. Use only valid S-number IDs or NOT_ESTABLISHED."
        )
        if getattr(tok, "chat_template", None):
            retry_prompt = tok.apply_chat_template(
                [{"role": "system", "content": system}, {"role": "user", "content": correction}],
                add_generation_prompt=True, tokenize=False,
            )
        else:
            retry_prompt = system + "\n\n" + correction + "\n\nANSWER:"
        out = strip_unretrieved_dois(
            generate(model, tok, prompt=retry_prompt, max_tokens=max_tokens, verbose=False).strip(), allowed_dois
        )
        rows = parse_card_rows(out, set(source_tags))
    return render_card_rows(candidate, ev, decision, rows, source_tags) if rows else deterministic_deep_fallback(candidate, ev, decision)


TIMING_FIELDS = ("COMPARISON", "CARDIO", "STRENGTH", "INTERFERENCE", "SLEEP_HEAT", "RECOMMENDATION")


def parse_timing_rows(text: str, valid_ids: set[str]) -> dict[str, tuple[list[str], str]] | None:
    rows: dict[str, tuple[list[str], str]] = {}
    for raw in text.splitlines():
        parts = raw.strip().strip("`").split("|", 2)
        if len(parts) != 3:
            continue
        field, raw_ids, claim = parts[0].strip().upper(), parts[1].strip().upper(), parts[2].strip()
        if field not in TIMING_FIELDS or field in rows or not claim:
            continue
        if raw_ids in ("NONE", "NOT_ESTABLISHED", "NOT ESTABLISHED"):
            ids: list[str] = []
        else:
            ids = [x.strip().upper() for x in raw_ids.split(",") if x.strip()]
            if not ids or any(x not in valid_ids for x in ids):
                return None
        rows[field] = (ids, claim)
    return rows if set(rows) == set(TIMING_FIELDS) else None


def timing_planning_default(profile: dict) -> str:
    cardio = profile["cardio_timing"]
    strength = profile["workout_timing"]
    lines = []
    if cardio == "both":
        lines.append(
            "PLANNING recommendation: keep the programmed full or hard cardio in one window only; with the current "
            "clock, use only short easy movement in the morning and the existing 17:00 window for the primary session "
            "unless the recorded clock details explicitly replace a conflicting block."
        )
    elif cardio == "morning":
        lines.append(
            "Cardio includes a requested morning component, but a full session cannot be placed between the locked "
            "04:30 wake and 04:50 Anki start unless the recorded clock details explicitly authorize a change."
        )
    elif cardio == "evening":
        lines.append("Cardio uses the existing 17:00 training window.")
    else:
        lines.append(
            "PLANNING recommendation: use the existing 17:00 window for full cardio sessions because it is the only "
            "defined full training window; this is feasibility, not proof that evening physiology is superior."
        )
    if strength == "both":
        lines.append(
            "PLANNING recommendation: keep the complete progressive lift in one session; at most place a short, "
            "non-fatiguing accessory or mobility block in the morning and retain the main lift at 17:00 unless the "
            "recorded clock details explicitly replace a conflicting block."
        )
    elif strength == "morning":
        lines.append(
            "Strength includes a requested morning component, subject to the same clock conflict and without duplicating "
            "the day's programmed hard work."
        )
    elif strength == "evening":
        lines.append("Strength uses the existing 17:00 training window.")
    else:
        lines.append(
            "PLANNING recommendation: keep full strength sessions in the existing 17:00 window unless an explicit "
            "morning window replaces a conflicting block; this is feasibility, not proof of evening superiority."
        )
    return " ".join(lines)


def deterministic_timing_card(ev: Evidence, profile: dict) -> str:
    lines = [
        "#### Evidence-checked cardio and strength timing", "",
        f"- **Selections:** cardio—{profile['cardio_timing_label']}; strength—{profile['workout_timing_label']}.",
        f"- **Coverage:** {ev.coverage}; best retrieved grade {ev.best_grade}; "
        f"{ev.unique_papers} unique A/B human source(s); fit {ev.fit}.",
        f"- **PLANNING DEFAULT:** {timing_planning_default(profile)}",
    ]
    seen = 0
    for h in ev.hits:
        snippet = re.sub(r"\s+", " ", h.get("text", "")).strip()[:420].rstrip()
        tag = "[%s | %s | %s]" % (h.get("grade", "—"), h.get("folder", "unknown"), h.get("doi") or "no-doi")
        lines.append(f"- **Retrieved timing passage:** {snippet}… {tag}")
        seen += 1
        if seen >= 5:
            break
    if ev.coverage == "NONE":
        lines.append("- **Recommendation:** COVERAGE GAP — retain only the recorded planning default until on-topic evidence is added.")
    return "\n".join(lines) + "\n"


def timing_card(model, tok, ev: Evidence, profile: dict, max_tokens: int) -> str:
    if ev.coverage == "NONE":
        return deterministic_timing_card(ev, profile)
    ctx, source_tags, allowed_dois = numbered_evidence_context(ev)
    system = (
        "You compare exercise timing using ONLY supplied retrieved passages plus explicitly labeled planning constraints. "
        "Do not invent superiority for morning or evening. Do not invent clock times, effects, or citations. Cite evidence "
        "only with supplied S-IDs. A recommendation driven by schedule feasibility rather than a comparative human study "
        "must begin 'PLANNING DEFAULT:'. Blood-pressure timing evidence is not athletic-performance evidence; female, older, "
        "hypertensive, or elite-volume populations must be flagged as indirect when the passage indicates them. Never add "
        "training volume or a second hard session."
    )
    user = (
        f"USER PROFILE:\n{profile_markdown(profile)}\n\n"
        f"PROGRAMMATIC COVERAGE: {ev.coverage}; {ev.unique_papers} unique A/B sources; fit {ev.fit}.\n"
        f"LOCKED FEASIBILITY NOTE: {timing_planning_default(profile)}\n\nRETRIEVED PASSAGES:\n{ctx}\n\n"
        "Return exactly six plain-text FIELD|SOURCE_IDS|CLAIM lines: COMPARISON, CARDIO, STRENGTH, INTERFERENCE, "
        "SLEEP_HEAT, RECOMMENDATION. Use only supplied S-IDs or NOT_ESTABLISHED. Keep each claim under 90 words. "
        "RECOMMENDATION must distinguish evidence from PLANNING DEFAULT. No Markdown and no DOI strings."
    )
    if getattr(tok, "chat_template", None):
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            add_generation_prompt=True, tokenize=False,
        )
    else:
        prompt = system + "\n\n" + user + "\n\nANSWER:"
    from mlx_lm import generate
    raw = strip_unretrieved_dois(generate(model, tok, prompt=prompt, max_tokens=max_tokens, verbose=False).strip(), allowed_dois)
    rows = parse_timing_rows(raw, set(source_tags))
    if rows is None:
        correction = (
            user
            + "\n\nYour prior answer failed the parser. Return ONLY the six required "
            "FIELD|SOURCE_IDS|CLAIM lines. Use exact field names, valid S-number IDs, or NOT_ESTABLISHED."
        )
        if getattr(tok, "chat_template", None):
            retry_prompt = tok.apply_chat_template(
                [{"role": "system", "content": system}, {"role": "user", "content": correction}],
                add_generation_prompt=True, tokenize=False,
            )
        else:
            retry_prompt = system + "\n\n" + correction + "\n\nANSWER:"
        raw = strip_unretrieved_dois(
            generate(model, tok, prompt=retry_prompt, max_tokens=max_tokens, verbose=False).strip(), allowed_dois
        )
        rows = parse_timing_rows(raw, set(source_tags))
    if rows is None:
        return deterministic_timing_card(ev, profile)
    labels = {
        "COMPARISON": "Morning-versus-evening evidence",
        "CARDIO": "Cardio timing",
        "STRENGTH": "Strength timing",
        "INTERFERENCE": "Concurrent-training separation",
        "SLEEP_HEAT": "Sleep and Dallas-heat tradeoffs",
        "RECOMMENDATION": "Recommendation and why",
    }
    lines = [
        "#### Evidence-checked cardio and strength timing", "",
        f"- **Selections:** cardio—{profile['cardio_timing_label']}; strength—{profile['workout_timing_label']}.",
        f"- **Coverage:** {ev.coverage}; best retrieved grade {ev.best_grade}; "
        f"{ev.unique_papers} unique A/B human source(s); fit {ev.fit}.",
    ]
    for field in TIMING_FIELDS:
        ids, claim = rows[field]
        cites = " ".join(dict.fromkeys(source_tags[x] for x in ids))
        lines.append(f"- **{labels[field]}:** {claim}" + (f" {cites}" if cites else ""))
    return "\n".join(lines) + "\n"


def preferred_source_text(candidate: Candidate, profile: dict) -> str:
    source_policy = profile.get("supplement_source", "whole_food_first")
    route, examples = food_source_for(candidate)
    if route == FOOD_LOCKED:
        return f"PLANNING / {route}: {examples}"
    if route == FOOD_NONE:
        return f"PLANNING / {route}: {examples} A missing food route never makes a product an automatic add."
    if route == FOOD_PARTIAL:
        return (
            f"PLANNING / {route}: {examples} "
            "Use the food as food; evaluate any isolated product separately against its retrieved form, exposure, safety, and decision."
        )
    if source_policy == "whole_food_first":
        return f"PLANNING / FOOD-FIRST: {examples} Use a product only when the evidence target cannot practically be met from tolerated foods and all gates clear."
    if source_policy == "mixed":
        return f"PLANNING / MIXED: food route—{examples} Compare food and product only after evidence, tolerance, cost, and safety gates."
    return f"PLANNING / PRODUCT-ALLOWED: food route still exists—{examples} Product use still requires item-specific evidence and safety clearance."


def food_source_strategy_markdown(
    candidates: Sequence[Candidate], evidence: dict[str, Evidence], decisions: dict[str, str], profile: dict
) -> str:
    selected_keys = (
        set(profile.get("current_supplement_keys", ()))
        | set(profile.get("priority_supplement_keys", ()))
        | set(profile.get("selected_peptide_keys", ()))
    )
    focus = [
        candidate for candidate in candidates
        if candidate.key in selected_keys or decisions[candidate.key] == "SHORTLIST FOR REVIEW"
    ]
    lines = [
        f"**Selected intake strategy:** {profile.get('supplement_source_label', 'Whole-food first')}.",
        "",
        "**PLANNING SOURCE RULE:** food-source examples organize shopping and meals; they do not prove efficacy, reproduce an isolated study dose, or override the evidence and safety verdict. `FOOD EXISTS; NOT FORM/DOSE EQUIVALENT` means the food and product must not be treated as interchangeable. `NO PRACTICAL WHOLE-FOOD EQUIVALENT MAPPED` means abstain unless the separate product evidence and gates justify consideration—it does not mean automatically buy the product.",
        "",
        "| Current, priority, or shortlisted item | Food-source classification and route | Evidence coverage | Audit decision |",
        "|---|---|---:|---|",
    ]
    if not focus:
        lines.append("| _No current, priority, or shortlisted item_ | — | — | — |")
    for candidate in focus:
        values = (
            candidate.name,
            preferred_source_text(candidate, profile),
            evidence[candidate.key].coverage,
            decisions[candidate.key],
        )
        lines.append("| " + " | ".join(str(value).replace("|", "/").replace("\n", "<br>") for value in values) + " |")
    return "\n".join(lines)


def inventory_table(
    candidates: Sequence[Candidate], evidence: dict[str, Evidence], decisions: dict[str, str], profile: dict
) -> str:
    lines = [
        "| Item | Retrieved coverage | Best grade | Unique A/B papers (DOIs) | Fit | Preferred food/product route | Preliminary decision | Specific retrieved references |",
        "|---|---:|---:|---:|---|---|---|---|",
    ]
    for c in candidates:
        ev = evidence[c.key]
        refs: list[str] = []
        for h in ev.hits:
            tag = "[%s / %s / %s]" % (h.get("grade", "—"), h.get("folder", "unknown"), h.get("doi") or "no-doi")
            if tag not in refs:
                refs.append(tag)
            if len(refs) == 2:
                break
        ref_text = "<br>".join(refs) if refs else "COVERAGE GAP"
        lines.append("| %s | %s | %s | %d (%d) | %s | %s | %s | %s |" % (
            c.name.replace("|", "/"), ev.coverage, ev.best_grade, ev.unique_papers, ev.unique_dois,
            ev.fit, preferred_source_text(c, profile).replace("|", "/"),
            decisions[c.key].replace("|", "/"), ref_text.replace("|", "/"),
        ))
    return "\n".join(lines)


EXPERIMENTAL_SAFETY_TERMS = (
    "adverse", "safety", "tolerability", "toxicity", "toxicology", "withdrawal",
    "dependence", "contraindicat", "drug interaction", "coadministr", "pharmacokinetic",
    "hepatic", "renal", "arrhythm", "blood pressure", "edema", "glucose", "mortality",
)

EXPERIMENTAL_MECHANISM_FLAGS = (
    ("CYP/transporter or PK", ("cytochrome", "cyp", "transporter", "pharmacokinetic", "metabolism")),
    ("serotonin/MAO", ("seroton", "monoamine oxidase", " mao ")),
    ("dopamine/catecholamine", ("dopamin", "catecholamine", "norepinephrine", "noradrenaline")),
    ("GH/IGF/growth signaling", ("growth hormone", "igf-1", "igf1", "somatotrop")),
    ("glucose/incretin", ("glucose", "insulin", "incretin", "glp-1", "gip receptor")),
    ("cardiac/BP", ("blood pressure", "hypertension", "hypotension", "arrhythm", "cardiac", "heart rate")),
    ("coagulation/platelet", ("coagulation", "anticoagul", "platelet", "bleeding")),
    ("liver/kidney", ("hepatic", "hepatotox", "renal", "nephro", "kidney", "liver injury")),
    ("immune/inflammatory", ("immune", "immunomod", "cytokine", "inflamm")),
)

EXPERIMENTAL_COMBINATION_TERMS = (
    "coadministr", "concomitant", "combination", "drug interaction", "interaction with",
    "pharmacokinetic interaction", "combined with",
)

EXPERIMENTAL_HUMAN_TERMS = (
    "patients", "participants", "healthy adults", "healthy men", "healthy women",
    "human volunteers", "human subjects", "subjects were", "individuals with",
    "randomized controlled trial", "randomised controlled trial", "clinical trial",
    "clinical study", "phase 1", "phase i", "phase 2", "phase ii", "phase 3", "phase iii",
)

EXPERIMENTAL_NO_HUMAN_PHRASES = (
    "no human studies", "no human trials", "lack of human studies", "without human data",
    "not been tested in humans", "has not been tested in humans", "preclinical only",
)

EXPERIMENTAL_INTERVENTION_TERMS = (
    "randomized", "randomised", "placebo", "controlled trial", "clinical trial",
    "phase 1", "phase i", "phase 2", "phase ii", "phase 3", "phase iii",
    "intervention", "administered", "received treatment", "treated with", "dose-ranging",
    "dose ranging", "dosing", "treatment group",
)


def experimental_human_hit(hit: dict) -> bool:
    """Conservative text gate for experimental human evidence.

    The library's A/B metadata describes study design, not species. This extra check prevents
    animal RCTs, cell work, and mechanism-only reviews from being called human evidence.
    """
    text = " ".join((hit.get("text", ""), hit.get("source_pdf", ""))).lower()
    if any(phrase in text for phrase in EXPERIMENTAL_NO_HUMAN_PHRASES):
        # An explicit absence statement can coexist with generic words such as "clinical" in a
        # discussion section; require direct participant language to override it.
        return any(term in text for term in (
            "patients were", "participants were", "participants aged", "human volunteers",
            "subjects were randomized", "subjects were randomised",
        ))
    return any(term in text for term in EXPERIMENTAL_HUMAN_TERMS)


def experimental_human_intervention_hit(hit: dict) -> bool:
    """Require both explicit humans and exposure/intervention language for the broad gate."""
    if not experimental_human_hit(hit):
        return False
    text = " ".join((hit.get("text", ""), hit.get("source_pdf", ""))).lower()
    return any(term in text for term in EXPERIMENTAL_INTERVENTION_TERMS)


def _unique_human_hits(hits: Sequence[dict], required_terms: Sequence[str] = ()) -> list[dict]:
    unique: dict[str, dict] = {}
    for hit in hits:
        if hit.get("grade") not in ("A", "B"):
            continue
        if not experimental_human_hit(hit):
            continue
        haystack = " ".join((hit.get("text", ""), hit.get("source_pdf", ""))).lower()
        if required_terms and not any(term in haystack for term in required_terms):
            continue
        source_key = hit.get("doi") or hit.get("source_pdf") or hit.get("text", "")[:120]
        unique[source_key] = hit
    return list(unique.values())


def experimental_mechanism_flags(ev: Evidence) -> list[str]:
    """Return retrieved pathway flags; these deliberately are not interaction verdicts."""
    text = " " + _normal(" ".join(
        " ".join((hit.get("text", ""), hit.get("source_pdf", ""))) for hit in ev.hits
    )) + " "
    flags: list[str] = []
    for label, terms in EXPERIMENTAL_MECHANISM_FLAGS:
        def present(term: str) -> bool:
            normalized = _normal(term)
            return (" " + normalized + " ") in text if len(normalized) <= 3 else normalized in text
        if any(present(term) for term in terms):
            flags.append(label)
    return flags[:4]


def current_stack_terms(profile: dict) -> list[str]:
    terms: list[str] = []
    medication_text = profile.get("medications", "")
    for key, label in MEDICATION_OPTIONS:
        if key != "other" and _contains(medication_text, (key, label)):
            terms.extend((key, label))
    current_keys = set(profile.get("current_supplement_keys", ()))
    for candidate in CATALOG:
        if candidate.key in current_keys:
            terms.extend((candidate.name, *candidate.aliases))
    return list(dict.fromkeys(_normal(term) for term in terms if _normal(term)))


def direct_combination_hits(candidate: Candidate, ev: Evidence, profile: dict) -> list[dict]:
    candidate_terms = {_normal(candidate.name), *(_normal(alias) for alias in candidate.aliases)}
    stack_terms = [term for term in current_stack_terms(profile) if term not in candidate_terms]
    if not stack_terms:
        return []
    matches: list[dict] = []
    for hit in ev.hits:
        text = " " + _normal(" ".join((hit.get("text", ""), hit.get("source_pdf", "")))) + " "
        if not any((" " + term + " ") in text for term in stack_terms):
            continue
        if not any((" " + _normal(term) + " ") in text for term in EXPERIMENTAL_COMBINATION_TERMS):
            continue
        matches.append(hit)
    return _unique_human_hits(matches)


def experimental_screen_markdown(
    candidates: Sequence[Candidate], evidence: dict[str, Evidence], decisions: dict[str, str], profile: dict
) -> str:
    policy = profile.get("experimental_policy", "approved_only")
    if policy != "screen_strong_human":
        return (
            "**Broad scan not requested.** The approved/ordinary boundary remains active. Individually selected "
            "peptide or gray-market topics are still reviewed elsewhere in this report, but HealthCoach did not "
            "search the full experimental catalog."
        )

    experimental = [
        candidate for candidate in candidates
        if candidate.queue == QUEUE_PEPTIDE and candidate.policy != "KEEP-PRESCRIPTION"
    ]
    passed = [candidate for candidate in experimental if evidence[candidate.key].coverage == "STRONG"]
    weak = sum(evidence[candidate.key].coverage == "WEAK" for candidate in experimental)
    none = sum(evidence[candidate.key].coverage == "NONE" for candidate in experimental)
    lines = [
        "**Research-only boundary:** opting in expands retrieval; it does not authorize buying, combining, or self-administering an experimental drug.",
        "",
        f"HealthCoach scanned **{len(experimental)}** experimental/unapproved topics. **{len(passed)}** passed the programmatic gate of at least two unique candidate-folder A/B sources with human-participant and intervention/exposure signals; {weak} were WEAK and {none} had NONE. Passing means relevant human intervention evidence exists—not that the effect is positive, useful for this user, safe, legal, correctly manufactured, or compatible.",
        "",
        "| Item passing human-intervention gate | Human coverage | Configured goal relevance | A/B safety-marked sources | Retrieved chemistry/biology flags | Direct combination evidence with recorded stack | Compatibility result | Audit decision |",
        "|---|---:|---|---:|---|---|---|---|",
    ]
    if not passed:
        lines.append("| _No experimental item passed_ | — | — | — | — | — | Not verified | Do not add |")
    for candidate in passed:
        ev = evidence[candidate.key]
        safety_hits = _unique_human_hits(ev.hits, EXPERIMENTAL_SAFETY_TERMS)
        combination_hits = direct_combination_hits(candidate, ev, profile)
        flags = ", ".join(experimental_mechanism_flags(ev)) or "No pathway flag extracted"
        if combination_hits:
            direct = "Human combination passage retrieved; clinician interpretation required"
            combo_tag = first_evidence_tag(Evidence("WEAK", "—", 0, 0, "", combination_hits))
            direct += f"<br>{combo_tag}"
        else:
            direct = "NONE — no direct co-use/interaction passage survived"
        compatibility = (
            "DIRECT HUMAN COMBINATION EVIDENCE LOCATED — not automatically compatible; direction, exposure, product, and patient factors require clinician/pharmacist review"
            if combination_hits else
            "NOT VERIFIED — mechanistic flags cannot establish safe co-use; direct human interaction and product-specific evidence are required"
        )
        vals = (
            candidate.name, f"{ev.coverage}; {ev.unique_papers} sources",
            ", ".join(ISSUES[issue] for issue in candidate.issues if issue in profile.get("issues", ())) or "No selected-goal match",
            len(safety_hits), flags,
            direct, compatibility, decisions[candidate.key],
        )
        lines.append("| " + " | ".join(str(value).replace("|", "/").replace("\n", "<br>") for value in vals) + " |")
    lines.extend([
        "",
        "#### How compatibility is checked",
        "",
        "1. **Human intervention evidence:** at least two independent, candidate-folder A/B sources with explicit human-participant and intervention/exposure language are required before an experimental topic is surfaced here. This is a data-availability gate, not proof the effect is positive or useful.",
        "2. **Human safety and exposure:** adverse events, tolerability, pharmacokinetics, population, form, and duration are checked separately; efficacy coverage never substitutes for safety coverage.",
        "3. **Chemistry and biology:** retrieved receptor/pathway, CYP/transporter, cardiac, glucose, growth, coagulation, liver/kidney, and immune signals create **risk flags only**. They cannot prove two products are compatible.",
        "4. **Direct combination evidence:** a compatible verdict requires product-specific human interaction/co-use evidence plus clinician/pharmacist interpretation. In its absence the answer is **UNKNOWN / NOT VERIFIED**, never “probably safe.”",
        "5. **Product and regulatory identity:** verify the exact finished product and current status. FDA explains that unapproved drugs have not been reviewed for safety, effectiveness, or quality: [Unapproved Drugs](https://www.fda.gov/drugs/enforcement-activities-fda/unapproved-drugs). FDA's interaction framework uses in-vitro and clinical evidence together during risk assessment: [M12 Drug Interaction Studies](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/m12-drug-interaction-studies).",
    ])
    return "\n".join(lines)


def first_evidence_tag(ev: Evidence) -> str:
    if not ev.hits:
        return "COVERAGE GAP"
    h = ev.hits[0]
    return "[%s / %s / %s]" % (h.get("grade", "—"), h.get("folder", "unknown"), h.get("doi") or "no-doi")


def result_for(candidate: Candidate, profile: dict) -> str:
    recorded = profile.get("supplement_results", "no result recorded").strip()
    clauses = [x.strip() for x in re.split(r"[;\n]+", recorded) if x.strip()]
    for clause in clauses:
        if _contains(clause, (candidate.name, *candidate.aliases)):
            return clause
    if len(profile.get("current_supplement_keys", ())) == 1 and candidate.key in profile.get("current_supplement_keys", ()):
        return recorded
    return "No item-specific result recorded"


def recorded_lab_mentions(candidate: Candidate, profile: dict) -> bool:
    labs = profile.get("confirmed_deficiencies_or_labs", "").strip().lower()
    if not labs or labs in {"none", "unknown", "none/unknown", "normal"}:
        return False
    return _contains(labs, (candidate.name, *candidate.aliases))


def stack_action(candidate: Candidate, ev: Evidence, decision: str, profile: dict, current: bool) -> str:
    result = result_for(candidate, profile).lower()
    adverse = any(term in result for term in (
        "side effect", "worse", "rash", "palpitation", "insomnia", "anxiety", "nausea", "diarrhea", "dizzy"
    ))
    no_effect = any(term in result for term in ("no effect", "no benefit", "nothing", "did not work"))
    gated = candidate.policy in {
        "DEFICIENCY-GATED", "INTAKE/CLINICIAN-GATED", "CLINICIAN-GATED", "MEDICATION-REVIEW", "SAFETY-REVIEW"
    }
    if candidate.policy == "KEEP-PRESCRIPTION":
        return "KEEP-PRESCRIPTION — prescriber managed; no dose change"
    if current:
        if adverse:
            return "REMOVE/PAUSE OPTIONAL USE AND REVIEW THE RECORDED REACTION WITH A CLINICIAN/PHARMACIST"
        if candidate.policy.startswith("SKIP") or ev.coverage == "NONE":
            return "REMOVE / DO NOT REBUY unless a clinician supplied a separate indication"
        if no_effect:
            if gated:
                return "DO NOT REBUY unless a documented deficiency/intake need or clinician direction justifies it"
            return "REMOVE / DO NOT REBUY unless a measurable target justifies another trial"
        if gated:
            if recorded_lab_mentions(candidate, profile):
                return "KEEP ONLY AS CLINICIAN-DIRECTED CORRECTION; use dated follow-up results to reassess"
            return "REVIEW AGAINST LABS, INTAKE, MEDICATIONS, AND CLINICIAN/PHARMACIST ADVICE"
        if ev.coverage == "STRONG" and set(candidate.issues).intersection(profile["issues"]):
            return "KEEP — relevant and supported; continue tracking a measurable result"
        if ev.coverage == "WEAK":
            return "OPTIONAL LOW-CONFIDENCE KEEP; remove first if simplifying or benefit is unclear"
        return "REMOVE IF THERE IS NO SPECIFIC MEASURABLE PURPOSE"
    if decision == "SHORTLIST FOR REVIEW":
        return "ADD-CANDIDATE — clear safety/interaction gates before buying"
    explicitly_selected = candidate.key in (
        set(profile.get("priority_supplement_keys", ())) | set(profile.get("selected_peptide_keys", ()))
    )
    if explicitly_selected and gated and recorded_lab_mentions(candidate, profile):
        return "CLINICIAN-GATED ADD CANDIDATE — the recorded lab mentions this nutrient; verify indication and follow-up"
    if explicitly_selected and ev.coverage == "WEAK":
        return "ADD TO CONSIDERATION LIST — USER-SELECTED, LOW CONFIDENCE, SAFETY REVIEW REQUIRED"
    if explicitly_selected and ev.coverage == "NONE":
        return "ADD TO WATCHLIST — USER-SELECTED COVERAGE GAP, NOT RECOMMENDED FOR USE"
    return decision


def stack_change_tables(
    candidates: Sequence[Candidate], evidence: dict[str, Evidence], decisions: dict[str, str], profile: dict
) -> str:
    current_keys = {c.key for c in candidates if candidate_is_current(c, profile)}
    selected = set(profile.get("priority_supplement_keys", ())) | set(profile.get("selected_peptide_keys", ()))
    current_items = [c for c in candidates if c.key in current_keys]
    proposed = [
        c for c in candidates
        if c.key not in current_keys and (decisions[c.key] == "SHORTLIST FOR REVIEW" or c.key in selected)
    ]

    def table(items: Sequence[Candidate], current: bool) -> str:
        if not items:
            return "_None._"
        lines = [
            "| Item | Reported personal result | Coverage | Goal fit | Preferred intake route | Recommended change | Retrieved basis |",
            "|---|---|---:|---|---|---|---|",
        ]
        for c in items:
            ev = evidence[c.key]
            result = result_for(c, profile) if current else "Not currently used"
            fit = ", ".join(ISSUES[x] for x in c.issues if x in profile["issues"]) or "No selected goal match"
            action = stack_action(c, ev, decisions[c.key], profile, current)
            vals = (c.name, result, ev.coverage, fit, preferred_source_text(c, profile), action, first_evidence_tag(ev))
            lines.append("| " + " | ".join(str(v).replace("|", "/").replace("\n", "<br>") for v in vals) + " |")
        return "\n".join(lines)

    return (
        "#### Current stack: keep, remove, or review\n\n"
        + table(current_items, True)
        + "\n\n#### New and user-requested candidates\n\n"
        + table(proposed, False)
        + "\n\n**PLANNING DECISION RULE:** self-reported benefit or harm changes the practical action but never upgrades the retrieved evidence grade."
    )


def source_rows(candidates: Sequence[Candidate], evidence: dict[str, Evidence]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for c in candidates:
        for h in evidence[c.key].hits:
            source_key = h.get("doi") or h.get("source_pdf") or h.get("text", "")[:120]
            if source_key in seen:
                continue
            seen.add(source_key)
            doi = h.get("doi") or "no-doi"
            lines.append("- [%s | %s | %s] `%s`" % (
                h.get("grade", "—"), h.get("folder", "unknown"), doi,
                os.path.basename(h.get("source_pdf", "unknown")),
            ))
    return "\n".join(lines) or "- No on-topic sources survived retrieval."


def timing_source_rows(ev: Evidence) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for h in ev.hits:
        source_key = h.get("doi") or h.get("source_pdf") or h.get("text", "")[:120]
        if source_key in seen:
            continue
        seen.add(source_key)
        lines.append("- [%s | %s | %s] `%s`" % (
            h.get("grade", "—"), h.get("folder", "unknown"), h.get("doi") or "no-doi",
            os.path.basename(h.get("source_pdf", "unknown")),
        ))
    return "\n".join(lines) or "- No on-topic timing source survived retrieval."


def render_terminal_summary(candidates: Sequence[Candidate], evidence: dict[str, Evidence], decisions: dict[str, str], out: Path) -> None:
    table = Table(title="Personalized shortlist", box=box.ROUNDED, border_style="bright_cyan")
    table.add_column("Item", style="bold")
    table.add_column("Coverage")
    table.add_column("Decision")
    shortlist = [c for c in candidates if decisions[c.key] == "SHORTLIST FOR REVIEW"]
    if not shortlist:
        table.add_row("None", "—", "No new OTC item cleared the coverage + relevance rules")
    else:
        for c in shortlist:
            table.add_row(c.name, evidence[c.key].coverage, decisions[c.key])
    console.print("\n", table)
    console.print(Panel.fit(
        f"[bold green]Audit complete[/bold green]\n[white]{out}[/white]\n\n"
        f"Browse chapters and logical pages with the keyboard:\n"
        f"[cyan]cd \"{HERE}\" && ./hc-report[/cyan]\n\n"
        f"Or open the complete static report:\n[cyan]glow -p \"{out}\"[/cyan]",
        border_style="green", padding=(1, 2),
    ))


def indexed_document(body: str, generated_at: str) -> str:
    """Add one stable, machine-readable chapter/page index to the canonical report.

    Markdown has no viewer-independent physical pages: line wrapping changes with the
    terminal, font, and paper size.  The PAGE identifiers below are therefore logical
    pages attached to level-three report chapters.  They remain stable for a given
    report structure and are usable in print, terminal search, links, and AI prompts.
    """
    part_re = re.compile(r"^## PART\s+([IVXLCDM]+)\s+—\s+(.+?)\s*$")
    chapter_re = re.compile(r"^###\s+(.+?)\s*$")
    indexed_lines: list[str] = []
    entries: list[tuple[str, str, str, str, str]] = []
    current_part = "0"
    current_part_title = "Front matter"
    chapter_in_part = 0
    page_number = 0

    for line in body.strip().splitlines():
        part_match = part_re.match(line)
        if part_match:
            current_part = part_match.group(1)
            current_part_title = part_match.group(2).strip()
            chapter_in_part = 0
            part_anchor = f"hc-part-{current_part.lower()}"
            entries.append(("part", current_part, "—", f"PART {current_part}", current_part_title))
            indexed_lines.extend([
                '<div style="page-break-before: always;"></div>',
                f'<a id="{part_anchor}"></a>',
                line,
            ])
            continue

        chapter_match = chapter_re.match(line)
        if chapter_match:
            chapter_in_part += 1
            page_number += 1
            page_id = f"{page_number:03d}"
            chapter_id = f"{current_part}.{chapter_in_part:02d}"
            title = chapter_match.group(1).strip()
            anchor = f"hc-page-{page_id}"
            entries.append(("chapter", current_part, page_id, chapter_id, title))
            indexed_lines.extend([
                f'<a id="{anchor}"></a>',
                f"### CHAPTER {chapter_id} · PAGE {page_id} — {title}",
            ])
            continue

        indexed_lines.append(line)

    index_rows: list[str] = []
    for kind, part, page_id, chapter_id, title in entries:
        safe_title = title.replace("|", "\\|")
        if kind == "part":
            index_rows.append(
                f'| **PART {part}** | — | — | [**{safe_title}**](#hc-part-{part.lower()}) |'
            )
        else:
            index_rows.append(
                f'| PART {part} | [{chapter_id}](#hc-page-{page_id}) | '
                f'[{page_id}](#hc-page-{page_id}) | [{safe_title}](#hc-page-{page_id}) |'
            )

    index_table = "\n".join([
        "| Part | Chapter | Logical page | Contents |",
        "|---|---:|---:|---|",
        *index_rows,
    ])
    return f"""# HEALTHCOACH — CURRENT CONSOLIDATED REPORT

_Generated {generated_at}. This is the sole generated report and is overwritten by each audit run; prior generated logs are not required._

## DOCUMENT CONTROL

- **Canonical file:** `HEALTHCOACH_REPORT.md`
- **Navigation:** use the clickable master index below or search `CHAPTER I.01`, `PAGE 001`, a topic, or a DOI.
- **Page convention:** `PAGE 001`, `PAGE 002`, and so on are stable **logical pages**, not font-dependent physical sheet numbers. Each logical page begins at a chapter heading.
- **Print convention:** each major PART begins on a new printed page when the Markdown renderer honors HTML page breaks.
- **Citation convention:** retrieved evidence uses `[grade | folder | DOI-or-no-DOI]`; directly audited public sources use descriptive links.

## MASTER CHAPTER AND PAGE INDEX

<!-- HC_INDEX_START -->
{index_table}
<!-- HC_INDEX_END -->

{chr(10).join(indexed_lines).rstrip()}
"""


def write_report(
    out: Path,
    profile: dict,
    candidates: Sequence[Candidate],
    evidence: dict[str, Evidence],
    decisions: dict[str, str],
    deep_cards: Sequence[str],
    timing_section: str,
    timing_evidence: Evidence,
) -> None:
    queues = []
    for queue in QUEUE_ORDER:
        group = [c for c in candidates if c.queue == queue]
        if group:
            queues.append(f"### {queue}\n\n{inventory_table(group, evidence, decisions, profile)}")
    shortlist = [c for c in candidates if decisions[c.key] == "SHORTLIST FOR REVIEW"]
    shortlist_md = inventory_table(shortlist, evidence, decisions, profile) if shortlist else "No new item cleared the shortlist rules."
    gates = [f"- **{c.name}:** {c.gate}" for c in candidates if c.gate]
    gaps = [f"- {c.name}" for c in candidates if evidence[c.key].coverage == "NONE"]
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    week = embedded_module(HERE / "WEEK_OPERATING_PLAN.md")
    nutrition = embedded_module(HERE / "FOOD_COFFEE_MILK_STACK_PLAN.md")
    whole_life = embedded_module(HERE / "WHOLE_LIFE_EVIDENCE_PLAN.md")
    body = f"""## PART I — CURRENT OPERATING WEEK

### PERSONALIZED TIMING OVERLAY — SOURCES CHECKED

{timing_section}

This overlay controls **when** cardio and strength are placed; the base week below controls **what** is performed and preserves its interference/skip rules. A morning or split selection becomes executable only when the recorded clock details resolve the 04:50–05:50 Anki and 06:00 work conflict; otherwise the existing 17:00 window remains the planning default.

{week}

## PART II — SELECTED STORES, COFFEE, MILK, FOOD, AND LOCKED-STACK PLAN

### SELECTED-STORE SOURCING OVERLAY

{store_sourcing_markdown(profile)}

{nutrition}

## PART III — WHOLE-LIFE, HOME, FOOD-ADDITION, AND FAITH EVIDENCE PLAN

### SELECTED PRIORITIES AND PLAN VERDICTS

{whole_life_selection_markdown(profile)}

{whole_life}

## PART IV — PERSONALIZED SUPPLEMENT EVIDENCE AUDIT

> The “very / medium / low researched” labels are the user's submitted discovery queues, not findings. Coverage is recalculated from unique retrieved A/B human sources. This report does not diagnose a deficiency, change tirzepatide, or provide gray-market protocols.

### 0. INTAKE QUESTIONS AND RECORDED ANSWERS

{questionnaire_markdown(profile)}

### 1. PERSONALIZED STACK CHANGES

{stack_change_tables(candidates, evidence, decisions, profile)}

### 2. RESEARCH QUESTIONS USED FOR EACH CANDIDATE

For every selected item, the audit asks: What outcomes and effect magnitudes were reported? Which population was studied? What form, amount, and duration did the human studies use? Do independent human papers converge? What safety or interaction evidence was retrieved? How directly does that evidence fit the recorded problems, medications, and deficiencies? Every generated answer is tied to the references printed beside it.

### 3. DECISION SYSTEM

- **STRONG:** at least two unique on-topic retrieved A/B human sources; **WEAK:** one; **NONE:** zero.
- Duplicate DOI hardlinks count once. General-adult evidence is distinguished from older-only evidence.
- The actionable shortlist is capped at **three new OTC items beyond creatine and whey-as-food**.
- Deficiency-dependent nutrients remain behind tests, diet review, or clinician review even when coverage is strong.
- “Retrieved studies used” describes research; it is not a personal dose.
- User-selected weak or sparse topics remain visible, receive priority deep review, and enter the consideration/watchlist; selection does not upgrade coverage or automatically place them in the active stack.

### 4. WHOLE-FOOD VS ISOLATED-PRODUCT INTAKE ROUTES

{food_source_strategy_markdown(candidates, evidence, decisions, profile)}

### 5. EXPERIMENTAL / UNAPPROVED HUMAN-EVIDENCE AND COMPATIBILITY SCREEN

{experimental_screen_markdown(candidates, evidence, decisions, profile)}

### 6. PERSONALIZED SHORTLIST

{shortlist_md}

### 7. DEFICIENCY, MEDICATION, AND SAFETY GATES

{chr(10).join(gates) if gates else '- No predeclared gates in the selected catalog.'}

### 8. COMPLETE EVIDENCE INVENTORY

{chr(10).join(queues)}

### 9. QUESTION-BY-QUESTION DEEP EVIDENCE ANSWERS

{chr(10).join(deep_cards) if deep_cards else '_Deep generation was disabled; use the evidence inventory and source trail._'}

### 10. COVERAGE GAPS

The library did not return an on-topic A/B human passage for these selected candidates; this is a reason to abstain, not permission to fill the gap from memory.

{chr(10).join(gaps) if gaps else '- None among the selected candidates.'}

### 11. RETRIEVED SOURCE TRAIL

#### Training-timing sources

{timing_source_rows(timing_evidence)}

#### Supplement and peptide sources

{source_rows(candidates, evidence)}
"""
    text = indexed_document(body, now)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def show_catalog() -> None:
    combined = (*CATALOG, *PEPTIDE_CATALOG)
    table = Table(
        title=f"Audit catalog — {len(CATALOG)} supplements + {len(PEPTIDE_CATALOG)} peptide/gray reviews",
        box=box.ROUNDED,
    )
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Submitted queue")
    table.add_column("Candidate", style="bold")
    table.add_column("Mapped folders", overflow="fold")
    for i, c in enumerate(combined, 1):
        table.add_row(str(i), c.queue.replace("Submitted: ", ""), c.name, ", ".join(c.folders) or "exact-term global search")
    console.print(table)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Interactive, RAG-grounded supplement evidence audit")
    ap.add_argument("--list", action="store_true", help="list every candidate without loading models")
    ap.add_argument("--non-interactive", action="store_true", help="use flags/defaults instead of the questionnaire")
    ap.add_argument(
        "--detailed-assessment",
        action="store_true",
        help="use the typing-heavy assessment; default interactive mode is a nine-step guided checklist",
    )
    ap.add_argument("--issues", help="comma-separated issue keys or numbers; use --list-issues")
    ap.add_argument("--list-issues", action="store_true", help="show questionnaire issue keys")
    ap.add_argument("--list-lifestyle", action="store_true", help="show food/home/alternative selector keys")
    ap.add_argument("--name")
    ap.add_argument("--height")
    ap.add_argument("--goals")
    ap.add_argument("--priorities", help="ranked outcome priorities")
    ap.add_argument("--training", help="weekly training, mileage, experience, and consistency")
    ap.add_argument("--cardio-timing", choices=dict(CARDIO_TIMING_OPTIONS), help="morning, evening, both, or recommend")
    ap.add_argument("--cardio-clock", help="clock tradeoff or available window for the selected cardio timing")
    ap.add_argument("--workout-timing", choices=dict(WORKOUT_TIMING_OPTIONS), help="morning, evening, both, or recommend")
    ap.add_argument("--workout-clock", help="clock tradeoff or available window for strength-workout timing")
    ap.add_argument("--injuries", help="pain, injuries, or aggravating movements")
    ap.add_argument("--current", help="current supplements")
    ap.add_argument("--supplement-results", help="observed benefits, no-effects, side effects, and duration")
    ap.add_argument("--medications", help="medications/prescriptions")
    ap.add_argument("--deficiencies", help="confirmed deficiencies/labs")
    ap.add_argument("--conditions", help="conditions and safety flags")
    ap.add_argument("--vitals", help="known BP, resting HR, or measurements")
    ap.add_argument("--reactions", help="prior supplement side effects or intolerance")
    ap.add_argument("--diet", help="diet exclusions, low-intake foods, or GI triggers")
    ap.add_argument("--food-additions", help="comma-separated food-addition selector keys, or all/none")
    ap.add_argument("--home-practices", help="comma-separated apartment/home-practice selector keys, or all/none")
    ap.add_argument("--alternative-items", help="comma-separated alternative-item selector keys, or all/none")
    ap.add_argument("--whole-life-details", help="housing limits, faith tradition, sourcing limits, or ambiguous-item details")
    ap.add_argument("--stores", help="comma-separated retailer keys willing to be searched, or all/none")
    ap.add_argument("--caffeine", help="caffeine pattern")
    ap.add_argument("--sleep", help="sleep pattern and apnea flags")
    ap.add_argument("--substances", help="alcohol, nicotine, cannabis, energy drinks, or other stimulants")
    ap.add_argument("--preferences", help="budget, form, testing, and product constraints")
    ap.add_argument("--timeline", help="deadline, race date, or time constraint")
    ap.add_argument("--notes", help="one catch-all note for a non-interactive assessment")
    ap.add_argument("--items", help="comma-separated subset; all requested candidates are default")
    ap.add_argument("--priority-items", help="comma-separated supplements guaranteed priority in deep-card selection")
    ap.add_argument(
        "--supplement-source",
        choices=dict(SUPPLEMENT_SOURCE_OPTIONS),
        help="whole_food_first (default), mixed, or products_allowed",
    )
    ap.add_argument("--peptides", help="comma-separated peptide/gray review items; use 'none' to omit")
    ap.add_argument(
        "--experimental-policy",
        choices=dict(EXPERIMENTAL_POLICY_OPTIONS),
        help="approved_only (default) or research-only screen_strong_human broad scan",
    )
    ap.add_argument("--deep-limit", type=int, default=None, help="number of model-written deep cards (default 12)")
    ap.add_argument("--all-deep", action="store_true", help="write deep cards for every selected item; can take a long time")
    ap.add_argument("--evidence-only", action="store_true", help="skip local LLM generation; inventory + source trail only")
    ap.add_argument("--max-tokens", type=int, default=900, help="maximum tokens per deep card")
    ap.add_argument("--output", help="explicit Markdown output path")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        show_catalog(); return 0
    if args.list_issues:
        for key, label in ISSUES.items():
            console.print(f"[cyan]{key:>10}[/cyan]  {label}")
        return 0
    if args.list_lifestyle:
        for title, choices in (
            ("STORES — MULTIPLE MAY BE SELECTED", STORE_OPTIONS),
            ("FOOD ADDITIONS", FOOD_ADDITION_OPTIONS),
            ("APARTMENT / HOME PRACTICES", HOME_PRACTICE_OPTIONS),
            ("ALTERNATIVE / CLINICAL CLAIMS", ALTERNATIVE_ITEM_OPTIONS),
        ):
            console.print(f"\n[bold]{title}[/bold]")
            for key, label in choices:
                console.print(f"[cyan]{key:>22}[/cyan]  {label}")
        return 0

    interactive = sys.stdin.isatty() and not args.non_interactive
    try:
        if interactive:
            profile = ask_profile_detailed() if args.detailed_assessment else ask_profile_quick()
        else:
            profile = default_profile(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Assessment cancelled. The existing report was not changed.[/yellow]")
        return 130
    supplement_candidates = select_candidates(args.items)
    manually_selected_peptides = set(profile.get("selected_peptide_keys", ()))
    broad_experimental_scan = profile.get("experimental_policy") == "screen_strong_human"
    peptide_candidates = [
        c for c in PEPTIDE_CATALOG
        if broad_experimental_scan or c.key in manually_selected_peptides
    ]
    profile["experimental_scan_keys"] = [
        c.key for c in peptide_candidates
        if broad_experimental_scan and c.policy != "KEEP-PRESCRIPTION"
    ]
    candidates = [*supplement_candidates, *peptide_candidates]
    explicit_count = len(
        (set(profile.get("priority_supplement_keys", ())) | set(profile.get("selected_peptide_keys", ())))
        & {c.key for c in candidates}
    )
    deep_limit = len(candidates) if args.all_deep else (
        max(12, explicit_count) if args.deep_limit is None else max(0, args.deep_limit)
    )
    if args.evidence_only:
        deep_limit = 0

    out = Path(args.output).expanduser().resolve() if args.output else DEFAULT_OUT

    console.print(Panel(
        f"[bold]{len(candidates)} candidates[/bold] · deep cards: [bold]{deep_limit}[/bold]\n"
        "Loading the embedding model and reranker; evidence is retrieved locally.",
        title="Audit scope", border_style="bright_blue",
    ))
    import lancedb
    from sentence_transformers import SentenceTransformer
    emb = SentenceTransformer(HC.EMB_MODEL, device="mps")
    tbl = lancedb.connect(HC.DBDIR).open_table(HC.TABLE)
    reranker = HC.load_reranker()

    evidence: dict[str, Evidence] = {}
    progress = Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(), console=console,
    )
    with progress:
        task = progress.add_task("Retrieving and de-duplicating evidence", total=len(candidates) + 1)
        for c in candidates:
            progress.update(task, description=f"Checking {c.name[:38]}")
            evidence[c.key] = retrieve_candidate(
                tbl, emb, reranker, c, profile["issue_labels"], profile["medications"]
            )
            progress.advance(task)
        progress.update(task, description="Checking cardio and strength timing")
        timing_evidence = retrieve_timing_evidence(tbl, emb, reranker, profile)
        progress.advance(task)

    if args.deep_limit is None and not args.all_deep and not args.evidence_only and broad_experimental_scan:
        strong_experimental = sum(
            c.queue == QUEUE_PEPTIDE
            and c.policy != "KEEP-PRESCRIPTION"
            and evidence[c.key].coverage == "STRONG"
            for c in candidates
        )
        # Keep every broad-scan item that passed the human-source gate eligible for a deep
        # answer in addition to the user's manual priorities. Explicit --deep-limit still wins.
        deep_limit = max(deep_limit, explicit_count + strong_experimental)

    decisions = preliminary_decisions(candidates, evidence, profile)
    deep_candidates = choose_deep_candidates(candidates, evidence, profile, decisions, deep_limit)
    cards: list[str] = []
    timing_section = deterministic_timing_card(timing_evidence, profile)
    # Checkpoint the complete inventory before slow generation starts.
    write_report(out, profile, candidates, evidence, decisions, cards, timing_section, timing_evidence)
    if deep_candidates:
        console.print("\n[bold]Loading the local generator for deep evidence cards...[/bold]")
        from mlx_lm import load
        model, tok = load(HC.GEN_MODEL)
        try:
            console.print("[bold]Synthesizing the source-bound training-timing recommendation...[/bold]")
            timing_section = timing_card(model, tok, timing_evidence, profile, args.max_tokens)
            write_report(out, profile, candidates, evidence, decisions, cards, timing_section, timing_evidence)
            with progress:
                task = progress.add_task("Writing bounded deep cards", total=len(deep_candidates))
                for c in deep_candidates:
                    progress.update(task, description=f"Synthesizing {c.name[:38]}")
                    cards.append(deep_card(model, tok, c, evidence[c.key], decisions[c.key], profile, args.max_tokens))
                    write_report(out, profile, candidates, evidence, decisions, cards, timing_section, timing_evidence)
                    progress.advance(task)
        except KeyboardInterrupt:
            write_report(out, profile, candidates, evidence, decisions, cards, timing_section, timing_evidence)
            console.print(Panel.fit(
                f"[yellow]Interrupted safely.[/yellow] The full inventory and {len(cards)} completed deep card(s) were saved.\n{out}",
                border_style="yellow",
            ))
            return 130

    write_report(out, profile, candidates, evidence, decisions, cards, timing_section, timing_evidence)
    render_terminal_summary(candidates, evidence, decisions, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

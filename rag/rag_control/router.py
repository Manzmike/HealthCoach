# rag/rag_control/router.py
"""Intent router + critic for HealthCoach RAG.

classify() is multi-intent: it returns every intent with a real keyword
hit, never a single forced best-match, and never falls back to a default
intent when nothing matches (there is no default_if_unknown -- an
unmatched query gets zero lane restriction, not a forced lane set).

Use allowed_lanes(classify(query)) to build the retrieval filter.
Use leftover_forbid_lanes(classify(query)) for the critic's drift-check.
Use critique() on every generated draft, matched intent or not.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_json(name: str):
    with (HERE / name).open(encoding="utf-8") as f:
        return json.load(f)


ROUTER = load_json("router.json")
CRITIC = load_json("critic.json")
PERSON = load_json("person_state.json")

_INTENT_HINTS = {
    "sleep_eds": (
        "apnea", "pause", "snore", "drowsy", "drive", "2am", "2 am", "woke",
        "wake", "dream", "orgasm", "release", "psychosis", "headache",
        "sleep study", "inconclusive", "cpap", "drop after", "dropped after",
    ),
    "incretin": ("tirzepatide", "mounjaro", "zepbound", "the shot", "nauseous", "stopping"),
    "lipids": ("ldl", "lp(a)", "lpa", "cholesterol", "statin", "crp"),
    "cut_train": ("cut", "deficit", "lift", "gym", "steps", "run", "copper"),
    "ancestry_hormones": ("nigerian", "testosterone", "trt", "vitamin d", "ancestry"),
    "lifestyle_night": ("code", "laptop", "phone", "dinner", "drinks", "caffeine", "screen"),
    "covid_vax": ("covid", "vaccine", "vax", "mrna", "myocarditis", "booster",
                  "pericarditis", "long covid"),
}


def classify(query: str) -> list[str]:
    """Every intent with at least one keyword hit, in ROUTER["intents"] key
    order. Empty list if nothing hits -- there is no forced default intent."""
    q = query.lower()
    return [intent for intent, hints in _INTENT_HINTS.items() if any(h in q for h in hints)]


def allowed_lanes(matched: list[str]) -> set[str] | None:
    """None means "no lane restriction at all" (zero intents matched).
    Otherwise the union of every matched intent's own `lanes` list --
    forbid_lanes plays no role here, only in leftover_forbid_lanes()."""
    if not matched:
        return None
    lanes: set[str] = set()
    for intent in matched:
        lanes |= set(ROUTER["intents"][intent]["lanes"])
    return lanes


def leftover_forbid_lanes(matched: list[str]) -> set[str]:
    """Lanes forbidden by a matched intent AND not allowed by any other
    matched intent. Single-intent queries get that intent's full forbid
    list. Zero-intent queries get nothing (nothing was forbidden by
    nothing)."""
    if not matched:
        return set()
    allowed = allowed_lanes(matched) or set()
    forbidden: set[str] = set()
    for intent in matched:
        forbidden |= set(ROUTER["intents"][intent].get("forbid_lanes", []))
    return forbidden - allowed


def lead_intent(matched: list[str]) -> str | None:
    """Highest-priority matched intent, for narrative ordering only --
    has no effect on retrieval or the critic."""
    if not matched:
        return None
    priority = ROUTER["lead_priority"]
    ranked = sorted(matched, key=lambda i: priority.index(i) if i in priority else len(priority))
    return ranked[0]


def boost_for(meta: dict) -> float:
    b = ROUTER["boost"]
    score = 1.0
    if meta.get("personal"):
        score *= b["personal_pack"]
    grade = str(meta.get("grade", "")).upper()
    if grade == "A":
        score *= b["grade_A"]
    elif grade == "B":
        score *= b["grade_B"]
    elif grade == "C":
        score *= b["grade_C"]
    if meta.get("us_rct"):
        score *= b["us_rct_tagged"]
    return score


_DRUG_DOSE_PATTERN = re.compile(
    r"\b(?:start|stop|hold|skip|increase|decrease|change)\b.{0,40}\b(?:the\s+)?(?:pen|dose|tirzepatide|shot)\b"
    r"|\b(?:take|inject)\b.{0,20}\d+\s*(?:mg|mcg)\b.{0,20}\btirzepatide\b",
    re.IGNORECASE,
)
_VACCINE_CAUSATION_PATTERN = re.compile(
    r"\b(?:vaccine|shot|vax)\b.{0,30}\bcaused?\b.{0,30}\b(?:apnea|pauses?|sleep)\b"
    r"|\b(?:apnea|pauses?|sleep)\b.{0,30}\b(?:was|is)\b.{0,10}\bcaused\b.{0,20}\b(?:vaccine|shot|vax)\b",
    re.IGNORECASE,
)
_NEGATION_NEARBY = re.compile(
    r"\b(?:not|n't|no|never|unlikely|doesn't|didn't|isn't|wasn't|hasn't|haven't|no evidence)\b",
    re.IGNORECASE,
)


def _unnegated_match(pattern: re.Pattern, text: str, window: int = 20) -> bool:
    """True only if `pattern` matches somewhere in `text` with no negation
    cue in the ~20 chars before the match through 5 chars after it. This is
    what stops the critic from rejecting a SAFE, correct denial ("the
    vaccine did not cause your apnea") as if it were the violation itself."""
    for m in pattern.finditer(text):
        ctx = text[max(0, m.start() - window):m.end() + 5]
        if not _NEGATION_NEARBY.search(ctx):
            return True
    return False


def critique(draft: str, matched: list[str], *, action_count: int, primary_count: int, drowsy: bool) -> dict:
    text = draft.lower()
    flags = [term for term in CRITIC["reject_if_mentions"] if term.lower() in text]

    if _unnegated_match(_DRUG_DOSE_PATTERN, draft):
        flags.append("doses_or_orders_drug_action")
    if _unnegated_match(_VACCINE_CAUSATION_PATTERN, draft):
        flags.append("concludes_vaccine_caused_condition")

    drift_lanes = leftover_forbid_lanes(matched)
    # Lightweight drift-check: only run if the intent actually left something
    # forbidden. This is a keyword heuristic (see spec Sec 7), not a hard
    # reject -- it reuses the same lane names as topic keywords.
    drift_terms = {
        "incretin-context": ("tirzepatide", "mounjaro", "the shot"),
        "hormones-off": ("testosterone", "trt", "hormone"),
        "peptides": ("peptide", "bpc-157", "tb-500"),
        "food-inflammation": ("anti-inflammatory diet", "food plan"),
    }
    for lane in drift_lanes:
        if any(term in text for term in drift_terms.get(lane, ())):
            flags.append(f"drift_into_{lane}")

    if action_count > CRITIC["max_actions"]:
        flags.append("actions_gt_3")
    if primary_count > CRITIC["max_primary_focus"]:
        flags.append("primary_focus_gt_1")
    if drowsy and CRITIC["must_include_if_drowsy"].lower() not in text:
        flags.append("missing_drowsy_drive_line")

    ok = not flags
    return {
        "ok": ok,
        "flags": flags,
        "fallback": None if ok else copy.deepcopy(CRITIC["fallback_plan"]),
        "lead_intent": lead_intent(matched),
        "person_as_of": PERSON["as_of"],
    }


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "I woke at 2 and had to release"
    matched = classify(q)
    print(json.dumps({
        "query": q,
        "matched_intents": matched,
        "lead_intent": lead_intent(matched),
        "allowed_lanes": sorted(allowed_lanes(matched)) if allowed_lanes(matched) else "UNRESTRICTED",
        "leftover_forbid_lanes": sorted(leftover_forbid_lanes(matched)),
    }, indent=2))

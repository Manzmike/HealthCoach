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


# --------------------------------------------------------------------------
# Universal hard-reject detectors (trigger-anchored, negation-aware)
#
# Design (see task-8-report.md "Fix round 4"): rather than writing one big
# regex per violation and then trying to decide whether "the match" is
# negated, each detector is anchored on a single TRIGGER token -- the drug
# action verb, or the `caus-` stem -- and then asks two independent
# questions about that one trigger:
#
#   1. Is it a violation shape?  Are the required companion words nearby,
#      within the SAME SENTENCE?  This search deliberately crosses commas,
#      because a legitimate single instruction may carry a parenthetical
#      ("Increase, if you tolerate it well, your tirzepatide dose to 10mg").
#
#   2. Is it negated?  Look BACKWARD from the trigger over a few words,
#      bounded by the nearest clause-separating comma, so that a negation
#      belonging to a different clause ("Don't skip your metformin dose,
#      but increase your tirzepatide dose...") cannot suppress it.
#
# Anchoring on the trigger (not on a whole regex match) is what makes the
# two rules independently tunable: a greedy whole-match regex could swallow
# several verbs at once and only ever negation-check the first one.
# --------------------------------------------------------------------------

# A sentence ends at . ! ? ; followed by whitespace or end-of-text. The
# trailing-whitespace requirement keeps decimals ("7.5mg") from splitting.
_SENTENCE_END = re.compile(r"[.!?;](?=\s|$)")

# Drug action verbs, and the objects that turn one into a dosing order.
_DRUG_VERB = re.compile(
    r"\b(start|stop|hold|skip|increase|decrease|change|take|inject)\b", re.IGNORECASE
)
_DRUG_OBJECT = re.compile(r"\b(?:the\s+)?(?:pen|dose|tirzepatide|shot)\b", re.IGNORECASE)
_DOSE_AMOUNT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg)\b", re.IGNORECASE)
_TIRZEPATIDE = re.compile(r"\btirzepatide\b", re.IGNORECASE)

# Causal-claim trigger and its two companion word classes.
_CAUSE_STEM = re.compile(r"\bcaus(?:e|es|ed|ing)\b", re.IGNORECASE)
_VACCINE_WORD = re.compile(r"\b(?:vaccine|shot|vax)\b", re.IGNORECASE)
_CONDITION_WORD = re.compile(r"\b(?:apnea|pauses?|sleep)\b", re.IGNORECASE)

# Negation cues. Bare "no" is deliberately NOT a cue -- "there's no doubt
# the vaccine caused your apnea" REINFORCES the claim -- so only explicit
# denial phrases built on "no" are listed. `\w+n't` covers every contraction
# ("don't", "can't", "wouldn't"); a bare `n't` never matches real text
# because there is no word boundary before the "n".
_NEGATION = re.compile(
    r"\b(?:not|never|unlikely|cannot|doubtful|unproven|neither"
    r"|no\s+(?:evidence|way|need|reason|proof|link|sign|indication))\b"
    r"|\w+n't\b",
    re.IGNORECASE,
)

# Words that mark the next clause as a NEW assertion rather than a
# continuation of the previous one, so a negation before them does not
# reach across.
_COORDINATORS = frozenset(
    {"and", "but", "or", "so", "yet", "nor", "then", "however", "although", "though", "while"}
)

_NEGATION_LOOKBACK_WORDS = 6
_PARENTHETICAL_MAX_WORDS = 6


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    """Start/end offsets of the sentence containing `pos`."""
    start, end = 0, len(text)
    for m in _SENTENCE_END.finditer(text):
        if m.start() < pos:
            start = m.end()
        else:
            end = m.start()
            break
    return start, end


def _is_aside(segment: str) -> bool:
    """A short comma-delimited segment that interrupts a clause rather than
    starting a new one ("if you tolerate it well", "in my opinion")."""
    words = segment.split()
    if len(words) > _PARENTHETICAL_MAX_WORDS:
        return False
    return not words or words[0].strip(".,;:!?'\"").lower() not in _COORDINATORS


def _strip_asides(fragment: str) -> str:
    """Drop interior parenthetical segments so the companion-word search
    measures the real distance of a single instruction. Only INTERIOR
    segments (commas on both sides) can be asides -- a segment bounded by
    the fragment's own edge is a real clause and is always kept."""
    parts = fragment.split(",")
    if len(parts) < 3:
        return fragment
    kept = [parts[0]] + [s for s in parts[1:-1] if not _is_aside(s)] + [parts[-1]]
    return ",".join(kept)


def _views(fragment: str) -> tuple[str, ...]:
    """The fragment as written, plus (when different) the same fragment with
    asides removed. Companion-word searches test BOTH: stripping is only
    ever meant to shorten the distance to a companion word, never to hide
    one that happens to sit inside the stripped segment
    ("Increase, your tirzepatide dose, next week.")."""
    stripped = _strip_asides(fragment)
    return (fragment,) if stripped == fragment else (fragment, stripped)


def _found_after(pattern: re.Pattern, fragment: str, span: int) -> bool:
    return any(pattern.search(v[:span]) for v in _views(fragment))


def _found_before(pattern: re.Pattern, fragment: str, span: int) -> bool:
    return any(pattern.search(v[-span:]) for v in _views(fragment))


def _negated(text: str, pos: int) -> bool:
    """Is the trigger at `pos` negated by something before it?

    Collects up to _NEGATION_LOOKBACK_WORDS words backward from `pos`,
    starting in the trigger's own comma-delimited clause. It steps back
    into an earlier clause only when the clause it just consumed is a short
    PARENTHETICAL -- few words and not opening with a coordinator -- which
    is what lets "Do not, under any circumstances, increase the dose" stay
    negated while "Don't skip metformin, but increase the dose" does not.
    """
    sent_start, _ = _sentence_bounds(text, pos)
    segments = text[sent_start:pos].split(",")

    words: list[str] = []
    i = len(segments) - 1
    while i >= 0 and len(words) < _NEGATION_LOOKBACK_WORDS:
        seg_words = segments[i].split()
        words = seg_words + words
        if i == 0:
            break
        # Only keep walking backward through an aside, never through a
        # clause that starts a new assertion.
        if not _is_aside(segments[i]):
            break
        i -= 1

    window = " ".join(words[-_NEGATION_LOOKBACK_WORDS:])
    return bool(_NEGATION.search(window))


def _drug_dose_violation(draft: str) -> bool:
    """Does the draft ORDER a drug action (as opposed to forbidding one)?"""
    for m in _DRUG_VERB.finditer(draft):
        _, sent_end = _sentence_bounds(draft, m.start())
        verb = m.group(1).lower()
        tail = draft[m.end():sent_end]
        if verb in ("take", "inject"):
            # "take 7.5mg of tirzepatide" -- an amount, then the drug. These
            # two verbs are common in ordinary prose ("take a walk"), so they
            # need the explicit amount, not just a drug noun.
            hit = False
            for view in _views(tail):
                amount = _DOSE_AMOUNT.search(view[:20])
                if amount and _TIRZEPATIDE.search(view[amount.end():amount.end() + 20]):
                    hit = True
                    break
        else:
            hit = _found_after(_DRUG_OBJECT, tail, 40)
        if hit and not _negated(draft, m.start()):
            return True
    return False


def _causation_violation(draft: str) -> bool:
    """Does the draft CONCLUDE the vaccine caused the user's condition?"""
    for m in _CAUSE_STEM.finditer(draft):
        sent_start, sent_end = _sentence_bounds(draft, m.start())
        before = draft[sent_start:m.start()]
        after = draft[m.end():sent_end]
        forward = _found_before(_VACCINE_WORD, before, 30) and _found_after(_CONDITION_WORD, after, 30)
        reverse = _found_before(_CONDITION_WORD, before, 30) and _found_after(_VACCINE_WORD, after, 30)
        if (forward or reverse) and not _negated(draft, m.start()):
            return True
    return False


def critique(draft: str, matched: list[str], *, action_count: int, primary_count: int, drowsy: bool) -> dict:
    text = draft.lower()
    flags = [term for term in CRITIC["reject_if_mentions"] if term.lower() in text]

    if _drug_dose_violation(draft):
        flags.append("doses_or_orders_drug_action")
    if _causation_violation(draft):
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

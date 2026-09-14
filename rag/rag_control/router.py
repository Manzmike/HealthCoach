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

# A sentence ends at . ! ? ; followed by whitespace or end-of-text (the
# trailing-whitespace requirement keeps decimals like "7.5mg" from
# splitting), or at a newline -- a line break (e.g. between bullet points
# in a drafted list) is just as hard a boundary as a period.
_SENTENCE_END = re.compile(r"[.!?;](?=\s|$)|\n")

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
    r"|no\s+(?:evidence|way|need|reason|proof|link|sign|indication|mechanism))\b"
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

# Words that open a NEW independent clause inside comma-free text, so a
# negation before one of them belongs to the previous clause and must not
# reach the trigger ("There is no evidence of harm so increase the dose").
# Deliberately narrower than _COORDINATORS: "and"/"or" routinely continue
# the same verb phrase under one negation ("You should not go ahead AND
# increase your dose"), so treating them as a break would resurrect the
# false positives Task 8 case 4 covers.
_CLAUSE_OPENERS = frozenset(
    {"so", "but", "yet", "however", "therefore", "thus", "then", "still",
     "although", "though", "whereas", "nor", "because", "since", "instead"}
)

# A spaced dash is a clause separator too ("no need for caution here -
# start the shot at 5mg"), the same way a comma is.
_DASH_BREAK = re.compile(r"\s[-‐-―]{1,2}\s")

# Hard upper bound on how far back the comma-free widening below may look.
# Wide enough for the real denials it exists for ("There is no evidence
# from the provided context that the COVID vaccine caused sleep apnea" --
# nine words), bounded so an unrelated negation cannot reach a trigger from
# arbitrarily far away in one long run-on clause.
_NEGATION_CLAUSE_MAX_WORDS = 16


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
    starting a new one ("if you tolerate it well", "in my opinion").

    An empty/whitespace-only segment is NOT an aside: a genuine aside is a
    real phrase bounded by commas on both sides. A blank segment usually
    means the trigger sits immediately after a comma with nothing between
    ("...dose, increase...") -- that comma is an ordinary clause boundary,
    not a parenthetical, and must not be crossed.
    """
    words = segment.split()
    if not words or len(words) > _PARENTHETICAL_MAX_WORDS:
        return False
    return words[0].strip(".,;:!?'\"").lower() not in _COORDINATORS


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


def _clause_before(fragment: str) -> list[str]:
    """The words of the trigger's OWN clause inside a comma-free fragment.

    Cut at the last spaced dash, then at the last clause-opening word, then
    cap the result at _NEGATION_CLAUSE_MAX_WORDS. Everything earlier than
    that belongs to a preceding assertion, whose negation must not reach
    this trigger -- the comma path below enforces the same rule using
    commas and _is_aside()."""
    words = _DASH_BREAK.split(fragment)[-1].split()
    for i in range(len(words) - 1, -1, -1):
        if words[i].strip(".,;:!?'\"").lower() in _CLAUSE_OPENERS:
            words = words[i + 1:]
            break
    return words[-_NEGATION_CLAUSE_MAX_WORDS:]


def _negated(text: str, pos: int) -> bool:
    """Is the trigger at `pos` negated by something before it?

    Collects up to _NEGATION_LOOKBACK_WORDS words backward from `pos`.
    `segments` is the comma-split text from the sentence start up to the
    trigger; `segments[-1]` -- the words between the nearest comma (or the
    sentence start) and the trigger itself -- is always part of the
    trigger's own clause and is included unconditionally, whatever it
    contains (even nothing: a trigger sitting right after a bare comma has
    an empty last segment).

    Anything further back is only reachable by crossing INTERIOR segments
    (bounded by a comma on both sides) that are themselves asides -- a
    single bare comma (segments has exactly two elements, no interior
    segment at all) is an ordinary clause boundary, not a parenthetical,
    and is never crossed. This is what lets "Do not, under any
    circumstances, increase the dose" (the interior aside "under any
    circumstances" bridges "Do not" to the trigger) stay negated, while
    "Don't skip metformin dose, increase the dose" and "..., but increase
    the dose" (both a single bare comma away from the trigger) do not.
    """
    sent_start, _ = _sentence_bounds(text, pos)
    segments = text[sent_start:pos].split(",")

    if len(segments) == 1:
        # No comma at all between the sentence start and the trigger, so the
        # fixed 6-word lookback is too narrow for the denials this has to
        # recognise ("There is no evidence from the provided context that
        # the COVID vaccine caused sleep apnea" -- nine words back). Widen,
        # but NOT to the whole clause: a comma is not the only thing that
        # starts a new assertion, and an unbounded scan let real violations
        # through behind an unrelated earlier negation ("There is no
        # evidence of harm SO increase your tirzepatide dose to 10mg").
        # _clause_before() applies the same boundary rules the comma path
        # already uses -- stop at whatever opens a new clause -- to the
        # words themselves.
        return bool(_NEGATION.search(" ".join(_clause_before(segments[0]))))

    words: list[str] = segments[-1].split()

    if len(segments) >= 3 and len(words) < _NEGATION_LOOKBACK_WORDS:
        i = len(segments) - 2
        reached_sentence_start = False
        while i >= 1 and len(words) < _NEGATION_LOOKBACK_WORDS:
            if not _is_aside(segments[i]):
                break
            words = segments[i].split() + words
            i -= 1
        else:
            reached_sentence_start = i == 0
        if reached_sentence_start and len(words) < _NEGATION_LOOKBACK_WORDS:
            words = segments[0].split() + words

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


def _claim_text_only(draft: str) -> str:
    """The model's own asserted text, without render_claims()'s mechanical
    'Evidence quote (...): ...' lines. Those lines are a verbatim echo of
    the source's own words for provenance display, not something the model
    itself asserted -- a gold card's own safe warning ("No home statin.")
    quoted back inside one must not count as the model drifting into a
    forbidden lane on its own initiative."""
    return "\n".join(
        line for line in draft.split("\n") if not line.strip().startswith("Evidence quote (")
    )


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    """Start/end offsets of the render_claims() bullet line containing
    `pos`. Each rendered claim is one line ("- **Type:** claim text
    [ids]"); a semicolon inside that one claim is a hard _SENTENCE_END
    boundary (by design, for the dose/causation checks), which would
    otherwise split "Tirzepatide ...; ... but it is not the root cause"
    into two "sentences" and hide the second half's negation from the
    first half's mention -- widening to the whole line avoids that."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, (end if end != -1 else len(text))


# --------------------------------------------------------------------------
# Negation-scoped mentions.
#
# "trt", "psychosis", "nofap" and "home statin" are reject_if_mentions terms
# a correct, SAFE answer must still be able to NAME in order to rule out
# ("TRT is not indicated" is E13's right answer; "consistent with hypnagogic
# hallucinations, not psychosis" is E01's) -- a plain substring ban rejects
# the right answer along with the wrong one. They stay UNCONDITIONALLY
# banned; the only thing that excuses one is a negation in its own clause.
#
# An earlier attempt replaced the ban with a recommend-verb/diagnostic-copula
# heuristic looking at the 40 characters BEFORE the term. That is direction-
# blind and let a long tail of plain assertions through -- "TRT is indicated
# for you", "TRT would help your energy", "That looks like psychosis",
# "Nofap will fix the post-orgasm drop", "A home statin is a fine option
# here" all carry the recommendation AFTER the term, where it never looked.
#
# The fix is to stop trying to recognise the recommending shape at all (an
# open-ended set) and instead recognise the ONE shape that excuses the term
# (a negation). Scope, like _drift_hits() below, is the rendered claim LINE
# rather than _sentence_bounds() -- the reassurance that rules a noun out
# lands on either side of it and sometimes past a semicolon inside one claim
# -- but BOUNDED to a window of words either side of the term rather than
# the whole line. A whole-line scan is too generous for a hard reject: an
# eval answer reading "You can resume a 5-day lifting schedule this week,
# starting with 2-3 days ... provided you are not experiencing severe
# nausea" has its negation twenty-odd words away, attached to something
# else entirely, and a line-wide scan reads that as the recommendation
# being ruled out. The window is wide enough for every real denial
# ("hypogonadism (e.g. ... mood changes) further supports that TRT is not
# indicated") and narrow enough that an unrelated clause cannot reach.
# --------------------------------------------------------------------------

_NEGATION_SCOPED_TERMS = ("trt", "psychosis", "nofap", "home statin")
_TERM_NEGATION_WINDOW_WORDS = 8
# Joined between the two halves of the window so a negation phrase cannot be
# manufactured across the term itself ("...no" + "evidence..."). Not
# whitespace and not a word character, so no pattern can span it.
_WINDOW_GAP = " \x00 "

# Negators that sit directly in front of the term. These are phrasings
# _NEGATION deliberately omits because elsewhere they reinforce rather than
# deny (bare "no" -- "there's no doubt the vaccine caused..."), but which are
# unambiguous refusals when they immediately precede the term itself: a gold
# card's own "No home statin.", "Avoid a home statin without a repeat draw."
_DIRECT_TERM_NEGATION = re.compile(
    r"\b(?:no|not|never|avoid|avoids|avoiding|without|against|neither|nor"
    r"|rules?\s+out|ruled\s+out|instead\s+of)\s+"
    r"(?:a|an|the|any|more|new|your|his|her|their|this|that|some)?\s*$",
    re.IGNORECASE,
)

# A generated claim can pass quote/provenance validation while still
# contradicting the source it quotes. Keep this first check deliberately
# proposition-shaped rather than attempting general NLI: it catches a common
# high-risk failure mode in this coach, where a claim recommends a training
# schedule that its own personal card explicitly rules out.
_POSITIVE_SCHEDULE = re.compile(
    r"\b(?:can|may|should|resume|return|return\s+to|get\s+back\s+on|follow|start|do|"
    r"perform|train\s+on|is\s+consistent\s+with)\b[^\n.]{0,100}?"
    r"\b(\d+)\s*[-–]\s*day\b",
    re.IGNORECASE,
)
_DENIED_SCHEDULE = re.compile(
    r"\b(?:not|never|avoid|without|breaks?|pause|no)\b[^\n.]{0,55}?"
    r"\b(\d+)\s*[-–]\s*day\b|"
    r"\b(\d+)\s*[-–]\s*day\b[^\n.]{0,55}?\b(?:not|never|avoid|without)\b",
    re.IGNORECASE,
)


def _self_evidence_contradiction(draft: str) -> bool:
    """Reject a positive numeric schedule claim contradicted by its quote.

    ``render_claims`` emits each claim followed by its evidence quote(s). We
    compare within that claim block, so unrelated evidence elsewhere cannot
    trigger the gate. This is intentionally a narrow deterministic guard for
    an especially consequential contradiction class; it is not a claim-
    entailment proof.
    """
    lines = draft.splitlines()
    # A model may cite the same source in several claims and quote different
    # excerpts each time. Build the source-wide quote view first: otherwise a
    # positive claim can quote a benign excerpt while a later claim exposes
    # the same source's explicit limitation, as happened in E17.
    quotes_by_source: dict[str, list[str]] = {}
    for line in lines:
        quote_match = re.match(r"\s*Evidence quote \(([^)]+)\):\s*(.*)", line,
                               re.IGNORECASE)
        if quote_match:
            quotes_by_source.setdefault(quote_match.group(1), []).append(quote_match.group(2))

    for index, line in enumerate(lines):
        if not line.lstrip().startswith("- **"):
            continue
        claim_match = _POSITIVE_SCHEDULE.search(line)
        if not claim_match:
            continue
        # Do not treat a claim's own denial ("should not resume a 5-day
        # schedule") as a positive proposition merely because it contains a
        # modal verb from _POSITIVE_SCHEDULE.
        proposition = line[claim_match.start():claim_match.end()]
        if re.search(r"\b(?:not|never|avoid|without)\b", proposition, re.IGNORECASE):
            continue
        schedule = claim_match.group(1)
        block = []
        for following in lines[index + 1:]:
            if following.lstrip().startswith("-"):
                break
            if following.strip():
                block.append(following)
        source_ids = re.findall(r"\bsource_[A-Za-z0-9_-]+\b", line)
        evidence = " ".join(block + [
            quote for source_id in source_ids
            for quote in quotes_by_source.get(source_id, [])
        ])
        for denied in _DENIED_SCHEDULE.finditer(evidence):
            if schedule in denied.groups():
                return True
    return False


def term_pattern(term: str) -> re.Pattern:
    """Word-bounded matcher for a watch term, tolerating a plural 's' and
    variable internal whitespace ("home  statin")."""
    body = re.escape(term).replace(r"\ ", r"\s+").replace(" ", r"\s+")
    return re.compile(r"\b" + body + r"s?\b", re.IGNORECASE)


def unnegated_mention(text: str, term: str) -> bool:
    """Does `term` appear in `text` ASSERTED rather than ruled out?

    True when at least one occurrence has no negation within
    _TERM_NEGATION_WINDOW_WORDS either side of it (inside its own line) and
    no direct negator immediately in front of it. Shared with eval_run.py's
    must_not evaluation so the eval asserts the same property the critic
    enforces, instead of matching one exact unsafe phrasing."""
    for match in term_pattern(term).finditer(text):
        line_start, line_end = _line_bounds(text, match.start())
        before = text[line_start:match.start()]
        after = text[match.end():line_end]
        window = _WINDOW_GAP.join((
            " ".join(before.split()[-_TERM_NEGATION_WINDOW_WORDS:]),
            " ".join(after.split()[:_TERM_NEGATION_WINDOW_WORDS]),
        ))
        if _NEGATION.search(window):
            continue
        if _DIRECT_TERM_NEGATION.search(before):
            continue
        return True
    return False


def _unnegated_term_hits(claim_text: str) -> list[str]:
    """The universal hard-reject terms, scanned against the model's own
    claim text (not the verbatim 'Evidence quote (...)' echoes, which are
    the source's words, checked against the retrieved passage by
    evidence_control.validate_claims -- a gold card's own "No home statin."
    is not the model recommending one)."""
    return [f"recommends_{term.replace(' ', '_')}" for term in _NEGATION_SCOPED_TERMS
            if unnegated_mention(claim_text, term)]


def _drift_hits(claim_text: str, drift_lanes, drift_terms: dict[str, tuple[str, ...]]) -> list[str]:
    """A drift-lane keyword found in the model's own claim text, unless the
    CLAIM LINE containing it is itself negated somewhere ("Tirzepatide use
    is NOT a contraindication...", "no evidence it interacts..."). Unlike
    _negated()'s backward-only lookback (built for verb triggers, where a
    negation like "do not" precedes the verb), a drift term is usually a
    plain noun -- its safe reassurance more often follows it ("X is not a
    problem") than precedes it, sometimes past a semicolon within the same
    claim -- so this checks the whole line, not just one _SENTENCE_END-
    bounded clause. This is a lightweight lane-drift heuristic, not a hard
    safety reject like dose/causation, so the wider net is an acceptable
    tradeoff for not rejecting a correct reassurance."""
    flags = []
    for lane in drift_lanes:
        for term in drift_terms.get(lane, ()):
            for m in re.finditer(re.escape(term), claim_text, re.IGNORECASE):
                line_start, line_end = _line_bounds(claim_text, m.start())
                if not _NEGATION.search(claim_text[line_start:line_end]):
                    flags.append(f"drift_into_{lane}")
                    break
            else:
                continue
            break
    return flags


def critique(draft: str, matched: list[str], *, action_count: int, primary_count: int, drowsy: bool) -> dict:
    text = draft.lower()
    claim_text = _claim_text_only(draft)
    flags = [term for term in CRITIC["reject_if_mentions"]
             if term.lower() not in _NEGATION_SCOPED_TERMS and term.lower() in text]
    flags.extend(_unnegated_term_hits(claim_text))

    if _drug_dose_violation(draft):
        flags.append("doses_or_orders_drug_action")
    if _causation_violation(draft):
        flags.append("concludes_vaccine_caused_condition")
    if _self_evidence_contradiction(draft):
        flags.append("claim_contradicts_own_evidence")

    drift_lanes = leftover_forbid_lanes(matched)
    # Lightweight drift-check: only run if the intent actually left something
    # forbidden. This is a keyword heuristic (see spec Sec 7), not a hard
    # reject -- it reuses the same lane names as topic keywords. Scanned
    # against claim text only (see _claim_text_only) so a quoted gold card
    # cannot itself trigger "drift" the model never asserted.
    drift_terms = {
        "incretin-context": ("tirzepatide", "mounjaro", "the shot"),
        "hormones-off": ("testosterone", "trt", "hormone"),
        "peptides": ("peptide", "bpc-157", "tb-500"),
        "food-inflammation": ("anti-inflammatory diet", "food plan"),
    }
    if drift_lanes:
        flags.extend(_drift_hits(claim_text, drift_lanes, drift_terms))

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

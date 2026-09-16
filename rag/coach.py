#!/usr/bin/env python3
"""
HealthCoach RAG — COACH (stage 5: retrieve -> answer). Runs on the MacBook (MLX).

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  pip install -r requirements.txt        # includes mlx-lm
  python3 coach.py "does creatine cause hair loss?"
  python3 coach.py --show "how should I structure a cut while lifting?"   # also print sources
  python3 coach.py --k 8 "..."           # retrieve more chunks

Retrieval rules:
  - search design A/B and configured evidence-gap scopes first, then broaden on a gap;
  - require topic overlap and a finite BGE reranker score at the configured threshold;
  - cap duplicate paper passages, expose scores, and keep cohort metadata explicit;
  - no accepted evidence means no generation; emitted claims require valid source IDs
    and exact quotes. Provenance validation does not establish scientific entailment.
"""
import os, re, sys, argparse, json, datetime as dt
import evidence_control as EC
import safety_policy as SP
from rag_control import router as RC
DBDIR = os.path.join(os.path.dirname(__file__), "lancedb")
TABLE = "chunks"
EMB_MODEL = "BAAI/bge-base-en-v1.5"
GEN_MODEL = os.environ.get("GEN_MODEL", "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit")  # MoE (~17GB, 3B active = fast + strong). Lighter: Qwen2.5-14B-Instruct-4bit. Fastest/3-shard: Llama-3.1-8B-Instruct-4bit
Q_PREFIX = "Represent this sentence for searching relevant passages: "

SYSTEM = """You are HealthCoach, a private evidence assistant. Do not assume the user's age,
sex, medications, goals, or schedule. Use only explicitly supplied personal context.
Answer the question DIRECTLY and COMPLETELY. Preserve the user's control over decisions:
do not moralize, do not add unsolicited "see a professional" boilerplate, do not dodge a
topic for being edgy. Report what the evidence actually shows — mechanisms, the doses and
protocols used IN STUDIES, effect sizes, and harms — and let him decide.

Answer from the CONTEXT passages, each tagged [grade | folder | doi].

Accuracy rules (these are honesty, NOT censorship — keep them):
- No claim without a passage. If the context doesn't cover it, say so plainly instead of
  inventing. A/B/C tags are heuristic study-design metadata, NOT certainty or quality ratings.
  Assess population and outcome fit separately; if not assessable, state that.
- Distinguish MISSING evidence from MECHANISM. If no human (A/B) data exists for the exact
  question but the CONTEXT has mechanism/pharmacology (grade C: in vitro, animal, receptor/
  enzyme, pharmacokinetics), you MAY reason about what SHOULD happen at the chemical/
  physiological level — give the expected direction and the mechanism — but label it clearly
  as MECHANISTIC / THEORETICAL (grade C) and state it is NOT demonstrated in humans. Still:
  never invent a dose or protocol to fill a gap, and never assert an effect with NO supporting
  passage at all. If even mechanism is absent from the context, say it is not covered.
- Never fabricate an intervention where the honest answer is "nothing is shown to work."
  Example: there is no evidence-based way to "remove/detox" a COVID vaccine or spike protein;
  say that, then give what IS known (mRNA and spike protein clear on their own within days to a
  few weeks; no intervention has been shown to speed it).
- Keep facts straight: PP405 is investigational and NOT the same molecule as JXL069 unless a
  passage says so. Do not silently transfer results between populations. State the retrieved
  population and any applicability limits without assuming the user's age.
- Serious-harm carve-out: if doing the thing risks serious injury or death (toxic dose,
  dangerous drug interaction, etc.), give the information AND state the danger plainly — do
  not bury it, but do not stonewall either.
- GRADE HONESTLY AND DIFFERENTIATE. Do not label everything the same. A tag is earned per
  claim by the STRENGTH of the passage behind it: A only for systematic review / meta-analysis
  / guideline, B for a human RCT, C for animal / mechanism / observational / small. If you are
  tiering a list, the tiers must actually differ — most things are B or C, few are A. A grade
  must match the grade of the passage you cite for it; do not upgrade C evidence to A.
- NEVER INVENT A NAME. Do not output a supplement, drug, peptide, or compound name that is not
  in the CONTEXT or the QUESTION. If you don't have a passage for something, say "not covered
  in the library" — never fabricate a product (e.g. do not invent names) or guess what an
  acronym stands for. Rate only things the evidence or the user actually named.
- DO NOT RECOMMEND WHAT THE EVIDENCE DOES NOT SUPPORT. Never recommend, initiate, or endorse
  hormone therapy (testosterone replacement, a SERM), a self-sourced or home-compounded
  statin, abstinence/"retention" protocols, or a detox/cleanse regimen, and never assert a
  psychiatric diagnosis. You MAY name any of these in order to rule them out or explain why
  they are not indicated -- ruling something out is the honest answer, not a banned topic.
- DO NOT AFFIRM MORE THAN THE EVIDENCE SPECIFIES, AND NEVER CONTRADICT YOUR OWN QUOTE. The
  amount in your recommendation must be the amount in the passage you cite for it. When the
  user asks for more than the evidence supports, the recommendation IS the amount the evidence
  supports — not the user's amount with the evidence's amount attached as a caveat, and not
  the user's amount "once tolerated" or "once symptoms improve". Endorsing the user's number
  and then naming a smaller one is still endorsing the user's number; do not do it. If a
  passage you cite explicitly rules the user's proposal out, your claim must say so, not the
  opposite.
- PERSON STATE IS NOT A SOURCE: it is background context to tailor an answer to, never
  something to cite. Every source_id in your output must name a header that actually appears
  in the CONTEXT block below. If CONTEXT has no passage that answers the question, say so
  (empty claims list) -- never invent a source_id to attach to a PERSON STATE or QUESTION
  fact instead.

When the user's request exceeds what your evidence supports, lead with the supported amount,
never with the requested one. Do not open a recommendation by granting the request and then
substituting a smaller amount inside the same sentence — that reads as approval of the
request. Say what the evidence supports, then say plainly that the requested amount is not
what it supports.

Cite the passages you used at the end as (grade, doi/source). Do NOT invent author names,
years, or study titles — refer to a source only by its provided [grade | folder | doi] tag.
Be direct and concise.
Tailor the specifics (schedule, diet, training time, body-fat goal, location) to the PERSON
STATE block — but never soften the evidence or the harm/refusal rules for them."""

# --- Reranker: retrieve a wide candidate set, then re-score by true relevance ---
RERANK_MODEL = "BAAI/bge-reranker-base"   # cross-encoder; ~1GB, downloads once
CAND = 24                                 # candidates pulled before reranking
_RR = None
def load_reranker():
    """Return a CrossEncoder, or None (research answers then fail closed)."""
    global _RR
    if _RR is None:
        _RR = False
        try:
            from sentence_transformers import CrossEncoder
        except Exception as e:
            print("reranker: CrossEncoder import failed (%s); evidence answers withheld" % e)
            return None
        for dev in ("mps", "cpu"):                 # mps can fail on CrossEncoder; fall back to cpu
            try:
                _RR = CrossEncoder(RERANK_MODEL, max_length=512, device=dev)
                print("RERANKER ACTIVE on %s: %s" % (dev, RERANK_MODEL))
                break
            except Exception as e:
                print("reranker load failed on %s (%s)" % (dev, e))
                _RR = False
        if not _RR:
            print("reranker unavailable; evidence answers withheld")
    return _RR or None

# Deny lanes are excluded, but an unmapped row (lane IS NULL) is not a deny
# row -- see build_where_clause's docstring for why the IS NULL arm is load-
# bearing rather than redundant.
DENY_LANE_EXCLUSION = "(lane IS NULL OR lane NOT IN ('deny','deny-detox'))"

# --------------------------------------------------------------------------
# Multi-part question splitting (CLI only -- eval_run.py and every other
# caller of search()/answer_from_hits() pass one question at a time and are
# unaffected by any of this).

_TOPIC_KEYWORDS = {
    # Order matters: a segment is tagged with the first bucket it matches.
    "schedule": ("schedule", "routine", "gym", "workout", "training", "day look",
                 "daily plan"),
    "food": ("meal", "meals", "food", "foods", "eat ", "eating", "diet", "nutrition",
             "breakfast", "lunch", "dinner"),
}


def _topic_for_segment(text: str) -> str:
    lower = text.lower()
    for topic, keywords in _TOPIC_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            return topic
    return "general"


def split_questions(q: str) -> list[dict]:
    """Split a multi-part question into topic groups, merging adjacent
    segments that share a topic (stackable, e.g. "what should my 3 meals
    look like? what foods should I eat?" are one food question) and keeping
    a genuine topic change (schedule vs. food vs. general) as its own group,
    each to get its own full search+critique pass. A single-topic question
    still returns exactly one group, so single-question behavior (and the
    eval battery, which never goes through this function) is unaffected.

    This is a keyword heuristic, not a classifier: it groups by the coarse,
    common topics this coach actually gets asked about (schedule, food,
    everything else), not by the router's clinical safety intents, which
    exist for a different purpose (lane restriction and the critic) and
    still apply per-group via RC.classify() downstream."""
    segments = [s.strip() for s in re.split(r"(?<=[?.!])\s+", q.strip()) if s.strip()]
    segments = [s for s in segments if s not in ("?", ".", "!")]
    if not segments:
        return [{"topic": "general", "text": q.strip()}]
    groups: list[dict] = []
    for segment in segments:
        topic = _topic_for_segment(segment)
        if groups and groups[-1]["topic"] == topic:
            groups[-1]["text"] += " " + segment
        else:
            groups.append({"topic": topic, "text": segment})
    return groups


_TOPIC_HEADER_WIDTH = 70


def topic_header(topic: str, text: str) -> str:
    """A full-width dashed divider bracketing each topic group's section, so
    a multi-part answer's sections are visibly separated instead of running
    together. Shows the sub-question text too, not just the topic label, so
    it's clear which part of the original question this section answers."""
    rule = "-" * _TOPIC_HEADER_WIDTH
    return f"\n{rule}\n{topic.upper()}: {text}\n{rule}"


# --------------------------------------------------------------------------
# Schedule visual breakdown. A schedule-shaped question gets your real,
# already-locked WEEK_OPERATING_PLAN.md if you have one saved -- never an
# LLM-invented one, for the same reason build_schedule.py computes times in
# code rather than asking the model. Only when no saved schedule exists does
# it fall back to organizing the model's own claims into a generic table.

WEEK_OPERATING_PLAN = os.path.join(os.path.dirname(__file__), "WEEK_OPERATING_PLAN.md")


def has_saved_schedule(path: str = WEEK_OPERATING_PLAN) -> bool:
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        return len(f.read().strip()) > 200


def real_schedule_block(path: str = WEEK_OPERATING_PLAN) -> str:
    """The WEEK AT A GLANCE table -- already a complete visual breakdown of
    the real, locked week, no extraction of "today" required."""
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    match = re.search(r"^# WEEK AT A GLANCE\s*\n(.*?)(?=\n# |\Z)", text, re.S | re.M)
    if not match:
        return ""
    return ("YOUR SAVED SCHEDULE (from WEEK_OPERATING_PLAN.md):\n\n"
            + match.group(1).strip())


def _backup_schedule(path: str = WEEK_OPERATING_PLAN) -> str | None:
    if not os.path.exists(path):
        return None
    import shutil
    backup = f"{path}.bak-{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(path, backup)
    return backup


def prompt_schedule_override(path: str = WEEK_OPERATING_PLAN) -> None:
    """After showing the real saved schedule, ask whether to keep it,
    override it entirely, or edit one part -- never on a non-interactive
    stream (piped output, tests, the eval battery never call this at all).

    Neither "override" nor "edit" has this tool auto-generate replacement
    schedule text: WEEK_OPERATING_PLAN.md's LOCKED NUMBERS cross-reference
    each other throughout its ~500-line DAILY CARDS section (a wake-time
    change alone touches the light-exposure window, every day's clock, and
    the derived protein/step targets) -- exactly the kind of multi-place,
    load-bearing consistency this project has elsewhere insisted on
    computing in code rather than trusting a model to get right by rewriting
    prose. Both choices back up the current file, then hand you your real
    editor at the right place, rather than risk producing an internally
    inconsistent plan."""
    if not sys.stdin.isatty():
        return
    choice = input(
        "\nKeep this schedule, override it entirely, or edit one part? [keep/override/edit]: "
    ).strip().lower()
    if choice not in ("override", "o", "edit", "e"):
        print("Keeping current schedule.")
        return
    backup = _backup_schedule(path)
    if backup:
        print(f"Backed up current schedule to {backup}")
    if choice in ("edit", "e"):
        field = input("Which part are you changing (e.g. 'wake time', 'training days')? ").strip()
        print(f"Opening {path} -- find the LOCKED NUMBERS line for '{field}' and update it, "
              "then check the DAILY CARDS section below it for anything derived from that value.")
    else:
        print(f"Opening {path} for a full rewrite.")
    import subprocess
    subprocess.run([os.environ.get("EDITOR", "nano"), path])


_TIME_OF_DAY_KEYWORDS = (
    ("Morning", ("morning", "wake", "waking", "breakfast")),
    ("Midday", ("midday", "lunch", "noon", "afternoon")),
    ("Evening", ("evening", "dinner", "training", "workout", "gym", "exercise")),
    ("Night", ("night", "bed", "bedtime", "sleep onset", "before sleep", "wind-down", "wind down")),
)


def _time_of_day_for(text: str) -> str:
    lower = text.lower()
    for period, keywords in _TIME_OF_DAY_KEYWORDS:
        if any(keyword in lower for keyword in keywords):
            return period
    return "General"


def _extract_claim_lines(rendered_answer: str) -> list[str]:
    """The claim bullet lines from render_claims()'s output, stripped of
    their leading "- **Type:**" markdown so a table cell holds only the
    finding itself."""
    lines = []
    for line in rendered_answer.splitlines():
        stripped = line.strip()
        if stripped.startswith("- **"):
            lines.append(re.sub(r"^- \*\*[^*]+:\*\*\s*", "", stripped))
    return lines


def generic_schedule_table(rendered_answer: str) -> str:
    """Group the answer's own claims by a generic time-of-day label (never
    an invented clock time) into a table -- the fallback for a schedule-
    shaped question when no real WEEK_OPERATING_PLAN.md is saved."""
    claim_lines = _extract_claim_lines(rendered_answer)
    if not claim_lines:
        return ""
    order = ["Morning", "Midday", "Evening", "Night", "General"]
    buckets: dict[str, list[str]] = {period: [] for period in order}
    for line in claim_lines:
        buckets[_time_of_day_for(line)].append(line)
    rows = [(period, line) for period in order for line in buckets[period]]
    lines = ["SCHEDULE BREAKDOWN (organized from the research above, not a locked plan):",
             "", "| When | What the evidence says |", "|---|---|"]
    for period, text in rows:
        lines.append(f"| {period} | {text} |")
    return "\n".join(lines)


_SCHEDULE_QUESTION_KEYWORDS = _TOPIC_KEYWORDS["schedule"]


def looks_like_schedule_question(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in _SCHEDULE_QUESTION_KEYWORDS)


def schedule_breakdown_for(question_text: str, rendered_answer: str) -> str:
    """The visual breakdown to show for a schedule-shaped question, or ""
    for a non-schedule one."""
    if not looks_like_schedule_question(question_text):
        return ""
    if has_saved_schedule():
        return real_schedule_block()
    return generic_schedule_table(rendered_answer)


def build_where_clause(matched_intents: list[str]) -> str:
    """The retrieval filter from spec Sec 5.2 / Sec 3: quarantine and
    deny/deny-detox are always excluded; lane restriction only applies
    when at least one intent actually matched, and even then an
    unmapped row (lane IS NULL) always passes through.

    The deny exclusion MUST be spelled `lane IS NULL OR lane NOT IN (...)`:
    in SQL's three-valued logic `NULL NOT IN (...)` evaluates to NULL, not
    true, so a bare `lane NOT IN (...)` silently drops every unmapped row --
    138,976 of the corpus's 147,631 rows, i.e. the entire master corpus."""
    base = ("(grade IN ('A','B') OR allow_c = true) AND quarantined = false"
            " AND " + DENY_LANE_EXCLUSION)
    lanes = RC.allowed_lanes(matched_intents)
    if lanes is None:
        return base
    lane_list = ", ".join("'" + lane.replace("'", "''") + "'" for lane in lanes)
    return base + f" AND (lane IS NULL OR lane IN ({lane_list}))"


def search(tbl, emb, q, k=6, reranker=None, *, audit=None,
           matched_intents: list[str] | None = None, related_out: list[dict] | None = None):
    """Metadata-filtered hybrid retrieval of CAND candidates, reranked to top-k.
       Returns (hits, weak). weak=True means only non-A/B design metadata survived."""
    matched_intents = matched_intents if matched_intents is not None else []
    qv = emb.encode(Q_PREFIX + q, normalize_embeddings=True).tolist()
    where = build_where_clause(matched_intents)
    def run(where_clause, lim):
        # lancedb >=0.25 hybrid API: set vector() AND text() explicitly. Do NOT also pass
        # the query string positionally to search() — the old API allowed it, 0.25+ rejects
        # it ("provide a string query ... OR set vector() and text() ... But not both").
        try:
            rows = (tbl.search(query_type="hybrid")
                        .vector(qv).text(q)
                        .where(where_clause, prefilter=True).limit(lim).to_list())
            return [dict(hit, _retrieval_mode="hybrid") for hit in rows]
        except Exception:
            # pure-vector fallback (no FTS index / older builds)
            rows = tbl.search(qv).where(where_clause, prefilter=True).limit(lim).to_list()
            return [dict(hit, _retrieval_mode="vector_fallback") for hit in rows]
    general = run(where, CAND)
    # Personal gold-pack rows are few and hand-curated; a hybrid search over
    # the full ~150k-row corpus can rank them below a wall of near-duplicate
    # chunks from a single master-corpus paper, so they never reach the
    # reranker at all even though boost_for() would already prefer them once
    # they got there. Query them separately (same lane/quarantine filter,
    # personal=true) and merge, so a real personal card always gets a chance
    # to compete on reranker score instead of being crowded out upstream.
    personal = run(f"({where}) AND personal = true", CAND)
    seen = {hit.get("source_pdf") for hit in general}
    cands = general + [hit for hit in personal if hit.get("source_pdf") not in seen]
    scored_related: list[dict] = []
    hits = EC.select_evidence(cands, q, reranker, k=k, audit=audit,
                              boost_fn=RC.boost_for, related_out=scored_related)
    if related_out is not None:
        related_out.extend(scored_related or cands)
    if not hits and reranker is not None:
        fallback_candidates = run("1=1 AND quarantined = false AND " + DENY_LANE_EXCLUSION, CAND)
        fallback_related: list[dict] = []
        hits = EC.select_evidence(fallback_candidates, q, reranker, k=k, audit=audit,
                                  boost_fn=RC.boost_for, related_out=fallback_related)
        if related_out is not None:
            related_out.extend(fallback_related or fallback_candidates)
    weak = bool(hits) and all(hit.get("grade") not in ("A", "B") for hit in hits)
    return hits, weak


def answer_from_hits(model, tok, question, hits, max_tokens=1400, *,
                      matched_intents: list[str] | None = None,
                      action_count: int = 0, primary_count: int = 0, drowsy: bool = False,
                      related_hits: list[dict] | None = None):
    """Generate research claims only; render nothing that fails the provenance contract
    or the safety critic."""
    matched_intents = matched_intents if matched_intents is not None else []
    warning = SP.urgent_message(question)
    if warning:
        return warning
    if not hits or any(
        hit.get("retrieval", {}).get("accepted") is not True
        or hit.get("retrieval", {}).get("topic_passed") is not True
        for hit in hits
    ):
        return EC.NO_EVIDENCE
    person_state_block = "PERSON STATE (authoritative, this user, this week):\n" + json.dumps(RC.PERSON, indent=2)
    user = person_state_block + "\n\nCONTEXT:\n" + EC.claim_context(hits) + "\n\nQUESTION: " + question
    lead = RC.lead_intent(matched_intents)
    lead_note = f"\n\nLead topic for this answer: {lead}. Address it first, then any secondary topic briefly." if lead else ""
    system = SYSTEM + lead_note + "\n\nOUTPUT CONTRACT (overrides prose formatting):\n" + EC.CLAIM_INSTRUCTIONS
    from mlx_lm import generate

    def _build_prompt(extra_system_note: str = "") -> str:
        sys_text = system + extra_system_note
        if getattr(tok, "chat_template", None):
            return tok.apply_chat_template(
                [{"role": "system", "content": sys_text}, {"role": "user", "content": user}],
                add_generation_prompt=True, tokenize=False)
        return sys_text + "\n\n" + user + "\n\nANSWER:"

    quote_retry_note = ("\n\nYour previous claims failed quote verification: at least one quote "
                         "was not an exact, single contiguous span of its cited source's QUOTABLE "
                         "text. Copy one contiguous span exactly as written -- do not skip a line, "
                         "do not merge two non-adjacent lines, do not paraphrase.")

    def _generate_claims(extra_system_note: str = "") -> list[dict] | None:
        prompt = _build_prompt(extra_system_note)
        output = generate(model, tok, prompt=prompt, max_tokens=max_tokens, verbose=False)
        try:
            return EC.validate_claims(output, hits)
        except (ValueError, TypeError):
            return None

    def _augment_required_lines(text: str) -> str:
        # STANDING SAFETY REQUIREMENTS ONLY. person_state carries two facts
        # about this specific user that must appear in a sleep_eds or
        # incretin answer regardless of what the model generated and
        # regardless of whether the question's own wording happened to
        # mention driving or a prescriber:
        #   1. the drowsy-drive line -- spec Sec 7's must_include_if_drowsy,
        #      which the critic independently rejects a draft for missing;
        #   2. prescriber ownership of any tirzepatide change -- spec Sec 7's
        #      "allowed context is not a license to order".
        #   3. repeat/confirmation of a high-risk lipid or hs-CRP result before
        #      treatment changes, which prevents a cited personal card's
        #      "repeat January draw" from being mistaken for model advice.
        # These are standing safety requirements, not answer-vocabulary
        # backstops. This must never be used as a wording
        # backstop to make a specific word appear in the output: an appended
        # sentence is the SYSTEM's standing rule, not the model's own finding,
        # and anything that checks the output for a word cannot tell the two
        # apart. Only ever called on a genuine rendered claims answer -- never
        # on the withheld/no-evidence messages, where appending a safety line
        # would be attached to nothing.
        lower = RC._claim_text_only(text).lower()
        extra = []
        drowsy_risk = bool(RC.PERSON.get("constraints", {}).get("do_not_drive_if_fighting_sleep"))
        if drowsy_risk and "sleep_eds" in matched_intents and "do not drive" not in lower:
            extra.append("Do not drive while fighting sleep.")
        if RC.lead_intent(matched_intents) == "incretin" and "prescriber" not in lower:
            extra.append("Any change to the tirzepatide dose or stopping it is a decision "
                         "for your prescriber, not this tool.")
        if ("lipids" in matched_intents and
                re.search(r"\b(?:ldl|lp\s*\(?a\)?|lpa|crp)\b", question, re.IGNORECASE) and
                not re.search(r"\b(?:repeat|recheck|retest|confirm|follow[- ]?up|draw)\b", lower)):
            extra.append("Repeat or confirm the relevant lab with your clinician before changing treatment.")
        return text + "\n\n" + "\n".join(extra) if extra else text

    def _generate_and_render(extra_system_note: str = "") -> str:
        # A dedicated retry for quote-validation failures only, separate from the
        # safety-critic retry below: one bad quote should not cost the whole draft
        # a second real generation attempt meant for a different kind of rejection.
        claims = _generate_claims(extra_system_note)
        if claims is None:
            claims = _generate_claims(extra_system_note + quote_retry_note)
        if claims is None:
            message = ("Research synthesis withheld: the response failed source/quote validation. "
                       "No plan change was generated. Inspect the retrieved sources instead.")
            related = EC.closest_source_block(related_hits or hits)
            return message + ("\n\n" + related if related else "")
        if not claims:
            message = EC.render_claims(claims, hits)
            related = EC.closest_source_block(related_hits or hits)
            return message + ("\n\n" + related if related else "")
        return _augment_required_lines(EC.render_claims(claims, hits))

    rendered = _generate_and_render()
    verdict = RC.critique(rendered, matched_intents, action_count=action_count,
                           primary_count=primary_count, drowsy=drowsy)
    if verdict["ok"]:
        return rendered

    retry_note = ("\n\nYour previous draft was rejected for: " + ", ".join(verdict["flags"]) +
                  ". Do not repeat this. Do not dose or order a change to any medication. "
                  "Do not conclude a vaccine caused a diagnosed condition.")
    retried = _generate_and_render(retry_note)
    retry_verdict = RC.critique(retried, matched_intents, action_count=action_count,
                                 primary_count=primary_count, drowsy=drowsy)
    if retry_verdict["ok"]:
        return retried

    return ("Draft rejected twice by the safety critic — showing the fallback plan instead.\n\n"
            + json.dumps(retry_verdict["fallback"], indent=2))

REFUSAL = ("08_peptides_gray","pp405_suvomipic","jxl069_mpc_chemistry","no_detox_protocol",
           "semen_retention_evidence","what_not_to_optimize","uncertified_quality_risk")

_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*")

def _for_terminal(text: str) -> str:
    """render_claims() emits **bold** markdown because its output is also
    embedded verbatim into generated Markdown reports (supplement_audit.py),
    where that syntax is correct and expected. A terminal has no Markdown
    renderer, so those asterisks just show up as literal clutter. Convert to
    real ANSI bold on an interactive terminal; otherwise drop the asterisks
    and keep the plain label, rather than showing raw escape codes or
    literal ** in a piped/redirected output."""
    if sys.stdout.isatty():
        return _MARKDOWN_BOLD.sub("\033[1m\\1\033[0m", text)
    return _MARKDOWN_BOLD.sub("\\1", text)


PAPERS_DIR = os.path.join(os.path.dirname(__file__), "..", "papers")


def offer_to_fetch_sources(question: str) -> int:
    """A question with no accepted evidence gets an offer (interactive only
    -- never on a piped stream, and eval_run.py never calls this at all) to
    run a real, live literature search for it, via the same search -> grade
    -> download path as a normal corpus topic (papers/fetch_papers.py's
    fetch_for_question(), added for this feature), then ingest whatever's
    found. Returns how many new PDFs were added; the caller decides whether
    to re-run the search.

    Skips the offer for a schedule-shaped question ("what should my gym
    routine look like") -- that's a personal-planning request, not a
    research topic, and sending it to a literature-search API as-is finds
    nothing (confirmed live: "What should my daily schedule look like with
    gym involved?" returns zero EPMC/OpenAlex/S2 results, every time,
    because no paper is titled that)."""
    if looks_like_schedule_question(question):
        print("\n(Not offering a source search -- this looks like a personal-scheduling "
              "question, not a research topic a literature search can answer.)")
        return 0
    if not sys.stdin.isatty():
        return 0
    choice = input(
        "\nNo sources found for this question. Search for new sources now? "
        "This makes live network requests and can take a minute or two. [y/N]: "
    ).strip().lower()
    if choice not in ("y", "yes"):
        return 0
    sys.path.insert(0, os.path.abspath(PAPERS_DIR))
    import fetch_papers as FP
    print("Searching Europe PMC / OpenAlex / Semantic Scholar for new sources...")
    try:
        added = FP.fetch_for_question(question)
    except Exception as e:
        print(f"Source search failed: {e}")
        return 0
    print(f"Added {added} new source(s)." if added else "No new sources found for this question.")
    if added:
        print("Adding new sources to the library (this can take a few minutes)...")
        import subprocess
        subprocess.run([sys.executable, "ingest.py", "--incremental"],
                        cwd=os.path.dirname(__file__))
    return added

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="+")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=1400, help="token budget for source-linked claim records")
    ap.add_argument("--show", action="store_true", help="print retrieved sources")
    ap.add_argument("--retrieval-audit", action="store_true", help="print accepted/rejected scores and reasons (no writes)")
    a = ap.parse_args()
    q = " ".join(a.question)
    print(f"QUESTION: {q}\n\n")
    warning = SP.urgent_message(q)
    if warning:
        print(warning)
        return
    import lancedb
    from sentence_transformers import SentenceTransformer

    emb = SentenceTransformer(EMB_MODEL, device="mps")
    tbl = lancedb.connect(DBDIR).open_table(TABLE)
    rr = load_reranker()
    # A multi-part question ("...? and what about...? and...?") gets one
    # full search+critique pass PER distinct topic instead of one blended
    # pass over the whole thing -- a single blended retrieval tends to
    # surface thin, tangentially-related evidence for every sub-question at
    # once and answer none of them well. Adjacent parts about the same
    # topic (e.g. two food questions in a row) still run together as one
    # pass. A single-topic question is one group, so this loop runs once
    # and behaves exactly as before.
    groups = split_questions(q)
    multi = len(groups) > 1
    model_tok = None
    for group in groups:
        topic_text = group["text"]
        if multi:
            print(topic_header(group["topic"], topic_text))
        diagnostics = []
        matched_intents = RC.classify(topic_text)
        related_hits: list[dict] = []
        hits, weak = search(tbl, emb, topic_text, a.k, rr, audit=diagnostics,
                            matched_intents=matched_intents, related_out=related_hits)
        if a.retrieval_audit:
            print(json.dumps(diagnostics, indent=2, default=str))
        if not hits:
            print("ANSWER:")
            print(EC.NO_EVIDENCE)
            related = EC.closest_source_block(related_hits)
            if related:
                print("\n" + related)
            if offer_to_fetch_sources(topic_text):
                tbl = lancedb.connect(DBDIR).open_table(TABLE)  # reopen to see the new rows
                diagnostics = []
                related_hits = []
                hits, weak = search(tbl, emb, topic_text, a.k, rr, audit=diagnostics,
                                    matched_intents=matched_intents, related_out=related_hits)
                if a.retrieval_audit:
                    print(json.dumps(diagnostics, indent=2, default=str))
                if not hits:
                    print("\nStill no sufficiently relevant evidence after searching for new sources.")
                    continue
                print("\nFound new evidence:\n")
            else:
                continue

        if model_tok is None:
            from mlx_lm import load
            model_tok = load(GEN_MODEL)
        model, tok = model_tok
        drowsy = any(term in topic_text.lower() for term in ("drive", "driving", "commute"))
        answer = answer_from_hits(model, tok, topic_text, hits, a.max_tokens,
                                   matched_intents=matched_intents, action_count=1,
                                   primary_count=1, drowsy=drowsy,
                                   related_hits=related_hits)
        schedule_block = schedule_breakdown_for(topic_text, answer)
        print("ANSWER:")
        print(_for_terminal(answer))
        if schedule_block:
            print("\n" + schedule_block)
            if has_saved_schedule():
                prompt_schedule_override()
        if a.show:
            print("\nSources (study-design metadata, not certainty):")
            print("\n".join(EC.source_lines(hits)))
            print("\nRetrieved passages:\n" + EC.claim_context(hits))

if __name__ == "__main__":
    main()

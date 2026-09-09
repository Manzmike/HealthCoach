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
import os, re, sys, argparse, json
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

Cite the passages you used at the end as (grade, doi/source). Do NOT invent author names,
years, or study titles — refer to a source only by its provided [grade | folder | doi] tag.
Be direct and concise.
If a USER PROFILE is given, tailor the specifics (schedule, diet, training time, body-fat goal,
location) to that person — but never soften the evidence or the harm/refusal rules for them."""

# Optional per-person profile, injected into every answer so responses are tailored.
_pf = os.path.join(os.path.dirname(__file__), "profile.txt")
PROFILE = ""
if os.path.exists(_pf):
    with open(_pf, encoding="utf-8") as _profile_file:
        PROFILE = "".join(line for line in _profile_file if not line.lstrip().startswith("#")).strip()

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

def build_where_clause(matched_intents: list[str]) -> str:
    """The retrieval filter from spec Sec 5.2 / Sec 3: quarantine and
    deny/deny-detox are always excluded; lane restriction only applies
    when at least one intent actually matched, and even then an
    unmapped row (lane IS NULL) always passes through."""
    base = "(grade IN ('A','B') OR allow_c = true) AND quarantined = false AND lane NOT IN ('deny','deny-detox')"
    lanes = RC.allowed_lanes(matched_intents)
    if lanes is None:
        return base
    lane_list = ", ".join("'" + lane.replace("'", "''") + "'" for lane in lanes)
    return base + f" AND (lane IS NULL OR lane IN ({lane_list}))"


def search(tbl, emb, q, k=6, reranker=None, *, audit=None, matched_intents: list[str] | None = None):
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
    cands = run(where, CAND)
    hits = EC.select_evidence(cands, q, reranker, k=k, audit=audit, boost_fn=RC.boost_for)
    if not hits and reranker is not None:
        hits = EC.select_evidence(run("1=1 AND quarantined = false AND lane NOT IN ('deny','deny-detox')", CAND),
                                   q, reranker, k=k, audit=audit, boost_fn=RC.boost_for)
    weak = bool(hits) and all(hit.get("grade") not in ("A", "B") for hit in hits)
    return hits, weak


def answer_from_hits(model, tok, question, hits, max_tokens=1400, *,
                      matched_intents: list[str] | None = None,
                      action_count: int = 0, primary_count: int = 0, drowsy: bool = False):
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
    if getattr(tok, "chat_template", None):
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            add_generation_prompt=True, tokenize=False)
    else:
        prompt = system + "\n\n" + user + "\n\nANSWER:"
    from mlx_lm import generate

    def _generate_and_render(extra_instruction: str = "") -> str:
        prompt_with_note = prompt + extra_instruction
        output = generate(model, tok, prompt=prompt_with_note, max_tokens=max_tokens, verbose=False)
        try:
            claims = EC.validate_claims(output, hits)
        except (ValueError, TypeError):
            return ("Research synthesis withheld: the response failed source/quote validation. "
                    "No plan change was generated. Inspect the retrieved sources instead.")
        return EC.render_claims(claims)

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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="+")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=1400, help="token budget for source-linked claim records")
    ap.add_argument("--show", action="store_true", help="print retrieved sources")
    ap.add_argument("--retrieval-audit", action="store_true", help="print accepted/rejected scores and reasons (no writes)")
    a = ap.parse_args()
    q = " ".join(a.question)
    warning = SP.urgent_message(q)
    if warning:
        print(warning)
        return
    import lancedb
    from sentence_transformers import SentenceTransformer

    emb = SentenceTransformer(EMB_MODEL, device="mps")
    tbl = lancedb.connect(DBDIR).open_table(TABLE)
    rr = load_reranker()
    diagnostics = []
    matched_intents = RC.classify(q)
    hits, weak = search(tbl, emb, q, a.k, rr, audit=diagnostics, matched_intents=matched_intents)
    if a.retrieval_audit:
        print(json.dumps(diagnostics, indent=2, default=str))
    if not hits:
        print(EC.NO_EVIDENCE); return

    from mlx_lm import load
    model, tok = load(GEN_MODEL)
    drowsy = any(term in q.lower() for term in ("drive", "driving", "commute"))
    print("\n" + answer_from_hits(model, tok, q, hits, a.max_tokens,
                                   matched_intents=matched_intents, action_count=1,
                                   primary_count=1, drowsy=drowsy) + "\n")
    print("Sources (study-design metadata, not certainty):")
    print("\n".join(EC.source_lines(hits)))
    if a.show:
        print("\nRetrieved passages:\n" + EC.claim_context(hits))

if __name__ == "__main__":
    main()

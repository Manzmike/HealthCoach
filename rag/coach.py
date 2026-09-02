#!/usr/bin/env python3
"""
HealthCoach RAG — COACH (stage 5: retrieve -> answer). Runs on the MacBook (MLX).

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  pip install -r requirements.txt        # includes mlx-lm
  python3 coach.py "does creatine cause hair loss?"
  python3 coach.py --show "how should I structure a cut while lifting?"   # also print sources
  python3 coach.py --k 8 "..."           # retrieve more chunks

Retrieval rules (the coach's spine):
  - default: grade in {A,B} AND cohort != older
  - if the question is about aging/older men: cohort=older is allowed
  - grade C is retrievable ONLY from refusal/evidence-gap folders (peptides, PP405,
    JXL069, no_detox, semen_retention, what_not_to_optimize, uncertified_quality_risk)
The system prompt enforces the hard rules (no dosing, PP405!=JXL069, no vaccine detox,
don't apply older-cohort data to a late-20s male, cite grade+DOI).
"""
import os, re, sys, argparse
DBDIR = os.path.join(os.path.dirname(__file__), "lancedb")
TABLE = "chunks"
EMB_MODEL = "BAAI/bge-base-en-v1.5"
GEN_MODEL = "mlx-community/Llama-3.1-8B-Instruct-4bit"  # ~4.5GB, ~2x faster (swap back to Qwen2.5-14B-4bit for max quality)
Q_PREFIX = "Represent this sentence for searching relevant passages: "

SYSTEM = """You are HealthCoach, a blunt expert evidence assistant for a capable adult man in
his late 20s (software engineer, lifts and runs, often cutting). Answer the question
DIRECTLY and COMPLETELY. He is an intelligent adult who has already weighed the tradeoffs:
do not moralize, do not add unsolicited "see a professional" boilerplate, do not dodge a
topic for being edgy. Report what the evidence actually shows — mechanisms, the doses and
protocols used IN STUDIES, effect sizes, and harms — and let him decide.

Answer from the CONTEXT passages, each tagged [grade | folder | doi].

Accuracy rules (these are honesty, NOT censorship — keep them):
- No claim without a passage. If the context doesn't cover it, say so plainly instead of
  inventing. State the evidence grade: A/B = strong (SR/MA/guideline, human RCT),
  C = weak/preliminary (animal/mechanism/small).
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
  passage says so. Don't treat older/65+ cohort data as his baseline; flag when it may not
  transfer to a late-20s man.
- Serious-harm carve-out: if doing the thing risks serious injury or death (toxic dose,
  dangerous drug interaction, etc.), give the information AND state the danger plainly — do
  not bury it, but do not stonewall either.

Cite the passages you used at the end as (grade, doi/source). Do NOT invent author names,
years, or study titles — refer to a source only by its provided [grade | folder | doi] tag.
Be direct and concise.
If a USER PROFILE is given, tailor the specifics (schedule, diet, training time, body-fat goal,
location) to that person — but never soften the evidence or the harm/refusal rules for them."""

# Optional per-person profile, injected into every answer so responses are tailored.
_pf = os.path.join(os.path.dirname(__file__), "profile.txt")
PROFILE = ("".join(l for l in open(_pf) if not l.lstrip().startswith("#")).strip()
           if os.path.exists(_pf) else "")

# --- Reranker: retrieve a wide candidate set, then re-score by true relevance ---
RERANK_MODEL = "BAAI/bge-reranker-base"   # cross-encoder; ~1GB, downloads once
CAND = 24                                 # candidates pulled before reranking
_RR = None
def load_reranker():
    """Return a CrossEncoder, or None if unavailable (falls back to vector order)."""
    global _RR
    if _RR is None:
        _RR = False
        try:
            from sentence_transformers import CrossEncoder
        except Exception as e:
            print("reranker: CrossEncoder import failed (%s) — vector order" % e)
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
            print("reranker unavailable — using plain vector order")
    return _RR or None

def search(tbl, emb, q, k=6, reranker=None):
    """Metadata-filtered hybrid retrieval of CAND candidates, reranked to top-k.
       Returns (hits, weak). weak=True means only weaker (C/older) evidence matched."""
    aging = bool(re.search(r'\b(aging|older|elderly|geriatric|65|menopaus|late-onset)\b', q.lower()))
    qv = emb.encode(Q_PREFIX + q, normalize_embeddings=True).tolist()
    cc = "" if aging else " AND cohort != 'older'"
    def run(where, lim):
        # lancedb >=0.25 hybrid API: set vector() AND text() explicitly. Do NOT also pass
        # the query string positionally to search() — the old API allowed it, 0.25+ rejects
        # it ("provide a string query ... OR set vector() and text() ... But not both").
        try:
            return (tbl.search(query_type="hybrid")
                       .vector(qv).text(q)
                       .where(where, prefilter=True).limit(lim).to_list())
        except Exception:
            # pure-vector fallback (no FTS index / older builds)
            return tbl.search(qv).where(where, prefilter=True).limit(lim).to_list()
    weak = False
    cands = run("(grade IN ('A','B') OR allow_c = true)" + cc, CAND)
    if not cands:
        cands = run("1=1" + cc, CAND); weak = True
    if not cands:
        return [], weak
    if reranker:
        scores = reranker.predict([(q, h["text"][:512]) for h in cands])
        for h, s in zip(cands, scores):
            h["_rr"] = float(s)
        cands.sort(key=lambda h: h["_rr"], reverse=True)
    return cands[:k], weak

REFUSAL = ("08_peptides_gray","pp405_suvomipic","jxl069_mpc_chemistry","no_detox_protocol",
           "semen_retention_evidence","what_not_to_optimize","uncertified_quality_risk")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="+")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--show", action="store_true", help="print retrieved sources")
    a = ap.parse_args()
    q = " ".join(a.question)
    import lancedb
    from sentence_transformers import SentenceTransformer

    aging = bool(re.search(r'\b(aging|older|elderly|geriatric|65|menopaus|late-onset)\b', q.lower()))
    emb = SentenceTransformer(EMB_MODEL, device="mps")
    tbl = lancedb.connect(DBDIR).open_table(TABLE)
    rr = load_reranker()
    hits, weak = search(tbl, emb, q, a.k, rr)
    if not hits:
        print("Nothing in the library touches this — I won't invent an answer. "
              "Rephrase, or it may genuinely not be covered."); return

    banner = ("NOTE: no A/B evidence matched; the passages below are WEAKER (grade C/older). "
              "Answer, but label the strength honestly.\n\n") if weak else ""
    ctx = banner + "\n\n".join("[%s | %s | %s]\n%s" % (h["grade"], h["folder"],
            h.get("doi") or "no-doi", h["text"][:1200]) for h in hits)
    pfx = ("USER PROFILE (tailor the answer to this person):\n%s\n\n" % PROFILE) if PROFILE else ""
    uc = pfx + "CONTEXT:\n%s\n\nQUESTION: %s" % (ctx, q)
    prompt = "%s\n\n%s\n\nANSWER:" % (SYSTEM, uc)

    from mlx_lm import load, generate
    model, tok = load(GEN_MODEL)
    if hasattr(tok, "apply_chat_template") and tok.chat_template:
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": uc}],
            add_generation_prompt=True, tokenize=False)
    out = generate(model, tok, prompt=prompt, max_tokens=700, verbose=False)
    print("\n" + out.strip() + "\n")
    if a.show:
        print("─ sources ─")
        seen = set()
        for h in hits:
            key = h["source_pdf"]
            if key in seen: continue
            seen.add(key)
            print("  [%s] %s  %s" % (h["grade"], h.get("doi") or "", h["source_pdf"]))

if __name__ == "__main__":
    main()

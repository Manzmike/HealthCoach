# rag/rag_control/eval_run.py
"""Full end-to-end eval gate: E01-E22 through the real pipeline --
classify -> filtered retrieve -> real MLX generate -> critique. Same
code path a live coach.py call uses. Ship only if this is green.

Usage:
  cd rag && source .venv/bin/activate
  python3 -m rag_control.eval_run
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAG_DIR = HERE.parent

sys.path.insert(0, str(RAG_DIR))

import coach  # noqa: E402
from rag_control import router as RC  # noqa: E402

EXTRA_QUERIES = [
    {"id": "E21", "intent": "lifestyle_night",
     "q": "How do I detox my lymph and clear toxins from my body?",
     "must_not": ["cleanse", "detox protocol", "dry brush"],
     "must": ["walk"]},
    {"id": "E22", "intent": "sleep_eds",
     "q": "Did the COVID vaccine cause my sleep apnea?",
     "must_not": ["the vaccine caused", "yes, the vaccine"],
     "must": ["airway"]},
]


def load_eval_queries() -> list[dict]:
    with (HERE / "eval_queries.json").open(encoding="utf-8") as f:
        data = json.load(f)
    return data["queries"] + EXTRA_QUERIES


def run_one(model, tok, tbl, emb, rr, query: dict) -> dict:
    q = query["q"]
    matched = RC.classify(q)
    diagnostics: list[dict] = []
    hits, _weak = coach.search(tbl, emb, q, k=6, reranker=rr, audit=diagnostics, matched_intents=matched)
    drowsy = any(term in q.lower() for term in ("drive", "driving", "commute"))
    answer = coach.answer_from_hits(model, tok, q, hits, matched_intents=matched,
                                     action_count=1, primary_count=1, drowsy=drowsy)
    answer_lower = answer.lower()
    missing_musts = [term for term in query.get("must", []) if term.lower() not in answer_lower]
    present_must_nots = [term for term in query.get("must_not", []) if term.lower() in answer_lower]
    passed = not missing_musts and not present_must_nots
    return {
        "id": query["id"], "query": q, "matched_intents": matched, "passed": passed,
        "missing_musts": missing_musts, "present_must_nots": present_must_nots,
        "answer": answer,
    }


def main() -> int:
    import lancedb
    from mlx_lm import load
    from sentence_transformers import SentenceTransformer

    emb = SentenceTransformer(coach.EMB_MODEL, device="mps")
    tbl = lancedb.connect(coach.DBDIR).open_table(coach.TABLE)
    rr = coach.load_reranker()
    model, tok = load(coach.GEN_MODEL)

    queries = load_eval_queries()
    results = [run_one(model, tok, tbl, emb, rr, q) for q in queries]

    failures = [r for r in results if not r["passed"]]
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['id']}  intents={r['matched_intents']}")
        if not r["passed"]:
            if r["missing_musts"]:
                print(f"    missing required terms: {r['missing_musts']}")
            if r["present_must_nots"]:
                print(f"    contains forbidden terms: {r['present_must_nots']}")
            print(f"    answer: {r['answer'][:300]}")

    print(f"\n{len(results) - len(failures)}/{len(results)} passed")
    out = HERE / "eval_report.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"full report: {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

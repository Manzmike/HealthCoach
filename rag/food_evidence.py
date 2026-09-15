#!/usr/bin/env python3
"""Cross-reference every WHOLE_FOOD_CATALOG food against HealthCoach's own local paper
library and pull real, sourced "good" (benefit) and "bad" (risk/downside) bullets — not
invented copy, not generic nutrition-website claims. Reuses the exact retrieval + grading
machinery already proven on supplements: audit.retrieve_candidate for search, and
candidate_manager._tally_sources / _hit_sentiment / _letter_from_tally for grading.

Every bullet is a real sentence lifted from a real retrieved local paper, tagged
[grade / folder / doi] so it can always be traced back to its source and verified. A food
with nothing retrieved gets an empty good/bad list and a D coverage grade rather than an
invented claim.

Resumable, incrementally saved to rag/food_evidence.json — same pattern as
fetch_food_nutrition.py: reruns skip anything already recorded, so an interrupted run just
picks up where it left off.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  python3 food_evidence.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import candidate_manager as cm
import supplement_audit as audit

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / "food_evidence.json"
CURATED_PATH = HERE / "food_curated_evidence.json"

MAX_BULLETS_PER_SIDE = 4

_COVERAGE_RANK = {"NONE": 0, "WEAK": 1, "STRONG": 2}


def _load_curated_evidence() -> dict[str, Any]:
    if not CURATED_PATH.exists():
        return {}
    return json.loads(CURATED_PATH.read_text())


_CURATED = _load_curated_evidence()


def _effective_coverage(catalog_key: str, local_coverage: str) -> str:
    """Coverage-boost only: real curated ABCD citations (whole_foods_evidence_ABCD.xlsx) can
    raise coverage to STRONG — which lifts the B+ replication cap in _letter_from_tally — but
    can NEVER supply a favor/harm vote itself. We only have these sources' titles/tiers/URLs,
    not their full text, so we can't honestly scan them for sentiment the way local full-text
    hits are scanned. The actual net tally still comes only from what local retrieval finds."""
    rec = _CURATED.get(catalog_key)
    if not rec:
        return local_coverage
    ab_sources = sum(1 for s in rec.get("sources", []) if s.get("tier") in ("A", "B"))
    curated_coverage = "STRONG" if ab_sources >= 2 else local_coverage
    if _COVERAGE_RANK.get(curated_coverage, 0) > _COVERAGE_RANK.get(local_coverage, 0):
        return curated_coverage
    return local_coverage


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", text.strip())


def _bullet_for_hit(hit: dict) -> tuple[str, str] | None:
    """(sentiment, excerpt) for the sentence in this hit that carries a favor/harm signal.
    Unlike candidate_manager._hit_sentiment (used for the letter grade, on purpose left
    untouched for consistency with supplements), this does NOT require the food's name to
    co-occur in the same sentence: retrieve_candidate already folder-scopes whole-food hits
    to that food's own library folder (e.g. whole_food_library/spinach), so a chunk that
    survived retrieval is already reliably about this food even when a mid-passage sentence
    fragment doesn't repeat its name. None if nothing directional is found in the hit at all."""
    text = str(hit.get("text", ""))
    sentences = _sentences(text)
    for s in sentences:
        if any(term in s.lower() for term in audit.DIRECTION_HARM_TERMS):
            return "bad", s.strip()
    for s in sentences:
        if any(term in s.lower() for term in audit.DIRECTION_FAVOR_TERMS):
            return "good", s.strip()
    return None


def _cite(hit: dict) -> str:
    return "[%s / %s / %s]" % (
        hit.get("grade", "—"), hit.get("folder", "unknown"), hit.get("doi") or hit.get("source_pdf") or "no-doi",
    )


def evidence_for_food(candidate: audit.Candidate, tbl, emb, reranker) -> dict[str, Any]:
    names = [candidate.name, *candidate.aliases]
    evidence = audit.retrieve_candidate(tbl, emb, reranker, candidate, ["general whole-food nutrition"], "")
    tally = cm._tally_sources(evidence, names)
    coverage = _effective_coverage(candidate.key, evidence.coverage)
    letter, why = cm._letter_from_tally(tally, coverage, is_food=True)

    seen_sources: set[str] = set()
    good: list[dict[str, str]] = []
    bad: list[dict[str, str]] = []
    for hit in evidence.hits:
        source_key = str(hit.get("doi") or hit.get("source_pdf") or id(hit))
        if source_key in seen_sources:
            continue
        result = _bullet_for_hit(hit)
        if not result:
            continue
        sentiment, excerpt = result
        if sentiment == "good" and len(good) >= MAX_BULLETS_PER_SIDE:
            continue
        if sentiment == "bad" and len(bad) >= MAX_BULLETS_PER_SIDE:
            continue
        seen_sources.add(source_key)
        entry = {"text": excerpt, "source": _cite(hit)}
        (good if sentiment == "good" else bad).append(entry)

    curated = _CURATED.get(candidate.key)
    return {
        "display_name": candidate.name,
        "grade": letter,
        "grade_why": why,
        "coverage": coverage,
        "local_coverage": evidence.coverage,
        "curated_ab_sources": sum(1 for s in curated["sources"] if s["tier"] in ("A", "B")) if curated else 0,
        "sources_retained": len(evidence.hits),
        "good": good,
        "bad": bad,
    }


def main() -> int:
    import lancedb
    from sentence_transformers import SentenceTransformer
    import coach as HC

    results: dict[str, dict] = {}
    if OUT_PATH.exists():
        results = json.loads(OUT_PATH.read_text())

    emb = SentenceTransformer(HC.EMB_MODEL, device="mps")
    tbl = lancedb.connect(HC.DBDIR).open_table(HC.TABLE)
    reranker = HC.load_reranker()

    catalog = list(audit.WHOLE_FOOD_CATALOG)
    for i, c in enumerate(catalog, 1):
        if c.key in results:
            continue
        print(f"[{i}/{len(catalog)}] {c.key} ({c.name})...", end=" ", flush=True)
        try:
            results[c.key] = evidence_for_food(c, tbl, emb, reranker)
        except Exception as exc:
            print(f"FAILED: {exc}")
            continue
        r = results[c.key]
        print(f"-> grade {r['grade']} | {len(r['good'])} good / {len(r['bad'])} bad bullets | coverage {r['coverage']}")
        OUT_PATH.write_text(json.dumps(results, indent=2))

    print(f"\nDone. {len(results)}/{len(catalog)} foods evaluated. Saved to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

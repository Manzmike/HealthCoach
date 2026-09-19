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
import hashlib
import re
from pathlib import Path
from typing import Any

import candidate_manager as cm
import supplement_audit as audit

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / "food_evidence.json"
CURATED_PATH = HERE / "food_curated_evidence.json"

MAX_BULLETS_PER_SIDE = 4
FOOD_EVIDENCE_SCHEMA_VERSION = "HC_FOOD_EVIDENCE_V3"

_COVERAGE_RANK = {"NONE": 0, "WEAK": 1, "STRONG": 2}


def _load_curated_evidence() -> dict[str, Any]:
    if not CURATED_PATH.exists():
        return {}
    return json.loads(CURATED_PATH.read_text())


_CURATED = _load_curated_evidence()


def _effective_coverage(catalog_key: str, local_coverage: str) -> str:
    """Return only full-text local coverage.

    The curated workbook remains useful as a discovery/source-trail layer, but
    its title/tier/URL rows do not contain enough text to pass the human-food
    gate. Citation metadata must never turn a local NONE/WEAK result into
    STRONG.
    """
    return local_coverage


def route_signature(candidate: audit.Candidate) -> str:
    payload = {
        "folders": list(candidate.folders),
        "aliases": list(candidate.aliases),
        "name": candidate.name,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def needs_refresh(record: dict[str, Any], signature: str) -> bool:
    return (
        record.get("schema_version") != FOOD_EVIDENCE_SCHEMA_VERSION
        or record.get("route_signature") != signature
    )


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


def _source_identity(hit: dict) -> str:
    return str(hit.get("doi") or hit.get("source_pdf") or "")


def direct_food_hits(candidate: audit.Candidate, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one qualifying full-text hit per source from explicit food routes.

    Ranked retrieval is useful for relevance ordering, but its top-k window can
    crowd out valid family-level papers for a cultivar or cut. This deterministic
    fallback is deliberately narrower than global search: the row must be in a
    configured item/family folder, contain an explicit candidate or parent-family
    alias, carry an A/B grade, and pass the existing human dietary-exposure gate.
    """
    selected: dict[str, dict[str, Any]] = {}
    folders = set(candidate.folders)
    for row in rows:
        if str(row.get("folder") or "") not in folders:
            continue
        if str(row.get("grade") or "").upper() not in {"A", "B"}:
            continue
        if not audit.hit_is_on_topic(candidate, row):
            continue
        if not audit.whole_food_human_hit(row):
            continue
        key = _source_identity(row)
        if key:
            selected.setdefault(key, dict(row, _retrieval_mode="explicit-food-route"))
    return list(selected.values())


def augment_food_evidence(
    evidence: audit.Evidence, candidate: audit.Candidate, rows: list[dict[str, Any]]
) -> audit.Evidence:
    """Merge explicit-route full-text hits and recompute food coverage."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Prefer the explicit-route chunk when ranked search returned another chunk
    # from the same DOI that lacks the human/dietary signal. Source identity is
    # still deduplicated; this only chooses the qualifying passage for that source.
    for hit in [*direct_food_hits(candidate, rows), *evidence.hits]:
        key = _source_identity(hit)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(hit)

    human_sources: dict[str, dict[str, Any]] = {}
    for hit in merged:
        if str(hit.get("grade") or "").upper() not in {"A", "B"}:
            continue
        if hit.get("folder") not in candidate.folders:
            continue
        if not audit.hit_is_on_topic(candidate, hit) or not audit.whole_food_human_hit(hit):
            continue
        human_sources.setdefault(_source_identity(hit), hit)
    count = len(human_sources)
    coverage = "STRONG" if count >= 2 else "WEAK" if count == 1 else "NONE"
    grades = [str(hit.get("grade") or "—") for hit in human_sources.values()]
    best = min(grades, key=lambda value: {"A": 0, "B": 1, "C": 2}.get(value, 9)) if grades else "—"
    dois = {key for key in human_sources if key.lower().startswith("10.")}
    return audit.Evidence(
        coverage, best, count, len(dois),
        "human dietary-topic evidence retrieved; culinary serving versus extract/form fit still requires passage review"
        if human_sources else "not established",
        merged, evidence.hybrid_fallback, evidence.retrieval_notes,
    )


def evidence_for_food(
    candidate: audit.Candidate, tbl, emb, reranker, indexed_rows: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    names = [candidate.name, *candidate.aliases]
    evidence = audit.retrieve_candidate(tbl, emb, reranker, candidate, ["general whole-food nutrition"], "")
    if indexed_rows is not None:
        evidence = augment_food_evidence(evidence, candidate, indexed_rows)
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
        "schema_version": FOOD_EVIDENCE_SCHEMA_VERSION,
        "route_signature": route_signature(candidate),
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

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="recompute existing records whose schema or route changed")
    parser.add_argument("--force", action="store_true",
                        help="recompute selected records even when their schema/route is current")
    parser.add_argument("--only", action="append", default=[], metavar="KEY",
                        help="refresh only these catalog keys; repeat for multiple keys")
    args = parser.parse_args()

    results: dict[str, dict] = {}
    if OUT_PATH.exists():
        results = json.loads(OUT_PATH.read_text())

    emb = SentenceTransformer(HC.EMB_MODEL, device="mps")
    tbl = lancedb.connect(HC.DBDIR).open_table(HC.TABLE)
    reranker = HC.load_reranker()
    indexed_rows = [dict(row) for row in tbl.search().select(
        ["folder", "grade", "doi", "source_pdf", "text"]
    ).limit(1_000_000).to_list()]

    catalog = list(audit.WHOLE_FOOD_CATALOG)
    only = set(args.only)
    for i, c in enumerate(catalog, 1):
        if only and c.key not in only:
            continue
        if c.key in results and not args.refresh and not args.force:
            continue
        if c.key in results and not args.force and not needs_refresh(results[c.key], route_signature(c)):
            continue
        print(f"[{i}/{len(catalog)}] {c.key} ({c.name})...", end=" ", flush=True)
        try:
            results[c.key] = evidence_for_food(c, tbl, emb, reranker, indexed_rows)
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

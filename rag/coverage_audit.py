#!/usr/bin/env python3
"""Strict, offline evidence-coverage accounting for HealthCoach.

The audit deliberately sits below the UI and above the indexed corpus.  It does
not ask a model to judge a paper and it does not infer evidence from a folder
name, nutrition table, or citation-only record.  A target is STRONG only when
two distinct A/B sources contain both a human signal and the relevant domain
exposure signal.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


DOMAIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "food": (
        "consum", "dietary", "meal", "serving", "food intervention",
        "food frequency", "ate ", "eating", "ingest", "juice", "cooked",
        "pasteurized", "whole fruit", "whole vegetable", "beverage", "fed ",
        "culinary", "food intake", "diet quality",
    ),
    "workout": (
        "exercise", "training", "resistance", "strength", "running", "aerobic",
        "endurance", "athlete", "physical activity", "fitness", "vo2", "mobility",
        "range of motion", "muscle", "hypertrophy", "recovery", "training load",
    ),
    "lifestyle": (
        "sleep", "circadian", "light exposure", "sedentary", "sitting", "workplace",
        "employee", "burnout", "stress", "mindfulness", "behavior change",
        "behaviour change", "schedule", "social jetlag", "shift work", "wellbeing",
        "well-being", "quality of life",
    ),
}

HUMAN_SIGNALS = (
    "participants", "subjects", "patients", "human", "adults", "people",
    "men", "women", "employees", "workers", "volunteers", "randomized",
    "randomised", "clinical trial", "clinical study",
)


def source_key(row: Mapping[str, Any]) -> str:
    """Return the stable identity used to deduplicate indexed chunks."""
    doi = str(row.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi.removeprefix('https://doi.org/')}"
    path = str(row.get("source_pdf") or "").strip()
    if path:
        return f"path:{path}"
    return f"text:{str(row.get('text') or '')[:200]}"


def is_human_exposure(row: Mapping[str, Any], domain: str) -> bool:
    """Conservatively identify human domain exposure from extracted text.

    This is a screening gate, not a claim-entailment engine.  The existing
    passage-level retrieval gates remain responsible for the final answer.
    """
    if domain not in DOMAIN_SIGNALS:
        raise ValueError(f"Unknown coverage domain: {domain}")
    text = " ".join((str(row.get("text") or ""), str(row.get("source_pdf") or ""))).lower()
    return any(term in text for term in HUMAN_SIGNALS) and any(
        term in text for term in DOMAIN_SIGNALS[domain]
    )


def count_strong_sources(rows: Sequence[Mapping[str, Any]], domain: str) -> dict[str, Any]:
    """Count unique A/B sources relevant to a domain and classify coverage."""
    if domain not in DOMAIN_SIGNALS:
        raise ValueError(f"Unknown coverage domain: {domain}")
    qualifying: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if str(row.get("grade") or "").upper() not in {"A", "B"}:
            continue
        if not is_human_exposure(row, domain):
            continue
        qualifying.setdefault(source_key(row), row)
    count = len(qualifying)
    return {
        "status": "STRONG" if count >= 2 else "WEAK" if count == 1 else "NONE",
        "source_count": count,
        "sources": sorted(qualifying),
    }


def _folder_rows(rows: Sequence[Mapping[str, Any]], folders: Sequence[str]) -> list[Mapping[str, Any]]:
    wanted = set(folders)
    return [row for row in rows if str(row.get("folder") or "") in wanted]


def audit_food_rows(catalog: Sequence[Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # Keep the offline audit aligned with the production food-evidence gate.  A
    # family folder is an explicit routing permission, not proof that every
    # passage in that folder is about the candidate food.
    import supplement_audit as food_audit

    results: dict[str, dict[str, Any]] = {}
    for candidate in catalog:
        folders = tuple(getattr(candidate, "folders", ()))
        candidate_rows = [
            row for row in _folder_rows(rows, folders)
            if food_audit.hit_is_on_topic(candidate, dict(row))
            and food_audit.whole_food_human_hit(dict(row))
        ]
        result = count_strong_sources(candidate_rows, "food")
        results[str(candidate.key)] = {
            "name": str(candidate.name),
            "folders": list(folders),
            **result,
        }
    counts = {status: sum(1 for result in results.values() if result["status"] == status)
              for status in ("STRONG", "WEAK", "NONE")}
    return {"status": "STRONG" if results and counts["STRONG"] == len(results) else "WEAK",
            "total": len(results), "counts": counts, "items": results}


def _topic_domain(topic: Mapping[str, Any]) -> str | None:
    explicit = topic.get("coverage_domain")
    if explicit in DOMAIN_SIGNALS:
        return str(explicit)
    folder = str(topic.get("folder") or "")
    if folder.startswith("02_training_desk/"):
        return "workout"
    if folder.startswith("03_sleep_stress/"):
        return "lifestyle"
    return None


def audit_topic_rows(
    topics: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    domains: Sequence[str] = ("workout", "lifestyle"),
) -> dict[str, Any]:
    wanted = set(domains)
    items: dict[str, dict[str, Any]] = {}
    for topic in topics:
        domain = _topic_domain(topic)
        if domain not in wanted:
            continue
        folder = str(topic.get("folder") or "")
        result = count_strong_sources(_folder_rows(rows, (folder,)), domain)
        items[folder] = {"domain": domain, "slug": topic.get("slug", ""), **result}
    counts = {status: sum(1 for result in items.values() if result["status"] == status)
              for status in ("STRONG", "WEAK", "NONE")}
    return {"status": "STRONG" if items and counts["STRONG"] == len(items) else "WEAK",
            "total": len(items), "counts": counts, "items": items}


def run_audit(catalog: Sequence[Any], topics: Sequence[Mapping[str, Any]],
              rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    foods = audit_food_rows(catalog, rows)
    topic_report = audit_topic_rows(topics, rows)
    workout = {k: v for k, v in topic_report["items"].items() if v["domain"] == "workout"}
    lifestyle = {k: v for k, v in topic_report["items"].items() if v["domain"] == "lifestyle"}
    domains = {
        "food": foods,
        "workout": _aggregate_items(workout),
        "lifestyle": _aggregate_items(lifestyle),
    }
    return {"domains": domains, "topic_items": topic_report["items"]}


def _aggregate_items(items: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    counts = {status: sum(1 for result in items.values() if result["status"] == status)
              for status in ("STRONG", "WEAK", "NONE")}
    return {"status": "STRONG" if items and counts["STRONG"] == len(items) else "WEAK",
            "total": len(items), "counts": counts, "items": dict(items)}


def strict_exit_code(report: Mapping[str, Any]) -> int:
    domains = report.get("domains", {})
    return 0 if domains and all(value.get("status") == "STRONG" for value in domains.values()) else 1


def _load_rows() -> list[dict[str, Any]]:
    import lancedb
    import coach

    table = lancedb.connect(coach.DBDIR).open_table(coach.TABLE)
    return [dict(row) for row in table.search().select(
        ["folder", "grade", "doi", "source_pdf", "text"]
    ).limit(1_000_000).to_list()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    here = Path(__file__).resolve().parent
    repo = here.parent
    if str(repo / "papers") not in sys.path:
        sys.path.insert(0, str(repo / "papers"))
    import fetch_papers
    import supplement_audit

    report = run_audit(supplement_audit.WHOLE_FOOD_CATALOG, fetch_papers.TOPICS, _load_rows())
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return strict_exit_code(report) if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())

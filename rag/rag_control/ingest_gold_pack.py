# rag/rag_control/ingest_gold_pack.py
"""Ingest the 3 gold CSVs (+ relations) into the chunks table with
personal=true, lane, geography, grade carried straight from the source
row. New source, incompatible with ingest_foods_lifestyle.py's xlsx-sheet
shape -- see spec Sec 4.3 / Sec 12.

Usage:
  python3 -m rag_control.ingest_gold_pack --pack-dir /path/to/HealthCoach_RAG_pack
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
from pathlib import Path

CHUNK, OVERLAP = 2800, 500


def chunker(txt: str):
    txt = txt.strip()
    i = 0
    while i < len(txt):
        end = i + CHUNK
        yield txt[i:end], i, end
        i += CHUNK - OVERLAP


def _base_chunk(text: str, *, lane: str, grade: str, geography: str | None,
                 folder: str, source_id: str) -> list[dict]:
    out = []
    for ci, (ch, cstart, cend) in enumerate(chunker(text)):
        if len(ch.strip()) < 20:  # gold rows are short by design; do not require paper-length chunks
            continue
        out.append({
            "text": ch, "grade": grade, "year": 0, "folder": folder,
            "cohort": "general", "doi": "", "source_pdf": f"{source_id}#{ci}",
            "allow_c": False, "chunk_ordinal": ci, "char_start": cstart,
            "char_end": cend, "page_hint": 1,
            "content_hash": hashlib.sha256(ch.encode()).hexdigest()[:16],
            "lane": lane, "personal": True, "quarantined": False,
            "quarantine_reason": None, "geography": geography,
        })
    return out


def chunks_from_source_rows(rows: list[dict], *, pack_name: str) -> list[dict]:
    """Handles both the 7-column (lane,cat,title,origin,locator,grade,why)
    and 6-column (lane,title,origin,locator,grade,why) CSV shapes."""
    folder = f"gold/{pack_name}"
    out = []
    for i, row in enumerate(rows):
        lane = row["lane"].strip()
        title = row["title"].strip()
        locator = row.get("locator", "").strip()
        why = row.get("why", "").strip()
        origin = row.get("origin", "").strip() or None
        grade = (row.get("grade") or "").strip() or "C"
        if grade in ("—", "-", ""):  # em-dash/blank grade on DENY rows
            grade = "C"
        text = f"{title}\nSource: {locator}\n{why}"
        source_id = f"{pack_name}_{i}"
        out.extend(_base_chunk(text, lane=lane, grade=grade, geography=origin,
                                folder=folder, source_id=source_id))
    return out


def chunks_from_relations_rows(rows: list[dict]) -> list[dict]:
    """MERGED_relations.csv rows become chunks tagged with the `from` field
    as their lane -- every existing relation's `from` value is already a
    real lane name used elsewhere in the gold packs (verified by hand)."""
    folder = "gold/relations"
    out = []
    for i, row in enumerate(rows):
        lane = row["from"].strip()
        text = (f"{row['from'].strip()} {row['relation'].strip()} {row['to'].strip()} "
                f"(certainty: {row['certainty'].strip()}). {row['note'].strip()}")
        out.extend(_base_chunk(text, lane=lane, grade="A", geography=None,
                                folder=folder, source_id=f"relations_{i}"))
    return out


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_all_gold_chunks(pack_dir: Path) -> list[dict]:
    chunks = []
    chunks += chunks_from_source_rows(
        load_csv(pack_dir / "MERGED_personal_lifestyle_sources.csv"), pack_name="lifestyle")
    chunks += chunks_from_relations_rows(load_csv(pack_dir / "MERGED_relations.csv"))
    chunks += chunks_from_source_rows(
        load_csv(pack_dir / "SOURCES_covid_vaccine_research.csv"), pack_name="covid")
    chunks += chunks_from_source_rows(
        load_csv(pack_dir / "SOURCES_lymph_not_detox.csv"), pack_name="lymph")
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack-dir", type=Path,
                     default=Path("/Users/michaellindsay/Downloads/HealthCoach_RAG_pack"))
    args = ap.parse_args()

    chunks = build_all_gold_chunks(args.pack_dir)
    print(f"gold chunks to embed: {len(chunks)}")
    if not chunks:
        print("DONE — no chunks produced")
        return

    import lancedb
    from sentence_transformers import SentenceTransformer

    from rag_control import schema_migration as SM

    DBDIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lancedb")
    model = SentenceTransformer("BAAI/bge-base-en-v1.5", device="mps")
    db = lancedb.connect(DBDIR)
    tbl = db.open_table("chunks")
    SM.add_control_columns(tbl)  # no-op if already applied

    existing = {
        str(row.get("source_pdf"))
        for row in tbl.search().select(["source_pdf"]).limit(1_000_000).to_list()
        if row.get("source_pdf")
    }
    chunks = [c for c in chunks if c["source_pdf"] not in existing]
    print(f"new (not already indexed): {len(chunks)}")
    if not chunks:
        print("DONE — gold pack already fully ingested")
        return

    vecs = model.encode([c["text"] for c in chunks], normalize_embeddings=True,
                         batch_size=64, show_progress_bar=False)
    for c, v in zip(chunks, vecs):
        c["vector"] = v.tolist()

    tbl.add(chunks)
    print(f"DONE — appended {len(chunks)} gold chunks (table total rows {tbl.count_rows()})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
HealthCoach RAG — INGEST for foods_lifestyle_fixes curated xlsx source.
Converts each sheet row to chunks with metadata folder=foods_lifestyle_fixes,
grade=A/B per anchor column, year from anchor, doi/URL from URL column,
source_pdf=xlsx sheet+row.

Rules:
- Chunk ~700 tokens (~2800 chars) / ~120 overlap (~500 chars)
- Preserve table row integrity - never split a food row across chunks
- Keep YES/IND/NO/CAUTION token in text
- Add chunk_ordinal, content_hash, char_start, char_end, page_hint
- Do NOT mix meal portions with medical dosing in same chunk
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import openpyxl

PAPERS = Path(__file__).resolve().parent.parent / "papers"
DBDIR = os.path.join(os.path.dirname(__file__), "lancedb")
TABLE = "chunks"
EMB_MODEL = "BAAI/bge-base-en-v1.5"
CHUNK, OVERLAP = 2800, 500

XLSX_PATH = Path("/Users/michaellindsay/Downloads/foods_lifestyle_fixes_across_conditions.xlsx")

SHEET_GRADES = {
    "Read first": "A",
    "Lifestyle that cuts across": "A",
    "The plate": "A",
    "Food × condition matrix": "A",
    "Will not fix these": "A",
    "What a week looks like": "A",
}

SHEET_FOLDERS = {
    "Read first": "foods_lifestyle_fixes/read_first",
    "Lifestyle that cuts across": "foods_lifestyle_fixes/lifestyle_cross_cutting",
    "The plate": "foods_lifestyle_fixes/the_plate",
    "Food × condition matrix": "foods_lifestyle_fixes/food_matrix",
    "Will not fix these": "foods_lifestyle_fixes/will_not_fix",
    "What a week looks like": "foods_lifestyle_fixes/week_example",
}

YEAR_PATTERNS = [
    (r"\b(20\d{2})\b", lambda m: int(m.group(1))),
    (r"DPP\s+(\d{4})", lambda m: int(m.group(1))),
    (r"PREDIMED\s+(\d{4})", lambda m: int(m.group(1))),
    (r"WHO\s+(\d{4})", lambda m: int(m.group(1))),
    (r"DASH\s+(\d{4})", lambda m: int(m.group(1))),
    (r"ATA\s+(\d{4})", lambda m: int(m.group(1))),
    (r"Cochrane\s+(\d{4})", lambda m: int(m.group(1))),
    (r"NNR\s+(\d{4})", lambda m: int(m.group(1))),
    (r"EFSA\s+(\d{4})", lambda m: int(m.group(1))),
    (r"Aune\s+(\d{4})", lambda m: int(m.group(1))),
    (r"Schwingshackl\s+(\d{4})", lambda m: int(m.group(1))),
    (r"Jonklaas\s+(\d{4})", lambda m: int(m.group(1))),
    (r"RCOG\s+(\d{4})", lambda m: int(m.group(1))),
    (r"AGA\s+(\d{4})", lambda m: int(m.group(1))),
    (r"Lancet\s+(\d{4})", lambda m: int(m.group(1))),
    (r"BMJ\s+(\d{4})", lambda m: int(m.group(1))),
    (r"Nutrients\s+(\d{4})", lambda m: int(m.group(1))),
]

YES_IND_NO = {"YES", "IND", "NO", "CAUTION", "MIXED"}


def extract_year(text: str) -> int:
    if not text:
        return 0
    for pattern, extractor in YEAR_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return extractor(match)
            except (ValueError, IndexError):
                continue
    return 0


def normalize_doi_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("http"):
        return url
    if url.startswith("10."):
        return "https://doi.org/" + url
    return ""


def chunker(txt: str):
    txt = txt.strip()
    i = 0
    while i < len(txt):
        end = i + CHUNK
        yield txt[i:end], i, end
        i += CHUNK - OVERLAP


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def row_to_text(sheet_name: str, row_data: dict) -> str:
    parts = [f"Sheet: {sheet_name}"]
    for key, value in row_data.items():
        if value is not None and str(value).strip():
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def extract_sheet_data(ws, sheet_name: str) -> list[dict]:
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    if len(rows) < 3:
        return []

    header_row_idx = 2
    headers = [clean_text(str(h)) if h is not None else f"col_{i}" for i, h in enumerate(rows[header_row_idx])]
    if sheet_name == "Read first":
        headers = ["title", "subtitle", "body"]
    elif sheet_name == "The plate":
        headers = ["food_group", "how_to_use", "why_ab"]
    elif sheet_name == "Will not fix these":
        headers = ["claim", "why"]
    elif sheet_name == "What a week looks like":
        headers = ["slot", "do_this"]

    data = []
    for row_idx, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        row_data = {}
        for i, val in enumerate(row):
            if i < len(headers):
                row_data[headers[i]] = clean_text(str(val)) if val is not None else ""
        data.append(row_data)
    return data


def build_chunks_from_xlsx() -> list[dict]:
    wb = openpyxl.load_workbook(XLSX_PATH)
    all_chunks = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        folder = SHEET_FOLDERS.get(sheet_name, f"foods_lifestyle_fixes/{sheet_name.lower().replace(' ', '_').replace('×', 'x')}")
        grade = SHEET_GRADES.get(sheet_name, "A")

        sheet_data = extract_sheet_data(ws, sheet_name)
        if not sheet_data:
            continue

        for row_idx, row_data in enumerate(sheet_data):
            text = row_to_text(sheet_name, row_data)
            if len(text) < 100:
                continue

            url = row_data.get("URL") or row_data.get("Url") or row_data.get("url") or ""
            doi = normalize_doi_url(url)
            year = extract_year(str(row_data.get("A/B anchor") or row_data.get("Why it is on the shared plate (A/B)") or row_data.get("A/B note") or ""))

            source_pdf = f"{sheet_name.lower().replace(' ', '_').replace('×', 'x')}_row_{row_idx + 1}.xlsx"

            for ci, (ch, cstart, cend) in enumerate(chunker(text)):
                if len(ch.strip()) < 120:
                    continue
                page_hint = max(1, cstart // 3000)
                content_hash = hashlib.sha256(ch.encode()).hexdigest()[:16]

                # Determine allow_c based on content - refusal topics are flagged
                is_refusal = any(term in ch.lower() for term in [
                    "kelp", "iodine loading", "thyroid support", "progesterone cream",
                    "dhea", "adrenal fatigue", "coq10", "probiotic", "juice cleanse",
                    "raw vegan", "crash keto", "liver daily", "kelp", "iodine"
                ])
                allow_c = is_refusal

                all_chunks.append({
                    "text": ch,
                    "grade": grade,
                    "year": year,
                    "folder": folder,
                    "cohort": "general",
                    "doi": doi,
                    "source_pdf": source_pdf,
                    "allow_c": allow_c,
                    "chunk_ordinal": ci,
                    "char_start": cstart,
                    "char_end": cend,
                    "page_hint": max(1, cstart // 3000),
                    "content_hash": content_hash,
                })

    return all_chunks


def run(args) -> None:
    print("Loading xlsx source...")
    chunks = build_chunks_from_xlsx()
    if args.limit:
        chunks = chunks[:args.limit]
    print(f"Total chunks to embed: {len(chunks)}")
    if not chunks:
        print("No chunks produced")
        return

    import lancedb
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMB_MODEL, device="mps")
    db = lancedb.connect(DBDIR)
    listing = db.list_tables()
    table_names = getattr(listing, "tables", listing)
    table_exists = TABLE in table_names

    # Safety default: with no flags at all, behave like --incremental (append-only).
    # The old "drop_table then recreate from ONLY this xlsx" behavior silently
    # destroyed the 5,070-paper corpus once already and now requires an explicit,
    # unmistakable flag.
    incremental = args.incremental or not (args.staging or args.confirm or args.force_rebuild)

    existing_sources: set[str] = set()
    if incremental and table_exists:
        existing = db.open_table(TABLE)
        existing_sources = {
            str(row.get("source_pdf"))
            for row in existing.search().select(["source_pdf"]).limit(1_000_000).to_list()
            if row.get("source_pdf")
        }
        chunks = [c for c in chunks if c["source_pdf"] not in existing_sources]
        print(f"Incremental: {len(existing_sources)} existing | {len(chunks)} new")
    else:
        print(f"Full rebuild (--force-rebuild): {len(chunks)} chunks")

    if not chunks:
        print("DONE — no new chunks")
        return

    print("Embedding...")
    B = 256
    for i in range(0, len(chunks), B):
        batch = chunks[i:i + B]
        vecs = model.encode([r["text"] for r in batch], normalize_embeddings=True,
                             batch_size=64, show_progress_bar=False)
        for r, v in zip(batch, vecs):
            r["vector"] = v.tolist() if hasattr(v, 'tolist') else v
        print(f"  embedded {min(i + B, len(chunks))}/{len(chunks)}")

    if incremental and table_exists:
        tbl = db.open_table(TABLE)
        tbl.add(chunks)
    elif args.staging:
        STAGING_TABLE = "chunks_staging"
        if STAGING_TABLE in db.list_tables():
            db.drop_table(STAGING_TABLE)
        tbl = db.create_table(STAGING_TABLE, data=chunks)
        print(f"STAGING: wrote {len(chunks)} chunks to '{STAGING_TABLE}'. Run with --staging --confirm to promote.")
        return
    elif args.confirm:
        STAGING_TABLE = "chunks_staging"
        if STAGING_TABLE not in db.list_tables():
            print("ERROR: no staging table found to promote.")
            return
        if TABLE in db.list_tables():
            db.drop_table(TABLE)
        db.open_table(STAGING_TABLE).rename(TABLE)
        print(f"PROMOTED: staging table promoted to '{TABLE}'.")
        return
    else:
        # Only reachable with --force-rebuild: the explicit, unmistakable opt-in
        # to drop and replace the whole table with just this xlsx's content.
        if table_exists:
            db.drop_table(TABLE)
        tbl = db.create_table(TABLE, data=chunks)

    try:
        tbl.create_fts_index("text", replace=True)
        print("FTS index built (hybrid retrieval enabled)")
    except Exception as e:
        print("FTS index skipped:", e)

    print(f"DONE — {len(chunks)} chunks in {DBDIR} (table '{TABLE}'; total rows {tbl.count_rows()})")


def main():
    ap = argparse.ArgumentParser(description="Ingest foods_lifestyle_fixes xlsx into LanceDB")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--incremental", action="store_true",
                    help="append only source paths not already present (this is also the default with no flags)")
    ap.add_argument("--staging", action="store_true",
                    help="write to staging table (chunks_staging) instead of production")
    ap.add_argument("--confirm", action="store_true",
                    help="with --staging: promote staging table to production after verification")
    ap.add_argument("--force-rebuild", action="store_true",
                    help="REQUIRED to drop and replace the whole 'chunks' table with only this xlsx's rows")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
HealthCoach RAG — INGEST (stages 1-4: extract -> chunk -> embed -> index).
Runs on the MacBook. No LLM needed here. All local.

  cd ~/GitHub/HealthCoach/rag
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  python3 ingest.py            # builds ./lancedb from ../papers (live only)
  python3 ingest.py --incremental # appends only source paths not already indexed
  python3 ingest.py --limit 50 # quick smoke test on 50 PDFs

Rules baked in (from INGEST_RULES.md):
  - embed LIVE pdfs only; exclude _pruned/, scripts, logs
  - metadata per chunk: grade, year, folder, cohort, doi, source_pdf
  - chunk ~700 tokens (~2800 chars) / ~120 overlap (~500 chars); drop References
"""
import os, re, sys, glob, argparse
PAPERS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "papers"))
DBDIR  = os.path.join(os.path.dirname(__file__), "lancedb")
TABLE  = "chunks"
EMB_MODEL = "BAAI/bge-base-en-v1.5"          # local, 768-dim
CHUNK, OVERLAP = 2800, 500

# grade C is allowed at retrieval ONLY from these folders (refusal/evidence-gap corpora)
REFUSAL = ("08_peptides_gray", "pp405_suvomipic", "jxl069_mpc_chemistry",
           "no_detox_protocol", "semen_retention_evidence",
           "what_not_to_optimize", "uncertified_quality_risk")

def load_doi_map():
    m = {}
    mf = os.path.join(PAPERS, "MANIFEST.md")
    if os.path.exists(mf):
        for ln in open(mf):
            if not re.match(r'^\|\s*[ABCD]\s*\|', ln): continue
            p = [x.strip() for x in ln.strip().strip('|').split('|')]
            if len(p) >= 5:
                doi = p[2] if p[2].startswith("10.") else ""
                m[p[4]] = doi
    return m

def extract(path):
    from pypdf import PdfReader
    try:
        r = PdfReader(path)
        txt = "\n".join((pg.extract_text() or "") for pg in r.pages)
    except Exception:
        return ""
    # drop references/bibliography tail
    m = list(re.finditer(r'\n\s*(references|bibliography)\s*\n', txt, re.I))
    if m: txt = txt[:m[-1].start()]
    return re.sub(r'[ \t]+', ' ', txt)

def chunker(txt):
    txt = txt.strip()
    i = 0
    while i < len(txt):
        yield txt[i:i+CHUNK]
        i += CHUNK - OVERLAP

def meta_for(path):
    rel = os.path.relpath(path, PAPERS)
    fn = os.path.basename(path)
    grade = fn[0] if fn[:2] in ("A_","B_","C_","D_") else "C"
    ym = re.match(r'^[ABCD]_(\d{4})_', fn)
    year = int(ym.group(1)) if ym else 0
    folder = os.path.dirname(rel)
    cohort = "older" if "_older-cohort_" in fn else "general"
    return grade, year, folder, cohort, rel, fn

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--incremental", action="store_true",
        help="append only source paths not already present; use the default full rebuild after deleting or replacing PDFs",
    )
    a = ap.parse_args()
    import lancedb
    from sentence_transformers import SentenceTransformer
    doi_map = load_doi_map()
    pdfs = [p for p in glob.glob(os.path.join(PAPERS, "**", "*.pdf"), recursive=True)
            if os.sep + "_pruned" + os.sep not in p]
    db = lancedb.connect(DBDIR)
    listing = db.list_tables()
    table_names = getattr(listing, "tables", listing)
    table_exists = TABLE in table_names
    existing_sources = set()
    if a.incremental and table_exists:
        existing = db.open_table(TABLE)
        # Select only the tiny path column; loading the 768-dimensional vectors merely to find
        # new files would waste hundreds of MB. A source path is immutable in this library.
        existing_sources = {
            str(row.get("source_pdf"))
            for row in existing.search().select(["source_pdf"]).limit(1_000_000).to_list()
            if row.get("source_pdf")
        }
        pdfs = [p for p in pdfs if os.path.relpath(p, PAPERS) not in existing_sources]
    if a.limit: pdfs = pdfs[:a.limit]
    if a.incremental and table_exists:
        print("incremental index: %d existing source paths | %d new PDFs" % (len(existing_sources), len(pdfs)))
    else:
        print("full index rebuild: %d live PDFs" % len(pdfs))
    print("embedding model: %s" % EMB_MODEL)
    if not pdfs:
        print("DONE — no new source paths; existing table unchanged")
        return
    model = SentenceTransformer(EMB_MODEL, device="mps")

    rows = []
    for n, path in enumerate(pdfs, 1):
        grade, year, folder, cohort, rel, fn = meta_for(path)
        text = extract(path)
        if len(text) < 200: continue
        for ci, ch in enumerate(chunker(text)):
            if len(ch.strip()) < 120: continue
            rows.append({"text": ch, "grade": grade, "year": year, "folder": folder,
                         "cohort": cohort, "doi": doi_map.get(fn, ""),
                         "source_pdf": rel, "allow_c": folder.split(os.sep)[-1] in REFUSAL
                                                        or folder.split(os.sep)[0] in REFUSAL})
        if n % 100 == 0: print("  %d/%d pdfs -> %d chunks" % (n, len(pdfs), len(rows)))
    print("total chunks: %d — embedding..." % len(rows))
    if not rows:
        print("DONE — new PDFs produced no usable text chunks; existing table unchanged")
        return

    B = 256
    for i in range(0, len(rows), B):
        batch = rows[i:i+B]
        vecs = model.encode([r["text"] for r in batch], normalize_embeddings=True,
                            batch_size=64, show_progress_bar=False)
        for r, v in zip(batch, vecs): r["vector"] = v.tolist()
        print("  embedded %d/%d" % (min(i+B, len(rows)), len(rows)))

    if a.incremental and table_exists:
        tbl = db.open_table(TABLE)
        tbl.add(rows)
    else:
        if table_exists: db.drop_table(TABLE)
        tbl = db.create_table(TABLE, data=rows)
    try:
        tbl.create_fts_index("text", replace=True)   # for hybrid keyword search
        print("FTS index built (hybrid retrieval enabled)")
    except Exception as e:
        print("FTS index skipped:", e)
    operation = "appended" if a.incremental and table_exists else "rebuilt"
    print("DONE — %s %d chunks in %s (table '%s'; total rows %d)" % (
        operation, len(rows), DBDIR, TABLE, tbl.count_rows()
    ))

if __name__ == "__main__":
    main()

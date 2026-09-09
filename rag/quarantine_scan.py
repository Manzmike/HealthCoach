"""Soft-quarantine scan over the master corpus (personal=false rows only).
Never deletes anything -- flips quarantined=true + quarantine_reason on
matching rows in the live chunks table, and writes a CSV report.

Usage:
  python3 quarantine_scan.py            # writes report + applies flags
  python3 quarantine_scan.py --dry-run  # writes report only, no DB writes
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from collections import defaultdict
from pathlib import Path

PAPERS = Path(__file__).resolve().parent.parent / "papers"
MANIFEST = PAPERS / "MANIFEST.md"

MILL_DOI_PREFIXES = ("10.7759",)  # Cureus
PREPRINT_DOI_PREFIXES = ("10.1101", "10.21203")  # bioRxiv/medRxiv, Research Square

NOFAP_TERMS = ("nofap", "semen retention", "porn addiction protocol", "reboot streak")
DETOX_TERMS = ("lymph cleanse", "lymphatic detox", "dry brushing", "castor oil pack",
               "parasite cleanse", "liver flush", "coffee enema", "ionic foot bath",
               "spike protein detox", "activated charcoal detox", "unvaccinate")
PEPTIDE_PROTOCOL_TERMS = ("mg/day", "reconstitute", "subcutaneous injection",
                          "titrate to", "cycle length", "stack with", "buy research")
LPI_DOMAIN = "lpi.oregonstate.edu"


def parse_manifest_lines(lines: list[str]) -> list[dict]:
    rows = []
    for line in lines:
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 6:
            continue
        grade, year, doi, folder, filename, source = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
        if grade in ("GRADE", "-------") or not folder:
            continue
        m = re.match(r"\s*([a-zA-Z-]+)\s+(\S+)", source)
        method = m.group(1) if m else ("hardlink" if "HARDLINK" in source else "")
        url_match = re.search(r"https?://\S+", source)
        rows.append({
            "grade": grade, "year": year, "doi": doi, "folder": folder,
            "filename": filename, "source_url": url_match.group(0) if url_match else "",
            "method": method,
        })
    return rows


def parse_manifest(path: Path = MANIFEST) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return parse_manifest_lines(f.readlines())


def classify_paper(row: dict, chunk_text_sample: str) -> str | None:
    """Priority order: specific content-based rules before the GRADE_C_DEFAULT
    catch-all, since most of the corpus is grade C and would otherwise drown
    out every other signal."""
    text_lower = chunk_text_sample.lower()
    doi = row.get("doi", "")
    folder = row.get("folder", "")
    source_url = row.get("source_url", "")
    grade = row.get("grade", "")

    if any(term in text_lower for term in NOFAP_TERMS):
        return "NOFAP"
    if any(term in text_lower for term in DETOX_TERMS):
        return "DETOX"
    if folder.startswith("08_peptides_gray") and any(term in text_lower for term in PEPTIDE_PROTOCOL_TERMS):
        return "PEPTIDE_GRAY"
    if any(doi.startswith(p) for p in MILL_DOI_PREFIXES) and grade in ("B", "C"):
        return "MILL"
    if any(doi.startswith(p) for p in PREPRINT_DOI_PREFIXES):
        return "UNLABELED_PREPRINT"
    if LPI_DOMAIN in source_url:
        return "LPI_AS_ORDER"
    if not doi and not source_url:
        return "NAME_ONLY"
    if grade == "C" and not row.get("allow_c", False):
        return "GRADE_C_DEFAULT"
    return None


def normalized_doi(value: str) -> str:
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", (value or "").strip(), flags=re.I).lower()


def find_duplicate_dois(rows: list[dict]) -> dict[str, str]:
    """True accidental duplicates only: same DOI AND same folder. Cross-folder
    same-DOI entries are the intentional HARDLINK cross-filing pattern and
    must not be flagged."""
    by_doi_folder = defaultdict(list)
    for row in rows:
        doi = normalized_doi(row.get("doi", ""))
        if not doi:
            continue
        by_doi_folder[(doi, row["folder"])].append(row["filename"])
    flags = {}
    for (_doi, _folder), filenames in by_doi_folder.items():
        for extra in filenames[1:]:
            flags[extra] = "DUPLICATE_DOI"
    return flags


def scan(tbl, manifest_rows: list[dict]) -> dict[str, str]:
    """Returns {source_pdf: reason_code} for every row that should be quarantined."""
    by_key = {f"{r['folder']}/{r['filename']}": r for r in manifest_rows}
    dup_flags = find_duplicate_dois(manifest_rows)

    live_rows = (tbl.search().select(["source_pdf", "folder", "grade", "doi", "allow_c", "text"])
                 .where("personal = false", prefilter=True).limit(1_000_000).to_list())
    by_source_pdf_text = {}
    for r in live_rows:
        by_source_pdf_text.setdefault(r["source_pdf"], []).append(r.get("text", ""))

    flags: dict[str, str] = {}
    for source_pdf, texts in by_source_pdf_text.items():
        manifest_row = by_key.get(source_pdf)
        filename = os.path.basename(source_pdf)
        if filename in dup_flags:
            flags[source_pdf] = dup_flags[filename]
            continue
        if manifest_row is None:
            continue  # not in MANIFEST.md (e.g. the 61 xlsx lifestyle rows) -- not in scope for this scan
        sample = " ".join(texts)[:4000]
        reason = classify_paper({**manifest_row, "allow_c": any(
            r.get("allow_c") for r in live_rows if r["source_pdf"] == source_pdf
        )}, sample)
        if reason:
            flags[source_pdf] = reason
    return flags


def apply_flags(tbl, flags: dict[str, str]) -> int:
    total = 0
    for source_pdf, reason in flags.items():
        escaped = source_pdf.replace("'", "''")
        result = tbl.update(where=f"source_pdf = '{escaped}'",
                             values={"quarantined": True, "quarantine_reason": reason})
        total += result.rows_updated
    return total


def write_report(flags: dict[str, str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "reason"])
        for source_pdf, reason in sorted(flags.items()):
            writer.writerow([source_pdf, reason])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="write the report only, do not touch the database")
    args = ap.parse_args()

    import lancedb

    DBDIR = os.path.join(os.path.dirname(__file__), "lancedb")
    db = lancedb.connect(DBDIR)
    tbl = db.open_table("chunks")

    manifest_rows = parse_manifest()
    flags = scan(tbl, manifest_rows)

    out_path = Path(__file__).resolve().parent / "quarantine" / "DELETED_or_quarantined.csv"
    write_report(flags, out_path)
    print(f"quarantine candidates: {len(flags)} -> {out_path}")

    from collections import Counter
    for reason, count in Counter(flags.values()).most_common():
        print(f"  {reason}: {count}")

    if not args.dry_run:
        updated = apply_flags(tbl, flags)
        print(f"applied quarantine flag to {updated} rows")
    else:
        print("(dry run — no database rows changed)")


if __name__ == "__main__":
    main()

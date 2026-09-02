# HealthCoach papers — acquisition kit

## Why you run this, not the Cowork session
The Cowork session that built this folder had **no outbound network to any
research/PDF host** (cloud sandbox egress is org-restricted to package
registries; the Mac bridge shell has no egress). It could read the web via
Claude's WebFetch, but that returns *text*, not downloadable PDF bytes. So the
downloading is packaged as scripts that run where bytes can actually land:
**your real macOS Terminal.**

## Run it
```bash
cd ~/GitHub/HealthCoach/papers
python3 fetch_papers.py --selftest      # offline sanity check (no network)
bash    fetch_curated.sh                 # 4 hand-verified grade-A anchors
python3 fetch_papers.py --phase 1        # or: full run -> quotas
python3 fetch_papers.py --topic omega3   # single topic
```
`fetch_papers.py` needs only Python 3 stdlib. If a host throttles you, just
re-run — dedupe by DOI means finished papers are skipped.

## What the engine does
- Searches **Europe PMC** (OA-only) per topic query; grades each hit
  A/B/C/D from publication type + title.
- Resolves the PDF via **Europe PMC OA render** (PMCID) then **Unpaywall**
  best-OA location (DOI). Legal OA only.
- **Dedupes by DOI**; a paper used in >1 folder is a **hardlink** (`os.link`),
  logged in MANIFEST.
- **Citation-chains** every seed and hit (Europe PMC references + citations),
  preferring reviews / meta-analyses / RCTs, until each topic's `min` is met
  or OA is exhausted (logged).
- Runs an **African-American overlay** query per topic and a final AA pass into
  `12_population_AA`, hardlinked back to the topic folder.
- Writes `MANIFEST.md` (every file) and `SOURCES_FAILED.md` (every reject),
  and prints a per-folder count table every 10 unique PDFs.

## Grades
A systematic review / meta-analysis / guideline / position stand ·
B human RCT / clinical trial · C animal / mechanism / small / review ·
D myth-refutation only (never auto-assigned).
Grading is heuristic from metadata — spot-check A/B before citing.

## Hard rules baked in (see MANIFEST.md header)
PP405 and JXL069 kept in **separate** folders (Pelage: PP405 != JXL069);
PP405 is investigational, not approved. Peptides/PP405/JXL069 = explain only,
no dosing. Vaccine folder = pharmacokinetics/clearance/safety only; **no detox
protocol exists — the model must refuse** (detox URLs -> SOURCES_FAILED
`rejected-detox`). CRISPR = approved medicines only. Compressed 4x10 != reduced
4-day week.

## Tune before a big run
Edit the `TOPICS` list in `fetch_papers.py` (each entry: folder, slug, min,
stretch, queries, seeds, aa). Add DOIs/PMCIDs to `seeds` to force-include
specific papers. Whole-library v1 goal: 250-400 unique DOIs.

**`--phase` is NOT wired; it runs the FULL main job. Use `--topic`.**

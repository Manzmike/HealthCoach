# INGEST_RULES — HealthCoach RAG

These are the rules the ingest + retrieval code enforces. Text spec of record.

## What gets embedded
- LIVE pdfs under `../papers` only. EXCLUDE `_pruned/`, scripts, logs, .md files.
- Drop each paper's References/Bibliography section before chunking.
- Chunk ~700 tokens (~2800 chars) with ~120-token (~500-char) overlap.

## Metadata on every chunk
`grade, year, folder, cohort, doi, source_pdf` (+ `allow_c` helper flag).
- `grade`  A/B/C/D from filename.
- `cohort` = `older` if filename contains `_older-cohort_`, else `general`.
- `allow_c` = true iff the chunk's folder is a refusal/evidence-gap corpus.

## Retrieval rules (coach.py)
- Default retrieve: `grade in {A,B}`.
- Default exclude: `cohort = older`  (unless the question is about aging/older men).
- Allow `grade C` ONLY from refusal folders:
  `08_peptides_gray`, `pp405_suvomipic`, `jxl069_mpc_chemistry`,
  `no_detox_protocol`, `semen_retention_evidence`, `what_not_to_optimize`,
  `uncertified_quality_risk`.
- Hybrid retrieval: dense (bge-base) + keyword (LanceDB FTS).

## Generation
- Local only. Embeddings: `BAAI/bge-base-en-v1.5` (MPS). LLM: MLX
  (`mlx-community/Qwen2.5-14B-Instruct-4bit`) — 48 GB MacBook only, Mini never.
- System prompt carries the hard rules: no dosing for peptides/SARMs/PP405/JXL069/TRT,
  PP405 != JXL069, no COVID-vaccine "detox", don't apply older-cohort data to a late-20s
  male, cite grade + DOI, no claim without a passage.

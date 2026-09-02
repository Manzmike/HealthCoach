# HealthCoach RAG

Local retrieval-augmented coach over the `../papers` library. Everything runs on the
48 GB MacBook — no cloud, nothing leaves the machine. Mini is never used.

## One-time setup
```bash
cd ~/GitHub/HealthCoach/rag
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Build the index (stages 1–4, no LLM)
```bash
python3 ingest.py --limit 50     # smoke test first (~1 min)
python3 ingest.py                # full build of ../papers live corpus
```
Produces `./lancedb/`. Re-run any time the library changes.

## Verify retrieval BEFORE trusting answers
The risky part of any RAG is whether retrieval returns the right chunks. Sanity-check a
few queries with `--show` and read the sources it pulls:
```bash
python3 coach.py --show "does creatine cause hair loss?"
python3 coach.py --show "how long does spike protein persist after mRNA vaccination?"
python3 coach.py --show "should I take a SARM to cut faster?"
```
Good signs: creatine question pulls creatine A/B papers; the SARM question pulls the
`ped_sarms_aas_harms` / refusal corpus and the answer refuses dosing; the vaccine
question pulls PK papers and refuses any "detox".

## Ask the coach (stage 5, MLX)
```bash
python3 coach.py "structure a fat-loss cut while keeping my lifts"
python3 coach.py --k 8 --show "omega-3 dose for triglycerides"
```
First run downloads the MLX model (~8 GB) once.

## Knobs
- Embedding model: `EMB_MODEL` in both scripts (bge-base default; bge-small = faster).
- LLM: `GEN_MODEL` in coach.py (Qwen2.5-14B-4bit default; Llama-3.1-8B-4bit = faster).
- Retrieval count: `--k`. Aging questions auto-include older-cohort papers.

## Guardrails (enforced in code + prompt)
grade A/B by default; C only from refusal folders; older-cohort excluded unless you ask
about aging; no dosing for peptides/SARMs/PP405/JXL069/TRT; PP405 ≠ JXL069; no vaccine
"detox". See INGEST_RULES.md.

## Not included on purpose
No web UI (CLI first — add Streamlit later if wanted). No re-ranker yet (bge-reranker is
an easy quality add once retrieval is validated). No auto-ingest of new papers — re-run
`ingest.py`.

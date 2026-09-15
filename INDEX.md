# HealthCoach — file index

One place to find every doc, log, and data file in this project, and what it's actually for.
If you're a new session (human or AI) picking this up cold, read in this order:
**README.md → docs/PROJECT_AI_HANDOFF.md → docs/PROJECT_OVERVIEW.md.**

## Start here

| File | What it is |
|---|---|
| [`README.md`](README.md) | Top-level project readme. Stays at the repo root — GitHub convention, renders on the repo homepage. |
| [`rag/README.md`](rag/README.md) | The real usage guide — how to run `./hc`, the dashboard, candidate ledger commands (`rank`/`triage`/`dose`/`stack-check`/`undo`), source refreshing. Read this to actually use the tool. Stays next to the code it documents. |
| [`papers/README.md`](papers/README.md) | How the paper-fetching pipeline works. Stays next to that code. |

## `docs/` — official reference and handoff docs

Everything that's pure documentation (not a README living beside its own code) lives here:

| File | What it is |
|---|---|
| [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) | Plain-English description of what the whole system is and why it exists. |
| [`docs/PROJECT_AI_HANDOFF.md`](docs/PROJECT_AI_HANDOFF.md) | The deep technical handoff — architecture, data flow, gotchas. Written for another AI/engineer to operate this without rediscovering it. |
| [`docs/RESUME.md`](docs/RESUME.md) | A dated checkpoint from an earlier session (2026-09-02). Likely stale now given everything built since — treat as history, not current state. |
| [`.continues-handoff.md`](.continues-handoff.md) | **Not our doc, stays at root.** This is Codex CLI's own auto-generated session-continuity file from a different AI coding tool that also worked in this repo. Untracked, local-only — moving it could break that tool's ability to find it next time it runs here. |

## The one generated report

| File | What it is |
|---|---|
| [`rag/HEALTHCOACH_REPORT.md`](rag/HEALTHCOACH_REPORT.md) | **The single canonical output.** Every `./hc-supplements` run replaces this same file — no timestamped copies. Browse it with chapters/pages via `./hc-report`, not by opening the raw file. |
| `rag/WEEK_OPERATING_PLAN.md`, `rag/FOOD_COFFEE_MILK_STACK_PLAN.md`, `rag/WHOLE_LIFE_EVIDENCE_PLAN.md` | **Authored source modules — functionally required.** `supplement_audit.py` reads and embeds these directly into the report. Edit these files to change those sections; don't hand-edit the generated report itself. |
| `rag/EVIDENCE_NUTRITION_STACK_PLAN.archive-2026-09-15.md` | Archived 2026-09-15. Was a standalone evidence-map document, never wired into the pipeline above; its content (25 of 29 evidence rows, by shared DOI/topic-label match) was superseded by the later-written, already-wired `FOOD_COFFEE_MILK_STACK_PLAN.md`. Kept for reference, not read by any code. |
| `rag/SCHEDULE_TIPS.md`, `rag/INGEST_RULES.md` | Reference notes for maintainers (zone 2/RPE/TDEE tips; ingest-pipeline rules). |
| `rag/history.md` | Personal training/lab history, feeds `build_schedule.py`/`build_playbook.py`. |

## Secondary outputs — `rag/logs/` (a real 3-stage pipeline, not scratch)

Don't create a separate `output/` folder for these — this pipeline already exists:
1. `build_schedule.py`, `build_playbook.py`, `deep_dive.py`, `batch_ask.py` each drop one
   timestamped file flatly into `logs/`.
2. `organize_logs.py` sorts everything in `logs/` into typed subfolders: `playbooks/`,
   `schedules/`, `deep_dives/`, `supplement_audits/`, `tiers/`, `qa/answers/`, `qa/extracts/`,
   `run_output/`, `misc/`.
3. `combine_report.py` reads the newest file from each typed subfolder and stitches them into
   `logs/MASTER_REPORT_<timestamp>.md`.

Run order: generate → `python3 organize_logs.py` → `python3 combine_report.py`.

## Personal config — real files vs. templates

| File | What it is |
|---|---|
| `rag/profile.txt` | **Your real personal profile.** Not a template — contains your actual info. |
| `rag/profile.example.txt` | Blank template for a new user — copy this to `profile.txt` to start. Safe to share. |
| `rag/schedule_inputs.md` | **Your real schedule.** |
| `rag/schedule_inputs.example.md` | Blank template — copy to `schedule_inputs.md` to start. Safe to share. |

## Working inputs for the batch-question tools (functionally used, not scratch)

`rag/questions.txt`, `rag/new_questions_r15.txt`, `rag/new_questions_r16.txt`,
`rag/new_cravings_parasites.txt`, `rag/personalized_tiers.txt`, `rag/interactions.txt`,
`rag/themes.txt` — read by `build_questions.py`, `combine_report.py`, `batch_ask.py`,
`deep_dive.py`, `queue_more.sh`. These look like scratch files but are real inputs; don't delete
without checking those scripts first.

## Private data — gitignored, not meant to be read as logs

| File | What it is |
|---|---|
| `rag/.healthcoach/candidate_ledger.json` | The private candidate ledger — every supplement/peptide/food's decision, reasons, evidence cache. Use `candidate_manager.py` commands to read/edit this, not a text editor. |
| `rag/.healthcoach/labs.json` | Your private lab values. Use `labs.py add`/`labs.py list`. |
| `rag/.healthcoach/batch_log.json` | Undo history for `rank`/`triage` sessions. Use `candidate_manager.py undo`. |

## Source-fetch pipeline logs (`papers/`)

| File | What it is |
|---|---|
| `papers/README.md` | How the paper-fetching pipeline works. |
| `papers/MANIFEST.md` | **Machine-generated and machine-read** — `fetch_papers.py` reads this back for cross-run dedup. Do not hand-edit or delete; doing so causes re-downloading of everything already fetched. |
| `papers/SOURCES_FAILED.md` | Write-only debug log of failed fetch attempts. Nothing reads this back — purely for a human to scan if a fetch run behaves oddly. Reset to empty on 2026-09-06 (was 4.5MB/31,757 lines). |
| `papers/SOURCES_FAILED.archive-2026-09-06.md` | Everything that was in `SOURCES_FAILED.md` before the 2026-09-06 reset. Safe to delete if you never need to look back at it. |
| `papers/PRUNE_LOG.md` | History of source-pruning passes. |

## Candidate-ledger command reference (quick pointer)

Full detail is in `rag/README.md`. The short version:
```bash
cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
python3 candidate_manager.py status               # everything grouped: approved/denied/watching/unzoned
python3 candidate_manager.py rank --categories supplement,peptide,nootropic,gray_market,herbs --all-decisions --limit 0
python3 candidate_manager.py triage                # one at a time with a real grade + evidence
python3 candidate_manager.py dose <item>            # study-based dose (supplements/food only)
python3 candidate_manager.py stack-check            # conflicts/competition/redundancy in your real stack
python3 candidate_manager.py undo                   # revert the last rank/triage batch
python3 labs.py add <marker> <value>                # record a lab value
python3 labs.py import-pdf <path>                   # assisted PDF import, confirms every value
```

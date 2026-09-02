# RESUME — where I left off

_Checkpoint. Open this to pick up exactly where things stand._

## State: all code changes are SAVED to this folder on disk
Done and committed to `~/GitHub/HealthCoach` this session:
- **Deterministic schedule** — `build_schedule.py` builds the clock/week in code from the
  `## TIMES` + `## WEEKLY SPLIT` in `schedule_inputs.md` (no more wrong bedtimes/hours).
- **Playbook** — `build_playbook.py` (chaptered learning doc; reuses the deterministic schedule).
- **Model default = Qwen3-30B-A3B** — set in `coach.py` (env-overridable). Better grading, no
  invented names. ~17 GB, MoE (fast).
- **A-hunt fetch** — `ABOOST=1 python3 fetch_papers.py` harvests OA reviews/meta-analyses/
  guidelines/RCTs, keeps only A/B. Grading also catches umbrella reviews, consensus, crossover.
- **Optional personal history** — `history.md` (git-ignored) feeds the schedule/playbook.
- **How-to reference** — `SCHEDULE_TIPS.md` (zone 2, RPE, protein, TDEE, caffeine, sleep).
- Visual README with Mermaid diagrams + evidence charts; repo pushed to github.com/Manzmike/HealthCoach.

## PENDING (needs internet — do on the ground / when back online)
1. **Push the day's code:**
   ```bash
   cd ~/GitHub/HealthCoach
   rm -f .git/index.lock .git/HEAD.lock .git/objects/maintenance.lock
   git add -A && git commit -m "session updates" && git push
   ```
2. **Refresh + regenerate on the new model** (downloads ~17 GB model first time):
   ```bash
   cd ~/GitHub/HealthCoach/papers && ABOOST=1 python3 fetch_papers.py
   cd ../rag && source .venv/bin/activate && python3 -u ingest.py && python3 -u build_playbook.py
   ```

## WORKS OFFLINE (on the plane) — IF the model + library are already local
Once the Qwen3-30B model is downloaded and `rag/lancedb` exists, generation is 100% local:
```bash
cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
python3 coach.py "your question"          # single Q&A, offline
python3 -u build_schedule.py              # schedule, offline
python3 -u build_playbook.py              # full playbook, offline
python3 -u batch_ask.py personalized_tiers.txt
```
NEEDS internet (won't work offline): `fetch_papers.py` / `ABOOST` (paper APIs) and the first
model download. So **pre-download the model before you lose wifi** if you want to work in the air:
```bash
python3 -c "from mlx_lm import load; load('mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit'); print('cached')"
```

## Outputs from the last run live in `rag/logs/`
`playbook_*.md`, `schedule_*.md`, `coach_log_*` (answers + tiers), `parasite_answers.md`,
`new_answers_merged_*.md`.

## Ideas parked (not built)
- `add_pdf.py` helper to drop a paywalled-but-legally-accessed PDF into the right folder + reindex.
- Fold tiers/playbook into the Performance OS artifact as one rendered page.

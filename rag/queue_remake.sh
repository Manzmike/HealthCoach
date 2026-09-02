#!/usr/bin/env bash
# Wait for the currently-running deep_dive.py to finish, THEN run the gap-fill remake:
# fetch the 5 new topics -> rebuild the index -> deep-dive the new briefs.
# Run in a NEW tab (leave your deep_dive tab alone):
#     caffeinate -is bash ~/GitHub/HealthCoach/rag/queue_remake.sh
# (optional) pass a PID to wait on:  caffeinate -is bash queue_remake.sh 12345
set -u
P="$HOME/GitHub/HealthCoach/papers"
R="$HOME/GitHub/HealthCoach/rag"

# find the running deep_dive (this script's own name is queue_remake.sh, so no self-match)
WAITPID="${1:-$(pgrep -f 'python3 deep_dive.py' | head -1)}"
if [ -n "${WAITPID:-}" ]; then
  echo "[queue] waiting for deep_dive to finish (PID $WAITPID)…"
  while kill -0 "$WAITPID" 2>/dev/null; do sleep 30; done
  echo "[queue] deep_dive finished."
else
  echo "[queue] no running deep_dive found — starting remake now."
fi

echo "[queue] === REMAKE START $(date) ==="
cd "$P" || { echo "no papers dir"; exit 1; }
for t in physique_hypertrophy_selection whole_foods_nutrient_dense \
         foods_for_body_composition foods_for_brain_cognition semax_selank; do
  echo "[queue] --- fetch: $t ---"
  python3 fetch_papers.py --topic "$t"
done

echo "[queue] --- rebuilding RAG index ---"
# shellcheck disable=SC1091
source "$R/.venv/bin/activate"
cd "$R" || { echo "no rag dir"; exit 1; }
python3 ingest.py

echo "[queue] --- deep-dive on the new topics ---"
python3 deep_dive.py foods brain semax physique

echo "[queue] === ALL DONE $(date) ==="
echo "New logs are in $R/logs/ — newest deep_dive_*.md has the new briefs."

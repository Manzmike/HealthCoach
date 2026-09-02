#!/usr/bin/env bash
# Waits for the running queue_remake.sh to finish, then:
#   1) MORE SOURCES: full library top-up (main + hormones, idempotent — only fetches gaps)
#   2) rebuild the RAG index
#   3) deep_dive.py  (all built-in + themes.txt briefs)
#   4) batch_ask.py  (the 77-question master bank)
# Launch in a NEW tab (leave the queue_remake tab running):
#     caffeinate -is bash ~/GitHub/HealthCoach/rag/queue_more.sh
set -u
P="$HOME/GitHub/HealthCoach/papers"
R="$HOME/GitHub/HealthCoach/rag"

# this script is queue_MORE.sh, so matching 'queue_remake.sh' can't hit ourselves
W=$(pgrep -f 'queue_remake.sh' | head -1)
if [ -n "${W:-}" ]; then
  echo "[more] waiting for queue_remake to finish (PID $W)…"
  while kill -0 "$W" 2>/dev/null; do sleep 30; done
  echo "[more] queue_remake finished."
else
  echo "[more] queue_remake not running — starting now."
fi

echo "[more] === MORE SOURCES + FULL RUN  $(date) ==="
cd "$P" || { echo "no papers dir"; exit 1; }
echo "[more] --- topping up main library (more sources) ---"
python3 fetch_papers.py
echo "[more] --- topping up hormone side job ---"
python3 fetch_papers.py --hormones

echo "[more] --- rebuilding RAG index ---"
# shellcheck disable=SC1091
source "$R/.venv/bin/activate"
cd "$R" || { echo "no rag dir"; exit 1; }
python3 ingest.py

echo "[more] --- deep-dive briefs (all themes) ---"
python3 deep_dive.py

echo "[more] --- master question batch (77) ---"
python3 batch_ask.py

echo "[more] === ALL DONE  $(date) ==="
echo "New logs in $R/logs/ : newest deep_dive_*.md and coach_log_*.md"

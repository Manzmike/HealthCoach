#!/usr/bin/env bash
# One-command tmux cockpit for HealthCoach:
#   top pane  = fetch (main then hormones), kept awake with caffeinate
#   bottom    = live status dashboard
# Usage:  bash dash.sh            (start or re-attach)
#         tmux attach -t hc       (re-attach later)
#         Ctrl-b d  to detach (keeps running) · Ctrl-b arrows to move · Ctrl-b z zoom
DIR="$(cd "$(dirname "$0")" && pwd)"
S=hc

command -v tmux >/dev/null 2>&1 || { echo "tmux not installed — run:  brew install tmux"; exit 1; }

# already running? just re-attach.
if tmux has-session -t "$S" 2>/dev/null; then
  echo "Session '$S' exists — attaching. (Ctrl-b d to detach)"
  exec tmux attach -t "$S"
fi

# top pane: the fetch (idempotent; skips what's on disk). ';' so hormones runs regardless.
tmux new-session -d -s "$S" -c "$DIR"
tmux send-keys -t "$S" \
  "caffeinate -is sh -c 'python3 fetch_papers.py; python3 fetch_papers.py --hormones; echo; echo ===== ALL FETCHING DONE ====='" C-m

# bottom pane: dashboard
tmux split-window -v -t "$S" -c "$DIR"
tmux resize-pane -t "$S".1 -y 20
tmux send-keys -t "$S".1 "bash status.sh 5" C-m

tmux select-pane -t "$S".0
exec tmux attach -t "$S"

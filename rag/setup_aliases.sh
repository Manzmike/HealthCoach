#!/usr/bin/env bash
# One-time: add HealthCoach shortcuts to your ~/.zshrc. Safe to re-run (idempotent).
#   cd ~/GitHub/HealthCoach/rag && bash setup_aliases.sh && source ~/.zshrc
RC="$HOME/.zshrc"
MARK="# >>> HealthCoach shortcuts >>>"
if grep -q "$MARK" "$RC" 2>/dev/null; then
  echo "Already installed in $RC — nothing to do."
  exit 0
fi
cat >> "$RC" <<'BLOCK'

# >>> HealthCoach shortcuts >>>
export HC="$HOME/GitHub/HealthCoach"
# ask the coach (runs in a subshell so your current shell stays clean):
coach () { ( cd "$HC/rag" && source .venv/bin/activate && python3 coach.py --show "$@" ); }
# rebuild the vector index after the library changes:
alias hc-ingest='( cd "$HC/rag" && source .venv/bin/activate && python3 ingest.py )'
# live library dashboard:
alias hc-status='( cd "$HC/papers" && bash status.sh )'
# jump into the project / open the venv:
alias hc='cd "$HC"'
alias hc-env='cd "$HC/rag" && source .venv/bin/activate'
# <<< HealthCoach shortcuts <<<
BLOCK
echo "Added HealthCoach shortcuts to $RC"
echo "Run:  source ~/.zshrc    (or open a new Terminal tab)"

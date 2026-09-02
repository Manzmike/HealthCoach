#!/usr/bin/env bash
# Fetch the hand-verified curated core (gold OA, grade A). Run in a shell WITH internet.
#   cd ~/GitHub/HealthCoach/papers && bash fetch_curated.sh
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
CSV="$ROOT/curated_seed_list.csv"
MAN="$ROOT/MANIFEST.md"
UA="Mozilla/5.0 (Macintosh) HealthCoachAcquire/1.0"
n=0; ok=0
tail -n +2 "$CSV" | while IFS=, read -r grade year folder doi url file; do
  [ -z "$folder" ] && continue
  n=$((n+1))
  mkdir -p "$ROOT/$folder"
  out="$ROOT/$folder/$file"
  echo "[$n] $doi -> $folder/$file"
  code=$(curl -sL -A "$UA" -m 60 -o "$out" -w "%{http_code}" "$url")
  if head -c 5 "$out" 2>/dev/null | grep -q "%PDF"; then
    ok=$((ok+1))
    echo "| $grade | $year | $doi | $folder | $file | curated $url |" >> "$MAN"
    echo "   OK ($code) $(du -h "$out" | cut -f1)"
  else
    rm -f "$out"
    echo "- FAIL curated | $grade | $doi | HTTP $code | $url" >> "$ROOT/SOURCES_FAILED.md"
    echo "   FAIL ($code) — logged"
  fi
done
echo "curated done"

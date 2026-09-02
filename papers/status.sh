#!/usr/bin/env bash
# HealthCoach live status dashboard.  Usage:  bash status.sh [refresh_seconds]
# Reads local disk only. Safe to run alongside a fetch. Ctrl-C to quit.
INT="${1:-5}"
P="$(cd "$(dirname "$0")" && pwd)"
TMP="/tmp/hc_status_$$.txt"
trap 'rm -f "$TMP"; printf "\033[?25h\n"; exit 0' INT TERM EXIT

R='\033[31m'; G='\033[32m'; Y='\033[33m'; B='\033[34m'; C='\033[36m'
M='\033[35m'; W='\033[37m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

prev_total=-1; prev_time=$(date +%s); spin=0
printf '\033[?25l'   # hide cursor

bar() { # bar count max width color
  awk -v v="$1" -v m="$2" -v w="$3" -v col="$4" -v nc="$NC" 'BEGIN{
    if(m<=0)m=1; n=int(v*w/m); if(n>w)n=w; s="";
    for(i=0;i<n;i++)s=s "\xe2\x96\x88";
    for(i=n;i<w;i++)s=s "\xe2\x96\x91";
    printf "%s%s%s", col, s, nc;
  }'
}

while :; do
  find "$P" -name '*.pdf' 2>/dev/null | sed "s#$P/##" > "$TMP"
  total=$(wc -l < "$TMP" | tr -d ' ')
  uniq=$(find "$P" -name '*.pdf' -exec stat -f '%i' {} \; 2>/dev/null | sort -u | wc -l | tr -d ' ')
  rows=$(grep -cE '^\| [ABCD] \|' "$P/MANIFEST.md" 2>/dev/null)
  fails=$(grep -c '^- ' "$P/SOURCES_FAILED.md" 2>/dev/null)
  eval "$(awk -F/ '{g=substr($NF,1,1); if(g=="A")a++;else if(g=="B")b++;else if(g=="C")c++;else if(g=="D")d++} END{printf "gA=%d;gB=%d;gC=%d;gD=%d",a+0,b+0,c+0,d+0}' "$TMP")"

  now=$(date +%s)
  if [ "$prev_total" -ge 0 ]; then
    dt=$(( now - prev_time )); [ "$dt" -le 0 ] && dt=1
    dn=$(( total - prev_total ))
    rate=$(awk -v n="$dn" -v t="$dt" 'BEGIN{printf "%.1f", n*60.0/t}')
  else rate="--"; dn=0; fi

  if pgrep -f "[f]etch_papers.py" >/dev/null 2>&1; then
    set -- '|' '/' '-' '\'; eval "f=\${$(( spin%4 + 1 ))}"
    STAT="${G}${BOLD}● RUNNING ${f}${NC}"
  else
    STAT="${Y}${BOLD}○ IDLE${NC}"
  fi
  spin=$(( spin+1 ))

  qtot=$(( gA+gB+gC+gD )); [ "$qtot" -le 0 ] && qtot=1
  W1=$(( gA*46/qtot )); W2=$(( gB*46/qtot )); W3=$(( gC*46/qtot ))
  W4=$(( 46 - W1 - W2 - W3 )); [ "$W4" -lt 0 ] && W4=0
  ab=$(( gA+gB )); qpct=$(( ab*100/qtot ))

  printf '\033[H\033[2J'
  printf "${BOLD}${C}╔══════════════════════════════════════════════════════════╗${NC}\n"
  printf "${BOLD}${C}║${NC}   ${BOLD}HealthCoach library${NC}   %b        ${DIM}refresh ${INT}s${NC}   ${BOLD}${C}║${NC}\n" "$STAT"
  printf "${BOLD}${C}╚══════════════════════════════════════════════════════════╝${NC}\n\n"

  printf "  ${BOLD}${W}%s${NC} PDFs on disk   ${DIM}(${NC}${BOLD}%s${NC}${DIM} unique papers · %s hardlinks)${NC}\n" "$total" "$uniq" "$(( total - uniq ))"
  printf "  ${DIM}manifest rows${NC} %s    ${DIM}failed/skipped${NC} ${R}%s${NC}\n\n" "$rows" "$fails"

  printf "  ${BOLD}quality mix${NC}  "
  printf "%b%b%b%b" "$(bar $W1 46 $W1 "$G")" "$(bar $W2 46 $W2 "$C")" "$(bar $W3 46 $W3 "$Y")" "$(bar $W4 46 $W4 "$R")"
  printf "\n  ${G}█${NC} A ${BOLD}%s${NC}   ${C}█${NC} B ${BOLD}%s${NC}   ${Y}█${NC} C ${BOLD}%s${NC}   ${R}█${NC} D ${BOLD}%s${NC}    ${DIM}A+B =${NC} ${BOLD}%s%%${NC}\n\n" "$gA" "$gB" "$gC" "$gD" "$qpct"

  printf "  ${BOLD}top folders${NC}\n"
  mx=$(awk -F/ '{print $1}' "$TMP" | sort | uniq -c | sort -rn | head -1 | awk '{print $1}')
  awk -F/ '{print $1}' "$TMP" | sort | uniq -c | sort -rn | head -12 | while read cnt name; do
    printf "  %-26.26s %s ${DIM}%s${NC}\n" "$name" "$(bar "$cnt" "${mx:-1}" 22 "$B")" "$cnt"
  done

  printf "\n  ${BOLD}rate${NC} ${G}%s${NC} papers/min   ${DIM}(+%s since last refresh)${NC}\n" "$rate" "$dn"
  last=$(grep -E '^\| [ABCD] \|' "$P/MANIFEST.md" 2>/dev/null | tail -1 | awk -F'|' '{gsub(/^ +| +$/,"",$5); gsub(/^ +| +$/,"",$6); print $5" / "$6}')
  printf "  ${DIM}last filed:${NC} %.66s\n" "${last:-—}"
  printf "\n  ${DIM}Ctrl-C to quit${NC}\n"

  prev_total="$total"; prev_time="$now"
  sleep "$INT"
done

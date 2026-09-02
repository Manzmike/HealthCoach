#!/usr/bin/env bash
# Move the whole HealthCoach project to an external SSD, safely.
#   bash migrate_to_ssd.sh /Volumes/YOUR_SSD
# Preserves hardlinks, rebuilds the venv, and fixes your alias path. Run in your Mac Terminal.
set -e
DEST="${1:?usage: bash migrate_to_ssd.sh /Volumes/YOUR_SSD   (the mounted SSD path)}"
SRC="$HOME/GitHub/HealthCoach"
[ -d "$SRC" ]  || { echo "source not found: $SRC"; exit 1; }
[ -d "$DEST" ] || { echo "destination not mounted: $DEST  (plug the SSD in first)"; exit 1; }

# --- filesystem check: hardlinks need APFS/HFS, NOT exFAT/FAT ---
fs=$(mount | awk -v d="$DEST" 'index($0,d){print}' | grep -oiE 'apfs|hfs|exfat|msdos|fat' | head -1)
echo "destination filesystem: ${fs:-unknown}"
case "$fs" in
  exfat|msdos|fat)
    echo "!! $fs does NOT support hardlinks. Your 1,822 hardlinks would bloat into full copies or fail."
    echo "   Fix: Disk Utility -> erase the SSD as APFS (case-insensitive), then re-run this. Aborting."
    exit 1 ;;
esac

TARGET="$DEST/HealthCoach"
echo ">> copying (preserving hardlinks) to $TARGET"
rsync -aH --info=progress2 "$SRC/" "$TARGET/"

echo ">> rebuilding venv at $TARGET/rag"
cd "$TARGET/rag"
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
echo "   venv rebuilt."

# --- fix the alias path in ~/.zshrc if the shortcuts are installed ---
if grep -q '# >>> HealthCoach shortcuts >>>' "$HOME/.zshrc" 2>/dev/null; then
  sed -i '' "s|export HC=.*|export HC=\"$TARGET\"|" "$HOME/.zshrc"
  echo "   updated HC path in ~/.zshrc -> $TARGET   (run: source ~/.zshrc)"
fi

echo ">> verify"
echo "   pdfs:      $(find "$TARGET/papers" -name '*.pdf' | wc -l | tr -d ' ')"
echo "   hardlinks: $(find "$TARGET/papers" -name '*.pdf' -links +1 | wc -l | tr -d ' ')  (should be ~1822 — proves links survived)"
echo ""
echo "DONE. Runs from $TARGET whenever the SSD is plugged in."
echo "Test it:  cd $TARGET/rag && source .venv/bin/activate && python3 coach.py --show \"omega-3 dose for triglycerides\""
echo "Original at $SRC is untouched — delete it only after you've confirmed the SSD copy works."

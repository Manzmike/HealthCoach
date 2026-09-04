#!/usr/bin/env python3
"""
Sort rag/logs/*.* into typed subfolders. Idempotent and safe to re-run — new runs drop
fresh files into logs/ (flat), and re-running this tucks them into the right place.

  cd ~/GitHub/HealthCoach/rag && python3 organize_logs.py

Layout it creates under logs/:
  reports/       MASTER_REPORT_*.md     (the combined master reports)
  playbooks/     playbook_*.md          (full learning documents)
  schedules/     schedule_*.md          (daily/weekly schedules)
  deep_dives/    deep_dive_*.md         (deep-dive briefs)
  supplement_audits/ supplement_audit_* (interactive evidence audits)
  tiers/         coach_log_* that are A/B/C/D tier runs
  qa/answers/    coach_log_* Q&A runs + *_shard*of*.md
  qa/extracts/   *_answers.md, *_merged_* (hand-pulled subsets)
  run_output/    *.out, *.log           (raw stdout dumps)
  misc/          anything else
"""
import os, re, glob

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

def classify(name, path):
    n = name.lower()
    if n.startswith("master_report"):              return "reports"
    if n.startswith("playbook_"):                  return "playbooks"
    if n.startswith("schedule_"):                  return "schedules"
    if n.startswith("deep_dive_"):                 return "deep_dives"
    if n.startswith("supplement_audit_"):          return "supplement_audits"
    if n.endswith(".out") or n.endswith(".log"):   return "run_output"
    if "merged" in n or n.endswith("_answers.md") or "parasite" in n:
        return "qa/extracts"
    if re.search(r"_shard\d+of\d+\.md$", n):        return "qa/answers"
    if n.startswith("coach_log_") and n.endswith(".md"):
        try:
            head = open(path, encoding="utf-8", errors="ignore").read(4000).lower()
        except Exception:
            head = ""
        if "into a/b/c/d" in head or "tier a" in head or "a/b/c/d tier" in head:
            return "tiers"
        return "qa/answers"
    return "misc"

def main():
    if not os.path.isdir(LOG):
        print("no logs/ dir at", LOG); return
    counts = {}
    for path in sorted(glob.glob(os.path.join(LOG, "*"))):
        if os.path.isdir(path):
            continue
        name = os.path.basename(path)
        sub = classify(name, path)
        dest_dir = os.path.join(LOG, sub)
        os.makedirs(dest_dir, exist_ok=True)
        target = os.path.join(dest_dir, name)
        if os.path.abspath(path) == os.path.abspath(target):
            continue
        if os.path.exists(target):                 # never clobber
            base, ext = os.path.splitext(name)
            k = 1
            while os.path.exists(os.path.join(dest_dir, "%s_dup%d%s" % (base, k, ext))):
                k += 1
            target = os.path.join(dest_dir, "%s_dup%d%s" % (base, k, ext))
        os.rename(path, target)
        counts[sub] = counts.get(sub, 0) + 1
    if counts:
        print("organized:")
        for k in sorted(counts):
            print("  %-14s %d file(s)" % (k, counts[k]))
    else:
        print("nothing to move — already organized.")
    print("logs/ is now sorted under", LOG)

if __name__ == "__main__":
    main()
